from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components import mqtt

from . import UNASDataUpdateCoordinator
from .const import CONF_DEVICE_MODEL, DOMAIN, get_device_info, get_mqtt_topics

DEFAULT_FAN_SPEED_50_PCT = 128

_LOGGER = logging.getLogger(__name__)

MODE_CUSTOM_CURVE = "Custom Curve"
MODE_SET_SPEED = "Set Speed"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UNASDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([UNASFanModeSelect(coordinator, hass)])


class UNASFanModeSelect(CoordinatorEntity, SelectEntity, RestoreEntity):
    def __init__(self, coordinator: UNASDataUpdateCoordinator, hass: HomeAssistant) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._topics = get_mqtt_topics(coordinator.entry.entry_id)
        self._attr_has_entity_name = True
        self._attr_name = "Fan Mode"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fan_mode"
        self._attr_icon = "mdi:fan-auto"
        self._current_option = None
        self._last_pwm = None
        self._unsubscribe = None

        device_name, device_model = get_device_info(coordinator.entry.data[CONF_DEVICE_MODEL])
        self._mode_managed = f"{device_name} Managed"
        self._attr_options = [self._mode_managed, MODE_CUSTOM_CURVE, MODE_SET_SPEED]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=device_name,
            manufacturer="Ubiquiti",
            model=device_model,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            self._current_option = last_state.state
            self._last_pwm = last_state.attributes.get("last_pwm")

            mqtt_mode = "unas_managed"
            if self._current_option == MODE_CUSTOM_CURVE:
                mqtt_mode = "auto"
            elif self._current_option == MODE_SET_SPEED:
                mqtt_mode = str(self._last_pwm or DEFAULT_FAN_SPEED_50_PCT)
                self._last_pwm = self._last_pwm or DEFAULT_FAN_SPEED_50_PCT

            await self._publish_mode(mqtt_mode)
        else:
            self._current_option = self._mode_managed
            await self._publish_mode("unas_managed")

        @callback
        def message_received(msg):
            payload = msg.payload

            if payload == "unas_managed":
                self._current_option = self._mode_managed
            elif payload == "auto":
                self._current_option = MODE_CUSTOM_CURVE
            elif payload.isdigit():
                self._current_option = MODE_SET_SPEED
                try:
                    self._last_pwm = int(payload)
                except (ValueError, TypeError):
                    pass
            else:
                self._current_option = self._mode_managed

            self.async_write_ha_state()

        self._unsubscribe = await mqtt.async_subscribe(
            self.hass, f"{self._topics['control']}/fan/mode", message_received, qos=0
        )

    async def _publish_mode(self, mode: str) -> None:
        try:
            await mqtt.async_publish(self.hass, f"{self._topics['control']}/fan/mode", mode, qos=0, retain=True)
        except Exception as err:
            _LOGGER.error("Failed to publish fan mode: %s", err)

    async def _ensure_service_running(self) -> None:
        try:
            if not await self.coordinator.ssh_manager.service_running("fan_control"):
                await self.coordinator.ssh_manager.execute_command("systemctl start fan_control")
        except Exception as err:
            _LOGGER.error("Failed to start fan_control service: %s", err)

    @property
    def available(self) -> bool:
        mqtt_available = self.coordinator.mqtt_client.is_available()
        service_running = self.coordinator.data.get("fan_control_running", False)
        has_state = self._current_option is not None
        return mqtt_available and service_running and has_state

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        await super().async_will_remove_from_hass()

    @property
    def current_option(self) -> str | None:
        return self._current_option

    @property
    def extra_state_attributes(self) -> dict:
        return {"last_pwm": self._last_pwm} if self._last_pwm is not None else {}

    async def async_select_option(self, option: str) -> None:
        await self._ensure_service_running()

        if option == self._mode_managed:
            await self._publish_mode("unas_managed")
        elif option == MODE_CUSTOM_CURVE:
            await self._publish_mode("auto")
        elif option == MODE_SET_SPEED:
            mqtt_data = self.coordinator.mqtt_client.get_data()
            current_speed = mqtt_data.get("unas_fan_speed", DEFAULT_FAN_SPEED_50_PCT)
            self._last_pwm = current_speed
            await self._publish_mode(str(current_speed))

        self._current_option = option
        self.async_write_ha_state()
