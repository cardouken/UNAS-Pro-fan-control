"""Tests for SSH Manager."""
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from custom_components.unas_pro.ssh_manager import SSHManager


@pytest.mark.asyncio
async def test_mqtt_credential_validation_success(mock_asyncssh):
    """Test MQTT credentials are validated after deployment."""
    manager = SSHManager(
        host="192.168.1.25",
        username="root",
        password="test123",
        mqtt_host="192.168.1.111",
        mqtt_user="homeassistant",
        mqtt_password="mqtt_pass",
    )

    # Mock file reading
    mock_script = """#!/bin/bash
MQTT_HOST="192.168.1.111"
MQTT_USER="homeassistant"
MQTT_PASS="mqtt_pass"
"""
    mock_service = "[Unit]\nDescription=Test\n"

    with patch("pathlib.Path.read_text", return_value=mock_script):
        mock_conn = await mock_asyncssh.connect()
        manager._conn = mock_conn

        # Mock execute_command to return success
        manager.execute_command = AsyncMock(return_value=("", ""))

        # Mock _upload_file
        manager._upload_file = AsyncMock()

        # Should not raise
        await manager.deploy_scripts()


@pytest.mark.asyncio
async def test_mqtt_credential_validation_failure(mock_asyncssh):
    """Test MQTT credential validation catches failed replacement."""
    manager = SSHManager(
        host="192.168.1.25",
        username="root",
        password="test123",
        mqtt_host="192.168.1.222",  # Different from default
        mqtt_user="different_user",
        mqtt_password="different_pass",
    )

    # Mock file reading - credentials NOT replaced (still defaults)
    mock_script_with_defaults = """#!/bin/bash
MQTT_HOST="192.168.1.111"
MQTT_USER="homeassistant"
MQTT_PASS="unas_password_123"
"""

    with patch("pathlib.Path.read_text", return_value=mock_script_with_defaults):
        mock_conn = await mock_asyncssh.connect()
        manager._conn = mock_conn

        # Should raise ValueError because credentials don't match
        with pytest.raises(ValueError, match="Failed to replace MQTT_HOST"):
            await manager.deploy_scripts()


@pytest.mark.asyncio
async def test_mqtt_credential_validation_skips_matching_defaults(mock_asyncssh):
    """Test validation skips when user credentials match defaults."""
    manager = SSHManager(
        host="192.168.1.25",
        username="root",
        password="test123",
        mqtt_host="192.168.1.111",  # Same as default
        mqtt_user="homeassistant",  # Same as default
        mqtt_password="unas_password_123",  # Same as default
    )

    # Mock file reading - credentials match defaults
    mock_script = """#!/bin/bash
MQTT_HOST="192.168.1.111"
MQTT_USER="homeassistant"
MQTT_PASS="unas_password_123"
"""

    with patch("pathlib.Path.read_text", return_value=mock_script):
        mock_conn = await mock_asyncssh.connect()
        manager._conn = mock_conn
        manager.execute_command = AsyncMock(return_value=("", ""))
        manager._upload_file = AsyncMock()

        # Should not raise even though strings match defaults
        await manager.deploy_scripts()


@pytest.mark.asyncio
async def test_scripts_installed_check(mock_asyncssh):
    """Test checking if scripts are installed."""
    manager = SSHManager(
        host="192.168.1.25",
        username="root",
        password="test123",
    )

    mock_conn = await mock_asyncssh.connect()
    manager._conn = mock_conn

    # Test when scripts exist
    mock_result = MagicMock()
    mock_result.stdout = "yes\n"
    mock_result.stderr = ""
    mock_conn.run.return_value = mock_result

    result = await manager.scripts_installed()
    assert result is True

    # Test when scripts missing
    mock_result.stdout = "no\n"
    result = await manager.scripts_installed()
    assert result is False


@pytest.mark.asyncio
async def test_service_running_check(mock_asyncssh):
    """Test checking if service is running."""
    manager = SSHManager(
        host="192.168.1.25",
        username="root",
        password="test123",
    )

    mock_conn = await mock_asyncssh.connect()
    manager._conn = mock_conn

    # Test when service active
    mock_result = MagicMock()
    mock_result.stdout = "active\n"
    mock_result.stderr = ""
    mock_conn.run.return_value = mock_result

    result = await manager.service_running("unas_monitor")
    assert result is True

    # Test when service inactive
    mock_result.stdout = "inactive\n"
    result = await manager.service_running("unas_monitor")
    assert result is False


@pytest.mark.asyncio
async def test_connection_management(mock_asyncssh):
    """Test SSH connection management."""
    manager = SSHManager(
        host="192.168.1.25",
        username="root",
        password="test123",
    )

    # Test connect
    await manager.connect()
    assert manager._conn is not None
    mock_asyncssh.connect.assert_called_once()

    # Test disconnect
    mock_conn = manager._conn
    await manager.disconnect()
    assert manager._conn is None
    mock_conn.close.assert_called_once()
    mock_conn.wait_closed.assert_called_once()
