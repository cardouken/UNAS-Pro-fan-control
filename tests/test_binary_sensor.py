"""Tests for Binary Sensors."""
from unittest.mock import MagicMock

import pytest

from custom_components.unas_pro.binary_sensor import (
    UNASFanControlRunningSensor,
    UNASMonitorRunningSensor,
    UNASScriptsInstalledSensor,
)


def test_scripts_installed_sensor_on(mock_coordinator):
    """Test scripts installed sensor shows on when scripts exist."""
    mock_coordinator.data = {"scripts_installed": True}

    sensor = UNASScriptsInstalledSensor(mock_coordinator)

    assert sensor.is_on is True
    assert sensor._attr_name == "UNAS Pro Scripts Installed"


def test_scripts_installed_sensor_off(mock_coordinator):
    """Test scripts installed sensor shows off when scripts missing."""
    mock_coordinator.data = {"scripts_installed": False}

    sensor = UNASScriptsInstalledSensor(mock_coordinator)

    assert sensor.is_on is False


def test_monitor_running_sensor_on(mock_coordinator):
    """Test monitor service sensor shows on when service running."""
    mock_coordinator.data = {"monitor_running": True}

    sensor = UNASMonitorRunningSensor(mock_coordinator)

    assert sensor.is_on is True
    assert sensor._attr_name == "UNAS Pro Monitor Service"


def test_monitor_running_sensor_off(mock_coordinator):
    """Test monitor service sensor shows off when service stopped."""
    mock_coordinator.data = {"monitor_running": False}

    sensor = UNASMonitorRunningSensor(mock_coordinator)

    assert sensor.is_on is False


def test_fan_control_running_sensor_on(mock_coordinator):
    """Test fan control sensor shows on when service running."""
    mock_coordinator.data = {"fan_control_running": True}

    sensor = UNASFanControlRunningSensor(mock_coordinator)

    assert sensor.is_on is True
    assert sensor._attr_name == "UNAS Pro Fan Control Service"


def test_fan_control_running_sensor_off(mock_coordinator):
    """Test fan control sensor shows off when service stopped."""
    mock_coordinator.data = {"fan_control_running": False}

    sensor = UNASFanControlRunningSensor(mock_coordinator)

    assert sensor.is_on is False


def test_binary_sensor_defaults_false_when_missing(mock_coordinator):
    """Test binary sensors default to False when data missing."""
    mock_coordinator.data = {}  # No data

    sensor = UNASScriptsInstalledSensor(mock_coordinator)

    assert sensor.is_on is False


def test_binary_sensors_have_device_info(mock_coordinator):
    """Test binary sensors have correct device info."""
    mock_coordinator.ssh_manager.host = "192.168.1.25"
    mock_coordinator.entry.entry_id = "test_entry"

    sensor = UNASMonitorRunningSensor(mock_coordinator)

    assert "identifiers" in sensor._attr_device_info
    assert "name" in sensor._attr_device_info
    assert "UNAS Pro (192.168.1.25)" in sensor._attr_device_info["name"]
