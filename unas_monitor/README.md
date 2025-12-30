# UNAS Monitor Service

Monitors and publishes UNAS Pro system metrics to Home Assistant via MQTT. Includes temperature monitoring, storage
usage, and more.

## Features

- **Temperature Monitoring**: Individual drive temps, CPU temp, current fan speed
- **Storage Monitoring**: Pool usage, size, used space, and available space
- **Future Expansion Ready**: Designed to easily add drive health (SMART), operating hours, and other metrics
- **Auto-discovery**: All sensors automatically appear in Home Assistant
- **10-second update interval**: Real-time monitoring

## What Gets Published

### Temperature Sensors

- Individual HDD temperatures (via SMART)
- CPU temperature
- Current fan speed (PWM and percentage)

### Storage Sensors

- Pool usage percentage
- Total pool size (GB, convertible to TB)
- Used space (GB)
- Available space (GB)

All storage sensors use Home Assistant's `data_size` device class, allowing you to choose display units (GB, TB, etc.)
in the HA UI.

## Configuration

Edit `unas_monitor.sh` to configure:

```bash
hdd_devices=(sda sdb sdc sdd sde sdf)  # Your drive list
MONITOR_INTERVAL=10                    # Update interval in seconds

MQTT_HOST="192.168.1.111"              # Your HA IP
MQTT_USER="homeassistant"              # MQTT username
MQTT_PASS="your_password"              # MQTT password
```

## Deployment

```bash
./deploy_unas_monitor.sh root@YOUR_UNAS_IP
```

This will:

1. Copy `unas_monitor.sh` to `/root/`
2. Copy `unas_monitor.service` to `/etc/systemd/system/`
3. Install dependencies (mosquitto-clients, nano)
4. Enable and start the service

## Manual Testing

Run once to see output:

```bash
ssh root@YOUR_UNAS_IP
/root/unas_monitor.sh
```

Example output:

```
2025-12-30 06:36:20: 186 (72%) (CPU 63°C) (HDD 44°C, 46°C, 46°C, 47°C, 45°C, 47°C)
```

## MQTT Topics

### Published Topics

**Temperatures:**

- `homeassistant/sensor/unas_sda/state` through `unas_sdf/state` - Drive temps
- `homeassistant/sensor/unas_cpu/state` - CPU temp

**Storage:**

- `homeassistant/sensor/unas_pool1_usage/state` - Usage percentage
- `homeassistant/sensor/unas_pool1_size/state` - Total size
- `homeassistant/sensor/unas_pool1_used/state` - Used space
- `homeassistant/sensor/unas_pool1_available/state` - Available space

All topics include auto-discovery configs published to `/config` topics.

## Home Assistant Setup

### Template Sensors

Add to `configuration.yaml` for aggregate temperature sensor:

```yaml
template:
  - sensor:
      - name: "UNAS Average Temperature"
        unit_of_measurement: "°C"
        device_class: temperature
        state: >
          {% set drives = [
            states('sensor.unas_sda_temperature'),
            states('sensor.unas_sdb_temperature'),
            states('sensor.unas_sdc_temperature'),
            states('sensor.unas_sdd_temperature'),
            states('sensor.unas_sde_temperature'),
            states('sensor.unas_sdf_temperature')
          ] %}
          {% set valid = drives | reject('in', ['unknown', 'unavailable']) | map('float') | list %}
          {{ (valid | sum / valid | length) | round(1) if valid | length > 0 else 'unavailable' }}
```

### Critical Temperature Automation

See main README and fan_control README for failsafe automation that monitors temps and forces fan control to auto mode
if thresholds are exceeded.

## Logs

View service logs:

```bash
ssh root@YOUR_UNAS_IP "journalctl -u unas_monitor -f"
```

## Troubleshooting

**Sensors not appearing in HA:**

- Check MQTT credentials in `unas_monitor.sh`
- Verify MQTT broker is running in HA
- Check logs: `journalctl -u unas_monitor -n 50`

**Missing drive temperatures:**

- Verify drive device names: `ls /dev/sd*`
- Update `hdd_devices` array if needed
- Test SMART: `smartctl -a /dev/sda`

**Storage sensors showing wrong values:**

- Only volumes >100GB are published (filters out system partitions)
- Multiple bind mounts of same device are deduplicated
- Check what `df -BG` shows on the UNAS

**MQTT connection fails:**

- Verify broker is accessible: `mosquitto_sub -h YOUR_HA_IP -u user -P pass -t test -v`
- Check firewall allows port 1883
- Ensure credentials are correct

## Adding New Metrics

Use the `publish_mqtt_sensor()` helper function:

```bash
# Example: Publish drive health
smart_health=$(smartctl -H /dev/sda | grep "SMART overall-health" | awk '{print $NF}')
publish_mqtt_sensor "unas_sda_health" "UNAS sda Health" "$smart_health" "" ""

# Example: Publish drive hours
drive_hours=$(smartctl -a /dev/sda | grep "Power_On_Hours" | awk '{print $10}')
publish_mqtt_sensor "unas_sda_hours" "UNAS sda Operating Hours" "$drive_hours" "h" ""
```

Just add calls to `publish_mqtt_sensor()` in the main monitoring loop.

## Post-Update Redeployment

UNAS firmware updates wipe custom scripts. After an update:

```bash
./deploy_unas_monitor.sh root@YOUR_UNAS_IP
```

The systemd service file persists, so the service will auto-restart with the newly deployed script.
