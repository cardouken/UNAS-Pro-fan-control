#!/bin/bash
#
# Fan control service for UNAS Pro with configurable piecewise linear fan curve. Based only on HDD temps.
#
# See UNAS Pro fan speed curve calculator in Google Sheets to calculate the desired fan speed values:
# https://docs.google.com/spreadsheets/d/1tRFY_sbZ05NGviTWXEZ2xo6C26Qct_KZbIP7jislLXI/edit?usp=sharing
#

set -euo pipefail

# HDD fan curve parameters (piecewise)
HDD_MIN_TEMP=40           # temp at which fans stay at baseline
HDD_SMOOTH_MAX=49         # temp at which fans reach gentle top
HDD_GENTLE_TOP=0.55       # fan % (0.38=38%) at HDD_SMOOTH_MAX
HDD_JUMP_TEMP=50          # temp at which fans jump to jump level
HDD_JUMP_LEVEL=0.65       # fan % (0.60=60%) at jump temp
HDD_AFTER_JUMP_STEP=0.05  # fan % (0.05=5%) to increase fans per °C above jump temp
MIN_FAN=64                # baseline PWM to keep fans at (64=~25%)

# Service parameters
SERVICE_INTERVAL=3       # how often to check temperatures in service mode (seconds)

# HDD devices arrays
hdd_devices=(sda sdb sdc sdd sde sdf sdg)

# Parameter checks
if [ "$HDD_SMOOTH_MAX" -le "$HDD_MIN_TEMP" ]; then
    echo "Error: HDD_SMOOTH_MAX ($HDD_SMOOTH_MAX) must be greater than HDD_MIN_TEMP ($HDD_MIN_TEMP)" >&2
    exit 1
fi

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

read_all_temperatures() {
    HDD_TEMP=0

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
    local hdd_temp=$2
    local fan_data

    fan_data=$(awk -v hdd_temp="$hdd_temp" \
        -v hdd_min_temp="$HDD_MIN_TEMP" -v hdd_smooth_max="$HDD_SMOOTH_MAX" \
        -v hdd_gentle_top="$HDD_GENTLE_TOP" -v hdd_jump_temp="$HDD_JUMP_TEMP" \
        -v hdd_jump_level="$HDD_JUMP_LEVEL" -v hdd_step="$HDD_AFTER_JUMP_STEP" \
        -v min_fan="$MIN_FAN" '
    BEGIN {
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

        printf "%d", hdd_fan
    }')

    read -r HDD_FAN <<< "$fan_data"
}

set_fan_speed() {
    # Read temperatures from sensors
    read_all_temperatures

    # Calculate all fan speeds in single AWK call
    calculate_fan_speeds "$HDD_TEMP"

    # Final fan speed: max of HDD_FAN, and MIN_FAN
    FAN_SPEED=$(( HDD_FAN < MIN_FAN ? MIN_FAN : HDD_FAN ))

    # Logging
    log_echo "== Fan Decision =="
    log_echo "Max HDD Temp: ${HDD_TEMP}°C → HDD Fan PWM: ${HDD_FAN} ($((HDD_FAN * 100 / 255))%)"
    log_echo "Final Fan PWM: ${FAN_SPEED} ($((FAN_SPEED * 100 / 255))%)"
    log_echo "=================="

    # Apply fan speed
    echo $FAN_SPEED > /sys/class/hwmon/hwmon0/pwm1
    echo $FAN_SPEED > /sys/class/hwmon/hwmon0/pwm2

    if $LOGGING; then
        echo "Confirmed fan speeds:"
        cat /sys/class/hwmon/hwmon0/pwm1
        cat /sys/class/hwmon/hwmon0/pwm2
    fi
}

if $SERVICE; then
    while true; do
        set_fan_speed
        sleep "$SERVICE_INTERVAL"
    done
else
    set_fan_speed
fi

