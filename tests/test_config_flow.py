"""Tests for Config Flow."""
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from custom_components.unas_pro.config_flow import UNASProConfigFlow
from custom_components.unas_pro.const import (
    CONF_HOST,
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_USER,
    CONF_PASSWORD,
    CONF_USERNAME,
)


@pytest.mark.asyncio
async def test_config_flow_user_step_success():
    """Test successful user configuration step."""
    flow = UNASProConfigFlow()
    flow.hass = MagicMock()
    flow.hass.data = {"mqtt": {}}  # MQTT integration loaded

    user_input = {
        CONF_HOST: "192.168.1.25",
        CONF_USERNAME: "root",
        CONF_PASSWORD: "test123",
        CONF_MQTT_HOST: "192.168.1.111",
        CONF_MQTT_USER: "homeassistant",
        CONF_MQTT_PASSWORD: "mqtt_pass",
    }

    with patch.object(flow, "_test_connection", new_callable=AsyncMock):
        with patch.object(flow, "async_set_unique_id"):
            with patch.object(flow, "_abort_if_unique_id_configured"):
                result = await flow.async_step_user(user_input)

    assert result["type"] == "create_entry"
    assert result["title"] == "UNAS Pro (192.168.1.25)"
    assert result["data"] == user_input


@pytest.mark.asyncio
async def test_config_flow_cannot_connect():
    """Test config flow with SSH connection failure."""
    flow = UNASProConfigFlow()
    flow.hass = MagicMock()
    flow.hass.data = {"mqtt": {}}

    user_input = {
        CONF_HOST: "192.168.1.25",
        CONF_USERNAME: "root",
        CONF_PASSWORD: "wrong_password",
        CONF_MQTT_HOST: "192.168.1.111",
        CONF_MQTT_USER: "homeassistant",
        CONF_MQTT_PASSWORD: "mqtt_pass",
    }

    with patch.object(
        flow, "_test_connection", new_callable=AsyncMock, side_effect=asyncssh.Error()
    ):
        result = await flow.async_step_user(user_input)

    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_config_flow_timeout():
    """Test config flow with SSH timeout."""
    flow = UNASProConfigFlow()
    flow.hass = MagicMock()
    flow.hass.data = {"mqtt": {}}

    user_input = {
        CONF_HOST: "192.168.1.25",
        CONF_USERNAME: "root",
        CONF_PASSWORD: "test123",
        CONF_MQTT_HOST: "192.168.1.111",
        CONF_MQTT_USER: "homeassistant",
        CONF_MQTT_PASSWORD: "mqtt_pass",
    }

    with patch.object(
        flow,
        "_test_connection",
        new_callable=AsyncMock,
        side_effect=TimeoutError(),
    ):
        result = await flow.async_step_user(user_input)

    assert result["type"] == "form"
    assert result["errors"] == {"base": "timeout_connect"}


@pytest.mark.asyncio
async def test_config_flow_mqtt_required():
    """Test config flow aborts when MQTT is not installed."""
    flow = UNASProConfigFlow()
    flow.hass = MagicMock()
    flow.hass.data = {}  # No MQTT integration

    result = await flow.async_step_user(None)

    assert result["type"] == "abort"
    assert result["reason"] == "mqtt_required"


@pytest.mark.asyncio
async def test_config_flow_shows_form_initially():
    """Test config flow shows form on initial load."""
    flow = UNASProConfigFlow()
    flow.hass = MagicMock()
    flow.hass.data = {"mqtt": {}}

    result = await flow.async_step_user(None)

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert "data_schema" in result


@pytest.mark.asyncio
async def test_test_connection_validates_ssh():
    """Test SSH connection validation."""
    flow = UNASProConfigFlow()

    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.stdout = "test\n"
    mock_conn.run = AsyncMock(return_value=mock_result)
    mock_conn.close = MagicMock()
    mock_conn.wait_closed = AsyncMock()

    with patch("asyncssh.connect", new_callable=AsyncMock, return_value=mock_conn):
        await flow._test_connection("192.168.1.25", "root", "test123")

    # Should have called echo test command
    mock_conn.run.assert_called_once_with("echo 'test'", check=True)
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_test_connection_fails_on_wrong_output():
    """Test SSH connection fails if test command returns wrong output."""
    flow = UNASProConfigFlow()

    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.stdout = "wrong output\n"
    mock_conn.run = AsyncMock(return_value=mock_result)
    mock_conn.close = MagicMock()
    mock_conn.wait_closed = AsyncMock()

    with patch("asyncssh.connect", new_callable=AsyncMock, return_value=mock_conn):
        with pytest.raises(Exception, match="Command execution test failed"):
            await flow._test_connection("192.168.1.25", "root", "test123")


@pytest.mark.asyncio
async def test_config_flow_unique_id_already_configured():
    """Test config flow prevents duplicate configurations."""
    flow = UNASProConfigFlow()
    flow.hass = MagicMock()
    flow.hass.data = {"mqtt": {}}

    user_input = {
        CONF_HOST: "192.168.1.25",
        CONF_USERNAME: "root",
        CONF_PASSWORD: "test123",
        CONF_MQTT_HOST: "192.168.1.111",
        CONF_MQTT_USER: "homeassistant",
        CONF_MQTT_PASSWORD: "mqtt_pass",
    }

    with patch.object(flow, "_test_connection", new_callable=AsyncMock):
        with patch.object(flow, "async_set_unique_id"):
            # Mock that unique_id is already configured
            flow._abort_if_unique_id_configured = MagicMock(
                side_effect=Exception("already_configured")
            )

            with pytest.raises(Exception, match="already_configured"):
                await flow.async_step_user(user_input)
