# Temperature Monitoring Service

Monitors HDD and CPU temperatures and publishes to Home Assistant via MQTT.

## Features

- Reads all drive temperatures via SMART every 10 seconds
- Reads CPU temperature from thermal zone
- Publishes individual sensors to Home Assistant
- Auto-discovery in Home Assistant
- Auto-installs dependencies (mosquitto-clients, nano)

## Configuration

Edit `temp_monitor.sh` to adjust:
```bash
MONITOR_INTERVAL=10       # Seconds between readings
MQTT_HOST="192.168.1.111" # Your HA IP
MQTT_USER="homeassistant"
MQTT_PASS="your_password"
hdd_devices=(sda sdb sdc sdd sde sdf) # Your drive list
```

## Deployment
```bash
./deploy_temp_monitor.sh root@YOUR_UNAS_IP
```

This will:
1. Copy `temp_monitor.sh` to `/root/`
2. Copy `temp_monitor.service` to `/etc/systemd/system/`
3. Install dependencies if missing
4. Enable and start the service

## MQTT Topics

**Publishes to:**
- `homeassistant/sensor/unas_sda/state` (through sdf) - Drive temperatures
- `homeassistant/sensor/unas_cpu/state` - CPU temperature
- Auto-discovery configs for all sensors

## Home Assistant Setup

To get the average temperature of all drives, add to `configuration.yaml`:
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

Sensors will auto-appear in Home Assistant within 10 seconds of deployment.

## Logs

View service output:
```bash
ssh root@YOUR_UNAS_IP "journalctl -u temp_monitor -f"
```

Example output:
```
2025-12-30 02:22:19: 242 (94%) (CPU 57°C) (HDD 43°C, 45°C, 45°C, 46°C, 43°C, 45°C)
```

## Dependencies

Auto-installed on first run:
- mosquitto-clients - MQTT publishing
- nano - Text editor for SSH editing

## Troubleshooting

**Sensors not appearing in HA:**
- Check MQTT credentials in `temp_monitor.sh`
- Verify MQTT integration is configured in HA
- Check logs for connection errors

**Missing drive temperatures:**
- Verify drive device names match your setup: `ls /dev/sd*`
- Update `hdd_devices` array in `temp_monitor.sh` if needed

**Service not running:**
- Check status: `ssh root@YOUR_UNAS_IP "systemctl status temp_monitor"`
- Restart: `ssh root@YOUR_UNAS_IP "systemctl restart temp_monitor"`