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

        # Deploy scripts on first setup
        if not await ssh_manager.scripts_installed():
            _LOGGER.info("Scripts not found, deploying...")
            await ssh_manager.deploy_scripts()
        else:
            _LOGGER.info("Scripts already installed")

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

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["mqtt_client"].async_unsubscribe()
        await data["ssh_manager"].disconnect()

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

            # check for new drives when sensor platform is ready
            if hasattr(self, "sensor_add_entities") and hasattr(
                self, "_discovered_bays"
            ):
                from .sensor import _discover_and_add_drive_sensors

                await _discover_and_add_drive_sensors(self, self.sensor_add_entities)

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
