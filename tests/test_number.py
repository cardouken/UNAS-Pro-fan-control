"""Tests for Number entities (fan control)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.unas_pro.number import UNASFanCurveNumber, UNASFanSpeedNumber


@pytest.mark.asyncio
async def test_fan_speed_number_initialization(mock_coordinator, hass_instance):
    """Test fan speed number entity initialization."""
    number = UNASFanSpeedNumber(mock_coordinator, hass_instance)

    assert number._attr_name == "UNAS Fan Speed"
    assert number._attr_native_min_value == 0
    assert number._attr_native_max_value == 100
    assert number._attr_native_unit_of_measurement == "%"


@pytest.mark.asyncio
async def test_fan_speed_converts_pwm_to_percentage(mock_coordinator, hass_instance):
    """Test fan speed converts PWM to percentage correctly."""
    number = UNASFanSpeedNumber(mock_coordinator, hass_instance)
    number._unsubscribe_speed = MagicMock()
    number._unsubscribe_mode = MagicMock()

    with patch("custom_components.unas_pro.number.mqtt") as mock_mqtt:
        mock_mqtt.async_subscribe = AsyncMock(return_value=MagicMock())
        await number.async_added_to_hass()

        # Get the speed callback
        speed_callback = mock_mqtt.async_subscribe.call_args_list[0][0][2]

        # Simulate receiving PWM 255 (should be 100%)
        mock_msg = MagicMock()
        mock_msg.payload = "255"
        speed_callback(mock_msg)

        assert number._current_value == 100

        # Simulate receiving PWM 128 (should be ~50%)
        mock_msg.payload = "128"
        speed_callback(mock_msg)

        assert number._current_value == 50


@pytest.mark.asyncio
async def test_fan_speed_only_works_in_set_speed_mode(
    mock_coordinator, hass_instance, mock_mqtt
):
    """Test fan speed can only be set in Set Speed mode."""
    number = UNASFanSpeedNumber(mock_coordinator, hass_instance)
    number._current_mode = "auto"  # Not in set_speed mode
    number._current_value = 80

    with patch.object(number, "async_write_ha_state"):
        await number.async_set_native_value(90)

    # Should not have published (not in set_speed mode)
    mock_mqtt.async_publish.assert_not_called()


@pytest.mark.asyncio
async def test_fan_speed_publishes_pwm_value(mock_coordinator, hass_instance, mock_mqtt):
    """Test fan speed converts percentage to PWM when publishing."""
    number = UNASFanSpeedNumber(mock_coordinator, hass_instance)
    number._current_mode = "set_speed"  # In set_speed mode
    number._current_value = 80

    with patch.object(number, "async_write_ha_state"):
        await number.async_set_native_value(80)  # 80% = 204 PWM

    # Should have published PWM value
    mock_mqtt.async_publish.assert_called_once()
    call_args = mock_mqtt.async_publish.call_args
    assert call_args[0][2] == "204"  # 80% of 255


@pytest.mark.asyncio
async def test_fan_curve_number_initialization(mock_coordinator, hass_instance):
    """Test fan curve number entity initialization."""
    number = UNASFanCurveNumber(
        coordinator=mock_coordinator,
        hass=hass_instance,
        key="min_temp",
        name="Min Temperature",
        min_val=30,
        max_val=50,
        default=43,
        unit="°C",
        icon="mdi:thermometer-low",
    )

    assert number._attr_name == "Min Temperature"
    assert number._attr_native_min_value == 30
    assert number._attr_native_max_value == 50
    assert number._default == 43
    assert number._attr_native_unit_of_measurement == "°C"


@pytest.mark.asyncio
async def test_fan_curve_validates_min_max_temp(mock_coordinator, hass_instance):
    """Test fan curve validates min temp < max temp."""
    number = UNASFanCurveNumber(
        coordinator=mock_coordinator,
        hass=hass_instance,
        key="max_temp",
        name="Max Temperature",
        min_val=45,
        max_val=60,
        default=47,
        unit="°C",
        icon="mdi:thermometer-high",
    )

    # Mock current curve values
    mock_coordinator.mqtt_client.get_data = MagicMock(
        return_value={
            "fan_curve_min_temp": 50,  # Min is 50
            "fan_curve_max_temp": 47,
            "fan_curve_min_fan": 204,
            "fan_curve_max_fan": 255,
        }
    )

    # Try to set max_temp to 45 (less than min 50)
    with pytest.raises(ValueError, match="must be greater than min temperature"):
        await number._validate_curve_parameters(45)


@pytest.mark.asyncio
async def test_fan_curve_validates_min_max_fan(mock_coordinator, hass_instance):
    """Test fan curve validates min fan <= max fan."""
    number = UNASFanCurveNumber(
        coordinator=mock_coordinator,
        hass=hass_instance,
        key="max_fan",
        name="Max Fan Speed",
        min_val=0,
        max_val=100,
        default=100,
        unit="%",
        icon="mdi:fan-speed-3",
    )

    # Mock current curve values
    mock_coordinator.mqtt_client.get_data = MagicMock(
        return_value={
            "fan_curve_min_temp": 43,
            "fan_curve_max_temp": 47,
            "fan_curve_min_fan": 204,  # 80%
            "fan_curve_max_fan": 255,
        }
    )

    # Try to set max_fan to 50 (less than min 80%)
    with pytest.raises(ValueError, match="must be greater than or equal to min fan"):
        await number._validate_curve_parameters(50)


@pytest.mark.asyncio
async def test_fan_curve_converts_percentage_to_pwm(
    mock_coordinator, hass_instance, mock_mqtt
):
    """Test fan curve converts percentage to PWM for fan params."""
    number = UNASFanCurveNumber(
        coordinator=mock_coordinator,
        hass=hass_instance,
        key="min_fan",
        name="Min Fan Speed",
        min_val=0,
        max_val=100,
        default=80,
        unit="%",
        icon="mdi:fan-speed-1",
    )

    # Mock validation
    mock_coordinator.mqtt_client.get_data = MagicMock(
        return_value={
            "fan_curve_min_temp": 43,
            "fan_curve_max_temp": 47,
            "fan_curve_min_fan": 204,
            "fan_curve_max_fan": 255,
        }
    )

    await number._publish_to_mqtt(80)  # 80% should be 204 PWM

    # Should have published PWM value
    mock_mqtt.async_publish.assert_called_once()
    call_args = mock_mqtt.async_publish.call_args
    assert call_args[0][2] == "204"  # PWM value


@pytest.mark.asyncio
async def test_fan_curve_temperature_stays_as_is(
    mock_coordinator, hass_instance, mock_mqtt
):
    """Test fan curve temperature values don't get converted."""
    number = UNASFanCurveNumber(
        coordinator=mock_coordinator,
        hass=hass_instance,
        key="min_temp",
        name="Min Temperature",
        min_val=30,
        max_val=50,
        default=43,
        unit="°C",
        icon="mdi:thermometer-low",
    )

    await number._publish_to_mqtt(45)  # Temperature value

    # Should have published temperature as-is
    mock_mqtt.async_publish.assert_called_once()
    call_args = mock_mqtt.async_publish.call_args
    assert call_args[0][2] == "45"  # Not converted


@pytest.mark.asyncio
async def test_fan_curve_defaults_to_value_when_mqtt_empty(
    mock_coordinator, hass_instance
):
    """Test fan curve uses default when MQTT has no retained value."""
    number = UNASFanCurveNumber(
        coordinator=mock_coordinator,
        hass=hass_instance,
        key="min_temp",
        name="Min Temperature",
        min_val=30,
        max_val=50,
        default=43,
        unit="°C",
        icon="mdi:thermometer-low",
    )

    number._unsubscribe = MagicMock()

    with patch("custom_components.unas_pro.number.mqtt") as mock_mqtt:
        mock_mqtt.async_subscribe = AsyncMock(return_value=MagicMock())
        mock_mqtt.async_publish = AsyncMock()

        with patch.object(hass_instance, "async_add_executor_job") as mock_executor:
            # Simulate waiting for MQTT and not receiving anything
            def wait_for_mqtt():
                import time

                time.sleep(0.01)
                # Still None after waiting
                if number._attr_native_value is None:
                    number._attr_native_value = int(number._default)
                    hass_instance.add_job(number._publish_to_mqtt, number._default)

            mock_executor.side_effect = lambda func: func()

            await number.async_added_to_hass()

    # Should have initialized to default
    assert number._attr_native_value == 43
