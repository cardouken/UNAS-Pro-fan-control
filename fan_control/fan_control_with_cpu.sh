#!/bin/bash
#
# Fan control service for UNAS Pro with configurable piecewise linear fan curve.
# Supports both CPU and HDD temperature monitoring with MQTT override capability.
#
# See UNAS Pro fan speed curve calculator in Google Sheets to calculate the desired fan speed values:
# https://docs.google.com/spreadsheets/d/1tRFY_sbZ05NGviTWXEZ2xo6C26Qct_KZbIP7jislLXI/edit?usp=sharing
#

set -euo pipefail

# CPU fan curve parameters (simple linear)
CPU_TGT=70            # temperature where CPU fans start ramping up
CPU_MAX=80            # temperature for full CPU fan

# HDD fan curve parameters (piecewise)
HDD_MIN_TEMP=38           # temp at which fans stay at baseline
HDD_SMOOTH_MAX=49         # temp at which fans reach gentle top
HDD_GENTLE_TOP=0.38       # fan % (0.38=38%) at HDD_SMOOTH_MAX
HDD_JUMP_TEMP=47          # temp at which fans jump to jump level
HDD_JUMP_LEVEL=0.6       # fan % (0.60=60%) at jump temp
HDD_AFTER_JUMP_STEP=0.05  # fan % (0.05=5%) to increase fans per °C above jump temp
MIN_FAN=64               # baseline PWM to keep fans at (64=~25%)

# MQTT config for override control
MQTT_HOST="192.168.1.111"
MQTT_USER="homeassistant"
MQTT_PASS="unas_password_123"
OVERRIDE_FILE="/tmp/fan_override"

# Service parameters
SERVICE_INTERVAL=1       # how often to check temperatures in service mode (seconds)

# CPU and HDD devices arrays
cpu_devices=("hwmon/hwmon0/temp1_input" "hwmon/hwmon0/temp2_input" "hwmon/hwmon0/temp3_input" "thermal/thermal_zone0/temp")
hdd_devices=(sda sdb sdc sdd sde sdf sdg)

# run as service: loop every N seconds based on SERVICE_INTERVAL, otherwise run once with logging
LOGGING=true
SERVICE=false
if [ "${1:-}" = "--service" ]; then
    LOGGING=false
    SERVICE=true
fi

log_echo() {
    if $LOGGING; then
        echo "$@"
    fi
}

# Check for MQTT override
check_mqtt_override() {
    # Subscribe to override topic and write to file (timeout after 0.5s)
    timeout 0.5 mosquitto_sub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "homeassistant/unas/fan_override" -C 1 2>/dev/null > "$OVERRIDE_FILE" || true
}

get_override_value() {
    if [ -f "$OVERRIDE_FILE" ]; then
        local override_val=$(cat "$OVERRIDE_FILE" 2>/dev/null || echo "")
        # Check if it's "auto" or a valid number 0-255
        if [ "$override_val" = "auto" ]; then
            echo "auto"
        elif [[ "$override_val" =~ ^[0-9]+$ ]] && [ "$override_val" -ge 0 ] && [ "$override_val" -le 255 ]; then
            echo "$override_val"
        else
            echo "auto"
        fi
    else
        echo "auto"
    fi
}

read_all_temperatures() {
    CPU_TEMP=0
    HDD_TEMP=0

    # Read all CPU temperatures in quick succession
    local cpu_temps=()
    local dev temp
    for dev in "${cpu_devices[@]}"; do
        if [ -f "/sys/class/$dev" ]; then
            temp=$(cat "/sys/class/$dev" 2>/dev/null || echo "0")
            temp=$((temp / 1000))
            cpu_temps+=("$temp")
            log_echo "/sys/class/$dev CPU Temp: ${temp}°C"
            if [[ "$temp" =~ ^[0-9]+$ ]] && [ "$temp" -gt "$CPU_TEMP" ]; then
                CPU_TEMP=$temp
            fi
        fi
    done

    # Read all HDD temperatures in quick succession
    local hdd_temps=()
    for dev in "${hdd_devices[@]}"; do
        if [ -e "/dev/$dev" ]; then
            # Use timeout to prevent hanging
            temp=$(timeout 5 smartctl -a "/dev/$dev" 2>/dev/null | awk '/194 Temperature_Celsius/ {print $10}' || echo "0")
            if [[ "$temp" =~ ^[0-9]+$ ]]; then
                hdd_temps+=("$temp")
                log_echo "/dev/$dev HDD Temp: ${temp}°C"
                if [ "$temp" -gt "$HDD_TEMP" ]; then
                    HDD_TEMP=$temp
                fi
            fi
        fi
    done
}

calculate_fan_speeds() {
    local cpu_temp=$1
    local hdd_temp=$2
    local fan_data

    fan_data=$(awk -v cpu_temp="$cpu_temp" -v hdd_temp="$hdd_temp" \
        -v cpu_tgt="$CPU_TGT" -v cpu_max="$CPU_MAX" \
        -v hdd_min_temp="$HDD_MIN_TEMP" -v hdd_smooth_max="$HDD_SMOOTH_MAX" \
        -v hdd_gentle_top="$HDD_GENTLE_TOP" -v hdd_jump_temp="$HDD_JUMP_TEMP" \
        -v hdd_jump_level="$HDD_JUMP_LEVEL" -v hdd_step="$HDD_AFTER_JUMP_STEP" \
        -v min_fan="$MIN_FAN" '
    BEGIN {
        # CPU fan calculation
        if (cpu_temp <= cpu_tgt) {
            cpu_ratio = 0
        } else if (cpu_temp >= cpu_max) {
            cpu_ratio = 1
        } else {
            cpu_ratio = (cpu_temp - cpu_tgt) / (cpu_max - cpu_tgt)
        }
        if (cpu_ratio < 0) cpu_ratio = 0
        if (cpu_ratio > 1) cpu_ratio = 1
        cpu_fan = int(cpu_ratio * 255)

        # HDD fan calculation (piecewise curve)
        min_fan_ratio = min_fan / 255
        if (hdd_temp <= hdd_min_temp) {
            hdd_fan_ratio = min_fan_ratio
        } else if (hdd_temp <= hdd_smooth_max) {
            hdd_fan_ratio = min_fan_ratio + (hdd_temp - hdd_min_temp) * (hdd_gentle_top - min_fan_ratio) / (hdd_smooth_max - hdd_min_temp)
        } else if (hdd_temp <= hdd_jump_temp) {
            hdd_fan_ratio = hdd_jump_level
        } else {
            hdd_fan_ratio = hdd_jump_level + (hdd_temp - hdd_jump_temp) * hdd_step
            if (hdd_fan_ratio > 1) hdd_fan_ratio = 1
        }
        hdd_fan = int(hdd_fan_ratio * 255)

        printf "%d %d", cpu_fan, hdd_fan
    }')

    read -r CPU_FAN HDD_FAN <<< "$fan_data"
}

set_fan_speed() {
    # Ensure manual fan control mode (prevents built-in controller interference)
    echo 1 > /sys/class/hwmon/hwmon0/pwm1_enable 2>/dev/null || true
    echo 1 > /sys/class/hwmon/hwmon0/pwm2_enable 2>/dev/null || true

    # Check for override every iteration
    check_mqtt_override