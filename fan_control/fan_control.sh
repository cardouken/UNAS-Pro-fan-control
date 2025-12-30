#!/bin/bash
#
# Fan control service for UNAS Pro with simple linear fan curve, optimized for Noctua NF-A8 PWM.
# Allows overriding this custom fan curve with a persistent value from HA that can be toggled on or set to auto.
#

set -euo pipefail

# Fan curve configuration
# Linear interpolation between MIN_TEMP and MAX_TEMP
# Below MIN_TEMP: MIN_FAN speed
# Above MAX_TEMP: MAX_FAN speed
# Between: Linear scaling

MIN_TEMP=43               # Temperature (°C) where fans start ramping up from baseline
MAX_TEMP=47               # Temperature (°C) where fans reach maximum speed
MIN_FAN=204               # Baseline PWM (204 = 80%)
MAX_FAN=255               # Maximum PWM (255 = 100%)

# Example configurations:
# Conservative (quieter, warmer drives):
#   MIN_TEMP=40, MAX_TEMP=50, MIN_FAN=153 (60%), MAX_FAN=255 (100%)
#   40°C: 60%, 45°C: 80%, 50°C: 100%
#
# Balanced (recommended for Noctua fans):
#   MIN_TEMP=43, MAX_TEMP=47, MIN_FAN=204 (80%), MAX_FAN=255 (100%)
#   43°C: 80%, 45°C: 90%, 47°C: 100%
#
# Aggressive (cooler, louder):
#   MIN_TEMP=38, MAX_TEMP=45, MIN_FAN=178 (70%), MAX_FAN=255 (100%)
#   38°C: 70%, 41.5°C: 85%, 45°C: 100%

SERVICE_INTERVAL=1        # how often to check temperatures (seconds)

# MQTT config for override control
MQTT_HOST="192.168.1.111"
MQTT_USER="homeassistant"
MQTT_PASS="unas_password_123"
OVERRIDE_FILE="/tmp/fan_override"

# HDD devices
hdd_devices=(sda sdb sdc sdd sde sdf)

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

# Check for MQTT override
check_mqtt_override() {
    # Subscribe to override topic and write to file (timeout after 0.5s)
    timeout 0.5 mosquitto_sub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "homeassistant/unas/fan_override" -C 1 2>/dev/null > "$OVERRIDE_FILE" || true
}

get_override_value() {
    if [ -f "$OVERRIDE_FILE" ]; then
        local override_val=$(cat "$OVERRIDE_FILE" 2>/dev/null || echo "")
        # Check if it's "auto" or a valid number 0-MAX_FAN
        if [ "$override_val" = "auto" ]; then
            echo "auto"
        elif [[ "$override_val" =~ ^[0-9]+$ ]] && [ "$override_val" -ge 0 ] && [ "$override_val" -le "$MAX_FAN" ]; then
            echo "$override_val"
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
    # Ensure manual fan control mode (prevents built-in controller interference)
    echo 1 > /sys/class/hwmon/hwmon0/pwm1_enable 2>/dev/null || true
    echo 1 > /sys/class/hwmon/hwmon0/pwm2_enable 2>/dev/null || true

    # Check for override every iteration
    check_mqtt_override
    local override=$(get_override_value)

    if [ "$override" != "auto" ]; then
        FAN_SPEED=$override
        echo "MANUAL OVERRIDE MODE ACTIVE: ${FAN_SPEED} ($((FAN_SPEED * 100 / MAX_FAN))%)"

        # Publish override fan speed
        mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
            -t "homeassistant/sensor/unas_fan_speed/state" \
            -m "$FAN_SPEED"
    else
        read_hdd_temperatures
        calculate_fan_speed "$HDD_TEMP"

        log_echo "== Fan Decision =="
        log_echo "Max HDD Temp: ${HDD_TEMP}°C → Fan PWM: ${FAN_SPEED} ($((FAN_SPEED * 100 / MAX_FAN))%)"
        log_echo "=================="

        # Publish auto-calculated fan speed
        mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
            -t "homeassistant/sensor/unas_fan_speed/state" \
            -m "$FAN_SPEED"
    fi

    # Auto-discovery config (publish once per iteration is fine)
    mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "homeassistant/sensor/unas_fan_speed/config" \
        -m "{\"name\":\"UNAS Fan Speed\",\"state_topic\":\"homeassistant/sensor/unas_fan_speed/state\",\"unit_of_measurement\":\"PWM\",\"unique_id\":\"unas_fan_speed\"}" \
        -r

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