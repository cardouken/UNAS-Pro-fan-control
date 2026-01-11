# UNAS Pro for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/cardouken/homeassistant-unas-pro.svg)](https://github.com/cardouken/homeassistant-unas-pro/releases)
[![License](https://img.shields.io/github/license/cardouken/homeassistant-unas-pro.svg)](LICENSE.md)

Monitoring and fan control for UniFi UNAS with native Home Assistant integration.

## Supported Devices

- **UNAS Pro** – Fully supported
- **UNAS Pro 8** – Fully supported (bays 7-8 possibly not mapped correctly, assumed sequential)
- **UNAS Pro 4** – Unconfirmed, but very likely supported, bays possibly not mapped correctly
- **UNAS 4** – Unconfirmed
- **UNAS 2** – Unconfirmed

<details>
<summary><strong>Help confirm device support!</strong></summary>

If you own a UNAS Pro 8, UNAS Pro 4, UNAS 4, or UNAS 2, you can help confirm drive bay mappings by running this command on your UNAS via SSH:

```bash
for dev in /dev/sd?; do
    ata_port=$(udevadm info -q path -n "$dev" | grep -oP 'ata\K[0-9]+')
    serial=$(smartctl -i "$dev" 2>/dev/null | grep 'Serial Number' | awk '{print $NF}')
    model=$(smartctl -i "$dev" 2>/dev/null | grep 'Device Model' | awk '{$1=$2=""; print $0}' | xargs)
    echo "Device: $dev | ATA Port: $ata_port | Serial: $serial | Model: $model"
done
```

**Example output:**
```
Device: /dev/sda | ATA Port: 1 | Serial: ZR5FFXXX | Model: ST18000NM001J-2TV113
Device: /dev/sdb | ATA Port: 4 | Serial: ZR51DXXX | Model: ST18000NM000J-2TV103
Device: /dev/sdc | ATA Port: 5 | Serial: ZR5FHXXX | Model: ST18000NM001J-2TV113
```

Then check the UniFi Drive UI and match the serial numbers to physical bay numbers. For example:
- `/dev/sda` - ATA Port 1 - Bay 6
- `/dev/sdb` - ATA Port 4 - Bay 3
- `/dev/sdc` - ATA Port 5 - Bay 5

Please [open a GitHub issue](https://github.com/cardouken/homeassistant-unas-pro/issues) with your results to help improve device support!

</details>

## Features

- **One-Click Setup** - Automatic script deployment via SSH
- **Full Monitoring** - Drive SMART data, temperatures, pool stats, system metrics
- **Fan Control** - Three modes with custom temperature curves
- **Auto-Recovery** - Survives firmware updates
- **Native Integration** - Proper HA devices and entities

## Included metrics

### UNAS Pro

- CPU temperature & usage
- Disk I/O (read/write throughput)
- Memory usage & total
- Fan speed (PWM & percentage)
- Storage pool metrics
- System info & uptime
- SMB/NFS connections with client/share attributes

### Drives

- Temperature, SMART health
- Model, serial, firmware, RPM, etc.
- Power-on hours & bad sectors

### Controls

- **Fan Mode Select** - UNAS Managed / Custom Curve / Set Speed
- **Fan Speed Slider** - Manual control in Set Speed mode
- **Fan Curve Configuration** - Min/max temperature and fan speeds, linear curve
- **Service Monitors** - Binary sensors for script health

![dashboard](dashboard.png)

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

3. **SSH Access to UNAS**
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
    - **Device Model**: Select your UNAS model from the dropdown
    - **Polling Interval**: How often the integration should poll for metrics

The integration will automatically:

- Deploy scripts to UNAS via SSH
- Configure systemd services
- Set up MQTT auto-discovery
- Create all devices and entities

## Fan Control Modes

### 1. UNAS Managed

Lets UNAS control the fans automatically based on the selected Fan Mode (default behavior). Useful if you only want to
get data from the UNAS and not control it.

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

**Example: Aggressive**

- Min Temperature: `38°C`
- Max Temperature: `45°C`
- Min Fan Speed: `70%`
- Max Fan Speed: `100%`

### 3. Set Speed

Lock fans to a specific speed (0-100%).

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

### Removing integration

Removing the integration removes all scripts, services, and packages installed by the integration from the UNAS, restoring it to stock.

## Credits

- **Fan control concept**: [hoxxep/UNAS-Pro-fan-control](https://github.com/hoxxep/UNAS-Pro-fan-control)
- **Metrics and integration**: This project

## License

MIT - See [LICENSE.md](LICENSE.md)

## Support

- [GitHub Issues](https://github.com/cardouken/homeassistant-unas-pro/issues)
