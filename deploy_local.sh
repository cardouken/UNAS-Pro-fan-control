#!/bin/bash
set -e

SRC="$HOME/repos/personal/homeassistant-unifi-unas/custom_components/unifi_unas/"

HA_HOST="root@192.168.1.111"
TEMP_DIR="/tmp/unifi_unas_deploy"

echo "📦 Preparing deployment..."

# Clean and create temp directory
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"

# Copy to temp directory (excludes __pycache__)
rsync -av --exclude='__pycache__' --exclude='*.pyc' "$SRC/" "$TEMP_DIR/"

echo "🚀 Deploying to Home Assistant via SSH..."

# Deploy via SSH
ssh "$HA_HOST" "rm -rf /config/custom_components/unifi_unas"
scp -r "$TEMP_DIR" "$HA_HOST:/config/custom_components/unifi_unas"

echo "✅ Files deployed to HA"
echo "🔄 Restarting Home Assistant..."

ssh "$HA_HOST" "ha core restart"

echo "📋 Showing logs (Ctrl+C to stop)..."
ssh "$HA_HOST" "ha core logs -f" | grep --color=auto unas
