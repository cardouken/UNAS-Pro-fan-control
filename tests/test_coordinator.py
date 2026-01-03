"""Tests for Coordinator (firmware update detection)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.unas_pro import UNASDataUpdateCoordinator


@pytest.mark.asyncio
async def test_coordinator_detects_missing_scripts_and_reinstalls(hass_instance):
    """Test coordinator detects missing scripts (firmware update) and reinstalls."""
    mock_ssh_manager = MagicMock()
    mock_mqtt_client = MagicMock()
    mock_entry = MagicMock()

    mock_ssh_manager.scripts_installed = AsyncMock(return_value=False)
    mock_ssh_manager.deploy_scripts = AsyncMock()
    mock_ssh_manager.service_running = AsyncMock(return_value=True)
    mock_mqtt_client.get_data = MagicMock(return_value={})

    coordinator = UNASDataUpdateCoordinator(
        hass_instance, mock_ssh_manager, mock_mqtt_client, mock_entry
    )

    # Mock MQTT domain check
    hass_instance.data = {"mqtt": {}}

    await coordinator._async_update_data()

    # Should have called deploy_scripts
    mock_ssh_manager.deploy_scripts.assert_called_once()


@pytest.mark.asyncio
async def test_coordinator_skips_reinstall_when_scripts_present(hass_instance):
    """Test coordinator doesn't reinstall when scripts are present."""
    mock_ssh_manager = MagicMock()
    mock_mqtt_client = MagicMock()
    mock_entry = MagicMock()

    mock_ssh_manager.scripts_installed = AsyncMock(return_value=True)
    mock_ssh_manager.deploy_scripts = AsyncMock()
    mock_ssh_manager.service_running = AsyncMock(return_value=True)
    mock_mqtt_client.get_data = MagicMock(return_value={})

    coordinator = UNASDataUpdateCoordinator(
        hass_instance, mock_ssh_manager, mock_mqtt_client, mock_entry
    )

    hass_instance.data = {"mqtt": {}}

    await coordinator._async_update_data()

    # Should NOT have called deploy_scripts
    mock_ssh_manager.deploy_scripts.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_checks_service_status(hass_instance):
    """Test coordinator checks service status."""
    mock_ssh_manager = MagicMock()
    mock_mqtt_client = MagicMock()
    mock_entry = MagicMock()

    mock_ssh_manager.scripts_installed = AsyncMock(return_value=True)
    mock_ssh_manager.service_running = AsyncMock(side_effect=[True, False])
    mock_mqtt_client.get_data = MagicMock(return_value={})

    coordinator = UNASDataUpdateCoordinator(
        hass_instance, mock_ssh_manager, mock_mqtt_client, mock_entry
    )

    hass_instance.data = {"mqtt": {}}

    data = await coordinator._async_update_data()

    # Should have checked both services
    assert mock_ssh_manager.service_running.call_count == 2
    assert data["monitor_running"] is True
    assert data["fan_control_running"] is False


@pytest.mark.asyncio
async def test_coordinator_raises_on_mqtt_missing(hass_instance):
    """Test coordinator raises UpdateFailed when MQTT integration is missing."""
    mock_ssh_manager = MagicMock()
    mock_mqtt_client = MagicMock()
    mock_entry = MagicMock()

    coordinator = UNASDataUpdateCoordinator(
        hass_instance, mock_ssh_manager, mock_mqtt_client, mock_entry
    )

    # MQTT not in hass.data
    hass_instance.data = {}

    with pytest.raises(UpdateFailed, match="MQTT integration is required"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_handles_ssh_errors(hass_instance):
    """Test coordinator handles SSH errors gracefully."""
    mock_ssh_manager = MagicMock()
    mock_mqtt_client = MagicMock()
    mock_entry = MagicMock()

    mock_ssh_manager.scripts_installed = AsyncMock(
        side_effect=Exception("SSH connection failed")
    )

    coordinator = UNASDataUpdateCoordinator(
        hass_instance, mock_ssh_manager, mock_mqtt_client, mock_entry
    )

    hass_instance.data = {"mqtt": {}}

    with pytest.raises(UpdateFailed, match="Error communicating with UNAS"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_async_reinstall_scripts(hass_instance):
    """Test coordinator reinstall_scripts method."""
    mock_ssh_manager = MagicMock()
    mock_mqtt_client = MagicMock()
    mock_entry = MagicMock()

    mock_ssh_manager.deploy_scripts = AsyncMock()

    coordinator = UNASDataUpdateCoordinator(
        hass_instance, mock_ssh_manager, mock_mqtt_client, mock_entry
    )
    coordinator.async_request_refresh = AsyncMock()

    await coordinator.async_reinstall_scripts()

    # Should have deployed scripts and requested refresh
    mock_ssh_manager.deploy_scripts.assert_called_once()
    coordinator.async_request_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_coordinator_returns_complete_data(hass_instance):
    """Test coordinator returns all expected data fields."""
    mock_ssh_manager = MagicMock()
    mock_mqtt_client = MagicMock()
    mock_entry = MagicMock()

    mock_ssh_manager.scripts_installed = AsyncMock(return_value=True)
    mock_ssh_manager.service_running = AsyncMock(side_effect=[True, True])
    mock_mqtt_client.get_data = MagicMock(
        return_value={"unas_cpu": 65, "unas_fan_speed": 255}
    )

    coordinator = UNASDataUpdateCoordinator(
        hass_instance, mock_ssh_manager, mock_mqtt_client, mock_entry
    )

    hass_instance.data = {"mqtt": {}}

    data = await coordinator._async_update_data()

    # Check all expected keys are present
    assert "scripts_installed" in data
    assert "ssh_connected" in data
    assert "monitor_running" in data
    assert "fan_control_running" in data
    assert "mqtt_data" in data

    # Check values
    assert data["scripts_installed"] is True
    assert data["ssh_connected"] is True
    assert data["monitor_running"] is True
    assert data["fan_control_running"] is True
    assert data["mqtt_data"]["unas_cpu"] == 65
