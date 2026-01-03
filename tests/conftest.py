"""Fixtures for UNAS Pro tests."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_ssh_connection():
    """Mock SSH connection."""
    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock()
    mock_conn.start_sftp_client = AsyncMock()
    mock_conn.close = MagicMock()
    mock_conn.wait_closed = AsyncMock()
    return mock_conn


@pytest.fixture
def mock_asyncssh(mock_ssh_connection):
    """Mock asyncssh module."""
    with patch("custom_components.unas_pro.ssh_manager.asyncssh") as mock:
        mock.connect = AsyncMock(return_value=mock_ssh_connection)
        yield mock


@pytest.fixture
def mock_mqtt():
    """Mock MQTT."""
    with patch("custom_components.unas_pro.select.mqtt") as mock:
        mock.async_publish = AsyncMock()
        mock.async_subscribe = AsyncMock(return_value=MagicMock())
        yield mock


@pytest.fixture
def mock_coordinator():
    """Mock coordinator."""
    coordinator = MagicMock()
    coordinator.ssh_manager = MagicMock()
    coordinator.mqtt_client = MagicMock()
    coordinator.entry = MagicMock()
    coordinator.entry.entry_id = "test_entry"
    coordinator.data = {}
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.fixture
async def hass_instance():
    """Create a test Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    hass.async_create_task = MagicMock()
    hass.config_entries = MagicMock()
    return hass
