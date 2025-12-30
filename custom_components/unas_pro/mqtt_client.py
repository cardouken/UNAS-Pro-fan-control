from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)


class UNASMQTTClient:
    def __init__(self, hass: HomeAssistant, unas_host: str) -> None:
        self.hass = hass
        self.unas_host = unas_host
        self._data: dict[str, Any] = {}
        self._subscriptions: list = []

    async def async_subscribe(self) -> None:
        # check if MQTT integration is loaded
        if not mqtt.DOMAIN in self.hass.data:
            _LOGGER.error("MQTT integration not loaded! Cannot subscribe to topics.")
            return

        # subscribe to all UNAS sensor topics (state and config)
        # use single-level wildcard for sensor name, then # for rest
        sensor_topic = "homeassistant/sensor/+/+"

        try:
            subscription = await mqtt.async_subscribe(
                self.hass,
                sensor_topic,
                self._message_received,
                qos=0,
            )
            self._subscriptions.append(subscription)
            _LOGGER.info("Successfully subscribed to MQTT topic: %s", sensor_topic)
        except Exception as err:
            _LOGGER.error("Failed to subscribe to MQTT sensors: %s", err)

        fan_curve_topic = "homeassistant/unas/fan_curve/+"

        try:
            subscription = await mqtt.async_subscribe(
                self.hass,
                fan_curve_topic,
                self._fan_curve_message_received,
                qos=0,
            )
            self._subscriptions.append(subscription)
            _LOGGER.info("Successfully subscribed to MQTT topic: %s", fan_curve_topic)
        except Exception as err:
            _LOGGER.error("Failed to subscribe to fan curve: %s", err)

    async def async_unsubscribe(self) -> None:
        for unsubscribe in self._subscriptions:
            unsubscribe()
        self._subscriptions.clear()
        _LOGGER.info("Unsubscribed from MQTT topics")

    @callback
    def _message_received(self, msg) -> None:
        topic = msg.topic
        payload = msg.payload

        # extract sensor name from topic
        # format: homeassistant/sensor/SENSOR_NAME/state or /config
        parts = topic.split("/")
        if len(parts) < 3:
            return

        sensor_name = parts[2]

        # only process UNAS sensors
        if not sensor_name.startswith("unas_"):
            return

        # only process state messages, ignore config
        if parts[-1] != "state":
            return

        _LOGGER.debug("MQTT received: %s = %s", sensor_name, payload)

        try:
            # try to parse as number
            value = float(payload) if "." in payload else int(payload)
        except (ValueError, TypeError):
            # keep as string
            value = payload

        self._data[sensor_name] = value

        # notify coordinator of new data (trigger entity updates)
        if hasattr(self, "_coordinator") and self._coordinator:
            # Trigger a manual refresh without fetching SSH data
            self.hass.async_create_task(self._coordinator.async_request_refresh())

    @callback
    def _fan_curve_message_received(self, msg) -> None:
        topic = msg.topic
        payload = msg.payload

        # extract parameter name from topic
        # format: homeassistant/unas/fan_curve/PARAM_NAME
        parts = topic.split("/")
        if len(parts) < 4:
            return

        param_name = parts[3]  # min_temp, max_temp, min_fan, max_fan

        _LOGGER.debug("MQTT fan curve received: %s = %s", param_name, payload)

        # store the value with a key prefix
        try:
            value = float(payload) if "." in payload else int(payload)
        except (ValueError, TypeError):
            value = payload

        self._data[f"fan_curve_{param_name}"] = value
        _LOGGER.debug("Stored fan curve: fan_curve_%s = %s", param_name, value)

    def get_data(self) -> dict[str, Any]:
        _LOGGER.debug("get_data called, returning %d keys", len(self._data))
        return self._data.copy()

    def get_sensor_value(self, sensor_name: str) -> Any:
        return self._data.get(sensor_name)
