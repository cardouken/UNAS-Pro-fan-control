#!/bin/bash

set -euo pipefail

# Configuration
hdd_devices=(sda sdb sdc sdd sde sdf sdg)
MONITOR_INTERVAL=10       # how often to check temperatures (seconds)

# Store previous temps
declare -A prev_temps=()

# ANSI color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Function to read all HDD temperatures at once
read_all_hdd_temperatures() {
    local dev temp

    # Clear current temps
    declare -gA current_temps=()

    # Read all HDD temperatures in quick succession
    for dev in "${hdd_devices[@]}"; do
        if [ -e "/dev/$dev" ]; then
            # Use timeout to prevent hanging - declare temp separately
            temp=$(timeout 5 smartctl -a "/dev/$dev" 2>/dev/null | awk '/194 Temperature_Celsius/ {print $10}' || echo "0")
            if [[ "$temp" =~ ^[0-9]+$ ]]; then
                current_temps["$dev"]="$temp"
            fi
        fi
    done
}

# Function to format temperature output with color comparison
format_temperature_output() {
    local temps_output_colored=()
    local temps_output_plain=()
    local dev temp prev_temp

    for dev in "${hdd_devices[@]}"; do
        if [[ -n "${current_temps[$dev]:-}" ]]; then
            temp="${current_temps[$dev]}"
            prev_temp="${prev_temps[$dev]:-}"

            # Add to plain output
            temps_output_plain+=("${temp}°C")

            # Add to colored output with comparison
            if [[ -n "$prev_temp" ]]; then
                if (( temp > prev_temp )); then
                    temps_output_colored+=("${RED}${temp}°C${NC}")
                elif (( temp < prev_temp )); then
                    temps_output_colored+=("${GREEN}${temp}°C${NC}")
                else
                    temps_output_colored+=("${temp}°C")
                fi
            else
                temps_output_colored+=("${temp}°C")
            fi
        fi
    done

    # Format output strings manually to ensure proper spacing
    temp_str_colored=""
    temp_str_plain=""

    for i in "${!temps_output_colored[@]}"; do
        if [ "$i" -eq 0 ]; then
            temp_str_colored="${temps_output_colored[$i]}"
            temp_str_plain="${temps_output_plain[$i]}"
        else
            temp_str_colored="${temp_str_colored}, ${temps_output_colored[$i]}"
            temp_str_plain="${temp_str_plain}, ${temps_output_plain[$i]}"
        fi
    done

    echo "$temp_str_colored|$temp_str_plain"
}

# Function to update previous temperatures
update_previous_temps() {
    local dev
    for dev in "${hdd_devices[@]}"; do
        if [[ -n "${current_temps[$dev]:-}" ]]; then
            prev_temps["$dev"]="${current_temps[$dev]}"
        fi
    done
}

# Main monitoring loop
monitor_temperatures() {
    local next_ts raw percent timestamp
    local temp_output temp_str_colored temp_str_plain
    local terminal_output log_output

    next_ts=$(date +%s)

    while true; do
        # Get PWM raw value and percentage
        raw=$(cat /sys/class/hwmon/hwmon0/pwm1)
        percent=$(( raw * 100 / 255 ))

        # Read all temperatures
        read_all_hdd_temperatures

        # Format temperature output
        temp_output=$(format_temperature_output)
        temp_str_colored="${temp_output%|*}"
        temp_str_plain="${temp_output#*|}"

        # Create output strings
        timestamp=$(date +"%Y-%m-%d %H:%M:%S")
        terminal_output=$(printf "%s: %3d (%d%%) (HDD %s)" "$timestamp" "$raw" "$percent" "$temp_str_colored")
        log_output=$(printf "%s: %3d (%d%%) (HDD %s)" "$timestamp" "$raw" "$percent" "$temp_str_plain")

        # Output to terminal and log
        echo -e "$terminal_output"
        echo "$log_output" >> temp_monitor_log.txt

        # Update previous temps for next iteration
        update_previous_temps

        # Calculate when to run next (precise timing)
        next_ts=$((next_ts + MONITOR_INTERVAL))
        local sleep_time=$((next_ts - $(date +%s)))

        if (( sleep_time > 0 )); then
            sleep $sleep_time
        else
            # If we're behind schedule, reset to now
            next_ts=$(date +%s)
        fi
    done
}

# Start monitoring
monitor_temperatures
