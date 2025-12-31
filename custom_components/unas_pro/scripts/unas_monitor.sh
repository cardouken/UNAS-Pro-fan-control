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
MONITOR_INTERVAL=30

MQTT_HOST="192.168.1.111"
MQTT_USER="homeassistant"
MQTT_PASS="unas_password_123"

# Device identifiers for grouping
UNAS_DEVICE='{"identifiers":["unas_pro"],"name":"UNAS Pro","manufacturer":"Ubiquiti","model":"UNAS Pro"}'

# UNAS Pro bay mapping (ATA port -> physical bay number as shown in Unifi UI)
declare -A ATA_TO_BAY_MAP=(
    ["1"]="6"   # ata1 -> Bay 6
    ["3"]="7"   # ata3 -> Bay 7
    ["4"]="3"   # ata4 -> Bay 3
    ["5"]="5"   # ata5 -> Bay 5
    ["6"]="2"   # ata6 -> Bay 2
    ["7"]="4"   # ata7 -> Bay 4
    ["8"]="1"   # ata8 -> Bay 1
)

# Auto-detect all SATA/NVMe drives (excludes loop, ram, etc.)
detect_drives() {
    local drives=()
    for dev in /dev/sd? /dev/nvme?n?; do
        if [ -b "$dev" ]; then
            drives+=("$(basename "$dev")")
        fi
    done
    echo "${drives[@]}"
}

# Get physical bay number from device name
get_bay_number() {
    local dev=$1
    local ata_port
    
    # Get ATA port number from udev path
    ata_port=$(udevadm info -q path -n "/dev/$dev" 2>/dev/null | grep -oP 'ata\K[0-9]+' || echo "")
    
    if [ -n "$ata_port" ] && [ -n "${ATA_TO_BAY_MAP[$ata_port]:-}" ]; then
        echo "${ATA_TO_BAY_MAP[$ata_port]}"
    else
        echo "unknown"
    fi
}

# Helper function to publish MQTT sensor state (no auto-discovery)
publish_mqtt_sensor() {
    local sensor_name=$1
    local value=$3
    
    # publish state with retain flag so entities get initial values
    mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "homeassistant/sensor/${sensor_name}/state" \
        -m "$value" \
        -r
}

# Function to read system info (uptime, versions, cpu, memory)
read_system_info() {
    local uptime_seconds unifi_os_version unifi_drive_version
    local cpu_usage mem_total mem_used mem_percent
    
    # Get uptime in seconds
    uptime_seconds=$(awk '{print int($1)}' /proc/uptime)
    
    # Get UniFi OS version (from unifi-core package)
    unifi_os_version=$(dpkg -l | awk '/unifi-core/ {print $3}')
    
    # Get UniFi Drive version
    unifi_drive_version=$(dpkg -l | awk '/^ii  unifi-drive / {print $3}')
    
    # Get CPU usage (100 - idle%)
    cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print 100 - $8}' | awk -F. '{print $1}')
    
    # Get memory usage
    mem_total=$(free -m | awk '/^Mem:/ {print $2}')
    mem_used=$(free -m | awk '/^Mem:/ {print $3}')
    mem_percent=$(awk "BEGIN {printf \"%.1f\", ($mem_used / $mem_total) * 100}")
    
    # Publish system info under main UNAS device
    publish_mqtt_sensor "unas_uptime" "System Uptime" "$uptime_seconds" "s" "duration" "$UNAS_DEVICE"
    publish_mqtt_sensor "unas_os_version" "UniFi OS Version" "$unifi_os_version" "" "" "$UNAS_DEVICE"
    publish_mqtt_sensor "unas_drive_version" "UniFi Drive Version" "$unifi_drive_version" "" "" "$UNAS_DEVICE"
    publish_mqtt_sensor "unas_cpu_usage" "CPU Usage" "$cpu_usage" "%" "" "$UNAS_DEVICE"
    publish_mqtt_sensor "unas_memory_used" "Memory Used" "$mem_used" "MB" "data_size" "$UNAS_DEVICE"
    publish_mqtt_sensor "unas_memory_total" "Memory Total" "$mem_total" "MB" "data_size" "$UNAS_DEVICE"
    publish_mqtt_sensor "unas_memory_usage" "Memory Usage" "$mem_percent" "%" "" "$UNAS_DEVICE"
}

# Read drive data (SMART attributes + disk usage)
read_drive_data() {
    local dev smart_output temp model serial rpm status health power_hours bad_sectors firmware
    local total_size_bytes total_size_tb manufacturer bay_num
    local hdd_devices

    # Get list of drives dynamically
    read -ra hdd_devices <<< "$(detect_drives)"

    for dev in "${hdd_devices[@]}"; do
        if [ ! -e "/dev/$dev" ]; then
            continue
        fi

        # Get physical bay number
        bay_num=$(get_bay_number "$dev")
        if [ "$bay_num" = "unknown" ] || [ "$bay_num" = "0" ]; then
            continue
        fi

        # Get SMART data
        smart_output=$(timeout 10 smartctl -a "/dev/$dev" 2>/dev/null || echo "")
        if [ -z "$smart_output" ]; then
            continue
        fi

        # Parse SMART attributes
        temp=$(echo "$smart_output" | awk '/194 Temperature_Celsius/ {print $10}' || echo "unknown")
        model=$(echo "$smart_output" | awk -F': ' '/Device Model:/ {print $2; exit} /Product:/ {print $2; exit}' | xargs || echo "unknown")
        serial=$(echo "$smart_output" | awk -F': ' '/Serial Number:/ {print $2}' | xargs || echo "unknown")
        firmware=$(echo "$smart_output" | awk -F': ' '/Firmware Version:/ {print $2}' | xargs || echo "unknown")
        power_hours=$(echo "$smart_output" | awk '/Power_On_Hours/ {print $10; exit} /power on hours/ {print $4; exit}' || echo "0")
        bad_sectors=$(echo "$smart_output" | awk '/Reallocated_Sector_Ct/ {print $10; exit} /reallocated sectors/ {print $4; exit}' || echo "0")
        
        # Parse RPM
        rpm=$(echo "$smart_output" | awk -F': ' '/Rotation Rate:/ {print $2}' | xargs)
        case "$rpm" in
            ""|"Solid State Device") rpm="SSD" ;;
            *[!0-9]*) rpm=$(echo "$rpm" | grep -oE '[0-9]+' | head -1); [ -z "$rpm" ] && rpm="unknown" ;;
        esac
        
        # Extract manufacturer from model (usually just the first word)
        manufacturer=$(echo "$model" | awk '{print $1}')
        
        # SMART health status
        health=$(echo "$smart_output" | grep -i "SMART overall-health" | awk '{print $NF}' || echo "unknown")
        status=$([ "$health" = "PASSED" ] && echo "Optimal" || echo "Warning")

        # Get disk size from blockdev
        total_size_bytes=$(blockdev --getsize64 "/dev/$dev" 2>/dev/null || echo "0")
        total_size_tb=$(awk "BEGIN {printf \"%.2f\", $total_size_bytes / 1024 / 1024 / 1024 / 1024}")
        
        # Build device definition with bay number in name
        local drive_name="HDD $bay_num"
        local drive_device="{\"identifiers\":[\"unas_drive_bay${bay_num}\"],\"name\":\"UNAS $drive_name\",\"manufacturer\":\"$manufacturer\",\"model\":\"$model\",\"serial_number\":\"$serial\",\"hw_version\":\"$firmware\",\"via_device\":\"unas_pro\"}"

        # Publish all drive attributes grouped under this drive's device (using bay number)
        publish_mqtt_sensor "unas_hdd_${bay_num}_temperature" "Temperature" "$temp" "°C" "temperature" "$drive_device"
        publish_mqtt_sensor "unas_hdd_${bay_num}_model" "Model" "$model" "" "" "$drive_device"
        publish_mqtt_sensor "unas_hdd_${bay_num}_serial" "Serial Number" "$serial" "" "" "$drive_device"
        publish_mqtt_sensor "unas_hdd_${bay_num}_rpm" "RPM" "$rpm" "rpm" "" "$drive_device"
        publish_mqtt_sensor "unas_hdd_${bay_num}_firmware" "Firmware" "$firmware" "" "" "$drive_device"
        publish_mqtt_sensor "unas_hdd_${bay_num}_status" "Status" "$status" "" "" "$drive_device"
        publish_mqtt_sensor "unas_hdd_${bay_num}_total_size" "Total Size" "$total_size_tb" "TB" "data_size" "$drive_device"
        publish_mqtt_sensor "unas_hdd_${bay_num}_power_hours" "Power-On Hours" "$power_hours" "h" "duration" "$drive_device"
        publish_mqtt_sensor "unas_hdd_${bay_num}_bad_sectors" "Bad Sectors" "$bad_sectors" "" "" "$drive_device"
    done
}

# Format temperature output for console logging
format_temperature_output() {
    local temps_output=()
    local dev temp smart_output
    local hdd_devices

    # Get list of drives dynamically
    read -ra hdd_devices <<< "$(detect_drives)"

    for dev in "${hdd_devices[@]}"; do
        if [ -e "/dev/$dev" ]; then
            smart_output=$(timeout 5 smartctl -a "/dev/$dev" 2>/dev/null || echo "")
            temp=$(echo "$smart_output" | awk '/194 Temperature_Celsius/ {print $10}' || echo "0")
            if [[ "$temp" =~ ^[0-9]+$ ]] && [ "$temp" != "0" ]; then
                temps_output+=("${temp}°C")
            fi
        fi
    done

    (IFS=", "; echo "${temps_output[*]}")
}

# Publish storage pool to MQTT
publish_storage_pool() {
    local pool_num=$1 size_gb=$2 used_gb=$3 avail_gb=$4 capacity_num=$5
    local fs_name="pool${pool_num}"

    publish_mqtt_sensor "unas_${fs_name}_usage" "Storage Pool ${pool_num} Usage" "$capacity_num"
    publish_mqtt_sensor "unas_${fs_name}_size" "Storage Pool ${pool_num} Size" "$size_gb"
    publish_mqtt_sensor "unas_${fs_name}_used" "Storage Pool ${pool_num} Used" "$used_gb"
    publish_mqtt_sensor "unas_${fs_name}_available" "Storage Pool ${pool_num} Available" "$avail_gb"
}

# Read storage pool usage from UniFi Drive /volume mounts
read_storage_usage() {
    local pool_num=1
    local -a volume_dirs

    # collect and sort volume directories for consistent ordering
    mapfile -t volume_dirs < <(find /volume -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort)

    # Iterate through sorted /volume mounts (each UUID is a storage pool)
    for volume_dir in "${volume_dirs[@]}"; do
        [ -d "$volume_dir" ] || continue

        local df_output=$(df -BG "$volume_dir" 2>/dev/null | tail -n 1)
        [ -n "$df_output" ] || continue

        read -r source size used avail pcent mountpoint <<< "$df_output"
        local size_gb=${size%G}

        # Only process if larger than 75GB (avoid boot/system partitions)
        if [[ "$size_gb" -gt 75 ]]; then
            publish_storage_pool "$pool_num" "$size_gb" "${used%G}" "${avail%G}" "${pcent%\%}"
            pool_num=$((pool_num + 1))
        fi
    done
}

# Main monitoring loop
monitor_system() {
    local next_ts raw percent timestamp temp_str cpu_temp

    next_ts=$(date +%s)

    while true; do
        raw=$(cat /sys/class/hwmon/hwmon0/pwm1)
        percent=$(( raw * 100 / 255 ))

        cpu_temp=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
        cpu_temp=$((cpu_temp / 1000))

        # Read system info (uptime, versions, cpu, memory)
        read_system_info

        # Read all drive data (SMART attributes)
        read_drive_data

        # Read storage pool usage
        read_storage_usage

        # Get temperature string for console output
        temp_str=$(format_temperature_output)

        timestamp=$(date +"%Y-%m-%d %H:%M:%S")
        printf "%s: %3d (%d%%) (CPU %d°C) (HDD %s)\n" "$timestamp" "$raw" "$percent" "$cpu_temp" "$temp_str"

        # Publish CPU temperature and fan speed under main UNAS device
        publish_mqtt_sensor "unas_cpu" "CPU Temperature" "$cpu_temp" "°C" "temperature" "$UNAS_DEVICE"
        publish_mqtt_sensor "unas_fan_speed" "Fan Speed" "$raw" "PWM" "" "$UNAS_DEVICE"
        publish_mqtt_sensor "unas_fan_speed_percent" "Fan Speed Percentage" "$percent" "%" "" "$UNAS_DEVICE"

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
monitor_system
