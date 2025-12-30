# UNAS Monitor Service

Monitors and publishes UNAS Pro system metrics to Home Assistant via MQTT. Provides visibility into storage health,
system performance, and hardware status.

## Features

- **Drive Monitoring**: Complete SMART data for all drives (temperature, power-on hours, health status, RPM, capacity,
  bad sectors, etc.)
- **Storage Pool Tracking**: Real-time usage, capacity, and availability metrics
- **System Metrics**: CPU temperature, fan speed, uptime, software versions
- **Auto-discovery**: All sensors automatically appear in Home Assistant with proper device grouping
- **Drive Detection**: Automatically detects all SATA/NVMe drives without manual configuration
- **10-second update interval**: Real-time monitoring with minimal overhead

## Device Organization in Home Assistant

Sensors are organized into logical devices:

- **UNAS Pro Device**: System-level metrics (CPU temp, fan speed, storage pools, uptime, versions)
- **Individual Drive Devices**: Per-drive SMART data and health metrics (one device per physical drive)

This organization keeps your Home Assistant clean and makes it easy to view related metrics together.

## What Gets Published

### UNAS Pro Device

- CPU temperature
- Fan speed (raw PWM and percentage)
- Storage pool metrics (usage %, size, used, available)
- System uptime
- UniFi OS version
- UniFi Drive version

### Per-Drive Devices (auto-detected)

- Temperature
- SMART health status
- Power-on hours
- Bad sector count
- Drive model, serial number, firmware
- RPM (or "SSD" for solid state drives)
- Total capacity
- etc

All storage sensors support Home Assistant's unit conversion (display in GB, TB, etc.).

## Configuration

Edit `unas_monitor.sh` to configure:

```bash
MONITOR_INTERVAL=10                    # Update interval in seconds

MQTT_HOST="192.168.1.111"              # Your HA IP
MQTT_USER="homeassistant"              # MQTT username
MQTT_PASS="your_password"              # MQTT password
```

Drives are automatically detected, no manual configuration needed.

## Deployment

```bash
./deploy_unas_monitor.sh root@YOUR_UNAS_IP
```

This will:

1. Copy `unas_monitor.sh` to `/root/`
2. Copy `unas_monitor.service` to `/etc/systemd/system/`
3. Install dependencies (mosquitto-clients)
4. Enable and start the service

## Manual Testing

Run once to see output:

```bash
ssh root@YOUR_UNAS_IP
/root/unas_monitor.sh
```

Example output:

```
2025-12-30 08:15:30: 186 (72%) (CPU 63°C) (HDD 44°C, 46°C, 46°C, 47°C, 45°C, 47°C)
```

## Home Assistant Setup

### MQTT Integration

The service uses MQTT auto-discovery. Once deployed:

1. Go to Settings → Devices & Services → MQTT
2. Click "Reload" to discover all sensors
3. Find "UNAS Pro" device and individual drive devices

### Template Sensors (Optional)

Add to `configuration.yaml` for aggregate metrics:

```yaml
template:
  - sensor:
      - name: "UNAS Average Drive Temperature"
        unit_of_measurement: "°C"
        device_class: temperature
        state: >
          {% set temps = states.sensor 
            | selectattr('entity_id', 'match', 'sensor.unas_sd._temperature')
            | selectattr('state', 'is_number')
            | map(attribute='state') | map('float') | list %}
          {{ (temps | sum / temps | length) | round(1) if temps | length > 0 else 'unavailable' }}
```

## Logs

View service logs:

```bash
ssh root@YOUR_UNAS_IP "journalctl -u unas_monitor -f"
```

## Troubleshooting

**Sensors not appearing in HA:**

- Check MQTT credentials in `unas_monitor.sh`
- Verify MQTT broker is running in HA (Settings → Integrations → MQTT)
- Reload MQTT integration: Settings → Devices & Services → MQTT → three dots → Reload
- Check logs: `journalctl -u unas_monitor -n 50`

**Drive entities not grouped under drive devices:**

- Restart Home Assistant completely
- Reload MQTT integration after restart

**Missing/incorrect drive data:**

- Verify drives are detected: `ls /dev/sd*`
- Test SMART manually: `smartctl -a /dev/sda`
- Check service logs for errors

**Storage sensors showing wrong values:**

- Only volumes >100GB are published (filters out system partitions)
- Bind mounts are automatically deduplicated

**MQTT connection fails:**

- Test broker: `mosquitto_sub -h YOUR_HA_IP -u user -P pass -t test -v`
- Check firewall allows port 1883
- Ensure credentials are correct

## Extending with New Metrics

The `publish_mqtt_sensor()` helper function makes adding new metrics straightforward:

```bash
# Example: Add memory usage
mem_used=$(free -m | awk '/^Mem:/ {print $3}')
publish_mqtt_sensor "unas_memory_used" "Memory Used" "$mem_used" "MB" "" "$UNAS_DEVICE"
```

Just add calls to `publish_mqtt_sensor()` in the main monitoring loop or create a new function following the existing
pattern.

## Post-Update Redeployment

UNAS firmware updates wipe custom scripts. After an update:

```bash
./deploy_unas_monitor.sh root@YOUR_UNAS_IP
```

The systemd service file persists, so the service will auto-restart with the newly deployed script.
