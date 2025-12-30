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
hdd_devices=(sda sdb sdc sdd sde sdf sdg)
MONITOR_INTERVAL=10

MQTT_HOST="192.168.1.111"
MQTT_USER="homeassistant"
MQTT_PASS="unas_password_123"

# Function to read all HDD temperatures at once
read_all_hdd_temperatures() {
    local dev temp

    # Clear current temps
    declare -gA current_temps=()

    # Read all HDD temperatures in quick succession
    for dev in "${hdd_devices[@]}"; do
        if [ -e "/dev/$dev" ]; then
            # Use timeout to prevent hanging
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

    # Join with commas and spaces
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

        timestamp=$(date +"%Y-%m-%d %H:%M:%S")
        printf "%s: %3d (%d%%) (CPU %d°C) (HDD %s)\n" "$timestamp" "$raw" "$percent" "$cpu_temp" "$temp_str"

        # Publish each drive temp to MQTT
        for dev in "${hdd_devices[@]}"; do
            if [[ -n "${current_temps[$dev]:-}" ]]; then
                temp="${current_temps[$dev]}"

                # Auto-discovery config
                mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
                    -t "homeassistant/sensor/unas_${dev}/config" \
                    -m "{\"name\":\"UNAS ${dev} Temperature\",\"state_topic\":\"homeassistant/sensor/unas_${dev}/state\",\"unit_of_measurement\":\"°C\",\"device_class\":\"temperature\",\"unique_id\":\"unas_${dev}_temp\"}" \
                    -r

                # Actual temperature value
                mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
                    -t "homeassistant/sensor/unas_${dev}/state" \
                    -m "$temp"
            fi
        done

        # Publish CPU temperature to MQTT
        mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
            -t "homeassistant/sensor/unas_cpu/config" \
            -m "{\"name\":\"UNAS CPU Temperature\",\"state_topic\":\"homeassistant/sensor/unas_cpu/state\",\"unit_of_measurement\":\"°C\",\"device_class\":\"temperature\",\"unique_id\":\"unas_cpu_temp\"}" \
            -r

        mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
            -t "homeassistant/sensor/unas_cpu/state" \
            -m "$cpu_temp"

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