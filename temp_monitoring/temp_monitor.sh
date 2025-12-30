#!/bin/bash

set -euo pipefail

# Install dependencies if missing
PACKAGES=("mosquitto-clients" "nano")
MISSING=()

for pkg in "${PACKAGES[@]}"; do
    if ! dpkg -l | grep -q "^ii  $pkg "; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "Installing missing packages: ${MISSING[*]}"
    apt-get update
    apt install -y "${MISSING[@]}"
    echo "Installation complete."
fi

# Configuration
hdd_devices=(sda sdb sdc sdd sde sdf)
MONITOR_INTERVAL=10

MQTT_HOST="192.168.1.111"
MQTT_USER="homeassistant"
MQTT_PASS="unas_password_123"

# Helper function to publish MQTT sensor
publish_mqtt_sensor() {
    local sensor_name=$1
    local friendly_name=$2
    local value=$3
    local unit=$4
    local device_class=${5:-}
    
    local config_json="{\"name\":\"$friendly_name\",\"state_topic\":\"homeassistant/sensor/${sensor_name}/state\",\"unit_of_measurement\":\"$unit\",\"unique_id\":\"$sensor_name\""
    
    if [ -n "$device_class" ]; then
        config_json="${config_json},\"device_class\":\"$device_class\""
    fi
    
    config_json="${config_json}}"
    
    # Publish config
    mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "homeassistant/sensor/${sensor_name}/config" \
        -m "$config_json" \
        -r
    
    # Publish state
    mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "homeassistant/sensor/${sensor_name}/state" \
        -m "$value"
}

# Function to read storage pool usage
read_storage_usage() {
    local pool_num=1
    local temp_file="/tmp/df_output.$$"

    df -BG --output=source,size,used,avail,pcent 2>/dev/null | tail -n +2 > "$temp_file"

    declare -A seen_devices

    while read -r source size used avail pcent; do
        # Skip tmpfs, devtmpfs, loop devices, and other virtual filesystems
        [[ "$source" =~ ^(tmpfs|devtmpfs|overlay|shm|udev) ]] && continue
        [[ "$source" =~ /loop ]] && continue
        [[ ! "$source" =~ ^/dev/ ]] && continue

        size_gb=${size%G}

        if [[ "$size_gb" -gt 100 ]]; then
            [[ -n "${seen_devices[$source]:-}" ]] && continue
            seen_devices[$source]=1

            fs_name="pool${pool_num}"
            capacity_num=${pcent%\%}
            used_gb=${used%G}
            avail_gb=${avail%G}

            # Publish storage sensors
            publish_mqtt_sensor "unas_${fs_name}_usage" "UNAS Storage Pool ${pool_num} Usage" "$capacity_num" "%"
            publish_mqtt_sensor "unas_${fs_name}_size" "UNAS Storage Pool ${pool_num} Size" "$size_gb" "GB" "data_size"
            publish_mqtt_sensor "unas_${fs_name}_used" "UNAS Storage Pool ${pool_num} Used" "$used_gb" "GB" "data_size"
            publish_mqtt_sensor "unas_${fs_name}_available" "UNAS Storage Pool ${pool_num} Available" "$avail_gb" "GB" "data_size"

            pool_num=$((pool_num + 1))
        fi
    done < "$temp_file"

    rm -f "$temp_file"
}

# Function to read all HDD temperatures at once
read_all_hdd_temperatures() {
    local dev temp

    declare -gA current_temps=()

    for dev in "${hdd_devices[@]}"; do
        if [ -e "/dev/$dev" ]; then
            temp=$(timeout 5 smartctl -a "/dev/$dev" 2>/dev/null | awk '/194 Temperature_Celsius/ {print $10}' || echo "0")
            if [[ "$temp" =~ ^[0-9]+$ ]]; then
                current_temps["$dev"]="$temp"
            fi
        fi
    done
}

# Function to format temperature output
format_temperature_output() {
    local temps_output=()
    local dev temp

    for dev in "${hdd_devices[@]}"; do
        if [[ -n "${current_temps[$dev]:-}" ]]; then
            temp="${current_temps[$dev]}"
            temps_output+=("${temp}°C")
        fi
    done

    local output=""
    for i in "${!temps_output[@]}"; do
        if [ "$i" -eq 0 ]; then
            output="${temps_output[$i]}"
        else
            output="${output}, ${temps_output[$i]}"
        fi
    done

    echo "$output"
}

# Main monitoring loop
monitor_temperatures() {
    local next_ts raw percent timestamp temp_str cpu_temp

    next_ts=$(date +%s)

    while true; do
        raw=$(cat /sys/class/hwmon/hwmon0/pwm1)
        percent=$(( raw * 100 / 255 ))

        cpu_temp=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
        cpu_temp=$((cpu_temp / 1000))

        read_all_hdd_temperatures
        temp_str=$(format_temperature_output)

        read_storage_usage

        timestamp=$(date +"%Y-%m-%d %H:%M:%S")
        printf "%s: %3d (%d%%) (CPU %d°C) (HDD %s)\n" "$timestamp" "$raw" "$percent" "$cpu_temp" "$temp_str"

        # Publish drive temperatures
        for dev in "${hdd_devices[@]}"; do
            if [[ -n "${current_temps[$dev]:-}" ]]; then
                publish_mqtt_sensor "unas_${dev}" "UNAS ${dev} Temperature" "${current_temps[$dev]}" "°C" "temperature"
            fi
        done

        # Publish CPU temperature
        publish_mqtt_sensor "unas_cpu" "UNAS CPU Temperature" "$cpu_temp" "°C" "temperature"

        next_ts=$((next_ts + MONITOR_INTERVAL))
        local sleep_time=$((next_ts - $(date +%s)))

        if (( sleep_time > 0 )); then
            sleep $sleep_time
        else
            next_ts=$(date +%s)
        fi
    done
}

# Start monitoring
monitor_temperatures
