from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import asyncssh

_LOGGER = logging.getLogger(__name__)

# script files are bundled with the integration
SCRIPTS_DIR = Path(__file__).parent / "scripts"


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
            return

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

    async def deploy_scripts(self) -> None:
        await self.connect()

        _LOGGER.info("Deploying scripts to UNAS...")

        try:
            monitor_script = (SCRIPTS_DIR / "unas_monitor.sh").read_text()
            monitor_service = (SCRIPTS_DIR / "unas_monitor.service").read_text()
            fan_control_script = (SCRIPTS_DIR / "fan_control.sh").read_text()
            fan_control_service = (SCRIPTS_DIR / "fan_control.service").read_text()

            # Replace MQTT placeholders with actual credentials
            if self.mqtt_host and self.mqtt_user and self.mqtt_password:
                monitor_script = monitor_script.replace(
                    'MQTT_HOST="192.168.1.111"', f'MQTT_HOST="{self.mqtt_host}"'
                )
                monitor_script = monitor_script.replace(
                    'MQTT_USER="homeassistant"', f'MQTT_USER="{self.mqtt_user}"'
                )
                monitor_script = monitor_script.replace(
                    'MQTT_PASS="unas_password_123"', f'MQTT_PASS="{self.mqtt_password}"'
                )

                fan_control_script = fan_control_script.replace(
                    'MQTT_HOST="192.168.1.111"', f'MQTT_HOST="{self.mqtt_host}"'
                )
                fan_control_script = fan_control_script.replace(
                    'MQTT_USER="homeassistant"', f'MQTT_USER="{self.mqtt_user}"'
                )
                fan_control_script = fan_control_script.replace(
                    'MQTT_PASS="unas_password_123"', f'MQTT_PASS="{self.mqtt_password}"'
                )

                # Validate that credentials were actually replaced (unless they match defaults)
                # Only validate if the user credentials differ from defaults
                if (
                    self.mqtt_host != "192.168.1.111"
                    and 'MQTT_HOST="192.168.1.111"' in monitor_script
                ):
                    raise ValueError("Failed to replace MQTT_HOST in monitor script")
                if (
                    self.mqtt_user != "homeassistant"
                    and 'MQTT_USER="homeassistant"' in monitor_script
                ):
                    raise ValueError("Failed to replace MQTT_USER in monitor script")
                if (
                    self.mqtt_password != "unas_password_123"
                    and 'MQTT_PASS="unas_password_123"' in monitor_script
                ):
                    raise ValueError("Failed to replace MQTT_PASS in monitor script")
                if (
                    self.mqtt_host != "192.168.1.111"
                    and 'MQTT_HOST="192.168.1.111"' in fan_control_script
                ):
                    raise ValueError(
                        "Failed to replace MQTT_HOST in fan control script"
                    )
                if (
                    self.mqtt_user != "homeassistant"
                    and 'MQTT_USER="homeassistant"' in fan_control_script
                ):
                    raise ValueError(
                        "Failed to replace MQTT_USER in fan control script"
                    )
                if (
                    self.mqtt_password != "unas_password_123"
                    and 'MQTT_PASS="unas_password_123"' in fan_control_script
                ):
                    raise ValueError(
                        "Failed to replace MQTT_PASS in fan control script"
                    )

                _LOGGER.info(
                    "MQTT credentials validated in scripts (host=%s, user=%s)",
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

            # set fan mode to UNAS Managed by default on first install (if mode file doesn't exist)
            await self.execute_command(
                "if [ ! -f /tmp/fan_mode ]; then echo 'unas_managed' > /tmp/fan_mode; fi"
            )

            _LOGGER.info("Scripts deployed and services started successfully")

        except Exception as err:
            _LOGGER.error("Failed to deploy scripts: %s", err)
            raise

    async def _upload_file(
        self, remote_path: str, content: str, executable: bool = False
    ) -> None:
        # Create temp file and upload
        async with self._conn.start_sftp_client() as sftp:
            async with sftp.open(remote_path, "w") as remote_file:
                await remote_file.write(content)

        if executable:
            await self.execute_command(f"chmod +x {remote_path}")

        _LOGGER.debug("Uploaded file to %s", remote_path)
