from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.device_registry import DeviceInfo

from homeassistant.components import mqtt

from . import UNASDataUpdateCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# fan curve parameter definitions: (key, name, min, max, default, unit, icon)
FAN_CURVE_PARAMS = [
    ("min_temp", "Min Temperature", 30, 50, 43, "°C", "mdi:thermometer-low"),
    ("max_temp", "Max Temperature", 45, 60, 47, "°C", "mdi:thermometer-high"),
    ("min_fan", "Min Fan Speed", 0, 100, 80, "%", "mdi:fan-speed-1"),
    ("max_fan", "Max Fan Speed", 0, 100, 100, "%", "mdi:fan-speed-3"),
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


class UNASFanSpeedNumber(CoordinatorEntity, NumberEntity, RestoreEntity):
    def __init__(
        self, coordinator: UNASDataUpdateCoordinator, hass: HomeAssistant
    ) -> None:
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
        self._unsubscribe_mode = None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=f"UNAS Pro ({coordinator.ssh_manager.host})",
            manufacturer="Ubiquiti",
            model="UNAS Pro",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._current_value = float(last_state.state)
            except (ValueError, TypeError):
                pass

        @callback
        def speed_message_received(msg):
            try:
                pwm_value = int(msg.payload)
                percentage = round((pwm_value * 100) / 255)
                self._current_value = percentage
                self.async_write_ha_state()
            except (ValueError, TypeError) as err:
                _LOGGER.error("Failed to parse fan speed: %s", err)

        @callback
        def mode_message_received(msg):
            payload = msg.payload
            if payload == "unas_managed":
                self._current_mode = "unas_managed"
            elif payload == "auto":
                self._current_mode = "auto"
            elif payload.isdigit():
                self._current_mode = "set_speed"
            else:
                self._current_mode = None
            self.async_write_ha_state()

        self._unsubscribe_speed = await mqtt.async_subscribe(
            self.hass, "homeassistant/sensor/unas_fan_speed/state", speed_message_received, qos=0
        )

        self._unsubscribe_mode = await mqtt.async_subscribe(
            self.hass, "homeassistant/unas/fan_mode", mode_message_received, qos=0
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe_speed:
            self._unsubscribe_speed()
        if self._unsubscribe_mode:
            self._unsubscribe_mode()
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
    def available(self) -> bool:
        mqtt_available = self.coordinator.mqtt_client.is_available()
        service_running = self.coordinator.data.get("fan_control_running", False)
        return mqtt_available and service_running

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
        if self._current_mode != "set_speed":
            _LOGGER.warning("Cannot set fan speed - not in Set Speed mode")
            return

        pwm_value = round((value * 255) / 100)

        await mqtt.async_publish(
            self.hass, "homeassistant/unas/fan_mode", str(pwm_value), qos=0, retain=True
        )

        self._current_value = value
        self.async_write_ha_state()


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
        self._attr_name = name  # use short name without prefix
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fan_curve_{key}"
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = 1
        self._attr_native_value = None  # unknown until synced
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_mode = NumberMode.BOX
        self._default = default
        self._unsubscribe = None
        self._is_fan_param = key in [
            "min_fan",
            "max_fan",
        ]  # track if this is a fan speed param

        self._mqtt_topic = f"homeassistant/unas/fan_curve/{key}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=f"UNAS Pro ({coordinator.ssh_manager.host})",
            manufacturer="Ubiquiti",
            model="UNAS Pro",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def message_received(msg):
            try:
                value = int(float(msg.payload))
                
                if self._is_fan_param:
                    value = round((value * 100) / 255)

                if self._attr_native_min_value <= value <= self._attr_native_max_value:
                    self._attr_native_value = value
                    self.async_write_ha_state()
            except (ValueError, TypeError):
                pass

        self._unsubscribe = await mqtt.async_subscribe(
            self.hass, self._mqtt_topic, message_received, qos=0
        )

        # Set default after brief delay if no MQTT value received
        await self.hass.async_add_executor_job(self._init_default)

    def _init_default(self) -> None:
        import time
        time.sleep(1)
        
        if self._attr_native_value is None:
            self._attr_native_value = int(self._default)
            self.hass.add_job(self._publish_to_mqtt, self._default)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        mqtt_available = self.coordinator.mqtt_client.is_available()
        service_running = self.coordinator.data.get("fan_control_running", False)
        has_value = self._attr_native_value is not None
        return mqtt_available and service_running and has_value

    async def async_set_native_value(self, value: float) -> None:
        value = int(value)

        mqtt_data = self.coordinator.mqtt_client.get_data()

        min_temp = mqtt_data.get("fan_curve_min_temp", 43 if self._key != "min_temp" else value)
        max_temp = mqtt_data.get("fan_curve_max_temp", 47 if self._key != "max_temp" else value)
        min_fan_pwm = mqtt_data.get("fan_curve_min_fan", 204)
        max_fan_pwm = mqtt_data.get("fan_curve_max_fan", 255)

        min_fan = round((min_fan_pwm * 100) / 255) if isinstance(min_fan_pwm, (int, float)) else 80
        max_fan = round((max_fan_pwm * 100) / 255) if isinstance(max_fan_pwm, (int, float)) else 100

        if self._key == "min_temp":
            min_temp = value
        elif self._key == "max_temp":
            max_temp = value
        elif self._key == "min_fan":
            min_fan = value
        elif self._key == "max_fan":
            max_fan = value

        if max_temp <= min_temp:
            raise ValueError(f"Max temperature ({max_temp}°C) must be greater than min temperature ({min_temp}°C)")
        if max_fan < min_fan:
            raise ValueError(f"Max fan speed ({max_fan}%) must be >= min fan speed ({min_fan}%)")

        self._attr_native_value = value
        self.async_write_ha_state()
        await self._publish_to_mqtt(value)

    async def _publish_to_mqtt(self, value: float) -> None:
        mqtt_value = value
        if self._is_fan_param:
            mqtt_value = round((value * 255) / 100)

        await mqtt.async_publish(
            self.hass, self._mqtt_topic, str(int(mqtt_value)), qos=0, retain=True
        )
