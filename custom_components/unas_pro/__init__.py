from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_MQTT_HOST,
    CONF_MQTT_USER,
    CONF_MQTT_PASSWORD,
    DEFAULT_SCAN_INTERVAL,
)
from .ssh_manager import SSHManager
from .mqtt_client import UNASMQTTClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
]

# key to track last version that performed MQTT cleanup
LAST_CLEANUP_VERSION_KEY = "last_cleanup_version"
LAST_DEPLOY_VERSION_KEY = "last_deploy_version"
PERFORM_MQTT_CLEANUP = True


async def _cleanup_old_mqtt_configs_on_upgrade(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    if not PERFORM_MQTT_CLEANUP:
        return

    # get current version from manifest
    from homeassistant.loader import async_get_integration

    integration = await async_get_integration(hass, DOMAIN)
    current_version = str(integration.version)

    # get last cleanup version
    last_cleanup_version = entry.data.get(LAST_CLEANUP_VERSION_KEY)

    # run cleanup if version changed or never run before
    if last_cleanup_version != current_version:
        _LOGGER.info(
            "Integration upgraded from %s to %s - running MQTT config cleanup",
            last_cleanup_version or "unknown",
            current_version,
        )

    from homeassistant.components import mqtt

    # list of topics to clear (system sensors)
    topics_to_clear = [
        "unas_uptime",
        "unas_os_version",
        "unas_drive_version",
        "unas_cpu_usage",
        "unas_memory_used",
        "unas_memory_total",
        "unas_memory_usage",
        "unas_cpu",
        "unas_fan_speed",
        "unas_fan_speed_percent",
    ]

    # storage pool sensors (up to 5 pools)
    for i in range(1, 6):
        topics_to_clear.extend(
            [
                f"unas_pool{i}_usage",
                f"unas_pool{i}_size",
                f"unas_pool{i}_used",
                f"unas_pool{i}_available",
            ]
        )

    # HDD sensors (bays 1-7)
    for bay in range(1, 8):
        topics_to_clear.extend(
            [
                f"unas_hdd_{bay}_temperature",
                f"unas_hdd_{bay}_model",
                f"unas_hdd_{bay}_serial",
                f"unas_hdd_{bay}_rpm",
                f"unas_hdd_{bay}_firmware",
                f"unas_hdd_{bay}_status",
                f"unas_hdd_{bay}_total_size",
                f"unas_hdd_{bay}_power_hours",
                f"unas_hdd_{bay}_bad_sectors",
            ]
        )

    # clear each config topic by publishing empty retained message
    cleared_count = 0
    for topic in topics_to_clear:
        try:
            await mqtt.async_publish(
                hass,
                f"homeassistant/sensor/{topic}/config",
                "",
                qos=0,
                retain=True,
            )
            cleared_count += 1
        except Exception as err:
            _LOGGER.debug("Failed to clear MQTT config for %s: %s", topic, err)

    _LOGGER.info("Cleared %d old MQTT auto-discovery configs", cleared_count)

    # mark this version as cleaned up
    new_data = dict(entry.data)
    new_data[LAST_CLEANUP_VERSION_KEY] = current_version
    hass.config_entries.async_update_entry(entry, data=new_data)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ssh_manager = SSHManager(
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data.get(CONF_PASSWORD),
        mqtt_host=entry.data.get(CONF_MQTT_HOST),
        mqtt_user=entry.data.get(CONF_MQTT_USER),
        mqtt_password=entry.data.get(CONF_MQTT_PASSWORD),
    )

    # Test connection and deploy scripts
    try:
        await ssh_manager.connect()
        _LOGGER.info("SSH connection established to %s", entry.data[CONF_HOST])

        # deploy scripts on version change or if missing
        from homeassistant.loader import async_get_integration

        integration = await async_get_integration(hass, DOMAIN)
        current_version = str(integration.version)
        last_deploy_version = entry.data.get(LAST_DEPLOY_VERSION_KEY)
        scripts_installed = await ssh_manager.scripts_installed()

        if last_deploy_version != current_version or not scripts_installed:
            if not scripts_installed:
                _LOGGER.info("Scripts not found, deploying...")
            else:
                _LOGGER.info(
                    "Integration upgraded from %s to %s - redeploying scripts",
                    last_deploy_version or "unknown",
                    current_version,
                )
            await ssh_manager.deploy_scripts()

            # mark this version as deployed
            new_data = dict(entry.data)
            new_data[LAST_DEPLOY_VERSION_KEY] = current_version
            hass.config_entries.async_update_entry(entry, data=new_data)
        else:
            _LOGGER.info("Scripts up to date (version %s)", current_version)

    except Exception as err:
        _LOGGER.error("Failed to connect to UNAS: %s", err)
        return False

    # Initialize MQTT client
    mqtt_client = UNASMQTTClient(hass, entry.data[CONF_HOST])

    # Create coordinator
    coordinator = UNASDataUpdateCoordinator(hass, ssh_manager, mqtt_client, entry)

    # Link coordinator back to MQTT client for updates
    mqtt_client._coordinator = coordinator

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator and clients
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "ssh_manager": ssh_manager,
        "mqtt_client": mqtt_client,
    }

    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Subscribe to MQTT topics
    await mqtt_client.async_subscribe()

    # cleanup old MQTT configs on upgrade (runs every version change)
    await _cleanup_old_mqtt_configs_on_upgrade(hass, entry)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)

        # clean up MQTT subscription
        await data["mqtt_client"].async_unsubscribe()

        # stop and remove services from UNAS to restore stock behavior
        ssh_manager = data["ssh_manager"]
        try:
            _LOGGER.info("Cleaning up UNAS services and scripts...")

            # Stop services
            await ssh_manager.execute_command("systemctl stop unas_monitor || true")
            await ssh_manager.execute_command("systemctl stop fan_control || true")

            # Disable services
            await ssh_manager.execute_command("systemctl disable unas_monitor || true")
            await ssh_manager.execute_command("systemctl disable fan_control || true")

            # Remove service files
            await ssh_manager.execute_command(
                "rm -f /etc/systemd/system/unas_monitor.service"
            )
            await ssh_manager.execute_command(
                "rm -f /etc/systemd/system/fan_control.service"
            )

            # Remove scripts
            await ssh_manager.execute_command("rm -f /root/unas_monitor.sh")
            await ssh_manager.execute_command("rm -f /root/fan_control.sh")

            # Remove state files
            await ssh_manager.execute_command("rm -f /tmp/fan_mode")

            # Reload systemd
            await ssh_manager.execute_command("systemctl daemon-reload")

            # Re-enable UNAS firmware fan control by setting pwm_enable back to auto (2)
            await ssh_manager.execute_command(
                "echo 2 > /sys/class/hwmon/hwmon0/pwm1_enable || true"
            )
            await ssh_manager.execute_command(
                "echo 2 > /sys/class/hwmon/hwmon0/pwm2_enable || true"
            )

            _LOGGER.info("Successfully cleaned up UNAS - restored to stock fan control")
        except Exception as err:
            _LOGGER.error("Failed to clean up UNAS (non-critical): %s", err)

        # Disconnect SSH
        await ssh_manager.disconnect()

    return unload_ok


class UNASDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        ssh_manager: SSHManager,
        mqtt_client: UNASMQTTClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        self.ssh_manager = ssh_manager
        self.mqtt_client = mqtt_client
        self.entry = entry

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self):
        # check if MQTT integration is still available
        from homeassistant.components import mqtt

        if mqtt.DOMAIN not in self.hass.data:
            _LOGGER.error(
                "MQTT integration has been removed - UNAS Pro requires MQTT to function"
            )
            from homeassistant.helpers import issue_registry as ir

            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "mqtt_missing",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="mqtt_missing",
            )
            raise UpdateFailed("MQTT integration is required but not found")

        try:
            # check if scripts are still installed (firmware update detection)
            scripts_installed = await self.ssh_manager.scripts_installed()

            if not scripts_installed:
                _LOGGER.warning("Scripts missing (firmware update?), reinstalling...")
                await self.ssh_manager.deploy_scripts()

            # check service status
            monitor_running = await self.ssh_manager.service_running("unas_monitor")
            fan_control_running = await self.ssh_manager.service_running("fan_control")

            # get MQTT data
            mqtt_data = self.mqtt_client.get_data()

            # check for new drives and pools when sensor platform is ready
            if hasattr(self, "sensor_add_entities") and hasattr(
                self, "_discovered_bays"
            ):
                from .sensor import (
                    _discover_and_add_drive_sensors,
                    _discover_and_add_pool_sensors,
                )

                await _discover_and_add_drive_sensors(self, self.sensor_add_entities)
                await _discover_and_add_pool_sensors(self, self.sensor_add_entities)

            return {
                "scripts_installed": scripts_installed,
                "ssh_connected": True,
                "monitor_running": monitor_running,
                "fan_control_running": fan_control_running,
                "mqtt_data": mqtt_data,
            }

        except Exception as err:
            raise UpdateFailed(f"Error communicating with UNAS: {err}")

    async def async_reinstall_scripts(self) -> None:
        await self.ssh_manager.deploy_scripts()
        await self.async_request_refresh()
