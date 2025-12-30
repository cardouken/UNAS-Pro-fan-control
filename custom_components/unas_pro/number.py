from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components import mqtt

from . import UNASDataUpdateCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# fan curve parameter definitions: (key, name, min, max, default, unit, icon)
FAN_CURVE_PARAMS = [
    ("min_temp", "Min Temperature", 30, 50, 43, "°C", "mdi:thermometer-low"),
    ("max_temp", "Max Temperature", 45, 60, 47, "°C", "mdi:thermometer-high"),
    ("min_fan", "Min Fan Speed", 0, 255, 204, "PWM", "mdi:fan-speed-1"),
    ("max_fan", "Max Fan Speed", 0, 255, 255, "PWM", "mdi:fan-speed-3"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UNASDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    entities = [
        UNASFanSpeedNumber(coordinator, hass),
    ]

    # add fan curve configuration entities
    for key, name, min_val, max_val, default, unit, icon in FAN_CURVE_PARAMS:
        entities.append(
            UNASFanCurveNumber(
                coordinator, hass, key, name, min_val, max_val, default, unit, icon
            )
        )

    async_add_entities(entities)

class UNASFanSpeedNumber(CoordinatorEntity, NumberEntity):
    def __init__(self, coordinator: UNASDataUpdateCoordinator, hass: HomeAssistant) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._attr_name = "UNAS Fan Speed"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fan_speed_control"
        self._attr_icon = "mdi:fan"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = NumberMode.SLIDER
        self._current_value = None
        self._current_mode = None
        self._unsubscribe_speed = None
        self._unsubscribe_override = None

        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": f"UNAS Pro ({coordinator.ssh_manager.host})",
            "manufacturer": "Ubiquiti",
            "model": "UNAS Pro",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def speed_message_received(msg):
            try:
                pwm_value = int(msg.payload)
                # convert PWM (0-255) to percentage (0-100)
                percentage = round((pwm_value * 100) / 255)
                old_value = self._current_value
                self._current_value = percentage
                if old_value != self._current_value:
                    self.async_write_ha_state()
                    _LOGGER.debug("Fan speed updated: %s%% (PWM: %s)", percentage, pwm_value)
            except (ValueError, TypeError) as err:
                _LOGGER.error("Failed to parse fan speed: %s", err)

        @callback
        def override_message_received(msg):
            payload = msg.payload
            # track current mode to determine if slider should be editable
            if payload == "unas_managed":
                self._current_mode = "unas_managed"
            elif payload == "auto":
                self._current_mode = "auto"
            elif payload.isdigit():
                self._current_mode = "set_speed"
            else:
                self._current_mode = None
            self.async_write_ha_state()
            _LOGGER.debug("Fan mode updated: %s", self._current_mode)

        # subscribe to fan speed topic to get current speed
        self._unsubscribe_speed = await mqtt.async_subscribe(
            self.hass,
            "homeassistant/sensor/unas_fan_speed/state",
            speed_message_received,
            qos=0,
        )

        # subscribe to mode topic to know current mode
        self._unsubscribe_override = await mqtt.async_subscribe(
            self.hass,
            "homeassistant/unas/fan_mode",
            override_message_received,
            qos=0,
        )

        _LOGGER.info("Fan speed number entity subscribed to MQTT topics")

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe_speed:
            self._unsubscribe_speed()
        if self._unsubscribe_override:
            self._unsubscribe_override()
        await super().async_will_remove_from_hass()

    @property
    def native_value(self) -> float | None:
        return self._current_value

    @property
    def available(self) -> bool:
        return self._current_value is not None

    @property
    def entity_registry_enabled_default(self) -> bool:
        return True

    @property
    def icon(self) -> str:
        if self._current_mode == "unas_managed":
            return "mdi:fan-off"
        elif self._current_mode == "auto":
            return "mdi:fan-auto"
        elif self._current_mode == "set_speed":
            return "mdi:fan"
        return "mdi:fan"

    async def async_set_native_value(self, value: float) -> None:
        # check if we're in Set Speed mode
        if self._current_mode != "set_speed":
            _LOGGER.warning("Cannot set fan speed - not in Set Speed mode (current: %s)", self._current_mode)
            return

        try:
            # convert percentage to PWM (0-255)
            pwm_value = round((value * 255) / 100)
            _LOGGER.info("Setting fan speed to %s%% (PWM: %s)", value, pwm_value)

            await mqtt.async_publish(
                self.hass,
                "homeassistant/unas/fan_mode",
                str(pwm_value),
                qos=0,
                retain=True,
            )

            # update local value immediately for responsiveness
            self._current_value = value
            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.error("Failed to set fan speed: %s", err)

class UNASFanCurveNumber(CoordinatorEntity, NumberEntity):
    def __init__(
        self,
        coordinator: UNASDataUpdateCoordinator,
        hass: HomeAssistant,
        key: str,
        name: str,
        min_val: float,
        max_val: float,
        default: float,
        unit: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._key = key
        self._attr_name = f"UNAS Fan Curve {name}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fan_curve_{key}"
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = 1
        self._attr_native_value = None  # Unknown until synced
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_mode = NumberMode.BOX
        self._default = default
        self._unsubscribe = None

        self._mqtt_topic = f"homeassistant/unas/fan_curve/{key}"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": f"UNAS Pro ({coordinator.ssh_manager.host})",
            "manufacturer": "Ubiquiti",
            "model": "UNAS Pro",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def message_received(msg):
            try:
                value = float(msg.payload)
                if self._attr_native_min_value <= value <= self._attr_native_max_value:
                    self._attr_native_value = value
                    self.async_write_ha_state()
                    _LOGGER.debug("Fan curve %s updated to %s", self._key, value)
            except (ValueError, TypeError):
                _LOGGER.warning("Invalid value for %s: %s", self._key, msg.payload)

        self._unsubscribe = await mqtt.async_subscribe(
            self.hass,
            self._mqtt_topic,
            message_received,
            qos=0,
        )

        # try to read current value from MQTT (retained message)
        # if not available after 1 second, use default
        await self.hass.async_add_executor_job(self._wait_for_mqtt_or_default)

        _LOGGER.info("Fan curve %s subscribed to MQTT", self._key)

    def _wait_for_mqtt_or_default(self) -> None:
        import time

        time.sleep(1)

        # if still None after waiting, set to default and publish
        if self._attr_native_value is None:
            self._attr_native_value = self._default
            self.hass.add_job(self._publish_to_mqtt, self._default)
            _LOGGER.info(
                "Fan curve %s initialized to default: %s", self._key, self._default
            )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        return self._attr_native_value is not None

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()

        await self._publish_to_mqtt(value)

    async def _publish_to_mqtt(self, value: float) -> None:
        try:
            await mqtt.async_publish(
                self.hass,
                self._mqtt_topic,
                str(int(value)),
                qos=0,
                retain=True,
            )
            _LOGGER.info("Published fan curve %s = %s to MQTT", self._key, value)
        except Exception as err:
            _LOGGER.error("Failed to publish %s to MQTT: %s", self._key, err)
