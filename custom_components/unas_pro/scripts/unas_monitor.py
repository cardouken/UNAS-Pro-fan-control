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

MQTT_HOST = "REPLACE_ME"
MQTT_USER = "REPLACE_ME"
MQTT_PASS = "REPLACE_ME"
DEFAULT_MONITOR_INTERVAL = 30
MONITOR_INTERVAL_TOPIC = "homeassistant/unas/monitor_interval"

DEVICE_MODEL = "UNAS_PRO"

BAY_MAPPINGS = {
    "UNAS_PRO": {
        "1": "6",
        "3": "7",
        "4": "3",
        "5": "5",
        "6": "2",
        "7": "4",
        "8": "1"
    },
    "UNAS_PRO_8": {
        "1": "1",
        "2": "2",
        "3": "3",
        "4": "4",
        "5": "5",
        "6": "6",
        "7": "7", # unconfirmed, assuming based on confirmed 1-6
        "8": "8" # unconfirmed, assuming based on confirmed 1-6
    },
    # Pro 4 all unconfirmed, just assumed defaults to allow drive discovery even if mapped incorrectly
    "UNAS_PRO_4": {
        "1": "1",
        "2": "2",
        "3": "3",
        "4": "4"
    },
    # UNAS 4 all unconfirmed, just assumed defaults to allow drive discovery even if mapped incorrectly
    "UNAS_4": {
        "1": "1",
        "2": "2",
        "3": "3",
        "4": "4"
    },
    # UNAS 2 all unconfirmed, just assumed defaults to allow drive discovery even if mapped incorrectly
    "UNAS_2": {
        "1": "1",
        "2": "2"
    }
}

ATA_TO_BAY = BAY_MAPPINGS.get(DEVICE_MODEL)


class UNASMonitor:
    def __init__(self):
        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt.username_pw_set(MQTT_USER, MQTT_PASS)
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_disconnect = self._on_disconnect
        self.mqtt.on_message = self._on_message

        self.mqtt.will_set("homeassistant/unas/status", "offline", retain=True)
        self.mqtt.connect(MQTT_HOST, 1883, 60)
        self.mqtt.loop_start()
        time.sleep(2)

        self.monitor_interval = DEFAULT_MONITOR_INTERVAL
        self.mqtt.subscribe(MONITOR_INTERVAL_TOPIC)
        self.mqtt.publish("homeassistant/unas/status", "online", retain=True)

        self.bay_cache = {}
        self.known_drives = set()
        self.prev_cpu_idle = None
        self.prev_cpu_total = None
        self.prev_disk_read = None
        self.prev_disk_write = None
        self.prev_time = None

    def _on_connect(self, _client, _userdata, _flags, reason_code, _properties):
        if reason_code == 0:
            logger.info("MQTT connected")
        else:
            logger.error(f"MQTT failed: {reason_code}")

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            logger.warning("MQTT disconnected")

    def _on_message(self, _client, _userdata, msg):
        if msg.topic == MONITOR_INTERVAL_TOPIC:
            try:
                new_interval = int(float(msg.payload.decode()))
                if 5 <= new_interval <= 60:
                    old = self.monitor_interval
                    self.monitor_interval = new_interval
                    logger.info(f"Monitor interval: {old}s -> {new_interval}s")
            except (ValueError, TypeError):
                pass

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
        data['disk_read'], data['disk_write'] = self.get_disk_throughput()

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
        def read_proc_stat():
            with open('/proc/stat') as f:
                parts = f.readline().split()
                values = list(map(int, parts[1:]))
            idle_time = values[3] + values[4]  # idle + iowait
            total_time = sum(values)
            return idle_time, total_time

        # handle script startup/restart to avoid reporting 0% usage to HA
        if self.prev_cpu_idle is None:
            idle_start, total_start = read_proc_stat()
            time.sleep(1.0)
            idle_end, total_end = read_proc_stat()

            self.prev_cpu_idle = idle_end
            self.prev_cpu_total = total_end

            delta_idle = idle_end - idle_start
            delta_total = total_end - total_start

            if delta_total <= 0:
                return 0

            return int(100 * (1 - delta_idle / delta_total))

        idle_now, total_now = read_proc_stat()
        delta_idle = idle_now - self.prev_cpu_idle
        delta_total = total_now - self.prev_cpu_total

        self.prev_cpu_idle = idle_now
        self.prev_cpu_total = total_now

        if delta_total <= 0:
            return 0

        return int(100 * (1 - delta_idle / delta_total))

    def get_disk_throughput(self):
        def read_diskstats():
            read_sectors = 0
            write_sectors = 0
            with open('/proc/diskstats') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    device = parts[2]
                    if device.startswith('sd') and len(device) == 3:
                        read_sectors += int(parts[5])
                        write_sectors += int(parts[9])
            return read_sectors, write_sectors

        # handle script startup/restart to avoid reporting 0mbps usage to HA
        if self.prev_disk_read is None:
            read_start, write_start = read_diskstats()
            time_start = time.time()
            time.sleep(1.0)
            read_end, write_end = read_diskstats()
            time_end = time.time()

            self.prev_disk_read = read_end
            self.prev_disk_write = write_end
            self.prev_time = time_end

            time_delta = time_end - time_start
            read_bytes = (read_end - read_start) * 512
            write_bytes = (write_end - write_start) * 512

            read_mbps = (read_bytes / time_delta) / (1024 * 1024)
            write_mbps = (write_bytes / time_delta) / (1024 * 1024)

            return round(read_mbps, 2), round(write_mbps, 2)

        read_now, write_now = read_diskstats()
        time_now = time.time()

        time_delta = time_now - self.prev_time
        read_bytes = (read_now - self.prev_disk_read) * 512
        write_bytes = (write_now - self.prev_disk_write) * 512

        self.prev_disk_read = read_now
        self.prev_disk_write = write_now
        self.prev_time = time_now

        if time_delta <= 0:
            return 0.0, 0.0

        read_mbps = (read_bytes / time_delta) / (1024 * 1024)
        write_mbps = (write_bytes / time_delta) / (1024 * 1024)

        return round(read_mbps, 2), round(write_mbps, 2)

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
                    drive['power_on_hours'] = attr.get('raw', {}).get('value', 0)
                elif name == 'reallocated_sector_ct':
                    drive['bad_sectors'] = attr.get('raw', {}).get('value', 0)

            if 'bad_sectors' not in drive:
                drive['bad_sectors'] = 0

            if 'power_on_hours' not in drive:
                drive['power_on_hours'] = data.get('power_on_time', {}).get('hours', 0)

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

    def get_smb_connections(self):
        output = self.run_cmd(['smbstatus', '-b'])
        lines = output.strip().split('\n')

        connections = {}
        for line in lines[3:]:
            if not line.strip() or line.startswith('---'):
                continue

            parts = line.split()
            if len(parts) < 6:
                continue

            pid = parts[0]
            username = parts[1]
            ip = parts[3].split('(')[1].split(':')[0] if '(' in parts[3] else parts[3]

            connections[pid] = {
                'username': username,
                'ip': ip
            }

        return connections

    def get_smb_shares(self):
        output = self.run_cmd(['smbstatus', '-S'])
        lines = output.strip().split('\n')

        shares = []
        for line in lines[2:]:
            if not line.strip() or line.startswith('---'):
                continue

            parts = line.split()
            if len(parts) < 3:
                continue

            shares.append({
                'share': parts[0],
                'pid': parts[1],
                'ip': parts[2]
            })

        return shares

    def get_nfs_mounts(self):
        output = self.run_cmd(['showmount', '-a'])
        lines = output.strip().split('\n')[1:]

        mounts = []
        for line in lines:
            if not line.strip():
                continue

            parts = line.split(':')
            if len(parts) != 2:
                continue

            ip = parts[0]
            path = parts[1]

            share_match = path.split('/.srv/.unifi-drive/')
            if len(share_match) == 2:
                share = share_match[1].split('/')[0]
            else:
                share = 'unknown'

            mounts.append({
                'ip': ip,
                'share': share
            })

        return mounts

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

        smb_connections = self.get_smb_connections()
        smb_shares = self.get_smb_shares()

        smb_data = {
            'count': len(smb_shares),
            'clients': []
        }

        for share in smb_shares:
            conn = smb_connections.get(share['pid'], {})
            smb_data['clients'].append({
                'username': conn.get('username', 'unknown'),
                'ip': share['ip'],
                'share': share['share']
            })

        self.mqtt.publish("homeassistant/sensor/unas_smb_connections/state", str(smb_data['count']), retain=True)
        self.mqtt.publish("homeassistant/sensor/unas_smb_connections/attributes", json.dumps(smb_data['clients']), retain=True)

        nfs_mounts = self.get_nfs_mounts()
        nfs_data = {
            'count': len(nfs_mounts),
            'clients': nfs_mounts
        }

        self.mqtt.publish("homeassistant/sensor/unas_nfs_mounts/state", str(nfs_data['count']), retain=True)
        self.mqtt.publish("homeassistant/sensor/unas_nfs_mounts/attributes", json.dumps(nfs_data['clients']), retain=True)

        temps = [d.get('temperature', 0) for d in drives if 'temperature' in d]
        temp_str = ', '.join(f"{t}°C" for t in temps) if temps else "no drives"

        logger.info(
            f"{system['fan_speed']} PWM ({system['fan_speed_percent']}%) | "
            f"CPU {system['cpu_temp']}°C | "
            f"HDD {temp_str} | "
            f"R: {system['disk_read']} MB/s W: {system['disk_write']} MB/s"
        )

    def run(self):
        logger.info(f"UNAS monitor started (interval: {self.monitor_interval}s)")

        while True:
            try:
                self.collect_and_publish()
            except Exception as e:
                logger.error(f"Error: {e}")

            time.sleep(self.monitor_interval)


if __name__ == '__main__':
    monitor = UNASMonitor()
    monitor.run()
