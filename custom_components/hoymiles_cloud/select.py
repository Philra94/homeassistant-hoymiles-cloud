"""Select platform for Hoymiles Cloud integration."""
from __future__ import annotations

import logging
from typing import Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import BATTERY_MODES, DOMAIN
from .data import battery_settings_writable, get_supported_modes
from .hoymiles_api import HoymilesAPI

_LOGGER = logging.getLogger(__name__)

MODE_OPTIONS = BATTERY_MODES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hoymiles Cloud select entities."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data["coordinator"]
    stations = runtime_data["stations"]
    api = runtime_data["api"]

    entities = []
    for station_id, station_name in stations.items():
        station_data = coordinator.data.get(station_id, {}) if coordinator.data else {}
        battery_settings = station_data.get("battery_settings", {})
        if battery_settings_writable(battery_settings) and get_supported_modes(battery_settings):
            entities.append(
                HoymilesBatteryModeSelect(
                    coordinator=coordinator,
                    api=api,
                    station_id=station_id,
                    station_name=station_name,
                )
            )

    async_add_entities(entities)


class HoymilesBatteryModeSelect(CoordinatorEntity, SelectEntity):
    """Select entity for battery mode selection."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: HoymilesAPI,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._api = api
        self._station_id = station_id
        self._attr_unique_id = f"{DOMAIN}_{station_id}_battery_mode_select"
        self._attr_name = f"{station_name} Battery Mode"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station_id)},
            "name": station_name,
            "manufacturer": "Hoymiles",
            "model": "Solar Inverter System",
        }
        self._attr_options = self._get_current_options()

    def _get_station_data(self) -> dict:
        """Return the coordinator payload for this station."""
        return self.coordinator.data.get(self._station_id, {}) if self.coordinator.data else {}

    def _get_current_options(self) -> list[str]:
        """Return supported mode options for this station."""
        battery_settings = self._get_station_data().get("battery_settings", {})
        return [
            MODE_OPTIONS[mode]
            for mode in get_supported_modes(battery_settings)
            if mode in MODE_OPTIONS
        ]

    @property
    def current_option(self) -> Optional[str]:
        """Return the current selected mode as a string."""
        battery_settings = self._get_station_data().get("battery_settings", {})
        mode = battery_settings.get("data", {}).get("mode")
        if mode is None:
            return None
        return MODE_OPTIONS.get(mode, f"Unknown ({mode})")

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        for mode_id, mode_name in MODE_OPTIONS.items():
            if mode_name != option:
                continue

            if not await self._api.set_battery_mode(self._station_id, mode_id):
                _LOGGER.error("Failed to set battery mode to %s (ID: %s)", option, mode_id)
                return

            await self.coordinator.async_request_refresh()
            self.async_write_ha_state()
            return

        _LOGGER.error("Unknown mode selected: %s", option)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False

        battery_settings = self._get_station_data().get("battery_settings", {})
        self._attr_options = self._get_current_options()
        return battery_settings_writable(battery_settings) and bool(self._attr_options)