from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components import mqtt

from . import UNASDataUpdateCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Fan control modes
MODE_UNAS_MANAGED = "UNAS Managed"
MODE_CUSTOM_CURVE = "Custom Curve"
MODE_SET_SPEED = "Set Speed"

MQTT_MODE_UNAS_MANAGED = "unas_managed"
MQTT_MODE_CUSTOM_CURVE = "auto"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UNASDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities([UNASFanModeSelect(coordinator, hass)])


class UNASFanModeSelect(CoordinatorEntity, SelectEntity):
    def __init__(
        self, coordinator: UNASDataUpdateCoordinator, hass: HomeAssistant
    ) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._attr_name = "UNAS Fan Mode"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fan_mode"
        self._attr_icon = "mdi:fan-auto"
        self._attr_options = [MODE_UNAS_MANAGED, MODE_CUSTOM_CURVE, MODE_SET_SPEED]
        self._current_option = None
        self._unsubscribe = None

        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": f"UNAS Pro ({coordinator.ssh_manager.host})",
            "manufacturer": "Ubiquiti",
            "model": "UNAS Pro",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # MQTT retained message is source of truth for fan mode
        # Migration path: /tmp/fan_mode (old) -> /root/fan_mode (new persistent)
        current_mode = None
        mode_source = "default"

        try:
            # Check new persistent location first
            stdout, _ = await self.coordinator.ssh_manager.execute_command(
                "cat /root/fan_mode 2>/dev/null || echo ''"
            )
            file_mode = stdout.strip()

            if file_mode:
                current_mode = file_mode
                mode_source = "persistent_file"
                _LOGGER.info("Found fan mode in persistent storage: %s", current_mode)
            else:
                # Migration: check old /tmp location
                stdout, _ = await self.coordinator.ssh_manager.execute_command(
                    "cat /tmp/fan_mode 2>/dev/null || echo ''"
                )
                old_mode = stdout.strip()

                if old_mode:
                    current_mode = old_mode
                    mode_source = "migrated_from_tmp"
                    _LOGGER.info(
                        "Migrating fan mode from /tmp to /root: %s", current_mode
                    )

                    # Write to new persistent location
                    await self.coordinator.ssh_manager.execute_command(
                        f"echo '{current_mode}' > /root/fan_mode"
                    )

            # Default to UNAS Managed if no mode found anywhere
            if not current_mode:
                current_mode = MQTT_MODE_UNAS_MANAGED
                mode_source = "default"
                _LOGGER.info("No existing mode found, defaulting to UNAS Managed")

                # Write default to persistent location
                await self.coordinator.ssh_manager.execute_command(
                    f"echo '{current_mode}' > /root/fan_mode"
                )

            # Always publish to MQTT to ensure retained message exists
            await mqtt.async_publish(
                self.hass,
                "homeassistant/unas/fan_mode",
                current_mode,
                qos=0,
                retain=True,
            )

            # Set initial state
            if current_mode == MQTT_MODE_UNAS_MANAGED:
                self._current_option = MODE_UNAS_MANAGED
            elif current_mode == MQTT_MODE_CUSTOM_CURVE:
                self._current_option = MODE_CUSTOM_CURVE
            elif current_mode.isdigit():
                self._current_option = MODE_SET_SPEED
            else:
                self._current_option = MODE_UNAS_MANAGED

            _LOGGER.info(
                "Fan mode initialized: %s from %s (display: %s)",
                current_mode,
                mode_source,
                self._current_option,
            )
        except Exception as err:
            _LOGGER.error("Failed to initialize fan mode: %s", err)
            self._current_option = MODE_UNAS_MANAGED  # Default

        @callback
        def message_received(msg):
            payload = msg.payload
            _LOGGER.warning(
                "FAN MODE SELECT RECEIVED MQTT: topic=%s payload=%s", msg.topic, payload
            )

            old_option = self._current_option
            if payload == MQTT_MODE_UNAS_MANAGED:
                self._current_option = MODE_UNAS_MANAGED
                self.hass.async_create_task(self._ensure_service_stopped())
            elif payload == MQTT_MODE_CUSTOM_CURVE:
                self._current_option = MODE_CUSTOM_CURVE
                self.hass.async_create_task(self._ensure_service_running())
            elif payload.isdigit():
                self._current_option = MODE_SET_SPEED
                self.hass.async_create_task(self._ensure_service_running())
            else:
                # Default to UNAS Managed if unknown
                self._current_option = MODE_UNAS_MANAGED
                self.hass.async_create_task(self._ensure_service_stopped())

            if old_option != self._current_option:
                self.async_write_ha_state()
                _LOGGER.warning(
                    "Fan mode CHANGED from MQTT: old=%s new=%s (payload: %s)",
                    old_option,
                    self._current_option,
                    payload,
                )
            else:
                _LOGGER.info(
                    "Fan mode unchanged: %s (payload: %s)",
                    self._current_option,
                    payload,
                )

        # subscribe to MQTT topic - this will immediately receive the retained message if it exists
        self._unsubscribe = await mqtt.async_subscribe(
            self.hass,
            "homeassistant/unas/fan_mode",
            message_received,
            qos=0,
        )
        _LOGGER.info(
            "Fan mode select subscribed to MQTT - will sync from retained message if present"
        )

    async def _ensure_service_running(self) -> None:
        try:
            service_running = await self.coordinator.ssh_manager.service_running(
                "fan_control"
            )
            if not service_running:
                _LOGGER.info("Starting fan_control service to match mode")
                await self.coordinator.ssh_manager.execute_command(
                    "systemctl start fan_control"
                )
        except Exception as err:
            _LOGGER.error("Failed to start fan_control service: %s", err)

    async def _ensure_service_stopped(self) -> None:
        try:
            service_running = await self.coordinator.ssh_manager.service_running(
                "fan_control"
            )
            if service_running:
                _LOGGER.info("Stopping fan_control service to match UNAS Managed mode")
                await self.coordinator.ssh_manager.execute_command(
                    "systemctl stop fan_control"
                )
        except Exception as err:
            _LOGGER.error("Failed to stop fan_control service: %s", err)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        await super().async_will_remove_from_hass()

    @property
    def current_option(self) -> str | None:
        return self._current_option

    @property
    def available(self) -> bool:
        return self._current_option is not None

    async def async_select_option(self, option: str) -> None:
        _LOGGER.info("Changing fan mode to: %s", option)

        try:
            if option == MODE_UNAS_MANAGED:
                # stop the fan_control service to let UNAS firmware manage fans
                _LOGGER.info("Stopping fan_control service for UNAS Managed mode")
                await self.coordinator.ssh_manager.execute_command(
                    "systemctl stop fan_control"
                )

                await mqtt.async_publish(
                    self.hass,
                    "homeassistant/unas/fan_mode",
                    MQTT_MODE_UNAS_MANAGED,
                    qos=0,
                    retain=True,
                )
                _LOGGER.info("Fan mode set to UNAS Managed - service stopped")

            elif option == MODE_CUSTOM_CURVE:
                service_running = await self.coordinator.ssh_manager.service_running(
                    "fan_control"
                )
                if not service_running:
                    _LOGGER.info("Starting fan_control service for Custom Curve mode")
                    await self.coordinator.ssh_manager.execute_command(
                        "systemctl start fan_control"
                    )

                await mqtt.async_publish(
                    self.hass,
                    "homeassistant/unas/fan_mode",
                    MQTT_MODE_CUSTOM_CURVE,
                    qos=0,
                    retain=True,
                )
                _LOGGER.info("Fan mode set to Custom Curve")

            elif option == MODE_SET_SPEED:
                service_running = await self.coordinator.ssh_manager.service_running(
                    "fan_control"
                )
                if not service_running:
                    _LOGGER.info("Starting fan_control service for Set Speed mode")
                    await self.coordinator.ssh_manager.execute_command(
                        "systemctl start fan_control"
                    )

                mqtt_data = self.coordinator.mqtt_client.get_data()
                current_speed = mqtt_data.get("unas_fan_speed", 204)  # Default to 80%

                await mqtt.async_publish(
                    self.hass,
                    "homeassistant/unas/fan_mode",
                    str(current_speed),
                    qos=0,
                    retain=True,
                )
                _LOGGER.info(
                    "Fan mode set to Set Speed (locked to %s PWM)", current_speed
                )

            self._current_option = option
            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.error("Failed to change fan mode: %s", err)
