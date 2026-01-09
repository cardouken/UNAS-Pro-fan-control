from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from . import UNASDataUpdateCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UNASDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    async_add_entities([UNASReinstallScriptsButton(coordinator)])


class UNASReinstallScriptsButton(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator: UNASDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "UNAS Pro Reinstall Scripts"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_reinstall_scripts"
        self._attr_icon = "mdi:cog-refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=f"UNAS Pro ({coordinator.ssh_manager.host})",
            manufacturer="Ubiquiti",
            model="UNAS Pro",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.mqtt_client.is_available()

    async def async_press(self) -> None:
        await self.coordinator.async_reinstall_scripts()
