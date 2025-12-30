#!/bin/bash

# Run remotely to deploy the UNAS monitor script onto a UNAS Pro.

set -euo pipefail

HOST="${1:-root@192.168.1.25}"

scp unas_monitor.sh "${HOST}:/root/unas_monitor.sh"
scp unas_monitor.service "${HOST}:/etc/systemd/system/unas_monitor.service"

ssh "$HOST" -t '\
    chmod +x /root/unas_monitor.sh && \
    systemctl daemon-reload && \
    systemctl enable unas_monitor.service && \
    systemctl restart unas_monitor.service && \
    systemctl status unas_monitor.service'
