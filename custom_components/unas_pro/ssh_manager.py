from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import aiofiles
import asyncssh

_LOGGER = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).parent / "scripts"

# Default values used in script templates
_DEFAULTS = {
    "MQTT_HOST": "REPLACE_ME",
    "MQTT_USER": "REPLACE_ME",
    "MQTT_PASS": "REPLACE_ME",
}


class SSHManager:
    def __init__(
            self,
            host: str,
            username: str,
            password: Optional[str] = None,
            ssh_key: Optional[str] = None,
            port: int = 22,
            mqtt_host: Optional[str] = None,
            mqtt_user: Optional[str] = None,
            mqtt_password: Optional[str] = None,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.ssh_key = ssh_key
        self.port = port
        self.mqtt_host = mqtt_host
        self.mqtt_user = mqtt_user
        self.mqtt_password = mqtt_password
        self._conn: Optional[asyncssh.SSHClientConnection] = None

    async def connect(self) -> None:
        if self._conn:
            try:
                await self._conn.run("true", timeout=2, check=False)
                _LOGGER.debug("SSH connection reused")
                return
            except Exception:
                try:
                    self._conn.close()
                    await self._conn.wait_closed()
                except Exception:
                    pass
                self._conn = None

        _LOGGER.debug("Establishing SSH connection to %s", self.host)
        self._conn = await asyncssh.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            client_keys=[self.ssh_key] if self.ssh_key else None,
            known_hosts=None,
        )
        _LOGGER.debug("SSH connection established")

    async def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    async def execute_command(self, command: str) -> tuple[str, str]:
        await self.connect()
        result = await self._conn.run(command, check=False)
        return result.stdout, result.stderr

    async def scripts_installed(self) -> bool:
        stdout, _ = await self.execute_command(
            "test -f /root/unas_monitor.py && test -f /root/fan_control.sh && echo 'yes' || echo 'no'"
        )
        installed = stdout.strip() == "yes"
        _LOGGER.debug("Scripts installed: %s", installed)
        return installed

    async def service_running(self, service_name: str) -> bool:
        stdout, _ = await self.execute_command(
            f"systemctl is-active {service_name} 2>/dev/null || echo 'inactive'"
        )
        running = stdout.strip() == "active"
        _LOGGER.debug("Service %s running: %s", service_name, running)
        return running

    def _replace_mqtt_credentials(self, script: str) -> str:
        replacements = {
            # python script replacement template (with spaces)
            f'MQTT_HOST = "{_DEFAULTS["MQTT_HOST"]}"': f'MQTT_HOST = "{self.mqtt_host}"',
            f'MQTT_USER = "{_DEFAULTS["MQTT_USER"]}"': f'MQTT_USER = "{self.mqtt_user}"',
            f'MQTT_PASS = "{_DEFAULTS["MQTT_PASS"]}"': f'MQTT_PASS = "{self.mqtt_password}"',

            # bash script replacement template (without spaces)
            f'MQTT_HOST="{_DEFAULTS["MQTT_HOST"]}"': f'MQTT_HOST="{self.mqtt_host}"',
            f'MQTT_USER="{_DEFAULTS["MQTT_USER"]}"': f'MQTT_USER="{self.mqtt_user}"',
            f'MQTT_PASS="{_DEFAULTS["MQTT_PASS"]}"': f'MQTT_PASS="{self.mqtt_password}"',
        }

        for old, new in replacements.items():
            script = script.replace(old, new)

        return script

    async def deploy_scripts(self) -> None:
        await self.connect()
        _LOGGER.info("Deploying scripts to UNAS...")

        try:
            async with aiofiles.open(SCRIPTS_DIR / "unas_monitor.py", "r") as f:
                monitor_script = await f.read()
            async with aiofiles.open(SCRIPTS_DIR / "unas_monitor.service", "r") as f:
                monitor_service = await f.read()
            async with aiofiles.open(SCRIPTS_DIR / "fan_control.sh", "r") as f:
                fan_control_script = await f.read()
            async with aiofiles.open(SCRIPTS_DIR / "fan_control.service", "r") as f:
                fan_control_service = await f.read()

            if self.mqtt_host and self.mqtt_user and self.mqtt_password:
                monitor_script = self._replace_mqtt_credentials(monitor_script)
                fan_control_script = self._replace_mqtt_credentials(fan_control_script)

            await self._upload_file("/root/unas_monitor.py", monitor_script, executable=True)
            await self._upload_file("/etc/systemd/system/unas_monitor.service", monitor_service)
            await self._upload_file("/root/fan_control.sh", fan_control_script, executable=True)
            await self._upload_file("/etc/systemd/system/fan_control.service", fan_control_service)

            await self.execute_command("apt-get update && apt-get install -y mosquitto-clients python3-pip")

            stdout, _ = await self.execute_command("pip3 show paho-mqtt 2>/dev/null || echo 'not_installed'")
            if "not_installed" in stdout:
                _LOGGER.info("Installing paho-mqtt on UNAS...")
                await self.execute_command("pip3 install paho-mqtt")

            await self.execute_command("systemctl daemon-reload")
            await self.execute_command("systemctl enable unas_monitor")
            await self.execute_command("systemctl restart unas_monitor")
            await self.execute_command("systemctl enable fan_control")
            await self.execute_command("systemctl restart fan_control")

            _LOGGER.info("Scripts deployed and services started")

        except Exception as err:
            _LOGGER.error("Failed to deploy scripts: %s", err)
            raise

    async def _upload_file(self, remote_path: str, content: str, executable: bool = False) -> None:
        async with self._conn.start_sftp_client() as sftp:
            async with sftp.open(remote_path, "w") as remote_file:
                await remote_file.write(content)

        if executable:
            await self.execute_command(f"chmod +x {remote_path}")
