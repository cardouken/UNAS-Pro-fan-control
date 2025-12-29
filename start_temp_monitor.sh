#!/bin/bash

# Install dependencies if missing
PACKAGES=("screen" "mosquitto-clients" "nano")
MISSING=()

for pkg in "${PACKAGES[@]}"; do
    if ! dpkg -l | grep -q "^ii  $pkg "; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "Installing missing packages: ${MISSING[*]}"
    sudo apt-get update
    sudo apt install -y "${MISSING[@]}"
    echo "Installation complete."
else
    echo "All dependencies already installed."
fi

# Kill existing temp-monitor screen sessions
echo "Checking for existing temp-monitor sessions..."
while screen -list | grep -q "temp-monitor"; do
    screen -S temp-monitor -X quit 2>/dev/null
    sleep 0.5
done
echo "All temp-monitor sessions stopped."

# Start the temp-monitor screen session with logging
echo "Starting temp-monitor screen session..."
screen -dmS temp-monitor -L bash -c './temp_monitor.sh'
screen -S temp-monitor -X colon "logfile flush 0^M"

echo "Setup complete! Temp monitor is running in screen session 'temp-monitor'."
echo "To view the session, run: screen -r temp-monitor"