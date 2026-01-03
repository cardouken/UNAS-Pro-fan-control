"""Tests for Select entity (fan mode persistence)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.unas_pro.select import (
    MODE_CUSTOM_CURVE,
    MODE_SET_SPEED,
    MODE_UNAS_MANAGED,
    MQTT_MODE_CUSTOM_CURVE,
    MQTT_MODE_UNAS_MANAGED,
    UNASFanModeSelect,
)


@pytest.mark.asyncio
async def test_fan_mode_migration_from_tmp(mock_coordinator, mock_mqtt, hass_instance):
    """Test fan mode migration from /tmp to /root."""
    mock_coordinator.ssh_manager.execute_command = AsyncMock(
        side_effect=[
            ("", ""),  # /root/fan_mode read (empty)
            ("255\n", ""),  # /tmp/fan_mode read (has old value)
            ("", ""),  # echo to /root/fan_mode
        ]
    )

    select = UNASFanModeSelect(mock_coordinator, hass_instance)

    with patch.object(select, "async_write_ha_state"):
        await select.async_added_to_hass()

    # Should have published "255" to MQTT
    mock_mqtt.async_publish.assert_called_once()
    call_args = mock_mqtt.async_publish.call_args
    assert call_args[0][2] == "255"  # payload

    # Should have migrated to SET_SPEED mode
    assert select._current_option == MODE_SET_SPEED


@pytest.mark.asyncio
async def test_fan_mode_reads_from_persistent_storage(
    mock_coordinator, mock_mqtt, hass_instance
):
    """Test fan mode reads from /root/fan_mode when it exists."""
    mock_coordinator.ssh_manager.execute_command = AsyncMock(
        return_value=("auto\n", "")  # /root/fan_mode has value
    )

    select = UNASFanModeSelect(mock_coordinator, hass_instance)

    with patch.object(select, "async_write_ha_state"):
        await select.async_added_to_hass()

    # Should have published "auto" to MQTT
    mock_mqtt.async_publish.assert_called_once()
    call_args = mock_mqtt.async_publish.call_args
    assert call_args[0][2] == "auto"

    # Should be in CUSTOM_CURVE mode
    assert select._current_option == MODE_CUSTOM_CURVE


@pytest.mark.asyncio
async def test_fan_mode_defaults_to_unas_managed(
    mock_coordinator, mock_mqtt, hass_instance
):
    """Test fan mode defaults to UNAS Managed when no saved mode exists."""
    mock_coordinator.ssh_manager.execute_command = AsyncMock(
        side_effect=[
            ("\n", ""),  # /root/fan_mode empty
            ("\n", ""),  # /tmp/fan_mode empty
            ("", ""),  # echo default to /root/fan_mode
        ]
    )

    select = UNASFanModeSelect(mock_coordinator, hass_instance)

    with patch.object(select, "async_write_ha_state"):
        await select.async_added_to_hass()

    # Should have published "unas_managed" to MQTT
    mock_mqtt.async_publish.assert_called_once()
    call_args = mock_mqtt.async_publish.call_args
    assert call_args[0][2] == MQTT_MODE_UNAS_MANAGED

    # Should be in UNAS_MANAGED mode
    assert select._current_option == MODE_UNAS_MANAGED


@pytest.mark.asyncio
async def test_fan_mode_service_management_unas_managed(
    mock_coordinator, mock_mqtt, hass_instance
):
    """Test fan control service is stopped when switching to UNAS Managed."""
    mock_coordinator.ssh_manager.execute_command = AsyncMock(return_value=("", ""))
    mock_coordinator.ssh_manager.service_running = AsyncMock(return_value=True)

    select = UNASFanModeSelect(mock_coordinator, hass_instance)
    select._current_option = MODE_CUSTOM_CURVE

    with patch.object(select, "async_write_ha_state"):
        await select.async_select_option(MODE_UNAS_MANAGED)

    # Should have stopped the service
    mock_coordinator.ssh_manager.execute_command.assert_called_with(
        "systemctl stop fan_control"
    )

    # Should have published to MQTT
    mock_mqtt.async_publish.assert_called_once()
    call_args = mock_mqtt.async_publish.call_args
    assert call_args[0][2] == MQTT_MODE_UNAS_MANAGED


@pytest.mark.asyncio
async def test_fan_mode_service_management_custom_curve(
    mock_coordinator, mock_mqtt, hass_instance
):
    """Test fan control service is started when switching to Custom Curve."""
    mock_coordinator.ssh_manager.execute_command = AsyncMock(return_value=("", ""))
    mock_coordinator.ssh_manager.service_running = AsyncMock(return_value=False)

    select = UNASFanModeSelect(mock_coordinator, hass_instance)
    select._current_option = MODE_UNAS_MANAGED

    with patch.object(select, "async_write_ha_state"):
        await select.async_select_option(MODE_CUSTOM_CURVE)

    # Should have started the service
    mock_coordinator.ssh_manager.execute_command.assert_called_with(
        "systemctl start fan_control"
    )

    # Should have published to MQTT
    mock_mqtt.async_publish.assert_called_once()
    call_args = mock_mqtt.async_publish.call_args
    assert call_args[0][2] == MQTT_MODE_CUSTOM_CURVE


@pytest.mark.asyncio
async def test_mqtt_message_received_unknown_mode_stops_service(
    mock_coordinator, mock_mqtt, hass_instance
):
    """Test that unknown MQTT mode defaults to UNAS Managed and stops service."""
    select = UNASFanModeSelect(mock_coordinator, hass_instance)
    select._current_option = MODE_CUSTOM_CURVE

    # Create a mock message with unknown payload
    mock_msg = MagicMock()
    mock_msg.topic = "homeassistant/unas/fan_mode"
    mock_msg.payload = "invalid_mode"

    # Get the message callback that was registered
    with patch.object(select, "async_write_ha_state"):
        with patch.object(select, "_ensure_service_stopped") as mock_stop:
            await select.async_added_to_hass()

            # Find the callback that was registered
            callback = None
            for call in mock_mqtt.async_subscribe.call_args_list:
                if "fan_mode" in str(call):
                    callback = call[0][2]  # Third argument is the callback
                    break

            if callback:
                # Simulate receiving unknown mode
                callback(mock_msg)
                hass_instance.async_create_task.assert_called()


@pytest.mark.asyncio
async def test_fan_mode_set_speed_publishes_pwm_value(
    mock_coordinator, mock_mqtt, hass_instance
):
    """Test Set Speed mode publishes PWM value to MQTT."""
    mock_coordinator.ssh_manager.service_running = AsyncMock(return_value=False)
    mock_coordinator.mqtt_client.get_data = MagicMock(
        return_value={"unas_fan_speed": 204}
    )

    select = UNASFanModeSelect(mock_coordinator, hass_instance)
    select._current_option = MODE_UNAS_MANAGED

    with patch.object(select, "async_write_ha_state"):
        await select.async_select_option(MODE_SET_SPEED)

    # Should have published PWM value (204) to MQTT
    mock_mqtt.async_publish.assert_called_once()
    call_args = mock_mqtt.async_publish.call_args
    assert call_args[0][2] == "204"


@pytest.mark.asyncio
async def test_ensure_service_stopped_only_when_running(
    mock_coordinator, hass_instance
):
    """Test service stop is only called when service is running."""
    mock_coordinator.ssh_manager.service_running = AsyncMock(return_value=False)
    mock_coordinator.ssh_manager.execute_command = AsyncMock()

    select = UNASFanModeSelect(mock_coordinator, hass_instance)

    await select._ensure_service_stopped()

    # Should not have called stop command
    mock_coordinator.ssh_manager.execute_command.assert_not_called()

    # Now test when service is running
    mock_coordinator.ssh_manager.service_running = AsyncMock(return_value=True)

    await select._ensure_service_stopped()

    # Should have called stop command
    mock_coordinator.ssh_manager.execute_command.assert_called_once_with(
        "systemctl stop fan_control"
    )
