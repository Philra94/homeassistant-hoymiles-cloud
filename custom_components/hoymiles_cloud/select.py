"""Select platform for Hoymiles Cloud integration."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DOMAIN,
    BATTERY_MODE_SELF_CONSUMPTION,
    BATTERY_MODE_TIME_OF_USE,
    BATTERY_MODE_BACKUP,
    BATTERY_MODES,
)
from .hoymiles_api import HoymilesAPI

_LOGGER = logging.getLogger(__name__)

# Extended mode options dictionary including all possible modes
MODE_OPTIONS = {
    1: "Self-Consumption Mode",
    2: "Economy Mode",
    3: "Backup Mode",
    4: "Off-Grid Mode",
    7: "Peak Shaving Mode",
    8: "Time of Use Mode",
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hoymiles Cloud select entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    stations = data["stations"]
    api = data["api"]
    
    entities = []
    
    # For each station, add a battery mode select entity
    for station_id, station_name in stations.items():
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
        self._station_name = station_name
        
        # Set entity properties - use a unique ID that won't conflict with the sensor
        self._attr_unique_id = f"{DOMAIN}_{station_id}_battery_mode_select"
        self._attr_name = f"{station_name} Battery Mode"
        self._attr_entity_category = EntityCategory.CONFIG
        
        # Set available options
        self._available_modes = self._get_available_modes()
        self._attr_options = list(self._available_modes.values())
        
        # Set device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station_id)},
            "name": station_name,
            "manufacturer": "Hoymiles",
            "model": "Solar Inverter System",
        }
    
    def _get_available_modes(self) -> Dict[int, str]:
        """Get available modes based on what's in the response."""
        # Include all defined modes by default
        modes = {
            1: MODE_OPTIONS[1],  # Self-Consumption Mode
            2: MODE_OPTIONS[2],  # Economy Mode
            3: MODE_OPTIONS[3],  # Backup Mode
            4: MODE_OPTIONS[4],  # Off-Grid Mode
            7: MODE_OPTIONS[7],  # Peak Shaving Mode
            8: MODE_OPTIONS[8],  # Time of Use Mode
        }
        
        return modes

    @property
    def current_option(self) -> Optional[str]:
        """Return the current selected mode as a string."""
        if self.coordinator.data is None:
            return None
            
        station_data = self.coordinator.data.get(self._station_id, {})
        if not station_data:
            return None
            
        battery_settings = station_data.get("battery_settings", {})
        if not battery_settings:
            return None
            
        # Get current mode number
        mode = battery_settings.get("data", {}).get("mode")
        if mode is None:
            return None
            
        # Convert mode number to text
        return MODE_OPTIONS.get(mode, f"Unknown ({mode})")

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug("Setting battery mode to: %s", option)
        
        # Find the mode ID that corresponds to the selected option
        mode_id = None
        for id, name in MODE_OPTIONS.items():
            if name == option:
                mode_id = id
                break
        
        if mode_id is None:
            _LOGGER.error("Unknown mode selected: %s", option)
            return
        
        _LOGGER.info("Setting battery mode to ID: %s, option: %s for station: %s", 
                    mode_id, option, self._station_id)
        
        # Set the battery mode via API
        success = await self._api.set_battery_mode(self._station_id, mode_id)
        if not success:
            _LOGGER.error("Failed to set battery mode to %s (ID: %s)", option, mode_id)
            return
            
        # Update coordinator to refresh the data
        _LOGGER.debug("Battery mode set successfully, requesting data refresh")
        await self.coordinator.async_request_refresh()
        
        # Update state without waiting for coordinator
        self.async_write_ha_state()
        _LOGGER.info("Successfully set battery mode to %s (ID: %s)", option, mode_id)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False
            
        if self.coordinator.data is None:
            return False
            
        station_data = self.coordinator.data.get(self._station_id, {})
        if not station_data:
            return False
            
        return True 