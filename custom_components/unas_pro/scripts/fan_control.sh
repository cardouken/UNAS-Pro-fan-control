#!/bin/bash
#
# Fan control service for UNAS Pro with simple linear fan curve, optimized for Noctua NF-A8 PWM.
# Allows overriding this custom fan curve with a persistent value from HA that can be toggled on or set to auto.
#

set -euo pipefail

# Fan curve configuration - loaded from MQTT or defaults
# Linear interpolation between MIN_TEMP and MAX_TEMP
# Below MIN_TEMP: MIN_FAN speed
# Above MAX_TEMP: MAX_FAN speed
# Between: Linear scaling

# Default values (will be overridden by MQTT if available)
DEFAULT_MIN_TEMP=40       # Temperature (°C) where fans start ramping up from baseline
DEFAULT_MAX_TEMP=50       # Temperature (°C) where fans reach maximum speed
DEFAULT_MIN_FAN=64        # Baseline PWM (64 = 25%)
DEFAULT_MAX_FAN=255       # Maximum PWM (255 = 100%)

# Current values (loaded from MQTT)
MIN_TEMP=$DEFAULT_MIN_TEMP
MAX_TEMP=$DEFAULT_MAX_TEMP
MIN_FAN=$DEFAULT_MIN_FAN
MAX_FAN=$DEFAULT_MAX_FAN

# Example configurations:
# Conservative (quieter, warmer drives):
#   MIN_TEMP=40, MAX_TEMP=50, MIN_FAN=153 (60%), MAX_FAN=255 (100%)
#   40°C: 60%, 45°C: 80%, 50°C: 100%
#
# Balanced (recommended for Noctua NF-A8 PWM fans):
#   MIN_TEMP=43, MAX_TEMP=47, MIN_FAN=204 (80%), MAX_FAN=255 (100%)
#   43°C: 80%, 45°C: 90%, 47°C: 100%
#
# Aggressive (cooler, louder):
#   MIN_TEMP=38, MAX_TEMP=45, MIN_FAN=178 (70%), MAX_FAN=255 (100%)
#   38°C: 70%, 41.5°C: 85%, 45°C: 100%

SERVICE_INTERVAL=1        # how often to check temperatures (seconds)

# MQTT config for mode control
MQTT_HOST="192.168.1.111"
MQTT_USER="homeassistant"
MQTT_PASS="unas_password_123"
MODE_FILE="/root/fan_mode"  # Persistent storage (survives reboots)

# HDD devices
hdd_devices=(sda sdb sdc sdd sde sdf sdg)

# run as service: loop every N seconds, otherwise run once with logging
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

# Load fan curve configuration from MQTT
load_fan_curve() {
    local min_temp=$(timeout 0.5 mosquitto_sub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "homeassistant/unas/fan_curve/min_temp" -C 1 2>/dev/null || true)
    local max_temp=$(timeout 0.5 mosquitto_sub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "homeassistant/unas/fan_curve/max_temp" -C 1 2>/dev/null || true)
    local min_fan=$(timeout 0.5 mosquitto_sub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "homeassistant/unas/fan_curve/min_fan" -C 1 2>/dev/null || true)
    local max_fan=$(timeout 0.5 mosquitto_sub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "homeassistant/unas/fan_curve/max_fan" -C 1 2>/dev/null || true)

    # Update values if they were retrieved successfully (otherwise keep defaults)
    if [[ "$min_temp" =~ ^[0-9]+$ ]]; then MIN_TEMP=$min_temp; fi
    if [[ "$max_temp" =~ ^[0-9]+$ ]]; then MAX_TEMP=$max_temp; fi
    if [[ "$min_fan" =~ ^[0-9]+$ ]]; then MIN_FAN=$min_fan; fi
    if [[ "$max_fan" =~ ^[0-9]+$ ]]; then MAX_FAN=$max_fan; fi
}

# Check for MQTT mode
check_mqtt_mode() {
    # Subscribe to mode topic and write to file (timeout after 0.5s)
    timeout 0.5 mosquitto_sub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "homeassistant/unas/fan_mode" -C 1 2>/dev/null > "$MODE_FILE" || true
}

get_mode_value() {
    if [ -f "$MODE_FILE" ]; then
        local mode_val=$(cat "$MODE_FILE" 2>/dev/null || echo "")
        # Check if it's "unas_managed", "auto" or a valid number 0-MAX_FAN
        if [ "$mode_val" = "unas_managed" ]; then
            echo "unas_managed"
        elif [ "$mode_val" = "auto" ]; then
            echo "auto"
        elif [[ "$mode_val" =~ ^[0-9]+$ ]] && [ "$mode_val" -ge 0 ] && [ "$mode_val" -le "$MAX_FAN" ]; then
            echo "$mode_val"
        else
            echo "auto"
        fi
    else
        echo "auto"
    fi
}

read_hdd_temperatures() {
    HDD_TEMP=0

    for dev in "${hdd_devices[@]}"; do
        if [ -e "/dev/$dev" ]; then
            temp=$(timeout 5 smartctl -a "/dev/$dev" 2>/dev/null | awk '/194 Temperature_Celsius/ {print $10}' || echo "0")
            if [[ "$temp" =~ ^[0-9]+$ ]]; then
                log_echo "/dev/$dev HDD Temp: ${temp}°C"
                if [ "$temp" -gt "$HDD_TEMP" ]; then
                    HDD_TEMP=$temp
                fi
            fi
        fi
    done
}

calculate_fan_speed() {
    local hdd_temp=$1

    # Simple linear interpolation between MIN_TEMP and MAX_TEMP
    if [ "$hdd_temp" -le "$MIN_TEMP" ]; then
        FAN_SPEED=$MIN_FAN
    elif [ "$hdd_temp" -ge "$MAX_TEMP" ]; then
        FAN_SPEED=$MAX_FAN
    else
        # Linear: MIN_FAN + (temp - MIN_TEMP) * (MAX_FAN - MIN_FAN) / (MAX_TEMP - MIN_TEMP)
        FAN_SPEED=$(awk -v temp="$hdd_temp" -v min_temp="$MIN_TEMP" -v max_temp="$MAX_TEMP" -v min_fan="$MIN_FAN" -v max_fan="$MAX_FAN" \
            'BEGIN {print int(min_fan + (temp - min_temp) * (max_fan - min_fan) / (max_temp - min_temp))}')
    fi
}

set_fan_speed() {
    # Load fan curve configuration from MQTT (only in auto mode)
    load_fan_curve

    # Check for mode every iteration
    check_mqtt_mode
    local mode=$(get_mode_value)

    if [ "$mode" = "unas_managed" ]; then
        # UNAS Managed mode: Enable automatic fan control, let UNAS firmware manage fans
        # pwm_enable values: 1 = manual control, 2 = automatic (UNAS firmware controls)
        current_enable=$(cat /sys/class/hwmon/hwmon0/pwm1_enable 2>/dev/null || echo "1")

        if [ "$current_enable" != "2" ]; then
            echo 2 > /sys/class/hwmon/hwmon0/pwm1_enable 2>/dev/null || true
            echo 2 > /sys/class/hwmon/hwmon0/pwm2_enable 2>/dev/null || true
            echo "UNAS MANAGED MODE: Switched to UNAS firmware control (pwm_enable=2)"
        fi

        # Read current fan speed set by UNAS firmware
        FAN_SPEED=$(cat /sys/class/hwmon/hwmon0/pwm1 2>/dev/null || echo "0")

        log_echo "UNAS MANAGED MODE: UNAS firmware controlling fans (Current: ${FAN_SPEED} PWM, $((FAN_SPEED * 100 / 255))%)"

        # Publish current fan speed
        mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
            -t "homeassistant/sensor/unas_fan_speed/state" \
            -m "$FAN_SPEED"

        # In UNAS managed mode, we don't touch the fans - just monitor and report
        return

    elif [ "$mode" = "auto" ]; then
        # Custom Curve mode: Use our temperature-based curve
        # Ensure manual fan control mode (prevents built-in controller interference)
        echo 1 > /sys/class/hwmon/hwmon0/pwm1_enable 2>/dev/null || true
        echo 1 > /sys/class/hwmon/hwmon0/pwm2_enable 2>/dev/null || true

        read_hdd_temperatures
        calculate_fan_speed "$HDD_TEMP"

        echo "CUSTOM CURVE MODE: Max HDD Temp ${HDD_TEMP}°C → Fan PWM ${FAN_SPEED} ($((FAN_SPEED * 100 / MAX_FAN))%)"

        # Apply fan speed
        echo $FAN_SPEED > /sys/class/hwmon/hwmon0/pwm1
        echo $FAN_SPEED > /sys/class/hwmon/hwmon0/pwm2

        # Publish auto-calculated fan speed
        mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
            -t "homeassistant/sensor/unas_fan_speed/state" \
            -m "$FAN_SPEED"

    else
        # Set Speed mode: Use manual mode value
        # Ensure manual fan control mode (prevents built-in controller interference)
        echo 1 > /sys/class/hwmon/hwmon0/pwm1_enable 2>/dev/null || true
        echo 1 > /sys/class/hwmon/hwmon0/pwm2_enable 2>/dev/null || true

        FAN_SPEED=$mode
        echo "SET SPEED MODE: ${FAN_SPEED} ($((FAN_SPEED * 100 / MAX_FAN))%)"

        # Apply fan speed
        echo $FAN_SPEED > /sys/class/hwmon/hwmon0/pwm1
        echo $FAN_SPEED > /sys/class/hwmon/hwmon0/pwm2

        # Publish mode fan speed
        mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
            -t "homeassistant/sensor/unas_fan_speed/state" \
            -m "$FAN_SPEED"
    fi

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
