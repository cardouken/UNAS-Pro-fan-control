#!/bin/bash
#
# Fan control service for UNAS Pro with configurable piecewise linear fan curve.
#
# See UNAS Pro fan speed curve calculator in Google Sheets to calculate the desired fan speed values:
# https://docs.google.com/spreadsheets/d/1tRFY_sbZ05NGviTWXEZ2xo6C26Qct_KZbIP7jislLXI/edit?usp=sharing
#

set -euo pipefail

# CPU fan curve parameters (simple linear)
CPU_TGT=70            # temperature where CPU fans start ramping up
CPU_MAX=80            # temperature for full CPU fan

# HDD fan curve parameters (piecewise)
HDD_MIN_TEMP=43           # temp at which fans stay at baseline
HDD_SMOOTH_MAX=49         # temp at which fans reach gentle top
HDD_GENTLE_TOP=0.38       # fan % (0.38=38%) at HDD_SMOOTH_MAX
HDD_JUMP_TEMP=50          # temp at which fans jump to jump level
HDD_JUMP_LEVEL=0.60       # fan % (0.60=60%) at jump temp
HDD_AFTER_JUMP_STEP=0.05  # fan % (0.05=5%) to increase fans per °C above jump temp

MIN_FAN=64                # baseline PWM to keep fans at (64=~25%)

# run as service: loop every 20s, otherwise run once with logging
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

# Piecewise HDD fan curve
fan_curve() {
    local temp=$1

    fan_speed=$(awk -v temp="$temp" \
        -v min_temp="$HDD_MIN_TEMP" -v smooth_max="$HDD_SMOOTH_MAX" \
        -v gentle_top="$HDD_GENTLE_TOP" -v jump_temp="$HDD_JUMP_TEMP" \
        -v jump_level="$HDD_JUMP_LEVEL" -v step="$HDD_AFTER_JUMP_STEP" '
    BEGIN {
        if (temp <= min_temp) {
            fan = 0.25
        } else if (temp <= smooth_max) {
            fan = 0.25 + (temp - min_temp) * (gentle_top - 0.25) / (smooth_max - min_temp)
        } else if (temp == jump_temp) {
            fan = jump_level
        } else {
            fan = jump_level + (temp - jump_temp) * step
            if (fan > 1) fan = 1
        }
        pwm = int(fan * 255)
        printf "%d", pwm
    }')
    echo $fan_speed
}

set_fan_speed() {
    # Read CPU temperatures from sensors
    cpu_devices=("hwmon/hwmon0/temp1_input" "hwmon/hwmon0/temp2_input" "hwmon/hwmon0/temp3_input" "thermal/thermal_zone0/temp")
    CPU_TEMP=0
    for dev in "${cpu_devices[@]}"; do
        if [ -f "/sys/class/$dev" ]; then
            temp=$(cat "/sys/class/$dev")
            temp=$((temp / 1000))
            log_echo "/sys/class/$dev CPU Temp: ${temp}°C"
            if [[ "$temp" =~ ^[0-9]+$ ]] && [ "$temp" -gt "$CPU_TEMP" ]; then
                CPU_TEMP=$temp
            fi
        fi
    done

    # Read HDD temperatures
    hdd_devices=(sda sdb sdc sdd sde sdf sdg)
    HDD_TEMP=0
    for dev in "${hdd_devices[@]}"; do
        if smartctl -a "/dev/$dev" &>/dev/null; then
            temp=$(smartctl -a "/dev/$dev" | awk '/194 Temperature_Celsius/ {print $10}')
            log_echo "/dev/$dev HDD Temp: ${temp}°C"
            if [[ "$temp" =~ ^[0-9]+$ ]] && [ "$temp" -gt "$HDD_TEMP" ]; then
                HDD_TEMP=$temp
            fi
        fi
    done

    # CPU fan: simple linear from CPU_TGT–CPU_MAX -> 0–255
    CPU_RATIO=$(awk -v temp="$CPU_TEMP" -v tgt="$CPU_TGT" -v max="$CPU_MAX" '
    BEGIN {
        if (temp <= tgt) { ratio=0 }
        else if (temp >= max) { ratio=1 }
        else { ratio=(temp - tgt) / (max - tgt) }
        if (ratio < 0) ratio=0
        if (ratio > 1) ratio=1
        printf "%f", ratio
    }')
    CPU_FAN=$(awk -v ratio="$CPU_RATIO" 'BEGIN { printf "%d", ratio * 255 }')

    # HDD fan using piecewise curve
    HDD_FAN=$(fan_curve "$HDD_TEMP")

    # Final fan speed: max of CPU_FAN, HDD_FAN, and MIN_FAN
    FAN_SPEED=$(( CPU_FAN > HDD_FAN ? CPU_FAN : HDD_FAN ))
    FAN_SPEED=$(( FAN_SPEED < MIN_FAN ? MIN_FAN : FAN_SPEED ))

    # Logging
    log_echo "== Fan Decision =="
    log_echo "CPU Temp: ${CPU_TEMP}°C → CPU Fan PWM: ${CPU_FAN} ($((CPU_FAN * 100 / 255))%)"
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
        sleep 20
    done
else
    set_fan_speed
fi
