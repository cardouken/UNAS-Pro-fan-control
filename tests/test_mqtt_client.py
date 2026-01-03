"""Tests for MQTT Client."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.unas_pro.mqtt_client import UNASMQTTClient


def test_mqtt_message_parsing_numbers(hass_instance):
    """Test MQTT message parsing for numeric values."""
    client = UNASMQTTClient(hass_instance, "192.168.1.25")

    # Create mock message
    mock_msg = MagicMock()
    mock_msg.topic = "homeassistant/sensor/unas_cpu/state"
    mock_msg.payload = "65"

    client._message_received(mock_msg)

    # Should parse as integer
    assert client._data["unas_cpu"] == 65
    assert isinstance(client._data["unas_cpu"], int)


def test_mqtt_message_parsing_floats(hass_instance):
    """Test MQTT message parsing for float values."""
    client = UNASMQTTClient(hass_instance, "192.168.1.25")

    mock_msg = MagicMock()
    mock_msg.topic = "homeassistant/sensor/unas_memory_usage/state"
    mock_msg.payload = "15.8"

    client._message_received(mock_msg)

    # Should parse as float
    assert client._data["unas_memory_usage"] == 15.8
    assert isinstance(client._data["unas_memory_usage"], float)


def test_mqtt_message_parsing_strings(hass_instance):
    """Test MQTT message parsing for string values."""
    client = UNASMQTTClient(hass_instance, "192.168.1.25")

    mock_msg = MagicMock()
    mock_msg.topic = "homeassistant/sensor/unas_os_version/state"
    mock_msg.payload = "4.0.21"

    client._message_received(mock_msg)

    # Should keep as string
    assert client._data["unas_os_version"] == "4.0.21"
    assert isinstance(client._data["unas_os_version"], str)


def test_mqtt_ignores_non_unas_topics(hass_instance):
    """Test MQTT client ignores non-UNAS sensor topics."""
    client = UNASMQTTClient(hass_instance, "192.168.1.25")

    mock_msg = MagicMock()
    mock_msg.topic = "homeassistant/sensor/other_device/state"
    mock_msg.payload = "100"

    client._message_received(mock_msg)

    # Should not be in data
    assert "other_device" not in client._data


def test_mqtt_ignores_config_topics(hass_instance):
    """Test MQTT client ignores config topics."""
    client = UNASMQTTClient(hass_instance, "192.168.1.25")

    mock_msg = MagicMock()
    mock_msg.topic = "homeassistant/sensor/unas_cpu/config"
    mock_msg.payload = '{"name": "CPU"}'

    initial_data_len = len(client._data)
    client._message_received(mock_msg)

    # Should not add anything to data
    assert len(client._data) == initial_data_len


def test_fan_curve_message_parsing(hass_instance):
    """Test fan curve parameter message parsing."""
    client = UNASMQTTClient(hass_instance, "192.168.1.25")

    mock_msg = MagicMock()
    mock_msg.topic = "homeassistant/unas/fan_curve/min_temp"
    mock_msg.payload = "43"

    client._fan_curve_message_received(mock_msg)

    # Should store with fan_curve_ prefix
    assert client._data["fan_curve_min_temp"] == 43


def test_get_data_returns_copy(hass_instance):
    """Test get_data returns a copy of the data."""
    client = UNASMQTTClient(hass_instance, "192.168.1.25")
    client._data = {"test": "value"}

    data = client.get_data()
    data["test"] = "modified"

    # Original should not be modified
    assert client._data["test"] == "value"


def test_get_sensor_value(hass_instance):
    """Test get_sensor_value retrieves specific sensor."""
    client = UNASMQTTClient(hass_instance, "192.168.1.25")
    client._data = {"unas_cpu": 65, "unas_fan_speed": 255}

    assert client.get_sensor_value("unas_cpu") == 65
    assert client.get_sensor_value("unas_fan_speed") == 255
    assert client.get_sensor_value("nonexistent") is None
