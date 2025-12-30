from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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

    async_add_entities(
        [
            UNASScriptsInstalledSensor(coordinator),
            UNASMonitorRunningSensor(coordinator),
            UNASFanControlRunningSensor(coordinator),
        ]
    )


class UNASBinarySensorBase(CoordinatorEntity, BinarySensorEntity):
    def __init__(
        self, coordinator: UNASDataUpdateCoordinator, key: str, name: str
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = f"UNAS Pro {name}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": f"UNAS Pro ({coordinator.ssh_manager.host})",
            "manufacturer": "Ubiquiti",
            "model": "UNAS Pro",
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.get(self._key, False)


class UNASScriptsInstalledSensor(UNASBinarySensorBase):
    def __init__(self, coordinator: UNASDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "scripts_installed", "Scripts Installed")
        self._attr_device_class = BinarySensorDeviceClass.RUNNING


class UNASMonitorRunningSensor(UNASBinarySensorBase):
    def __init__(self, coordinator: UNASDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "monitor_running", "Monitor Service")
        self._attr_device_class = BinarySensorDeviceClass.RUNNING


class UNASFanControlRunningSensor(UNASBinarySensorBase):
    def __init__(self, coordinator: UNASDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "fan_control_running", "Fan Control Service")
        self._attr_device_class = BinarySensorDeviceClass.RUNNING
