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
    "MQTT_HOST": "192.168.1.111",
    "MQTT_USER": "homeassistant",
    "MQTT_PASS": "unas_password_123",
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
                return
            except Exception:
                try:
                    self._conn.close()
                    await self._conn.wait_closed()
                except Exception:
                    pass
                self._conn = None

        try:
            self._conn = await asyncssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                client_keys=[self.ssh_key] if self.ssh_key else None,
                known_hosts=None,  # accept any host key (not ideal but necessary for NAS)
            )
            _LOGGER.info("SSH connection established to %s", self.host)
        except Exception as err:
            _LOGGER.error("Failed to connect via SSH: %s", err)
            raise

    async def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    async def execute_command(self, command: str) -> tuple[str, str]:
        await self.connect()

        try:
            result = await self._conn.run(command, check=False)
            return result.stdout, result.stderr
        except (asyncssh.ConnectionLost, asyncssh.DisconnectError, BrokenPipeError) as err:
            # Connection died, properly close and force reconnect on next attempt
            _LOGGER.warning("SSH connection lost during command '%s': %s", command, err)
            await self.disconnect()
            raise
        except Exception as err:
            _LOGGER.error("Failed to execute command '%s': %s", command, err)
            raise

    async def scripts_installed(self) -> bool:
        stdout, _ = await self.execute_command(
            "test -f /root/unas_monitor.sh && test -f /root/fan_control.sh && echo 'yes' || echo 'no'"
        )
        return stdout.strip() == "yes"

    async def service_running(self, service_name: str) -> bool:
        stdout, _ = await self.execute_command(
            f"systemctl is-active {service_name} 2>/dev/null || echo 'inactive'"
        )
        return stdout.strip() == "active"

    def _replace_mqtt_credentials(self, script: str) -> str:
        replacements = {
            f'MQTT_HOST="{_DEFAULTS["MQTT_HOST"]}"': f'MQTT_HOST="{self.mqtt_host}"',
            f'MQTT_USER="{_DEFAULTS["MQTT_USER"]}"': f'MQTT_USER="{self.mqtt_user}"',
            f'MQTT_PASS="{_DEFAULTS["MQTT_PASS"]}"': f'MQTT_PASS="{self.mqtt_password}"',
        }

        for old, new in replacements.items():
            script = script.replace(old, new)

        return script

    def _validate_replacements(self, script: str, script_name: str) -> None:
        checks = [
            (self.mqtt_host, "MQTT_HOST", _DEFAULTS["MQTT_HOST"]),
            (self.mqtt_user, "MQTT_USER", _DEFAULTS["MQTT_USER"]),
            (self.mqtt_password, "MQTT_PASS", _DEFAULTS["MQTT_PASS"]),
        ]

        for user_value, key, default in checks:
            if user_value != default and f'{key}="{default}"' in script:
                raise ValueError(f"Failed to replace {key} in {script_name}")

    async def deploy_scripts(self) -> None:
        await self.connect()
        _LOGGER.info("Deploying scripts to UNAS...")

        try:
            async with aiofiles.open(SCRIPTS_DIR / "unas_monitor.sh", "r") as f:
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

                self._validate_replacements(monitor_script, "monitor script")
                self._validate_replacements(fan_control_script, "fan control script")

                _LOGGER.debug(
                    "MQTT credentials configured (host=%s, user=%s)",
                    self.mqtt_host,
                    self.mqtt_user,
                )

            await self._upload_file(
                "/root/unas_monitor.sh", monitor_script, executable=True
            )
            await self._upload_file(
                "/etc/systemd/system/unas_monitor.service",
                monitor_service,
                executable=False,
            )
            await self._upload_file(
                "/root/fan_control.sh", fan_control_script, executable=True
            )
            await self._upload_file(
                "/etc/systemd/system/fan_control.service",
                fan_control_service,
                executable=False,
            )

            await self.execute_command(
                "apt-get update && apt-get install -y mosquitto-clients"
            )
            await self.execute_command("systemctl daemon-reload")
            await self.execute_command("systemctl enable unas_monitor")
            await self.execute_command("systemctl restart unas_monitor")
            await self.execute_command("systemctl enable fan_control")
            await self.execute_command("systemctl restart fan_control")

            _LOGGER.info("Scripts deployed and services started")

        except Exception as err:
            _LOGGER.error("Failed to deploy scripts: %s", err)
            raise

    async def _upload_file(
        self, remote_path: str, content: str, executable: bool = False
    ) -> None:
        async with self._conn.start_sftp_client() as sftp:
            async with sftp.open(remote_path, "w") as remote_file:
                await remote_file.write(content)

        if executable:
            await self.execute_command(f"chmod +x {remote_path}")

        _LOGGER.debug("Uploaded file to %s", remote_path)
