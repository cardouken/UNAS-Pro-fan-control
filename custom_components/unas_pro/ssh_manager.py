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
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.ssh_key = ssh_key
        self.port = port
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
