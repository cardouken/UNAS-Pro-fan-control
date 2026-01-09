from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncssh
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    DEFAULT_USERNAME,
    CONF_MQTT_HOST,
    CONF_MQTT_USER,
    CONF_MQTT_PASSWORD,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_MQTT_HOST,): str,
        vol.Required(CONF_MQTT_USER): str,
        vol.Required(CONF_MQTT_PASSWORD): str,
    }
)


class UNASProConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            if error_key := await self._test_ssh(user_input[CONF_HOST], user_input[CONF_USERNAME], user_input[CONF_PASSWORD]):
                errors["base"] = error_key
            elif error_key := await self._test_mqtt(user_input[CONF_MQTT_HOST], user_input[CONF_MQTT_USER], user_input[CONF_MQTT_PASSWORD]):
                errors["base"] = error_key
            else:
                self.hass.config_entries.async_update_entry(entry, data=user_input)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        reconfigure_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST)): str,
                vol.Optional(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, DEFAULT_USERNAME)): str,
                vol.Required(CONF_PASSWORD, default=entry.data.get(CONF_PASSWORD)): str,
                vol.Required(CONF_MQTT_HOST, default=entry.data.get(CONF_MQTT_HOST)): str,
                vol.Required(CONF_MQTT_USER, default=entry.data.get(CONF_MQTT_USER)): str,
                vol.Required(CONF_MQTT_PASSWORD, default=entry.data.get(CONF_MQTT_PASSWORD)): str,
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=reconfigure_schema,
            errors=errors,
            description_placeholders={"host": entry.data.get(CONF_HOST, "unknown")},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if mqtt.DOMAIN not in self.hass.data:
            return self.async_abort(reason="mqtt_required")

        if user_input is not None:
            if error_key := await self._test_ssh(user_input[CONF_HOST], user_input[CONF_USERNAME], user_input[CONF_PASSWORD]):
                errors["base"] = error_key
            elif error_key := await self._test_mqtt(user_input[CONF_MQTT_HOST], user_input[CONF_MQTT_USER], user_input[CONF_MQTT_PASSWORD]):
                errors["base"] = error_key
            else:
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"UNAS Pro ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    async def _test_ssh(self, host: str, username: str, password: str) -> str | None:
        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(host, username=username, password=password, known_hosts=None),
                timeout=10.0,
            )
            result = await conn.run("echo 'test'", check=True)
            conn.close()
            await conn.wait_closed()
            
            if result.stdout.strip() != "test":
                return "unknown"
            return None
        except asyncssh.Error:
            return "cannot_connect"
        except asyncio.TimeoutError:
            return "timeout_connect"
        except Exception:
            return "unknown"

    async def _test_mqtt(self, host: str, username: str, password: str) -> str | None:
        try:
            import paho.mqtt.client as mqtt_client  # type: ignore
            
            result = {"rc": None}
            
            def on_connect(_client, _userdata, _flags, rc):
                result["rc"] = rc
                _client.disconnect()
            
            client = mqtt_client.Client()
            client.username_pw_set(username, password)
            client.on_connect = on_connect
            
            try:
                client.connect(host, 1883, 60)
            except Exception as e:
                _LOGGER.debug("MQTT connection failed: %s", e)
                return "mqtt_cannot_connect"
            
            client.loop_start()
            await asyncio.sleep(3)
            client.loop_stop()
            
            if result["rc"] == 0:
                return None
            elif result["rc"] == 5:
                return "mqtt_invalid_auth"
            elif result["rc"] is None:
                return "mqtt_timeout"
            else:
                _LOGGER.debug("MQTT connection result code: %s", result["rc"])
                return "mqtt_cannot_connect"
                    
        except Exception as e:
            _LOGGER.debug("MQTT test failed: %s", e)
            return "mqtt_cannot_connect"

