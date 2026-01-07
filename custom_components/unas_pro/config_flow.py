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
        vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(
            CONF_MQTT_HOST,
            description={"suggested_value": "192.168.1.111 or homeassistant.local"},
        ): str,
        vol.Required(CONF_MQTT_USER): str,
        vol.Required(CONF_MQTT_PASSWORD): str,
    }
)


class UNASProConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            # clean up MQTT host - strip port if user accidentally included it
            mqtt_host = user_input[CONF_MQTT_HOST]
            if ":" in mqtt_host:
                mqtt_host = mqtt_host.split(":")[0]
                _LOGGER.info(
                    "Stripped port from MQTT host: %s -> %s",
                    user_input[CONF_MQTT_HOST],
                    mqtt_host,
                )
                user_input[CONF_MQTT_HOST] = mqtt_host

            # test SSH connection with new credentials
            try:
                await self._test_connection(
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except asyncssh.Error as err:
                _LOGGER.error("SSH connection failed: %s", err)
                errors["base"] = "cannot_connect"
            except asyncio.TimeoutError:
                _LOGGER.error("SSH connection timed out")
                errors["base"] = "timeout_connect"
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception: %s", err)
                errors["base"] = "unknown"
            else:
                # update the config entry with new data
                self.hass.config_entries.async_update_entry(entry, data=user_input)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        # pre-fill form with current values
        reconfigure_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST)): str,
                vol.Optional(
                    CONF_USERNAME, default=entry.data.get(CONF_USERNAME, DEFAULT_USERNAME)
                ): str,
                vol.Required(CONF_PASSWORD, default=entry.data.get(CONF_PASSWORD)): str,
                vol.Required(
                    CONF_MQTT_HOST,
                    default=entry.data.get(CONF_MQTT_HOST),
                    description={"suggested_value": "192.168.1.111 or homeassistant.local"},
                ): str,
                vol.Required(
                    CONF_MQTT_USER, default=entry.data.get(CONF_MQTT_USER)
                ): str,
                vol.Required(
                    CONF_MQTT_PASSWORD, default=entry.data.get(CONF_MQTT_PASSWORD)
                ): str,
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=reconfigure_schema,
            errors=errors,
            description_placeholders={
                "host": entry.data.get(CONF_HOST, "unknown"),
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        # check if MQTT integration is loaded
        if mqtt.DOMAIN not in self.hass.data:
            return self.async_abort(
                reason="mqtt_required",
                description_placeholders={
                    "error": "MQTT integration must be installed and configured before setting up UNAS Pro. Please add the MQTT integration first."
                },
            )

        if user_input is not None:
            # clean up MQTT host - strip port if user accidentally included it
            mqtt_host = user_input[CONF_MQTT_HOST]
            if ":" in mqtt_host:
                # remove port (mosquitto_pub uses -h for hostname only, port defaults to 1883)
                mqtt_host = mqtt_host.split(":")[0]
                _LOGGER.info(
                    "Stripped port from MQTT host: %s -> %s",
                    user_input[CONF_MQTT_HOST],
                    mqtt_host,
                )
                user_input[CONF_MQTT_HOST] = mqtt_host

            # Test SSH connection
            try:
                await self._test_connection(
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except asyncssh.Error as err:
                _LOGGER.error("SSH connection failed: %s", err)
                errors["base"] = "cannot_connect"
            except asyncio.TimeoutError:
                _LOGGER.error("SSH connection timed out")
                errors["base"] = "timeout_connect"
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception: %s", err)
                errors["base"] = "unknown"
            else:
                # set unique ID based on host
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"UNAS Pro ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def _test_connection(self, host: str, username: str, password: str) -> None:
        conn = None
        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(
                    host,
                    username=username,
                    password=password,
                    known_hosts=None,
                ),
                timeout=10.0,
            )
            # test a simple command
            result = await conn.run("echo 'test'", check=True)
            if result.stdout.strip() != "test":
                raise Exception("Command execution test failed")

        finally:
            if conn:
                conn.close()
                await conn.wait_closed()
