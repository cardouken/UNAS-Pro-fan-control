#!/bin/bash

hdd_devices=(sda sdb sdc sdd sde sdf sdg)

while true; do
    raw=$(cat /sys/class/hwmon/hwmon0/pwm1)
    percent=$(( raw * 100 / 255 ))

    temps=()
    for dev in "${hdd_devices[@]}"; do
        if smartctl -a "/dev/$dev" &>/dev/null; then
            temp=$(smartctl -a "/dev/$dev" | awk '/194 Temperature_Celsius/ {print $10}')
            if [[ "$temp" =~ ^[0-9]+$ ]]; then
                temps+=("${temp}°C")
            fi
        fi
    done

    hdd_str="HDD ${temps[*]}"
    hdd_str="${hdd_str// /, }"

    timestamp=$(date +"%Y-%m-%d %H:%M:%S")
    echo "$timestamp: $raw (${percent}%) ($hdd_str)" | tee -a pwm_log.txt

    sleep 1
done
