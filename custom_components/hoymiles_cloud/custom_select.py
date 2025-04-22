"""Select platform for Hoymiles Cloud Custom Mode settings."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import asyncio
import json

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
    BATTERY_MODE_CUSTOM,
    API_BATTERY_SETTINGS_WRITE_URL,
)
from .hoymiles_api import HoymilesAPI

_LOGGER = logging.getLogger(__name__)

# Time options for the custom mode
TIME_OPTIONS = [
    "00:00", "00:30", "01:00", "01:30", "02:00", "02:30", 
    "03:00", "03:30", "04:00", "04:30", "05:00", "05:30",
    "06:00", "06:30", "07:00", "07:30", "08:00", "08:30",
    "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
    "12:00", "12:30", "13:00", "13:30", "14:00", "14:30",
    "15:00", "15:30", "16:00", "16:30", "17:00", "17:30",
    "18:00", "18:30", "19:00", "19:30", "20:00", "20:30",
    "21:00", "21:30", "22:00", "22:30", "23:00", "23:30",
]

# Power percentage options
POWER_OPTIONS = ["10%", "20%", "30%", "40%", "50%", "60%", "70%", "80%", "90%", "100%"]

# SOC percentage options
SOC_OPTIONS = ["10%", "20%", "30%", "40%", "50%", "60%", "70%", "80%", "90%", "100%"]

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hoymiles Cloud custom mode select entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    stations = data["stations"]
    api = data["api"]
    
    entities = []
    
    # For each station, add the custom mode select entities
    for station_id, station_name in stations.items():
        # Charge Start Time
        entities.append(
            HoymilesCustomModeSelect(
                coordinator=coordinator,
                api=api,
                station_id=station_id,
                station_name=station_name,
                setting_key="cs_time",
                setting_name="Charge Start Time",
                options=TIME_OPTIONS,
            )
        )
        
        # Charge End Time
        entities.append(
            HoymilesCustomModeSelect(
                coordinator=coordinator,
                api=api,
                station_id=station_id,
                station_name=station_name,
                setting_key="ce_time",
                setting_name="Charge End Time",
                options=TIME_OPTIONS,
            )
        )
        
        # Discharge Start Time
        entities.append(
            HoymilesCustomModeSelect(
                coordinator=coordinator,
                api=api,
                station_id=station_id,
                station_name=station_name,
                setting_key="dcs_time",
                setting_name="Discharge Start Time",
                options=TIME_OPTIONS,
            )
        )
        
        # Discharge End Time
        entities.append(
            HoymilesCustomModeSelect(
                coordinator=coordinator,
                api=api,
                station_id=station_id,
                station_name=station_name,
                setting_key="dce_time",
                setting_name="Discharge End Time",
                options=TIME_OPTIONS,
            )
        )
        
        # Charge Power
        entities.append(
            HoymilesCustomModeSelect(
                coordinator=coordinator,
                api=api,
                station_id=station_id,
                station_name=station_name,
                setting_key="c_power",
                setting_name="Charge Power",
                options=POWER_OPTIONS,
            )
        )
        
        # Discharge Power
        entities.append(
            HoymilesCustomModeSelect(
                coordinator=coordinator,
                api=api,
                station_id=station_id,
                station_name=station_name,
                setting_key="dc_power",
                setting_name="Discharge Power",
                options=POWER_OPTIONS,
            )
        )
        
        # Charge SOC Limit
        entities.append(
            HoymilesCustomModeSelect(
                coordinator=coordinator,
                api=api,
                station_id=station_id,
                station_name=station_name,
                setting_key="charge_soc",
                setting_name="Charge SOC Limit",
                options=SOC_OPTIONS,
            )
        )
        
        # Discharge SOC Limit
        entities.append(
            HoymilesCustomModeSelect(
                coordinator=coordinator,
                api=api,
                station_id=station_id,
                station_name=station_name,
                setting_key="dis_charge_soc",
                setting_name="Discharge SOC Limit",
                options=SOC_OPTIONS,
            )
        )
    
    async_add_entities(entities)


class HoymilesCustomModeSelect(CoordinatorEntity, SelectEntity):
    """Select entity for Custom Mode time settings."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: HoymilesAPI,
        station_id: str,
        station_name: str,
        setting_key: str,
        setting_name: str,
        options: List[str],
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._api = api
        self._station_id = station_id
        self._station_name = station_name
        self._setting_key = setting_key
        self._setting_name = setting_name
        self._attr_options = options
        
        # Set entity properties
        self._attr_unique_id = f"{DOMAIN}_{station_id}_custom_mode_{setting_key}"
        self._attr_name = f"{station_name} Custom Mode {setting_name}"
        self._attr_entity_category = EntityCategory.CONFIG
        
        # Set device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station_id)},
            "name": station_name,
            "manufacturer": "Hoymiles",
            "model": "Solar Inverter System",
        }

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
            
        # Check if we have custom mode data
        battery_settings = station_data.get("battery_settings", {})
        if not battery_settings or "mode_data" not in battery_settings:
            return False
            
        # Check if k_8 exists
        mode_data = battery_settings.get("mode_data", {})
        if "k_8" not in mode_data:
            return False
            
        return True

    @property
    def current_option(self) -> Optional[str]:
        """Return the current selected option."""
        if not self.available:
            return None
            
        battery_settings = self.coordinator.data[self._station_id]["battery_settings"]
        k8_data = battery_settings.get("mode_data", {}).get("k_8", {})
        
        # Get the time settings
        time_settings = k8_data.get("time", [{}])[0] if "time" in k8_data and k8_data["time"] else {}
        
        # Get the current value for this setting
        value = time_settings.get(self._setting_key)
        
        # For power and SOC settings, add % sign to match options format
        if self._setting_key in ["c_power", "dc_power", "charge_soc", "dis_charge_soc"] and value is not None:
            return f"{value}%"
            
        return value

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug("Setting Custom Mode %s to: %s", self._setting_name, option)
        
        # Get current settings
        try:
            current_settings = await self._api.get_battery_settings(self._station_id)
            if not current_settings or "mode_data" not in current_settings:
                _LOGGER.error("Failed to get current battery settings")
                return
                
            # Get the k_8 data
            mode_data = current_settings.get("mode_data", {})
            k8_data = mode_data.get("k_8", {})
            
            # Ensure we have the time array
            if "time" not in k8_data or not k8_data["time"]:
                k8_data["time"] = [{}]
            
            # Update the setting
            value = option
            # Remove % sign for power and SOC settings
            if self._setting_key in ["c_power", "dc_power", "charge_soc", "dis_charge_soc"]:
                value = int(option.replace("%", ""))
                
            k8_data["time"][0][self._setting_key] = value
            
            # Update with the full k_8 data
            mode_data["k_8"] = k8_data
            
            # Switch to custom mode and update settings
            success = await self._api.set_battery_mode(self._station_id, BATTERY_MODE_CUSTOM)
            if not success:
                _LOGGER.error("Failed to set battery mode to Custom Mode")
                return
                
            # Give the system a moment to change modes
            await asyncio.sleep(2)
            
            # Now update the custom mode settings
            # Prepare mode data with nested structure
            mode_data_payload = {
                "mode": BATTERY_MODE_CUSTOM,
                "data": {
                    "time": k8_data["time"]
                }
            }
            
            # Add reserve_soc if present
            if "reserve_soc" in k8_data:
                mode_data_payload["data"]["reserve_soc"] = k8_data["reserve_soc"]
                
            # Call the API to update
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": self._api._token,
            }
            
            data = {
                "action": 1013,
                "data": {
                    "sid": int(self._station_id),
                    "data": mode_data_payload
                },
            }
            
            async with self._api._session.post(
                API_BATTERY_SETTINGS_WRITE_URL, headers=headers, json=data
            ) as response:
                resp_text = await response.text()
                _LOGGER.debug("Custom Mode update response: %s", resp_text)
                
                try:
                    resp = json.loads(resp_text)
                    
                    if resp.get("status") == "0" and resp.get("message") == "success":
                        _LOGGER.info("Successfully updated Custom Mode %s to %s", self._setting_name, option)
                        
                        # Update coordinator to refresh the data
                        await self.coordinator.async_request_refresh()
                        
                        # Update state without waiting for coordinator
                        self.async_write_ha_state()
                    else:
                        _LOGGER.error(
                            "Failed to update Custom Mode: %s - %s", 
                            resp.get("status"), 
                            resp.get("message")
                        )
                except json.JSONDecodeError as e:
                    _LOGGER.error("Error decoding Custom Mode response: %s", e)
                
        except Exception as e:
            _LOGGER.error("Error updating Custom Mode setting: %s", e) 