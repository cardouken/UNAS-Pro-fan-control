#!/bin/bash
#
# Fan control service for UNAS Pro with simple linear fan curve, optimized for Noctua NF-A8 PWM.
# Allows overriding this custom fan curve with a persistent value from HA that can be toggled on or set to auto.
#

set -euo pipefail

# Fan curve (linear between points)
# 43°C and under: 80% (204 PWM)
# 44°C: 85% (217 PWM)
# 45°C: 90% (230 PWM)
# 46°C: 95% (242 PWM)
# 47°C+: 100% (255 PWM)

MIN_FAN=204               # 80% baseline
SERVICE_INTERVAL=1        # how often to check temperatures (seconds)

# MQTT config for override control
MQTT_HOST="192.168.1.111"
MQTT_USER="homeassistant"
MQTT_PASS="unas_password_123"
OVERRIDE_FILE="/tmp/fan_override"

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

    # Simple linear interpolation: 43°C=204, 47°C=255
    # Below 43°C: 204 (80%)
    # 43-47°C: linear scale
    # Above 47°C: 255 (100%)

    if [ "$hdd_temp" -le 43 ]; then
        FAN_SPEED=204
    elif [ "$hdd_temp" -ge 47 ]; then
        FAN_SPEED=255
    else
        # Linear: 204 + (temp - 43) * (255 - 204) / (47 - 43)
        # = 204 + (temp - 43) * 12.75
        FAN_SPEED=$(awk -v temp="$hdd_temp" 'BEGIN {print int(204 + (temp - 43) * 12.75)}')
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
        echo "MANUAL OVERRIDE MODE ACTIVE: ${FAN_SPEED} ($((FAN_SPEED * 100 / 255))%)"

        # Publish override fan speed
        mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
            -t "homeassistant/sensor/unas_fan_speed/state" \
            -m "$FAN_SPEED"
    else
        read_hdd_temperatures
        calculate_fan_speed "$HDD_TEMP"

        log_echo "== Fan Decision =="
        log_echo "Max HDD Temp: ${HDD_TEMP}°C → Fan PWM: ${FAN_SPEED} ($((FAN_SPEED * 100 / 255))%)"
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