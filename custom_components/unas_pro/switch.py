from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components import mqtt

from . import UNASDataUpdateCoordinator
from .const import DOMAIN, get_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UNASDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    async_add_entities([UNASFanAutoModeSwitch(coordinator, hass)])


class UNASFanAutoModeSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(
        self, coordinator: UNASDataUpdateCoordinator, hass: HomeAssistant
    ) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._attr_name = "UNAS Fan Auto Mode"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fan_auto_mode"
        self._attr_icon = "mdi:fan-auto"
        self._is_on = None  # Unknown until we read from MQTT
        self._unsubscribe = None

        self._attr_device_info = get_device_info(
            coordinator.entry.entry_id, coordinator.ssh_manager.host
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def message_received(msg):
            payload = msg.payload
            old_state = self._is_on
            self._is_on = payload == "auto"
            if old_state != self._is_on:
                self.async_write_ha_state()
                _LOGGER.info(
                    "Fan auto mode state updated from MQTT: %s (payload: %s)",
                    "ON" if self._is_on else "OFF",
                    payload,
                )

        self._unsubscribe = await mqtt.async_subscribe(
            self.hass,
            "homeassistant/unas/fan_override",
            message_received,
            qos=0,
        )
        _LOGGER.info(
            "Fan auto mode switch subscribed to MQTT - will sync from retained message if present"
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        await super().async_will_remove_from_hass()

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def available(self) -> bool:
        return self._is_on is not None

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.info("Turning on fan auto mode (publishing 'auto' to override topic)")
        try:
            # publish to MQTT with retain flag - this is the single source of truth
            await mqtt.async_publish(
                self.hass,
                "homeassistant/unas/fan_override",
                "auto",
                qos=0,
                retain=True,
            )
            self._is_on = True
            self.async_write_ha_state()
            _LOGGER.info("Fan auto mode enabled - published 'auto' to MQTT")
        except Exception as err:
            _LOGGER.error("Failed to enable auto mode: %s", err)

    async def async_turn_off(self, **kwargs) -> None:
        # get current fan speed from MQTT data
        mqtt_data = self.coordinator.mqtt_client.get_data()
        current_speed = mqtt_data.get("unas_fan_speed", 204)  # Default to 80%

        _LOGGER.info("Turning off fan auto mode (locking to %s PWM)", current_speed)
        try:
            await mqtt.async_publish(
                self.hass,
                "homeassistant/unas/fan_override",
                str(current_speed),
                qos=0,
                retain=True,
            )
            self._is_on = False
            self.async_write_ha_state()
            _LOGGER.info(
                "Fan auto mode disabled - locked to %s PWM, adjust with slider",
                current_speed,
            )
        except Exception as err:
            _LOGGER.error("Failed to disable auto mode: %s", err)
