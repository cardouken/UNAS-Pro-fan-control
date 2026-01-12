#!/bin/bash

set -euo pipefail

MQTT_HOST="REPLACE_ME"
MQTT_USER="REPLACE_ME"
MQTT_PASS="REPLACE_ME"
MQTT_ROOT="REPLACE_ME"
MQTT_SYSTEM="${MQTT_ROOT}/system"
MQTT_CONTROL="${MQTT_ROOT}/control"
MQTT_FAN="${MQTT_CONTROL}/fan"

HDD_DEVICES=(sda sdb sdc sdd sde sdf sdg)

STATE_FILE="/tmp/fan_control_state"
LAST_PWM_FILE="/tmp/fan_control_last_pwm"

# Default values
FAN_MODE="unas_managed"
MIN_TEMP=40
MAX_TEMP=50
MIN_FAN=64
MAX_FAN=255

# Initialize state file with defaults
{
    echo "FAN_MODE=$FAN_MODE"
    echo "MIN_TEMP=$MIN_TEMP"
    echo "MAX_TEMP=$MAX_TEMP"
    echo "MIN_FAN=$MIN_FAN"
    echo "MAX_FAN=$MAX_FAN"
} > "$STATE_FILE"

echo "0" > "$LAST_PWM_FILE"

SERVICE=false
[ "${1:-}" = "--service" ] && SERVICE=true

update_state_from_mqtt() {
    local topic=$1 payload=$2
    local var_name
    
    case "${topic##*/}" in
        mode)
            var_name="FAN_MODE"
            ;;
        min_temp)
            [[ "$payload" =~ ^[0-9]+$ ]] || return
            var_name="MIN_TEMP"
            ;;
        max_temp)
            [[ "$payload" =~ ^[0-9]+$ ]] || return
            var_name="MAX_TEMP"
            ;;
        min_fan)
            [[ "$payload" =~ ^[0-9]+$ ]] || return
            var_name="MIN_FAN"
            ;;
        max_fan)
            [[ "$payload" =~ ^[0-9]+$ ]] || return
            var_name="MAX_FAN"
            ;;
        *)
            return
            ;;
    esac
    
    sed -i "s/^${var_name}=.*/${var_name}=${payload}/" "$STATE_FILE"
}

# Fetch retained MQTT messages on startup (retry up to 30 times every 2 seconds in case MQTT connection not ready yet)
echo "Fetching MQTT state..."
MQTT_OUTPUT=""
for i in {1..30}; do
    MQTT_OUTPUT=$(timeout 5 mosquitto_sub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
        -t "${MQTT_FAN}/mode" \
        -t "${MQTT_FAN}/curve/+" \
        -C 5 \
        -F "%t %p" 2>/dev/null || true)
    
    if [ -n "$MQTT_OUTPUT" ]; then
        break
    fi
    
    [ "$i" -lt 30 ] && sleep 2
done

if [ -n "$MQTT_OUTPUT" ]; then
    echo "$MQTT_OUTPUT" | while read -r topic payload; do
        update_state_from_mqtt "$topic" "$payload"
    done
    echo "Fan control initialized with MQTT state:"
else
    echo "No retained MQTT messages found, using defaults:"
fi

cat "$STATE_FILE"

# Start persistent MQTT subscription for updates
mosquitto_sub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
    -t "${MQTT_FAN}/mode" \
    -t "${MQTT_FAN}/curve/+" \
    -F "%t %p" 2>/dev/null | while read -r topic payload; do
    update_state_from_mqtt "$topic" "$payload"
done &
MQTT_PID=$!

cleanup() {
    kill "$MQTT_PID" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

get_max_hdd_temp() {
    local max=0 temp
    for dev in "${HDD_DEVICES[@]}"; do
        [ -e "/dev/$dev" ] || continue
        temp=$(timeout 5 smartctl -a "/dev/$dev" 2>/dev/null | awk '/194 Temperature_Celsius/ {print $10}' || echo 0)
        [[ "$temp" =~ ^[0-9]+$ ]] && [ "$temp" -gt "$max" ] && max=$temp
    done
    echo "$max"
}

calculate_pwm() {
    local temp=$1 min_temp=$2 max_temp=$3 min_fan=$4 max_fan=$5
    [ "$temp" -le "$min_temp" ] && echo "$min_fan" && return
    [ "$temp" -ge "$max_temp" ] && echo "$max_fan" && return
    awk -v t="$temp" -v t_min="$min_temp" -v t_max="$max_temp" -v f_min="$min_fan" -v f_max="$max_fan" \
        'BEGIN {print int(f_min + (t - t_min) * (f_max - f_min) / (t_max - t_min))}'
}

publish_if_changed() {
    local new_pwm=$1
    local last_pwm
    last_pwm=$(cat "$LAST_PWM_FILE" 2>/dev/null || echo "0")

    if [ "$new_pwm" != "$last_pwm" ]; then
        mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
            -t "${MQTT_SYSTEM}/fan_speed" -m "$new_pwm" 2>/dev/null || true
        echo "$new_pwm" > "$LAST_PWM_FILE"
    fi
}

set_pwm() {
    echo "$1" > /sys/class/hwmon/hwmon0/pwm1
    echo "$1" > /sys/class/hwmon/hwmon0/pwm2
}

set_fan_speed() {
    # shellcheck source=/dev/null
    source "$STATE_FILE"
    local pwm

    if [ "$FAN_MODE" = "unas_managed" ]; then
        # don't touch pwm values - just read and report
        pwm=$(cat /sys/class/hwmon/hwmon0/pwm1 2>/dev/null || echo 0)
        echo "UNAS MANAGED MODE: $pwm PWM ($((pwm * 100 / 255))%)"

    elif [ "$FAN_MODE" = "auto" ]; then
        local temp
        temp=$(get_max_hdd_temp)
        pwm=$(calculate_pwm "$temp" "$MIN_TEMP" "$MAX_TEMP" "$MIN_FAN" "$MAX_FAN")
        set_pwm "$pwm"
        echo "CUSTOM CURVE MODE: ${temp}°C → $pwm PWM ($((pwm * 100 / MAX_FAN))%)"

    elif [[ "$FAN_MODE" =~ ^[0-9]+$ ]] && [ "$FAN_MODE" -ge 0 ] && [ "$FAN_MODE" -le 255 ]; then
        set_pwm "$FAN_MODE"
        pwm=$FAN_MODE
        echo "SET SPEED MODE: $pwm PWM ($((pwm * 100 / 255))%)"

    else
        echo "Invalid mode: $FAN_MODE, defaulting to UNAS Managed"
        {
            echo "FAN_MODE=unas_managed"
            echo "MIN_TEMP=$MIN_TEMP"
            echo "MAX_TEMP=$MAX_TEMP"
            echo "MIN_FAN=$MIN_FAN"
            echo "MAX_FAN=$MAX_FAN"
        } > "$STATE_FILE"
        return
    fi

    publish_if_changed "$pwm"
}

if $SERVICE; then
    while true; do
        set_fan_speed
        sleep 1
    done
else
    set_fan_speed
fi
