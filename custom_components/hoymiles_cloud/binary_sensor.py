"""Binary sensor platform for Hoymiles Cloud integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN
from .device import build_primary_battery_device_info, build_station_device_info


def get_station_data(coordinator: DataUpdateCoordinator, station_id: str) -> dict[str, Any]:
    """Return one station payload."""
    return coordinator.data.get(station_id, {}) if coordinator.data else {}


def get_reflux_data(station_data: dict[str, Any]) -> dict[str, Any]:
    """Return the reflux payload."""
    return station_data.get("real_time_data", {}).get("reflux_station_data", {})


def safe_float(value: Any) -> float | None:
    """Return a float if the value is numeric."""
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class HoymilesBinarySensorDescription(BinarySensorEntityDescription):
    """Declarative binary sensor definition."""

    value_fn: Callable[[dict[str, Any]], bool] | None = None
    exists_fn: Callable[[dict[str, Any]], bool] | None = None
    device_info_fn: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None


DESCRIPTIONS: list[HoymilesBinarySensorDescription] = [
    HoymilesBinarySensorDescription(
        key="battery_charging",
        name="Battery Charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda data: (safe_float(get_reflux_data(data).get("bms_power")) or 0.0) > 0,
        exists_fn=lambda data: bool(data.get("capabilities", {}).get("battery_telemetry")),
        device_info_fn=lambda sid, name, data: build_primary_battery_device_info(sid, name, data),
    ),
    HoymilesBinarySensorDescription(
        key="grid_connected",
        name="Grid Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda data: bool(get_reflux_data(data)),
        exists_fn=lambda data: True,
        device_info_fn=lambda sid, name, data: build_station_device_info(sid, name, data.get("station_info")),
    ),
    HoymilesBinarySensorDescription(
        key="firmware_update_available",
        name="Firmware Update Available",
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: int(data.get("firmware", {}).get("upgrade", 0) or 0) > 0,
        exists_fn=lambda data: bool(data.get("capabilities", {}).get("firmware_available")),
        device_info_fn=lambda sid, name, data: build_station_device_info(sid, name, data.get("station_info")),
    ),
    HoymilesBinarySensorDescription(
        key="ai_mode_active",
        name="AI Mode Active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("ai_status", {}).get("ai") == 1,
        exists_fn=lambda data: bool(data.get("capabilities", {}).get("ai_available")),
        device_info_fn=lambda sid, name, data: build_station_device_info(sid, name, data.get("station_info")),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hoymiles Cloud binary sensors."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data["coordinator"]
    stations = runtime_data["stations"]

    entities: list[BinarySensorEntity] = []
    for station_id, station_name in stations.items():
        station_data = get_station_data(coordinator, station_id)
        for description in DESCRIPTIONS:
            if description.exists_fn and not description.exists_fn(station_data):
                continue
            entities.append(
                HoymilesBinarySensor(
                    coordinator,
                    station_id,
                    station_name,
                    description,
                )
            )

    async_add_entities(entities)


class HoymilesBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Coordinator-backed Hoymiles binary sensor."""

    entity_description: HoymilesBinarySensorDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station_id: str,
        station_name: str,
        description: HoymilesBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._station_id = station_id
        self.entity_description = description
        station_data = get_station_data(coordinator, station_id)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_{description.key}"
        self._attr_name = f"{station_name} {description.name}"
        self._attr_device_info = description.device_info_fn(station_id, station_name, station_data)

    def _get_station_data(self) -> dict[str, Any]:
        """Return the current station payload."""
        return get_station_data(self.coordinator, self._station_id)

    @property
    def is_on(self) -> bool | None:
        """Return whether the binary sensor is on."""
        if not self.entity_description.value_fn:
            return None
        return bool(self.entity_description.value_fn(self._get_station_data()))

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        if not self.coordinator.last_update_success:
            return False
        if self.entity_description.exists_fn:
            return self.entity_description.exists_fn(self._get_station_data())
        return True
