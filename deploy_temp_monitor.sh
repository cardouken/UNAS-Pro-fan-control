#!/bin/bash

# Run remotely to deploy the temp monitor script onto a UNAS Pro.

set -euo pipefail

HOST="${1:-root@192.168.1.25}"

scp temp_monitor.sh start_temp_monitor.sh "${HOST}:/root/"

ssh "$HOST" -t 'chmod +x /root/temp_monitor.sh /root/start_temp_monitor.sh && /root/start_temp_monitor.sh'