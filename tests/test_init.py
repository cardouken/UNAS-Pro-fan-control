"""Tests for integration __init__ (setup/teardown)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.unas_pro import (
    UNASDataUpdateCoordinator,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.unas_pro.const import DOMAIN


@pytest.mark.asyncio
async def test_setup_entry_success(hass_instance):
    """Test successful integration setup."""
    hass_instance.data = {}
    entry = MagicMock()
    entry.data = {
        "host": "192.168.1.25",
        "username": "root",
        "password": "test123",
        "mqtt_host": "192.168.1.111",
        "mqtt_user": "homeassistant",
        "mqtt_password": "mqtt_pass",
    }
    entry.entry_id = "test_entry"

    with patch(
        "custom_components.unas_pro.SSHManager"
    ) as mock_ssh_class, patch(
        "custom_components.unas_pro.UNASMQTTClient"
    ) as mock_mqtt_class, patch(
        "custom_components.unas_pro.async_get_integration"
    ) as mock_get_integration:
        # Setup mocks
        mock_ssh = MagicMock()
        mock_ssh.connect = AsyncMock()
        mock_ssh.scripts_installed = AsyncMock(return_value=True)
        mock_ssh_class.return_value = mock_ssh

        mock_mqtt = MagicMock()
        mock_mqtt.async_subscribe = AsyncMock()
        mock_mqtt_class.return_value = mock_mqtt

        mock_integration = MagicMock()
        mock_integration.version = "0.1.0"
        mock_get_integration.return_value = mock_integration

        hass_instance.config_entries.async_forward_entry_setups = AsyncMock()

        result = await async_setup_entry(hass_instance, entry)

        assert result is True
        assert DOMAIN in hass_instance.data
        assert entry.entry_id in hass_instance.data[DOMAIN]
        mock_ssh.connect.assert_called_once()


@pytest.mark.asyncio
async def test_setup_entry_deploys_scripts_on_first_install(hass_instance):
    """Test setup deploys scripts on first installation."""
    hass_instance.data = {}
    entry = MagicMock()
    entry.data = {
        "host": "192.168.1.25",
        "username": "root",
        "password": "test123",
        "mqtt_host": "192.168.1.111",
        "mqtt_user": "homeassistant",
        "mqtt_password": "mqtt_pass",
    }
    entry.entry_id = "test_entry"

    with patch(
        "custom_components.unas_pro.SSHManager"
    ) as mock_ssh_class, patch(
        "custom_components.unas_pro.UNASMQTTClient"
    ), patch(
        "custom_components.unas_pro.async_get_integration"
    ) as mock_get_integration:
        mock_ssh = MagicMock()
        mock_ssh.connect = AsyncMock()
        mock_ssh.scripts_installed = AsyncMock(return_value=False)  # Not installed
        mock_ssh.deploy_scripts = AsyncMock()
        mock_ssh_class.return_value = mock_ssh

        mock_integration = MagicMock()
        mock_integration.version = "0.1.0"
        mock_get_integration.return_value = mock_integration

        hass_instance.config_entries.async_forward_entry_setups = AsyncMock()
        hass_instance.config_entries.async_update_entry = MagicMock()

        await async_setup_entry(hass_instance, entry)

        # Should have deployed scripts
        mock_ssh.deploy_scripts.assert_called_once()


@pytest.mark.asyncio
async def test_setup_entry_redeploys_on_version_change(hass_instance):
    """Test setup redeploys scripts when version changes."""
    hass_instance.data = {}
    entry = MagicMock()
    entry.data = {
        "host": "192.168.1.25",
        "username": "root",
        "password": "test123",
        "mqtt_host": "192.168.1.111",
        "mqtt_user": "homeassistant",
        "mqtt_password": "mqtt_pass",
        "last_deploy_version": "0.0.9",  # Old version
    }
    entry.entry_id = "test_entry"

    with patch(
        "custom_components.unas_pro.SSHManager"
    ) as mock_ssh_class, patch(
        "custom_components.unas_pro.UNASMQTTClient"
    ), patch(
        "custom_components.unas_pro.async_get_integration"
    ) as mock_get_integration:
        mock_ssh = MagicMock()
        mock_ssh.connect = AsyncMock()
        mock_ssh.scripts_installed = AsyncMock(return_value=True)
        mock_ssh.deploy_scripts = AsyncMock()
        mock_ssh_class.return_value = mock_ssh

        mock_integration = MagicMock()
        mock_integration.version = "0.1.0"  # New version
        mock_get_integration.return_value = mock_integration

        hass_instance.config_entries.async_forward_entry_setups = AsyncMock()
        hass_instance.config_entries.async_update_entry = MagicMock()

        await async_setup_entry(hass_instance, entry)

        # Should have redeployed due to version change
        mock_ssh.deploy_scripts.assert_called_once()


@pytest.mark.asyncio
async def test_setup_entry_fails_on_ssh_error(hass_instance):
    """Test setup fails gracefully on SSH connection error."""
    hass_instance.data = {}
    entry = MagicMock()
    entry.data = {
        "host": "192.168.1.25",
        "username": "root",
        "password": "wrong_password",
        "mqtt_host": "192.168.1.111",
        "mqtt_user": "homeassistant",
        "mqtt_password": "mqtt_pass",
    }

    with patch("custom_components.unas_pro.SSHManager") as mock_ssh_class:
        mock_ssh = MagicMock()
        mock_ssh.connect = AsyncMock(side_effect=Exception("Connection failed"))
        mock_ssh_class.return_value = mock_ssh

        result = await async_setup_entry(hass_instance, entry)

        assert result is False


@pytest.mark.asyncio
async def test_unload_entry_success(hass_instance):
    """Test successful integration unload."""
    entry = MagicMock()
    entry.entry_id = "test_entry"

    mock_ssh = MagicMock()
    mock_ssh.execute_command = AsyncMock(return_value=("", ""))
    mock_ssh.disconnect = AsyncMock()

    mock_mqtt = MagicMock()
    mock_mqtt.async_unsubscribe = AsyncMock()

    hass_instance.data = {
        DOMAIN: {
            entry.entry_id: {
                "coordinator": MagicMock(),
                "ssh_manager": mock_ssh,
                "mqtt_client": mock_mqtt,
            }
        }
    }

    hass_instance.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    result = await async_unload_entry(hass_instance, entry)

    assert result is True
    # Should have cleaned up
    assert entry.entry_id not in hass_instance.data[DOMAIN]
    mock_mqtt.async_unsubscribe.assert_called_once()
    mock_ssh.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_unload_entry_cleans_up_unas(hass_instance):
    """Test unload removes services and scripts from UNAS."""
    entry = MagicMock()
    entry.entry_id = "test_entry"

    mock_ssh = MagicMock()
    execute_commands = []

    async def capture_command(cmd):
        execute_commands.append(cmd)
        return ("", "")

    mock_ssh.execute_command = capture_command
    mock_ssh.disconnect = AsyncMock()

    mock_mqtt = MagicMock()
    mock_mqtt.async_unsubscribe = AsyncMock()

    hass_instance.data = {
        DOMAIN: {
            entry.entry_id: {
                "coordinator": MagicMock(),
                "ssh_manager": mock_ssh,
                "mqtt_client": mock_mqtt,
            }
        }
    }

    hass_instance.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    await async_unload_entry(hass_instance, entry)

    # Verify cleanup commands were executed
    assert any("systemctl stop unas_monitor" in cmd for cmd in execute_commands)
    assert any("systemctl stop fan_control" in cmd for cmd in execute_commands)
    assert any("rm -f /root/unas_monitor.sh" in cmd for cmd in execute_commands)
    assert any("rm -f /root/fan_control.sh" in cmd for cmd in execute_commands)
    assert any("rm -f /root/fan_mode" in cmd for cmd in execute_commands)


@pytest.mark.asyncio
async def test_unload_entry_restores_firmware_fan_control(hass_instance):
    """Test unload restores UNAS firmware fan control."""
    entry = MagicMock()
    entry.entry_id = "test_entry"

    mock_ssh = MagicMock()
    execute_commands = []

    async def capture_command(cmd):
        execute_commands.append(cmd)
        return ("", "")

    mock_ssh.execute_command = capture_command
    mock_ssh.disconnect = AsyncMock()

    mock_mqtt = MagicMock()
    mock_mqtt.async_unsubscribe = AsyncMock()

    hass_instance.data = {
        DOMAIN: {
            entry.entry_id: {
                "coordinator": MagicMock(),
                "ssh_manager": mock_ssh,
                "mqtt_client": mock_mqtt,
            }
        }
    }

    hass_instance.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    await async_unload_entry(hass_instance, entry)

    # Verify firmware fan control was restored (pwm_enable=2)
    assert any("echo 2 > /sys/class/hwmon/hwmon0/pwm1_enable" in cmd for cmd in execute_commands)
    assert any("echo 2 > /sys/class/hwmon/hwmon0/pwm2_enable" in cmd for cmd in execute_commands)
