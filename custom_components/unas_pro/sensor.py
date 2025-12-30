from __future__ import annotations

import asyncio
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfInformation,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import UNASDataUpdateCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# sensor definitions: (mqtt_key, name, unit, device_class, state_class, icon)
UNAS_SENSORS = [
    (
        "unas_cpu",
        "CPU Temperature",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        None,
    ),
    (
        "unas_cpu_usage",
        "CPU Usage",
        PERCENTAGE,
        None,
        SensorStateClass.MEASUREMENT,
        "mdi:chip",
    ),
    (
        "unas_fan_speed",
        "Fan Speed (PWM)",
        None,
        None,
        SensorStateClass.MEASUREMENT,
        "mdi:fan",
    ),
    (
        "unas_fan_speed_percent",
        "Fan Speed",
        PERCENTAGE,
        None,
        SensorStateClass.MEASUREMENT,
        "mdi:fan",
    ),
    (
        "unas_memory_usage",
        "Memory Usage",
        PERCENTAGE,
        None,
        SensorStateClass.MEASUREMENT,
        "mdi:memory",
    ),
    (
        "unas_memory_used",
        "Memory Used",
        UnitOfInformation.MEGABYTES,
        SensorDeviceClass.DATA_SIZE,
        SensorStateClass.MEASUREMENT,
        None,
    ),
    (
        "unas_memory_total",
        "Memory Total",
        UnitOfInformation.MEGABYTES,
        SensorDeviceClass.DATA_SIZE,
        None,
        None,
    ),
    (
        "unas_uptime",
        "Uptime",
        UnitOfTime.SECONDS,
        SensorDeviceClass.DURATION,
        SensorStateClass.TOTAL_INCREASING,
        None,
    ),
    ("unas_os_version", "UniFi OS Version", None, None, None, "mdi:information"),
    ("unas_drive_version", "UniFi Drive Version", None, None, None, "mdi:information"),
    (
        "unas_pool1_usage",
        "Storage Pool 1 Usage",
        PERCENTAGE,
        None,
        SensorStateClass.MEASUREMENT,
        "mdi:harddisk",
    ),
    (
        "unas_pool1_size",
        "Storage Pool 1 Size",
        "GB",
        SensorDeviceClass.DATA_SIZE,
        None,
        None,
    ),
    (
        "unas_pool1_used",
        "Storage Pool 1 Used",
        "GB",
        SensorDeviceClass.DATA_SIZE,
        SensorStateClass.MEASUREMENT,
        None,
    ),
    (
        "unas_pool1_available",
        "Storage Pool 1 Available",
        "GB",
        SensorDeviceClass.DATA_SIZE,
        SensorStateClass.MEASUREMENT,
        None,
    ),
]

# drive sensor patterns (will be created dynamically for each bay)
DRIVE_SENSORS = [
    (
        "temperature",
        "Temperature",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        None,
    ),
    ("model", "Model", None, None, None, "mdi:harddisk"),
    ("serial", "Serial Number", None, None, None, "mdi:identifier"),
    ("rpm", "RPM", "rpm", None, None, "mdi:speedometer"),
    ("firmware", "Firmware", None, None, None, "mdi:information"),
    ("status", "Status", None, None, None, "mdi:check-circle"),
    ("total_size", "Total Size", "TB", SensorDeviceClass.DATA_SIZE, None, None),
    (
        "power_hours",
        "Power-On Hours",
        UnitOfTime.HOURS,
        SensorDeviceClass.DURATION,
        SensorStateClass.TOTAL_INCREASING,
        None,
    ),
    ("bad_sectors", "Bad Sectors", None, None, None, "mdi:alert-circle"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UNASDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    entities = []

    # add main UNAS sensors
    for mqtt_key, name, unit, device_class, state_class, icon in UNAS_SENSORS:
        entities.append(
            UNASSensor(
                coordinator, mqtt_key, name, unit, device_class, state_class, icon
            )
        )

    # add fan curve visualization sensor
    entities.append(UNASFanCurveVisualizationSensor(coordinator))

    async_add_entities(entities)

    # store add_entities callback for dynamic drive sensor creation
    coordinator.sensor_add_entities = async_add_entities
    coordinator._discovered_bays = set()  # Track which bays we've already created sensors for

    # schedule initial drive sensor discovery after a delay to let MQTT data arrive
    async def discover_drives():
        await asyncio.sleep(10)  # Wait 10 seconds for MQTT data
        await _discover_and_add_drive_sensors(coordinator, async_add_entities)

    hass.async_create_task(discover_drives())


async def _discover_and_add_drive_sensors(
    coordinator: UNASDataUpdateCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    mqtt_data = coordinator.mqtt_client.get_data()
    detected_bays = set()

    _LOGGER.debug(
        "Discovering drives from MQTT data. Available keys: %d", len(mqtt_data)
    )

    for key in mqtt_data.keys():
        if key.startswith("unas_hdd_") and "_temperature" in key:
            # extract bay number: unas_hdd_1_temperature -> 1
            bay_num = key.split("_")[2]
            detected_bays.add(bay_num)

    # only process bays we haven't seen before
    new_bays = detected_bays - coordinator._discovered_bays
    
    if not new_bays:
        if not detected_bays:
            _LOGGER.debug("No drives detected in MQTT data yet")
        return

    _LOGGER.info("Discovered new drive bays: %s (total: %s)", sorted(new_bays), sorted(detected_bays))

    # create sensors for each newly detected bay
    entities = []
    for bay_num in sorted(new_bays):
        for sensor_suffix, name, unit, device_class, state_class, icon in DRIVE_SENSORS:
            mqtt_key = f"unas_hdd_{bay_num}_{sensor_suffix}"
            full_name = f"HDD {bay_num} {name}"
            entities.append(
                UNASDriveSensor(
                    coordinator,
                    mqtt_key,
                    full_name,
                    bay_num,
                    unit,
                    device_class,
                    state_class,
                    icon,
                )
            )

    if entities:
        async_add_entities(entities)
        coordinator._discovered_bays.update(new_bays)
        _LOGGER.info(
            "Added %d drive sensors for %d new bays", len(entities), len(new_bays)
        )


class UNASSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        coordinator: UNASDataUpdateCoordinator,
        mqtt_key: str,
        name: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None,
        icon: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._mqtt_key = mqtt_key
        self._attr_name = f"UNAS Pro {name}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{mqtt_key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        if icon:
            self._attr_icon = icon

        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": f"UNAS Pro ({coordinator.ssh_manager.host})",
            "manufacturer": "Ubiquiti",
            "model": "UNAS Pro",
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        mqtt_data = self.coordinator.data.get("mqtt_data", {})
        self._attr_native_value = mqtt_data.get(self._mqtt_key)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        mqtt_data = self.coordinator.data.get("mqtt_data", {})
        return self._mqtt_key in mqtt_data

    @property
    def available(self) -> bool:
        mqtt_data = self.coordinator.data.get("mqtt_data", {})
        return self._mqtt_key in mqtt_data

    @property
    def native_value(self):
        mqtt_data = self.coordinator.data.get("mqtt_data", {})
        return mqtt_data.get(self._mqtt_key)


class UNASFanCurveVisualizationSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: UNASDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "UNAS Fan Curve"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fan_curve_viz"
        self._attr_icon = "mdi:chart-line"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": f"UNAS Pro ({coordinator.ssh_manager.host})",
            "manufacturer": "Ubiquiti",
            "model": "UNAS Pro",
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        mqtt_data = self.coordinator.data.get("mqtt_data", {})

        min_temp = mqtt_data.get("fan_curve_min_temp", 43)
        max_temp = mqtt_data.get("fan_curve_max_temp", 47)
        min_fan = mqtt_data.get("fan_curve_min_fan", 204)
        max_fan = mqtt_data.get("fan_curve_max_fan", 255)

        # convert PWM to percentage for display
        min_fan_pct = round((min_fan * 100) / 255)
        max_fan_pct = round((max_fan * 100) / 255)

        # state: summary string
        self._attr_native_value = (
            f"{min_temp}-{max_temp}°C → {min_fan_pct}-{max_fan_pct}%"
        )

        # generate curve points for charting (temp, fan%)
        curve_points = self._generate_curve_points(min_temp, max_temp, min_fan, max_fan)

        # Set attributes for charting
        self._attr_extra_state_attributes = {
            "min_temp": min_temp,
            "max_temp": max_temp,
            "min_fan_pwm": min_fan,
            "max_fan_pwm": max_fan,
            "min_fan_percent": min_fan_pct,
            "max_fan_percent": max_fan_pct,
            "curve_points": curve_points,
            "curve_formula": f"Linear: {min_temp}°C→{min_fan_pct}%, {max_temp}°C→{max_fan_pct}%",
        }

    def _generate_curve_points(
        self, min_temp: float, max_temp: float, min_fan: float, max_fan: float
    ) -> list:
        points = []

        # Generate points from 30°C to 60°C
        for temp in range(30, 61):
            if temp < min_temp:
                fan_pwm = min_fan
            elif temp > max_temp:
                fan_pwm = max_fan
            else:
                fan_pwm = min_fan + (temp - min_temp) * (max_fan - min_fan) / (
                    max_temp - min_temp
                )

            fan_percent = round((fan_pwm * 100) / 255)
            points.append([temp, fan_percent])

        return points

    @property
    def available(self) -> bool:
        mqtt_data = self.coordinator.data.get("mqtt_data", {})
        return (
            "fan_curve_min_temp" in mqtt_data
            and "fan_curve_max_temp" in mqtt_data
            and "fan_curve_min_fan" in mqtt_data
            and "fan_curve_max_fan" in mqtt_data
        )


class UNASDriveSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        coordinator: UNASDataUpdateCoordinator,
        mqtt_key: str,
        name: str,
        bay_num: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None,
        icon: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._mqtt_key = mqtt_key
        self._bay_num = bay_num
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{mqtt_key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        if icon:
            self._attr_icon = icon

        # get drive model/serial from MQTT data for device info
        mqtt_data = coordinator.mqtt_client.get_data()
        model = mqtt_data.get(f"unas_hdd_{bay_num}_model", "Unknown")
        serial = mqtt_data.get(f"unas_hdd_{bay_num}_serial", "")

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{coordinator.entry.entry_id}_hdd_{bay_num}")},
            "name": f"UNAS HDD {bay_num}",
            "manufacturer": model.split()[0] if model != "Unknown" else "Unknown",
            "model": model,
            "serial_number": serial,
            "via_device": (DOMAIN, coordinator.entry.entry_id),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        mqtt_data = self.coordinator.data.get("mqtt_data", {})
        self._attr_native_value = mqtt_data.get(self._mqtt_key)
        self.async_write_ha_state()
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        mqtt_data = self.coordinator.data.get("mqtt_data", {})
        return self._mqtt_key in mqtt_data

    @property
    def native_value(self):
        mqtt_data = self.coordinator.data.get("mqtt_data", {})
        return mqtt_data.get(self._mqtt_key)
