"""Tests for Button entities."""
from unittest.mock import AsyncMock

import pytest

from custom_components.unas_pro.button import UNASReinstallScriptsButton


@pytest.mark.asyncio
async def test_reinstall_scripts_button_press(mock_coordinator):
    """Test reinstall scripts button calls coordinator."""
    mock_coordinator.async_reinstall_scripts = AsyncMock()

    button = UNASReinstallScriptsButton(mock_coordinator)

    await button.async_press()

    # Should have called coordinator's reinstall method
    mock_coordinator.async_reinstall_scripts.assert_called_once()


def test_reinstall_scripts_button_has_device_info(mock_coordinator):
    """Test button has correct device info."""
    mock_coordinator.ssh_manager.host = "192.168.1.25"
    mock_coordinator.entry.entry_id = "test_entry"

    button = UNASReinstallScriptsButton(mock_coordinator)

    assert button._attr_name == "UNAS Pro Reinstall Scripts"
    assert button._attr_icon == "mdi:cog-refresh"
    assert "identifiers" in button._attr_device_info
    assert "UNAS Pro (192.168.1.25)" in button._attr_device_info["name"]
