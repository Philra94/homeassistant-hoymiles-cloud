"""Number platform for Hoymiles Cloud integration."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional
import json
import asyncio

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
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
    BATTERY_MODE_BACKUP,
    BATTERY_MODES,
    API_BATTERY_SETTINGS_WRITE_URL,
    BATTERY_MODE_PEAK_SHAVING,
)
from .hoymiles_api import HoymilesAPI

_LOGGER = logging.getLogger(__name__)

# Add extended mode mapping
BATTERY_MODE_TIME_OF_USE = 8
BATTERY_MODE_OFF_GRID = 4
BATTERY_MODE_PEAK_SHAVING = 7
BATTERY_MODE_ECONOMY = 2

# Extended mode dictionary with all modes from the API response
EXTENDED_BATTERY_MODES = {
    BATTERY_MODE_SELF_CONSUMPTION: "Self-Consumption Mode",
    BATTERY_MODE_ECONOMY: "Economy Mode",
    BATTERY_MODE_BACKUP: "Backup Mode",
    BATTERY_MODE_OFF_GRID: "Off-Grid Mode",
    BATTERY_MODE_PEAK_SHAVING: "Peak Shaving Mode",
    BATTERY_MODE_TIME_OF_USE: "Time of Use Mode"
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hoymiles number platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    stations = data["stations"]
    api = data["api"]
    update_soc = data["update_soc"]  # Get the update_soc function
    
    entities = []
    
    # Create battery reserve SOC number entities for each station
    for station_id, station_name in stations.items():
        # Create battery reserve SOC controls for all battery modes
        for mode_num, mode_name in EXTENDED_BATTERY_MODES.items():
            # Skip mode 4 if it's empty (as per API response)
            if mode_num == BATTERY_MODE_OFF_GRID:
                continue
                
            # Create user-friendly key for the entity ID
            mode_key = mode_name.lower().replace(" ", "_")
            
            entities.append(
                HoymilesBatteryReserveSOC(
                    coordinator=coordinator,
                    api=api,
                    station_id=station_id,
                    station_name=station_name,
                    mode=mode_num,
                    mode_key=mode_key,
                    update_soc_callback=update_soc,
                )
            )
            
            # Add Peak Shaving Mode specific settings
            if mode_num == BATTERY_MODE_PEAK_SHAVING:
                # Add max_soc control for Peak Shaving Mode
                entities.append(
                    HoymilesPeakShavingMaxSOC(
                        coordinator=coordinator,
                        api=api,
                        station_id=station_id,
                        station_name=station_name,
                    )
                )
                
                # Add meter_power control for Peak Shaving Mode
                entities.append(
                    HoymilesPeakShavingMeterPower(
                        coordinator=coordinator,
                        api=api,
                        station_id=station_id,
                        station_name=station_name,
                    )
                )
    
    async_add_entities(entities)


class HoymilesBatteryReserveSOC(CoordinatorEntity, NumberEntity):
    """Representation of a Hoymiles battery reserve SOC number control."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: HoymilesAPI,
        station_id: str,
        station_name: str,
        mode: int,
        mode_key: str,
        update_soc_callback,
    ) -> None:
        """Initialize the number control."""
        super().__init__(coordinator)
        self._api = api
        self._station_id = station_id
        self._station_name = station_name
        self._mode = mode
        self._mode_name = EXTENDED_BATTERY_MODES.get(mode, "Unknown")
        self._update_soc = update_soc_callback
        self._attr_native_value = None
        
        # Set default SOC values based on mode
        self._default_soc = 50 if mode == BATTERY_MODE_SELF_CONSUMPTION else 100
        
        # Set unique ID and name - make sure they're distinct and descriptive
        self._attr_unique_id = f"{DOMAIN}_{station_id}_battery_reserve_soc_{mode_key}"
        self._attr_name = f"{station_name} Battery Reserve SOC ({self._mode_name})"
        
        # Set number attributes
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_mode = NumberMode.SLIDER
        self._attr_native_unit_of_measurement = PERCENTAGE
        
        # Set entity category
        self._attr_entity_category = EntityCategory.CONFIG
        
        # Set device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station_id)},
            "name": station_name,
            "manufacturer": "Hoymiles",
            "model": "Solar Inverter System",
        }
    
    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        
        # Load the stored value from coordinator data
        self._load_stored_value()
    
    def _load_stored_value(self) -> None:
        """Load the stored SOC value from coordinator data."""
        if self.coordinator.data is None:
            return
            
        station_data = self.coordinator.data.get(self._station_id, {})
        if not station_data:
            return
            
        battery_settings = station_data.get("battery_settings", {})
        if not battery_settings:
            return
        
        # First check directly from mode_data if available (most accurate)
        if "mode_data" in battery_settings:
            mode_data = battery_settings.get("mode_data", {})
            mode_key = f"k_{self._mode}"
            
            if mode_key in mode_data and "reserve_soc" in mode_data[mode_key]:
                self._attr_native_value = mode_data[mode_key]["reserve_soc"]
                _LOGGER.debug("SOC %s - Loaded directly from mode_data (%s): %s", 
                             self._mode_name, mode_key, self._attr_native_value)
                return
                
        # Next check from stored_soc values which are synced with the API
        if "stored_soc" in battery_settings:
            if self._mode == BATTERY_MODE_SELF_CONSUMPTION:
                self._attr_native_value = battery_settings["stored_soc"]["self_consumption"]
                _LOGGER.debug("SOC %s - Loaded from stored/API value: %s", self._mode_name, self._attr_native_value)
                return
            elif self._mode == BATTERY_MODE_BACKUP:
                self._attr_native_value = battery_settings["stored_soc"]["backup"]
                _LOGGER.debug("SOC %s - Loaded from stored/API value: %s", self._mode_name, self._attr_native_value)
                return
            
        # Finally check mode_settings which is a processed version of the API data
        if "mode_settings" in battery_settings:
            mode_settings = battery_settings.get("mode_settings", {})
            if self._mode in mode_settings and "reserve_soc" in mode_settings[self._mode]:
                self._attr_native_value = int(mode_settings[self._mode]["reserve_soc"])
                _LOGGER.debug("SOC %s - Loaded from mode_settings: %s", self._mode_name, self._attr_native_value)
                return
        
        # If we still have no value, try the old format
        data = battery_settings.get("data", {})
        if "mode" in data and "reserve_soc" in data:
            # Only update the value if it corresponds to the current mode
            if int(data["mode"]) == self._mode:
                self._attr_native_value = int(data.get("reserve_soc", self._default_soc))
                _LOGGER.debug("SOC %s - Loaded from old format API: %s", self._mode_name, self._attr_native_value)
                return

    def _get_mode_name_for_storage(self) -> str:
        """Get the mode name for storage purposes."""
        if self._mode == BATTERY_MODE_SELF_CONSUMPTION:
            return "self_consumption"
        elif self._mode == BATTERY_MODE_BACKUP:
            return "backup"
        else:
            # For other modes, use the mode_key directly
            return self._mode_key

    @property
    def native_value(self) -> float:
        """Return the current value."""
        # Use the stored value from the entity state
        if self._attr_native_value is not None:
            _LOGGER.debug("SOC %s - Using stored value: %s", self._mode_name, self._attr_native_value)
            return self._attr_native_value
            
        # Otherwise try to get from coordinator data
        self._load_stored_value()
        
        # If still no value, use default
        if self._attr_native_value is None:
            _LOGGER.debug("SOC %s - No stored value, using default: %s", self._mode_name, self._default_soc)
            self._attr_native_value = self._default_soc
            
        return self._attr_native_value

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        _LOGGER.debug("SOC %s - Setting value to %s%%", self._mode_name, value)
        
        # Store the value locally
        self._attr_native_value = value
        
        # Save to persistent storage
        storage_mode = self._get_mode_name_for_storage()
        await self._update_soc(self._station_id, storage_mode, value)
        
        # The API expects an integer value for SOC
        soc_value = int(value)
        
        # Get current battery mode
        current_mode = None
        if self.coordinator.data:
            station_data = self.coordinator.data.get(self._station_id, {})
            if station_data:
                battery_settings = station_data.get("battery_settings", {})
                if battery_settings:
                    current_mode = battery_settings.get("data", {}).get("mode")
        
        _LOGGER.debug("SOC %s - Current mode detected: %s", self._mode_name, current_mode)
        
        # If we're not in the correct mode, we need to change the mode first
        if current_mode != self._mode:
            _LOGGER.info("SOC %s - Changing battery mode to set SOC", self._mode_name)
            success = await self._api.set_battery_mode(self._station_id, self._mode)
            if not success:
                _LOGGER.error("SOC %s - Failed to change battery mode", self._mode_name)
                return
            
            # Give the system a moment to change modes
            await asyncio.sleep(2)
        
        # Set the reserve SOC via API
        success = await self._api.set_reserve_soc(self._station_id, soc_value)
        if not success:
            _LOGGER.error("SOC %s - Failed to set battery reserve SOC to %s", self._mode_name, soc_value)
            return
            
        # Update coordinator to refresh the data
        await self.coordinator.async_request_refresh()
        
        # Publish state change without waiting for coordinator
        self.async_write_ha_state()
        _LOGGER.info("SOC %s - Successfully set to %s%%", self._mode_name, value)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False
            
        # All reserve SOC controls should be available
        # They will only show up in the UI if they exist in the API response
        return True 


class HoymilesPeakShavingMaxSOC(CoordinatorEntity, NumberEntity):
    """Entity for controlling Peak Shaving Mode's max_soc parameter."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: HoymilesAPI,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the number control."""
        super().__init__(coordinator)
        self._api = api
        self._station_id = station_id
        self._station_name = station_name
        self._attr_native_value = None
        
        # Set unique ID and name
        self._attr_unique_id = f"{DOMAIN}_{station_id}_peak_shaving_max_soc"
        self._attr_name = f"{station_name} Peak Shaving Max SOC"
        
        # Set number attributes
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_mode = NumberMode.SLIDER
        self._attr_native_unit_of_measurement = PERCENTAGE
        
        # Set entity category
        self._attr_entity_category = EntityCategory.CONFIG
        
        # Set device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station_id)},
            "name": station_name,
            "manufacturer": "Hoymiles",
            "model": "Solar Inverter System",
        }
    
    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        
        # Load the stored value from coordinator data
        self._load_stored_value()
    
    def _load_stored_value(self) -> None:
        """Load the stored max_soc value from coordinator data."""
        if self.coordinator.data is None:
            return
            
        station_data = self.coordinator.data.get(self._station_id, {})
        if not station_data:
            return
            
        battery_settings = station_data.get("battery_settings", {})
        if not battery_settings:
            return
        
        # Get from mode_data if available
        if "mode_data" in battery_settings:
            mode_data = battery_settings.get("mode_data", {})
            
            if "k_7" in mode_data and "max_soc" in mode_data["k_7"]:
                self._attr_native_value = mode_data["k_7"]["max_soc"]
                _LOGGER.debug("Loaded Peak Shaving max_soc: %s", self._attr_native_value)
                return
        
        # Default value
        self._attr_native_value = 70

    @property
    def native_value(self) -> float:
        """Return the current value."""
        if self._attr_native_value is not None:
            return self._attr_native_value
            
        # Otherwise try to get from coordinator data
        self._load_stored_value()
        
        # If still no value, use default
        if self._attr_native_value is None:
            self._attr_native_value = 70
            
        return self._attr_native_value

    async def async_set_native_value(self, value: float) -> None:
        """Set the max_soc value."""
        _LOGGER.debug("Setting Peak Shaving max_soc to %s%%", value)
        
        # Store the value locally
        self._attr_native_value = value
        
        # Get current battery mode and settings
        current_mode = None
        current_reserve_soc = 30
        current_meter_power = 3000
        
        if self.coordinator.data:
            station_data = self.coordinator.data.get(self._station_id, {})
            if station_data:
                battery_settings = station_data.get("battery_settings", {})
                if battery_settings:
                    current_mode = battery_settings.get("data", {}).get("mode")
                    
                    # Get current values from mode_data
                    if "mode_data" in battery_settings and "k_7" in battery_settings["mode_data"]:
                        k7_data = battery_settings["mode_data"]["k_7"]
                        current_reserve_soc = k7_data.get("reserve_soc", 30)
                        current_meter_power = k7_data.get("meter_power", 3000)
        
        # Check if we need to change to Peak Shaving Mode first
        if current_mode != BATTERY_MODE_PEAK_SHAVING:
            _LOGGER.info("Changing to Peak Shaving Mode to set max_soc")
            await self._api.set_battery_mode(self._station_id, BATTERY_MODE_PEAK_SHAVING)
            await asyncio.sleep(2)
        
        # Set the Peak Shaving Mode settings via API
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": self._api._token,
        }
        
        # Create the data structure
        mode_data = {
            "mode": BATTERY_MODE_PEAK_SHAVING,
            "data": {
                "reserve_soc": current_reserve_soc,
                "max_soc": int(value),
                "meter_power": current_meter_power
            }
        }
        
        data = {
            "action": 1013,
            "data": {
                "sid": int(self._station_id),
                "data": mode_data
            },
        }
        
        try:
            async with self._api._session.post(
                API_BATTERY_SETTINGS_WRITE_URL, headers=headers, json=data
            ) as response:
                resp_text = await response.text()
                
                try:
                    resp = json.loads(resp_text)
                    
                    if resp.get("status") == "0" and resp.get("message") == "success":
                        _LOGGER.info("Successfully set Peak Shaving max_soc to %s%%", value)
                        # Update coordinator to refresh the data
                        await self.coordinator.async_request_refresh()
                        # Publish state change without waiting for coordinator
                        self.async_write_ha_state()
                    else:
                        _LOGGER.error(
                            "Failed to set Peak Shaving max_soc: %s - %s", 
                            resp.get("status"), 
                            resp.get("message")
                        )
                except json.JSONDecodeError as e:
                    _LOGGER.error("Error decoding max_soc update response: %s", e)
        except Exception as e:
            _LOGGER.error("Error setting Peak Shaving max_soc: %s", e)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success


class HoymilesPeakShavingMeterPower(CoordinatorEntity, NumberEntity):
    """Entity for controlling Peak Shaving Mode's meter_power parameter."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: HoymilesAPI,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the number control."""
        super().__init__(coordinator)
        self._api = api
        self._station_id = station_id
        self._station_name = station_name
        self._attr_native_value = None
        
        # Set unique ID and name
        self._attr_unique_id = f"{DOMAIN}_{station_id}_peak_shaving_meter_power"
        self._attr_name = f"{station_name} Peak Shaving Meter Power"
        
        # Set number attributes
        self._attr_native_min_value = 0
        self._attr_native_max_value = 10000
        self._attr_native_step = 100
        self._attr_mode = NumberMode.BOX
        self._attr_native_unit_of_measurement = "W"
        
        # Set entity category
        self._attr_entity_category = EntityCategory.CONFIG
        
        # Set device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station_id)},
            "name": station_name,
            "manufacturer": "Hoymiles",
            "model": "Solar Inverter System",
        }
    
    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        
        # Load the stored value from coordinator data
        self._load_stored_value()
    
    def _load_stored_value(self) -> None:
        """Load the stored meter_power value from coordinator data."""
        if self.coordinator.data is None:
            return
            
        station_data = self.coordinator.data.get(self._station_id, {})
        if not station_data:
            return
            
        battery_settings = station_data.get("battery_settings", {})
        if not battery_settings:
            return
        
        # Get from mode_data if available
        if "mode_data" in battery_settings:
            mode_data = battery_settings.get("mode_data", {})
            
            if "k_7" in mode_data and "meter_power" in mode_data["k_7"]:
                self._attr_native_value = mode_data["k_7"]["meter_power"]
                _LOGGER.debug("Loaded Peak Shaving meter_power: %s", self._attr_native_value)
                return
        
        # Default value
        self._attr_native_value = 3000

    @property
    def native_value(self) -> float:
        """Return the current value."""
        if self._attr_native_value is not None:
            return self._attr_native_value
            
        # Otherwise try to get from coordinator data
        self._load_stored_value()
        
        # If still no value, use default
        if self._attr_native_value is None:
            self._attr_native_value = 3000
            
        return self._attr_native_value

    async def async_set_native_value(self, value: float) -> None:
        """Set the meter_power value."""
        _LOGGER.debug("Setting Peak Shaving meter_power to %s W", value)
        
        # Store the value locally
        self._attr_native_value = value
        
        # Get current battery mode and settings
        current_mode = None
        current_reserve_soc = 30
        current_max_soc = 70
        
        if self.coordinator.data:
            station_data = self.coordinator.data.get(self._station_id, {})
            if station_data:
                battery_settings = station_data.get("battery_settings", {})
                if battery_settings:
                    current_mode = battery_settings.get("data", {}).get("mode")
                    
                    # Get current values from mode_data
                    if "mode_data" in battery_settings and "k_7" in battery_settings["mode_data"]:
                        k7_data = battery_settings["mode_data"]["k_7"]
                        current_reserve_soc = k7_data.get("reserve_soc", 30)
                        current_max_soc = k7_data.get("max_soc", 70)
        
        # Check if we need to change to Peak Shaving Mode first
        if current_mode != BATTERY_MODE_PEAK_SHAVING:
            _LOGGER.info("Changing to Peak Shaving Mode to set meter_power")
            await self._api.set_battery_mode(self._station_id, BATTERY_MODE_PEAK_SHAVING)
            await asyncio.sleep(2)
        
        # Set the Peak Shaving Mode settings via API
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": self._api._token,
        }
        
        # Create the data structure
        mode_data = {
            "mode": BATTERY_MODE_PEAK_SHAVING,
            "data": {
                "reserve_soc": current_reserve_soc,
                "max_soc": current_max_soc,
                "meter_power": int(value)
            }
        }
        
        data = {
            "action": 1013,
            "data": {
                "sid": int(self._station_id),
                "data": mode_data
            },
        }
        
        try:
            async with self._api._session.post(
                API_BATTERY_SETTINGS_WRITE_URL, headers=headers, json=data
            ) as response:
                resp_text = await response.text()
                
                try:
                    resp = json.loads(resp_text)
                    
                    if resp.get("status") == "0" and resp.get("message") == "success":
                        _LOGGER.info("Successfully set Peak Shaving meter_power to %s W", value)
                        # Update coordinator to refresh the data
                        await self.coordinator.async_request_refresh()
                        # Publish state change without waiting for coordinator
                        self.async_write_ha_state()
                    else:
                        _LOGGER.error(
                            "Failed to set Peak Shaving meter_power: %s - %s", 
                            resp.get("status"), 
                            resp.get("message")
                        )
                except json.JSONDecodeError as e:
                    _LOGGER.error("Error decoding meter_power update response: %s", e)
        except Exception as e:
            _LOGGER.error("Error setting Peak Shaving meter_power: %s", e)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success 