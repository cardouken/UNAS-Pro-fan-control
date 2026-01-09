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

