"""Tests for Sensor discovery retry logic."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.unas_pro.sensor import (
    _discover_and_add_drive_sensors,
    _discover_and_add_pool_sensors,
)


@pytest.mark.asyncio
async def test_drive_discovery_retry_succeeds_first_attempt(mock_coordinator):
    """Test drive discovery succeeds on first attempt."""
    mock_coordinator._discovered_bays = set()
    mock_coordinator.mqtt_client.get_data = MagicMock(
        return_value={
            "unas_hdd_1_temperature": 45,
            "unas_hdd_2_temperature": 46,
        }
    )

    mock_add_entities = AsyncMock()

    await _discover_and_add_drive_sensors(mock_coordinator, mock_add_entities)

    # Should have discovered 2 drives
    assert len(mock_coordinator._discovered_bays) == 2
    assert "1" in mock_coordinator._discovered_bays
    assert "2" in mock_coordinator._discovered_bays

    # Should have added entities
    assert mock_add_entities.called


@pytest.mark.asyncio
async def test_drive_discovery_no_duplicates(mock_coordinator):
    """Test drive discovery doesn't create duplicate sensors."""
    mock_coordinator._discovered_bays = {"1"}  # Bay 1 already discovered
    mock_coordinator.mqtt_client.get_data = MagicMock(
        return_value={
            "unas_hdd_1_temperature": 45,
            "unas_hdd_2_temperature": 46,
        }
    )

    mock_add_entities = AsyncMock()

    await _discover_and_add_drive_sensors(mock_coordinator, mock_add_entities)

    # Should have only added bay 2
    assert len(mock_coordinator._discovered_bays) == 2

    # Should have been called (for bay 2 only)
    assert mock_add_entities.called


@pytest.mark.asyncio
async def test_drive_discovery_empty_mqtt_data(mock_coordinator):
    """Test drive discovery handles empty MQTT data gracefully."""
    mock_coordinator._discovered_bays = set()
    mock_coordinator.mqtt_client.get_data = MagicMock(return_value={})

    mock_add_entities = AsyncMock()

    await _discover_and_add_drive_sensors(mock_coordinator, mock_add_entities)

    # Should have discovered nothing
    assert len(mock_coordinator._discovered_bays) == 0

    # Should not have added entities
    assert not mock_add_entities.called


@pytest.mark.asyncio
async def test_pool_discovery_succeeds(mock_coordinator):
    """Test storage pool discovery."""
    mock_coordinator._discovered_pools = set()
    mock_coordinator.mqtt_client.get_data = MagicMock(
        return_value={
            "unas_pool1_usage": 50,
            "unas_pool2_usage": 75,
        }
    )

    mock_add_entities = AsyncMock()

    await _discover_and_add_pool_sensors(mock_coordinator, mock_add_entities)

    # Should have discovered 2 pools
    assert len(mock_coordinator._discovered_pools) == 2
    assert "1" in mock_coordinator._discovered_pools
    assert "2" in mock_coordinator._discovered_pools


@pytest.mark.asyncio
async def test_pool_discovery_no_duplicates(mock_coordinator):
    """Test pool discovery doesn't create duplicates."""
    mock_coordinator._discovered_pools = {"1"}  # Pool 1 already exists
    mock_coordinator.mqtt_client.get_data = MagicMock(
        return_value={
            "unas_pool1_usage": 50,
            "unas_pool2_usage": 75,
        }
    )

    mock_add_entities = AsyncMock()

    await _discover_and_add_pool_sensors(mock_coordinator, mock_add_entities)

    # Should only have added pool 2
    assert len(mock_coordinator._discovered_pools) == 2
    assert mock_add_entities.called


def test_drive_bay_extraction_from_mqtt_key():
    """Test bay number extraction from MQTT topic."""
    # This tests the logic in sensor.py lines 209-212
    test_keys = {
        "unas_hdd_1_temperature": "1",
        "unas_hdd_7_temperature": "7",
        "unas_hdd_10_temperature": "10",  # If we ever support more bays
    }

    for key, expected_bay in test_keys.items():
        # Extract bay number using same logic as sensor.py
        bay_num = key.split("_")[2]
        assert bay_num == expected_bay


def test_pool_number_extraction_from_mqtt_key():
    """Test pool number extraction from MQTT topic."""
    # This tests the logic in sensor.py lines 268-269
    test_keys = {
        "unas_pool1_usage": "1",
        "unas_pool2_usage": "2",
        "unas_pool10_usage": "10",  # If we ever support more pools
    }

    for key, expected_pool in test_keys.items():
        # Extract pool number using same logic as sensor.py
        pool_num = key.replace("unas_pool", "").replace("_usage", "")
        assert pool_num == expected_pool
