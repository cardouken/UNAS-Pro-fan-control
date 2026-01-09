from __future__ import annotations

import logging
from typing import Any
from datetime import datetime

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)


class UNASMQTTClient:
    def __init__(self, hass: HomeAssistant, unas_host: str) -> None:
        self.hass = hass
        self.unas_host = unas_host
        self._data: dict[str, Any] = {}
        self._subscriptions: list = []
        self._status: str = "unknown"
        self._last_update: datetime | None = None

    async def async_subscribe(self) -> None:
        if mqtt.DOMAIN not in self.hass.data:
            _LOGGER.error("MQTT integration not loaded")
            return

        topics = [
            ("homeassistant/sensor/+/+", self._handle_message),
            ("homeassistant/unas/fan_curve/+", self._handle_message),
            ("homeassistant/unas/status", self._handle_status),
        ]

        for topic, handler in topics:
            try:
                sub = await mqtt.async_subscribe(self.hass, topic, handler, qos=0)
                self._subscriptions.append(sub)
                _LOGGER.debug("Subscribed to MQTT topic: %s", topic)
            except Exception as err:
                _LOGGER.error("Failed to subscribe to %s: %s", topic, err)

    async def async_unsubscribe(self) -> None:
        for unsub in self._subscriptions:
            unsub()
        self._subscriptions.clear()
        _LOGGER.debug("Unsubscribed from %d MQTT topics", len(self._subscriptions))

    @callback
    def _handle_status(self, msg) -> None:
        self._status = msg.payload
        _LOGGER.debug("UNAS status: %s", self._status)
        
        if hasattr(self, "_coordinator") and self._coordinator:
            self.hass.async_create_task(self._coordinator.async_request_refresh())

    @callback
    def _handle_message(self, msg) -> None:
        parts = msg.topic.split("/")
        
        if len(parts) >= 4 and parts[1] == "sensor" and parts[-1] == "state":
            sensor_name = parts[2]
            if sensor_name.startswith("unas_"):
                self._store_value(sensor_name, msg.payload)
        
        elif len(parts) == 4 and parts[1] == "unas" and parts[2] == "fan_curve":
            param_name = parts[3]
            self._store_value(f"fan_curve_{param_name}", msg.payload)

    def _store_value(self, key: str, payload: str) -> None:
        try:
            value = float(payload) if "." in payload else int(payload)
        except (ValueError, TypeError):
            value = payload

        self._data[key] = value
        self._last_update = datetime.now()
        _LOGGER.debug("MQTT: %s = %s", key, value)

        if hasattr(self, "_coordinator") and self._coordinator:
            self.hass.async_create_task(self._coordinator.async_request_refresh())
    
    def is_available(self) -> bool:
        if self._status == "offline":
            return False
        
        if self._last_update is None:
            return False
        
        time_since_update = (datetime.now() - self._last_update).total_seconds()
        if time_since_update > 120:
            return False
        
        return True

    def get_data(self) -> dict[str, Any]:
        return self._data.copy()
