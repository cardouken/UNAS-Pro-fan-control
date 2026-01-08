from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components import mqtt

from . import UNASDataUpdateCoordinator
from .const import DOMAIN

DEFAULT_FAN_SPEED_50_PCT = 128

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


class UNASFanModeSelect(CoordinatorEntity, SelectEntity, RestoreEntity):
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
        self._last_pwm = None
        self._unsubscribe = None

        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": f"UNAS Pro ({coordinator.ssh_manager.host})",
            "manufacturer": "Ubiquiti",
            "model": "UNAS Pro",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            self._current_option = last_state.state
            self._last_pwm = last_state.attributes.get("last_pwm")
            _LOGGER.debug("Restored fan mode: %s (last_pwm: %s)", self._current_option, self._last_pwm)

            # publish restored state to MQTT so the script knows what mode to run
            mqtt_mode = MQTT_MODE_UNAS_MANAGED
            if self._current_option == MODE_UNAS_MANAGED:
                mqtt_mode = MQTT_MODE_UNAS_MANAGED
            elif self._current_option == MODE_CUSTOM_CURVE:
                mqtt_mode = MQTT_MODE_CUSTOM_CURVE
            elif self._current_option == MODE_SET_SPEED:
                if self._last_pwm is not None:
                    mqtt_mode = str(self._last_pwm)
                    _LOGGER.debug("Using stored last PWM: %s", self._last_pwm)
                else:
                    # fallback if no stored PWM
                    mqtt_mode = str(DEFAULT_FAN_SPEED_50_PCT)
                    self._last_pwm = DEFAULT_FAN_SPEED_50_PCT
                    _LOGGER.debug("No stored PWM, using default: %s", DEFAULT_FAN_SPEED_50_PCT)

            await self._publish_mode_to_mqtt(mqtt_mode)
            _LOGGER.info("Published restored fan mode to MQTT: %s -> %s", self._current_option, mqtt_mode)
        else:
            self._current_option = MODE_UNAS_MANAGED
            await self._publish_mode_to_mqtt(MQTT_MODE_UNAS_MANAGED)

        @callback
        def message_received(msg):
            payload = msg.payload
            old_option = self._current_option

            if payload == MQTT_MODE_UNAS_MANAGED:
                self._current_option = MODE_UNAS_MANAGED
            elif payload == MQTT_MODE_CUSTOM_CURVE:
                self._current_option = MODE_CUSTOM_CURVE
            elif payload.isdigit():
                self._current_option = MODE_SET_SPEED
                try:
                    self._last_pwm = int(payload)
                except (ValueError, TypeError):
                    pass
            else:
                self._current_option = MODE_UNAS_MANAGED

            self.async_write_ha_state()
            if old_option != self._current_option:
                _LOGGER.info("Fan mode changed: %s -> %s", old_option, self._current_option)
            else:
                _LOGGER.debug("Fan mode reconfirmed: %s", self._current_option)

        self._unsubscribe = await mqtt.async_subscribe(
            self.hass,
            "homeassistant/unas/fan_mode",
            message_received,
            qos=0,
        )

    async def _publish_mode_to_mqtt(self, mode: str) -> None:
        try:
            await mqtt.async_publish(
                self.hass,
                "homeassistant/unas/fan_mode",
                mode,
                qos=0,
                retain=True,
            )
        except Exception as err:
            _LOGGER.error("Failed to publish fan mode to MQTT: %s", err)

    async def _ensure_service_running(self) -> None:
        try:
            if not await self.coordinator.ssh_manager.service_running("fan_control"):
                await self.coordinator.ssh_manager.execute_command("systemctl start fan_control")
        except Exception as err:
            _LOGGER.error("Failed to start fan_control service: %s", err)

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

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {}
        if self._last_pwm is not None:
            attrs["last_pwm"] = self._last_pwm
        return attrs

    async def async_select_option(self, option: str) -> None:
        """Handle mode selection - just publish to MQTT, service handles all modes."""
        try:
            await self._ensure_service_running()

            if option == MODE_UNAS_MANAGED:
                await self._publish_mode_to_mqtt(MQTT_MODE_UNAS_MANAGED)
            elif option == MODE_CUSTOM_CURVE:
                await self._publish_mode_to_mqtt(MQTT_MODE_CUSTOM_CURVE)
            elif option == MODE_SET_SPEED:
                mqtt_data = self.coordinator.mqtt_client.get_data()
                current_speed = mqtt_data.get("unas_fan_speed", DEFAULT_FAN_SPEED_50_PCT)
                self._last_pwm = current_speed
                await self._publish_mode_to_mqtt(str(current_speed))

            self._current_option = option
            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.error("Failed to change fan mode: %s", err)
