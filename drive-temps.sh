#!/bin/bash

# List of HDD devices to check
hdd_devices=(sda sdb sdc sdd sde sdf sdg)

# Store previous temps
declare -a prev_temps=()

# ANSI color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Logging loop
interval=10
next_ts=$(date +%s)

while true; do
    now=$(date +%s)
    # Get PWM raw value and percentage
    raw=$(cat /sys/class/hwmon/hwmon0/pwm1)
    percent=$(( raw * 100 / 255 ))

    # Get HDD temperatures with comparison
    temps_output_colored=()
    temps_output_plain=()
    current_temps=()
    i=0

    for dev in "${hdd_devices[@]}"; do
        if smartctl -a "/dev/$dev" &>/dev/null; then
            temp=$(smartctl -a "/dev/$dev" | awk '/194 Temperature_Celsius/ {print $10}')
            if [[ "$temp" =~ ^[0-9]+$ ]]; then
                current_temps+=("$temp")
                if [[ -n "${prev_temps[$i]}" ]]; then
                    if (( temp > prev_temps[i] )); then
                        temps_output_colored+=("${RED}${temp}°C${NC}")
                    elif (( temp < prev_temps[i] )); then
                        temps_output_colored+=("${GREEN}${temp}°C${NC}")
                    else
                        temps_output_colored+=("${temp}°C")
                    fi
                else
                    temps_output_colored+=("${temp}°C")
                fi
                temps_output_plain+=("${temp}°C")
                ((i++))
            fi
        fi
    done

    # Store current as previous for next iteration
    prev_temps=("${current_temps[@]}")

    # Format output
    hdd_str_colored="HDD $(IFS=, ; echo "${temps_output_colored[*]}" | sed 's/,/, /g')"
    hdd_str_plain="HDD $(IFS=, ; echo "${temps_output_plain[*]}" | sed 's/,/, /g')"

    timestamp=$(date +"%Y-%m-%d %H:%M:%S")
    terminal_output="$timestamp: $raw (${percent}%) ($hdd_str_colored)"
    log_output="$timestamp: $raw (${percent}%) ($hdd_str_plain)"

    echo -e "$terminal_output"
    echo "$log_output" >> pwm_log.txt

    # Calculate when to run next
    next_ts=$((next_ts + interval))
    sleep_time=$((next_ts - $(date +%s)))

    if (( sleep_time > 0 )); then
        sleep $sleep_time
    else
        # If we’re behind schedule, reset to now
        next_ts=$(date +%s)
    fi
done
