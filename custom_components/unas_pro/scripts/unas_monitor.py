#!/usr/bin/env python3

import time
import subprocess
import logging
import json
from pathlib import Path
import paho.mqtt.client as mqtt  # type: ignore  # installed on UNAS, not HA

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

MQTT_HOST = "192.168.1.111"
MQTT_USER = "homeassistant"
MQTT_PASS = "unas_password_123"
MONITOR_INTERVAL = 30

ATA_TO_BAY = {
    "1": "6",
    "3": "7",
    "4": "3",
    "5": "5",
    "6": "2",
    "7": "4",
    "8": "1"
}


class UNASMonitor:
    def __init__(self):
        self.mqtt = mqtt.Client()
        self.mqtt.username_pw_set(MQTT_USER, MQTT_PASS)
        self.mqtt.on_connect = lambda c, u, f, rc: logger.info("MQTT connected" if rc == 0 else f"MQTT failed: {rc}")
        self.mqtt.on_disconnect = lambda c, u, rc: logger.warning("MQTT disconnected") if rc != 0 else None

        self.mqtt.will_set("homeassistant/unas/status", "offline", retain=True)
        self.mqtt.connect(MQTT_HOST, 1883, 60)
        self.mqtt.loop_start()
        time.sleep(2)
        
        self.mqtt.publish("homeassistant/unas/status", "online", retain=True)

        self.bay_cache = {}
        self.known_drives = set()

    def publish(self, topic, value):
        self.mqtt.publish(f"homeassistant/sensor/{topic}/state", str(value), retain=True)

    def run_cmd(self, cmd, timeout=10):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=isinstance(cmd, str))
            return result.stdout
        except:
            return ""

    def get_system_metrics(self):
        data = {}

        with open('/proc/uptime') as f:
            data['uptime'] = int(float(f.read().split()[0]))

        data['os_version'] = self.run_cmd(['dpkg-query', '-W', '-f=${Version}', 'unifi-core']).strip()
        data['drive_version'] = self.run_cmd(['dpkg-query', '-W', '-f=${Version}', 'unifi-drive']).strip()
        data['cpu_usage'] = self.get_cpu_usage()

        with open('/proc/meminfo') as f:
            meminfo = {parts[0].rstrip(':'): int(parts[1]) for line in f if len(parts := line.split()) >= 2}

        mem_total = meminfo.get('MemTotal', 0) // 1024
        mem_avail = meminfo.get('MemAvailable', 0) // 1024
        mem_used = mem_total - mem_avail

        data['memory_total'] = mem_total
        data['memory_used'] = mem_used
        data['memory_usage'] = round((mem_used / mem_total) * 100, 1) if mem_total else 0

        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as f:
                data['cpu_temp'] = int(f.read().strip()) // 1000
        except:
            data['cpu_temp'] = 0

        try:
            with open('/sys/class/hwmon/hwmon0/pwm1') as f:
                pwm = int(f.read().strip())
                data['fan_speed'] = pwm
                data['fan_speed_percent'] = int((pwm * 100) / 255)
        except:
            data['fan_speed'] = 0
            data['fan_speed_percent'] = 0

        return data

    def get_cpu_usage(self):
        def read():
            with open('/proc/stat') as f:
                parts = f.readline().split()
                values = list(map(int, parts[1:]))
                idle = values[3] + values[4]
                total = sum(values)
                return idle, total

        idle1, total1 = read()
        time.sleep(0.1)
        idle2, total2 = read()

        idle_delta = idle2 - idle1
        total_delta = total2 - total1

        return int(100 * (1 - idle_delta / total_delta))

    def get_bay_number(self, device):
        if device in self.bay_cache:
            return self.bay_cache[device]

        output = self.run_cmd(['udevadm', 'info', '-q', 'path', '-n', f'/dev/{device}'])
        bay = None
        for part in output.split('/'):
            if part.startswith('ata') and (ata_num := part[3:]) in ATA_TO_BAY:
                bay = ATA_TO_BAY[ata_num]
                break

        self.bay_cache[device] = bay
        return bay

    def get_drives(self):
        current_drives = {p.name for p in Path('/dev').glob('sd?')}

        if current_drives != self.known_drives:
            self.bay_cache.clear()
            self.known_drives = current_drives

        drives = []

        for device_path in Path('/dev').glob('sd?'):
            device = device_path.name
            bay = self.get_bay_number(device)

            if not bay:
                continue

            output = self.run_cmd(['smartctl', '-a', '-j', f'/dev/{device}'])
            if not output:
                continue

            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                continue

            if 'error' in data or not data.get('smart_status'):
                continue

            drive = {
                'bay': bay,
                'model': data.get('model_name') or data.get('product', 'Unknown'),
                'serial': data.get('serial_number', 'Unknown'),
                'firmware': data.get('firmware_version', 'Unknown'),
                'status': "Optimal" if data.get('smart_status', {}).get('passed') else "Warning",
                'temperature': data.get('temperature', {}).get('current', 0)
            }

            rotation = data.get('rotation_rate', 0)
            if rotation > 0:
                drive['rpm'] = rotation

            for attr in data.get('ata_smart_attributes', {}).get('table', []):
                name = attr.get('name', '').lower()
                if name == 'power_on_hours':
                    drive['power_hours'] = attr.get('raw', {}).get('value', 0)
                elif name == 'reallocated_sector_ct':
                    drive['bad_sectors'] = attr.get('raw', {}).get('value', 0)

            if 'bad_sectors' not in drive:
                drive['bad_sectors'] = 0

            if 'power_hours' not in drive:
                drive['power_hours'] = data.get('power_on_time', {}).get('hours', 0)

            size_bytes = data.get('user_capacity', {}).get('bytes', 0)
            drive['total_size'] = round(size_bytes / (1024 ** 4), 2)

            drives.append(drive)

        return drives

    def get_pools(self):
        pools = []
        pool_num = 1

        for volume_dir in sorted(Path('/volume').glob('*')):
            if not volume_dir.is_dir():
                continue

            df_output = self.run_cmd(['df', '-BG', str(volume_dir)])
            lines = df_output.strip().split('\n')

            if len(lines) < 2:
                continue

            parts = lines[1].split()
            size_gb = int(parts[1].rstrip('G'))

            if size_gb <= 75:
                continue

            pools.append({
                'pool': pool_num,
                'size': size_gb,
                'used': int(parts[2].rstrip('G')),
                'available': int(parts[3].rstrip('G')),
                'usage': int(parts[4].rstrip('%'))
            })
            pool_num += 1

        return pools

    def collect_and_publish(self):
        system = self.get_system_metrics()
        for key, value in system.items():
            self.publish(f"unas_{key}", value)

        drives = self.get_drives()
        for drive in drives:
            bay = drive.pop('bay')
            for key, value in drive.items():
                self.publish(f"unas_hdd_{bay}_{key}", value)

        pools = self.get_pools()
        for pool in pools:
            pool_num = pool.pop('pool')
            for key, value in pool.items():
                self.publish(f"unas_pool{pool_num}_{key}", value)

        temps = [d.get('temperature', 0) for d in drives if 'temperature' in d]
        temp_str = ', '.join(f"{t}°C" for t in temps) if temps else "no drives"

        logger.info(
            f"{system['fan_speed']} PWM ({system['fan_speed_percent']}%) | "
            f"CPU {system['cpu_temp']}°C | "
            f"HDD {temp_str}"
        )

    def run(self):
        logger.info("UNAS monitor started")

        while True:
            try:
                self.collect_and_publish()
            except Exception as e:
                logger.error(f"Error: {e}")

            time.sleep(MONITOR_INTERVAL)


if __name__ == '__main__':
    monitor = UNASMonitor()
    monitor.run()
