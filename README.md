# UNAS Pro for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/cardouken/homeassistant-unas-pro.svg)](https://github.com/cardouken/homeassistant-unas-pro/releases)
[![License](https://img.shields.io/github/license/cardouken/homeassistant-unas-pro.svg)](LICENSE.md)

Monitoring and fan control for UniFi UNAS Pro with native Home Assistant integration.

## Features

- **One-Click Setup** - Automatic script deployment via SSH
- **Full Monitoring** - Drive SMART data, temperatures, pool stats, system metrics
- **Fan Control** - Three modes with custom temperature curves
- **Auto-Recovery** - Survives firmware updates
- **Native Integration** - Proper HA devices and entities

## Included metrics

### UNAS Pro

- CPU temperature & usage
- Memory usage & total
- Fan speed (PWM & percentage)
- Storage pool metrics
- System info & uptime

### Drives

- Temperature, SMART health
- Model, serial, firmware, RPM, etc.
- Power-on hours & bad sectors

### Controls

- **Fan Mode Select** - UNAS Managed / Custom Curve / Set Speed
- **Fan Speed Slider** - Manual control in Set Speed mode
- **Fan Curve Configuration** - Min/max temperature and fan speeds, linear curve
- **Service Monitors** - Binary sensors for script health
- **Reinstall Button** - Manual script redeployment

## Installation

### Prerequisites

1. **MQTT Integration** (Required)
    - Settings → Devices & Services → Add Integration → MQTT
    - If using Mosquitto add-on: Select automatic discovery
    - If using external broker: Enter broker details manually

2. **Mosquitto MQTT Broker** (Recommended)
    - Settings → Add-ons → Add-on Store → Mosquitto broker
    - Install, start, and enable "Start on boot"
    - Configure login credentials under Mosquitto broker add-on → Configuration → Options → Logins
    - **Note**: You can use any MQTT broker, but Mosquitto add-on is easiest

3. **SSH Access to UNAS Pro**
    - Enable SSH access in UniFi Drive via Settings → Control Plane → Console → check "SSH" and configure password

### Install Integration

**Via HACS (Recommended):**

1. HACS → Integrations → ⋮ → Custom repositories
2. Repository: `https://github.com/cardouken/homeassistant-unas-pro`
3. Category: Integration → Add
4. Install "UNAS Pro" and restart HA

**Manual:**

1. Download latest release
2. Extract to `custom_components/unas_pro/`
3. Restart HA

## Setup

### Add Integration

1. Settings → Devices & Services → Add Integration
2. Search "UNAS Pro"
3. Enter details:
    - **Host**: UNAS IP (e.g., `192.168.1.25`)
    - **Username**: `root`
    - **Password**: Your UNAS SSH password
    - **MQTT Host**: Home Assistant IP (e.g., `192.168.1.111`)
    - **MQTT User**: Your Mosquitto username configured earlier in the add-on
    - **MQTT Password**: Your Mosquitto password configured earlier in the add-on

The integration will automatically:

- Deploy scripts to UNAS via SSH
- Configure systemd services
- Set up MQTT auto-discovery
- Create all devices and entities

## Fan Control Modes

### 1. UNAS Managed

Lets UNAS control the fans automatically based on the selected Fan Mode (default behavior). Disables fan_control.service
entirely. Useful if you only want to get data from the UNAS and not control it.

### 2. Custom Curve

Temperature-based fan curve with configurable parameters:

**Configure in Home Assistant:**

- Settings → Devices & Services → UNAS Pro → Device
- Adjust the four fan curve parameters

**Example: Quiet**

- Min Temperature: `40°C`
- Max Temperature: `50°C`
- Min Fan Speed: `15%`
- Max Fan Speed: `30%`

Result: Lower baseline, warmer drives, quieter operation.

**Example: Aggressive**

- Min Temperature: `38°C`
- Max Temperature: `45°C`
- Min Fan Speed: `70%`
- Max Fan Speed: `100%`

Result: Cooler drives, more aggressive cooling.

### 3. Set Speed

Lock fans to a specific speed (0-100%).

**How to use:**

1. Select "Set Speed" mode
2. Adjust "UNAS Fan Speed" slider
3. Fans stay locked at that speed

## Monitoring

All sensors appear automatically under the UNAS Pro device and individual HDD devices. No manual configuration needed.

## Troubleshooting

### Scripts Not Installing

Check logs: Settings → System → Logs → "unas_pro"

Common issues:

- **Cannot connect** → Verify UNAS IP and root password
- **Timeout** → Check SSH access (port 22)
- **Permission denied** → Must use `root` account

### Sensors Not Appearing

1. **Verify MQTT integration is installed** (Settings → Devices & Services → MQTT)
2. Verify Mosquitto broker is running
3. Check MQTT credentials are correct in integration config
4. Check service status:
   ```bash
   ssh root@YOUR_UNAS_IP
   systemctl status unas_monitor fan_control
   ```

### After Firmware Update

Scripts are reinstalled automatically. If needed, manually reinstall via the "Reinstall Scripts" button on the device
page.

## Credits

- **Fan control concept**: [hoxxep/UNAS-Pro-fan-control](https://github.com/hoxxep/UNAS-Pro-fan-control)
- **Metrics and integration**: This project

## License

MIT - See [LICENSE.md](LICENSE.md)

## Support

- [GitHub Issues](https://github.com/cardouken/homeassistant-unas-pro/issues)
- [GitHub Discussions](https://github.com/cardouken/homeassistant-unas-pro/discussions)
