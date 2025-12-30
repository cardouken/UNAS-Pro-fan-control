# UNAS Pro Monitoring & Control

Comprehensive monitoring and fan control for the Ubiquiti UNAS Pro, with full Home Assistant integration via MQTT.

## Overview

This project provides two **independent** systemd services for the UNAS Pro:

1. **UNAS Monitor** (`/unas_monitor`) - Publishes comprehensive system metrics to Home Assistant via MQTT
2. **Fan Control** (`/fan_control`) - Temperature-based fan speed control with Home Assistant override capability

**Important:** These services are completely independent. Use one, both, or neither:

- **Just monitoring?** → Deploy only `unas_monitor`
- **Just custom fan control?** → Deploy only `fan_control`
- **Full integration?** → Deploy both services

Both services survive reboots and can be quickly redeployed after UNAS firmware updates.

## Which Services Do I Need?

### Scenario 1: System Monitoring Only
**You want:** Drive health, temperatures, storage usage, and system metrics visible in Home Assistant  
**Deploy:** `unas_monitor` service only  
**You get:**
- Complete SMART data for all drives (temperature, power-on hours, health status, capacity, etc.)
- Storage pool usage and capacity tracking
- CPU temperature and fan speed visibility
- System uptime and software versions
- No changes to fan behavior (UNAS controls fans normally)

### Scenario 2: Custom Fan Control Only
**You want:** Better fan curve than stock UNAS firmware  
**Deploy:** `fan_control` service only (optionally remove MQTT code)  
**You get:**
- Custom linear fan curve based on drive temps
- Optimized for quiet operation with Noctua fans
- No Home Assistant integration needed

### Scenario 3: Full Integration
**You want:** Complete visibility and control from Home Assistant  
**Deploy:** Both `unas_monitor` and `fan_control` services  
**You get:**
- All monitoring metrics in Home Assistant
- Custom fan curves with manual override from HA
- Critical temperature failsafe automation
- Full system visibility and control

## Features

**UNAS Monitor:**
- Comprehensive drive monitoring (SMART data, health, temps, capacity, hours, sectors, etc.)
- Storage pool usage tracking with unit conversion support
- System metrics (CPU temp, fan speed, uptime, software versions)
- MQTT integration with Home Assistant auto-discovery
- Automatic drive detection (no manual configuration)
- Clean device organization in Home Assistant

**Fan Control:**
- Configurable linear fan curve
- Manual fan speed override from Home Assistant
- Critical temperature failsafe (auto-switches to 100% fans)
- 1-second response time

**Both Services:**
- Survive reboots via systemd
- Auto-install dependencies
- Quick redeployment after firmware updates

## Quick Start

### Prerequisites

- UNAS Pro with SSH access
- (Optional) Home Assistant instance with MQTT broker (Mosquitto)
- (Optional) MQTT user credentials

### Deployment - Monitoring Only

If you only want system metrics in Home Assistant:

1. Clone this repository
2. Update MQTT credentials in `unas_monitor/unas_monitor.sh`:
   ```bash
   MQTT_HOST="192.168.1.111"
   MQTT_USER="homeassistant"
   MQTT_PASS="your_password"
   ```
3. Deploy:
   ```bash
   cd unas_monitor
   ./deploy_unas_monitor.sh root@YOUR_UNAS_IP
   ```
4. Reload MQTT integration in Home Assistant to discover sensors

### Deployment - Fan Control Only

If you only want custom fan curves (no HA integration):

1. Clone this repository
2. (Optional) Remove MQTT code from `fan_control/fan_control.sh` if you don't need HA integration
3. Configure fan curve in `fan_control/fan_control.sh`:
   ```bash
   MIN_TEMP=43    # Start ramping up fans
   MAX_TEMP=47    # Full speed
   MIN_FAN=204    # 80% baseline
   ```
4. Deploy:
   ```bash
   cd fan_control
   ./deploy_fan_control.sh root@YOUR_UNAS_IP
   ```

### Deployment - Full Integration

If you want both monitoring and control:

1. Clone this repository
2. Update MQTT credentials in **both** scripts:
   - `fan_control/fan_control.sh` - Update `MQTT_HOST`, `MQTT_USER`, `MQTT_PASS`
   - `unas_monitor/unas_monitor.sh` - Update `MQTT_HOST`, `MQTT_USER`, `MQTT_PASS`
3. Configure fan curve in `fan_control/fan_control.sh` (see above)
4. Deploy both services:
   ```bash
   cd fan_control
   ./deploy_fan_control.sh root@YOUR_UNAS_IP
   
   cd ../unas_monitor
   ./deploy_unas_monitor.sh root@YOUR_UNAS_IP
   ```
5. Reload MQTT in Home Assistant to discover all devices and sensors

## How It Works

**UNAS Monitor (unas_monitor):**
- Reads drive SMART data and system metrics every 10 seconds
- Publishes all data to MQTT with auto-discovery enabled
- Home Assistant automatically creates organized devices and sensors
- **Does not change fan behavior** - read-only monitoring

**Fan Control (fan_control):**
- Reads drive temps via SMART every 1 second
- Calculates fan speed using configurable linear curve
- Checks MQTT for override commands from Home Assistant
- Applies fan speed via PWM control
- Publishes current fan speed to MQTT (if HA integration enabled)
- **Overrides UNAS firmware fan control**

**Home Assistant Integration (when both deployed):**
- User toggles auto/override mode or adjusts fan speed slider in HA
- HA publishes MQTT message with desired fan speed (or "auto")
- Fan control service reads override and applies it
- UNAS monitor shows real-time results
- Failsafe automation forces auto mode if temps too high

## Components

### UNAS Monitor Service
See [unas_monitor/README.md](unas_monitor/README.md) for details on:
- What metrics are monitored and published
- MQTT sensor configuration
- Home Assistant setup and device organization
- Extending with additional metrics
- Troubleshooting

### Fan Control Service
See [fan_control/README.md](fan_control/README.md) for details on:
- Fan curve configuration
- MQTT override system
- Deployment and testing
- Choosing between simple and advanced scripts

## Post-Update Redeployment

UNAS firmware updates wipe custom scripts but preserve systemd service files. After an update, redeploy the services you're using:

**Monitoring only:**
```bash
./unas_monitor/deploy_unas_monitor.sh root@YOUR_UNAS_IP
```

**Fan control only:**
```bash
./fan_control/deploy_fan_control.sh root@YOUR_UNAS_IP
```

**Both:**
```bash
./fan_control/deploy_fan_control.sh root@YOUR_UNAS_IP
./unas_monitor/deploy_unas_monitor.sh root@YOUR_UNAS_IP
```

Services will auto-restart and resume normal operation.

## Requirements

- UNAS Pro running Unifi OS 4.2.6+
- Root SSH access via SSH key
- (Optional) Home Assistant with MQTT integration
- (Optional) Mosquitto MQTT broker

## License

MIT License - see LICENSE.md

## Credits

Forked from [hoxxep/UNAS-Pro-fan-control](https://github.com/hoxxep/UNAS-Pro-fan-control)
