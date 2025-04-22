"""Sensor platform for Hoymiles Cloud integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfEnergy,
    UnitOfPower,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
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


@dataclass
class HoymilesSensorDescription(SensorEntityDescription):
    """Class describing Hoymiles sensor entities."""

    value_fn: Optional[Callable[[Dict], StateType]] = None
    available_fn: Optional[Callable[[Dict], bool]] = None


SENSORS = [
    # Power measurements (real-time)
    HoymilesSensorDescription(
        key="pv_power",
        name="PV Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: float(data.get("real_time_data", {}).get("real_power", 0) or 0),
    ),
    HoymilesSensorDescription(
        key="battery_power",
        name="Battery Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: float(data.get("real_time_data", {}).get("reflux_station_data", {}).get("bms_power", 0) or 0) * (
            # In the API: positive means charging, negative means discharging
            -1 if is_battery_charging(data) else 1
        ),
    ),
    HoymilesSensorDescription(
        key="battery_flow_direction",
        name="Battery Flow Direction",
        icon="mdi:battery-charging",
        value_fn=lambda data: "discharging" if not is_battery_charging(data) else "charging",
    ),
    HoymilesSensorDescription(
        key="grid_power",
        name="Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: float(data.get("real_time_data", {}).get("reflux_station_data", {}).get("grid_power", 0) or 0),
    ),
    HoymilesSensorDescription(
        key="load_power",
        name="Load Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: float(data.get("real_time_data", {}).get("reflux_station_data", {}).get("load_power", 0) or 0),
    ),
    
    # Battery state
    HoymilesSensorDescription(
        key="battery_soc",
        name="Battery State of Charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: int(
            # First try to get real-time data if available
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("bms_soc") or 
            # If not, use the current mode's reserve_soc from battery settings
            data.get("battery_settings", {}).get("data", {}).get("reserve_soc", 50)
        ),
    ),
    
    # Energy production - cumulative values
    HoymilesSensorDescription(
        key="today_energy",
        name="Today's Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("today_eq", 0) or 0),
    ),
    HoymilesSensorDescription(
        key="month_energy",
        name="Month Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("month_eq", 0) or 0),
    ),
    HoymilesSensorDescription(
        key="year_energy",
        name="Year Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("year_eq", 0) or 0),
    ),
    HoymilesSensorDescription(
        key="total_energy",
        name="Total Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("total_eq", 0) or 0),
    ),
    
    # Daily energy flows
    HoymilesSensorDescription(
        key="pv_to_load_energy_today",
        name="PV to Load Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("reflux_station_data", {}).get("pv_to_load_eq", 0) or 0),
    ),
    HoymilesSensorDescription(
        key="grid_import_energy_today",
        name="Grid Import Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("reflux_station_data", {}).get("meter_b_in_eq", 0) or 0),
    ),
    HoymilesSensorDescription(
        key="grid_export_energy_today",
        name="Grid Export Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("reflux_station_data", {}).get("meter_b_out_eq", 0) or 0),
    ),
    HoymilesSensorDescription(
        key="battery_charge_energy_today",
        name="Battery Charge Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("reflux_station_data", {}).get("bms_in_eq", 0) or 0),
    ),
    HoymilesSensorDescription(
        key="battery_discharge_energy_today",
        name="Battery Discharge Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("reflux_station_data", {}).get("bms_out_eq", 0) or 0),
    ),
    HoymilesSensorDescription(
        key="total_consumption_today",
        name="Total Consumption Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("reflux_station_data", {}).get("use_eq_total", 0) or 0),
    ),
    
    # Cumulative grid metrics
    HoymilesSensorDescription(
        key="grid_import_total",
        name="Grid Import Total",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("reflux_station_data", {}).get("mb_in_eq", {}).get("total_eq", 0) or 0),
    ),
    HoymilesSensorDescription(
        key="grid_export_total",
        name="Grid Export Total",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: int(data.get("real_time_data", {}).get("reflux_station_data", {}).get("mb_out_eq", {}).get("total_eq", 0) or 0),
    ),
    
    # System status information
    HoymilesSensorDescription(
        key="last_update_time",
        name="Last Data Update Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: parse_timestamp(data.get("real_time_data", {}).get("data_time")),
    ),

    # Add a temperature sensor if needed
    # Example:
    # HoymilesSensorDescription(
    #    key="temperature",
    #    name="Temperature",
    #    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    #    device_class=SensorDeviceClass.TEMPERATURE,
    #    state_class=SensorStateClass.MEASUREMENT,
    #    value_fn=lambda data: float(data.get("real_time_data", {}).get("temperature", 0) or 0),
    # ),
]

# Mode names for the mode number to text mapping
MODE_NAMES = {
    1: "Self-Consumption Mode",
    2: "Economy Mode",
    3: "Backup Mode",
    4: "Off-Grid Mode",
    7: "Peak Shaving Mode",
    8: "Time of Use Mode",
}

# Add extended mode mapping for diagnostic sensors
BATTERY_MODE_TIME_OF_USE = 8
BATTERY_MODE_UNKNOWN_4 = 4
BATTERY_MODE_FEED_IN_PRIORITY = 5
BATTERY_MODE_OFF_GRID = 4
BATTERY_MODE_ECONOMIC = 2
BATTERY_MODE_CUSTOM = 7

# Extended mode dictionary with all modes from the API response
EXTENDED_MODE_NAMES = {
    1: "Self-Consumption Mode",
    2: "Economy Mode",
    3: "Backup Mode",
    4: "Off-Grid Mode",
    7: "Peak Shaving Mode",
    8: "Time of Use Mode"
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hoymiles Cloud sensor entries."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    stations = data["stations"]
    
    entities = []
    
    # For each station, create all standard sensors first
    for station_id, station_name in stations.items():
        # Add standard sensors from SENSORS
        for description in SENSORS:
            entities.append(
                HoymilesSensor(
                    coordinator=coordinator,
                    description=description,
                    station_id=station_id,
                    station_name=station_name,
                )
            )
        
        # Add only one battery mode sensor
        entities.append(
            HoymilesBatteryModeSensor(
                coordinator=coordinator,
                station_id=station_id,
                station_name=station_name,
            )
        )
    
    async_add_entities(entities)


class HoymilesSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Hoymiles sensor."""

    entity_description: HoymilesSensorDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: HoymilesSensorDescription,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._station_id = station_id
        self._station_name = station_name
        
        # Set unique ID and name
        self._attr_unique_id = f"{DOMAIN}_{station_id}_{description.key}"
        self._attr_name = f"{station_name} {description.name}"
        
        # Set device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station_id)},
            "name": station_name,
            "manufacturer": "Hoymiles",
            "model": "Solar Inverter System",
        }

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
            
        try:
            station_data = self.coordinator.data.get(self._station_id, {})
            if self.entity_description.value_fn:
                return self.entity_description.value_fn(station_data)
            return None
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.error("Error getting sensor value: %s", e)
            return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False
            
        station_data = self.coordinator.data.get(self._station_id, {})
        
        # Check if we have the minimum data required
        if "real_time_data" not in station_data:
            return False
            
        # Check if specific availability function is defined
        if self.entity_description.available_fn:
            return self.entity_description.available_fn(station_data)
            
        return True 


class HoymilesBatteryModeSensor(CoordinatorEntity, SensorEntity):
    """Sensor for displaying the current battery mode."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._station_id = station_id
        self._station_name = station_name
        
        # Set entity properties
        self._attr_unique_id = f"{DOMAIN}_{station_id}_battery_mode"
        self._attr_name = f"{station_name} Battery Mode Status"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        
        # Set device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station_id)},
            "name": station_name,
            "manufacturer": "Hoymiles",
            "model": "Solar Inverter System",
        }

    @property
    def native_value(self) -> Optional[str]:
        """Return the current battery mode as text."""
        if self.coordinator.data is None:
            return None
            
        station_data = self.coordinator.data.get(self._station_id, {})
        if not station_data:
            return None
            
        battery_settings = station_data.get("battery_settings", {})
        if not battery_settings:
            return None
            
        mode = battery_settings.get("data", {}).get("mode")
        if mode is None:
            return None
            
        # Convert mode number to text
        return MODE_NAMES.get(mode, f"Unknown ({mode})")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not self.coordinator.last_update_success:
            return False
            
        if self.coordinator.data is None:
            return False
            
        station_data = self.coordinator.data.get(self._station_id, {})
        if not station_data:
            return False
            
        return True


class HoymilesBatteryModeSettingSensor(CoordinatorEntity, SensorEntity):
    """Sensor for displaying settings of a specific battery mode (k_1, k_2, etc.)."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station_id: str,
        station_name: str,
        mode_key: str,
        mode_name_key: str,
        mode_name: str,
        setting_name: str,
        unit: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._station_id = station_id
        self._station_name = station_name
        self._mode_key = mode_key
        self._mode_name_key = mode_name_key
        self._mode_name = mode_name
        self._setting_name = setting_name
        self._attr_native_unit_of_measurement = unit
        
        # Set entity properties
        self._attr_unique_id = f"{DOMAIN}_{station_id}_{mode_name_key}_{setting_name}_diagnostic"
        self._attr_name = f"{station_name} {self._mode_name} {setting_name.replace('_', ' ').title()}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        
        # Set device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station_id)},
            "name": station_name,
            "manufacturer": "Hoymiles",
            "model": "Solar Inverter System",
        }

    @property
    def native_value(self) -> Optional[int]:
        """Return the mode setting value."""
        if self.coordinator.data is None:
            return None
            
        station_data = self.coordinator.data.get(self._station_id, {})
        if not station_data:
            return None
            
        battery_settings = station_data.get("battery_settings", {})
        if not battery_settings:
            return None
            
        # First try to get the value directly from mode_data
        if "mode_data" in battery_settings:
            mode_data = battery_settings.get("mode_data", {})
            if self._mode_key in mode_data and self._setting_name in mode_data[self._mode_key]:
                return mode_data[self._mode_key][self._setting_name]
        
        # As fallback, check in mode_settings
        if "mode_settings" in battery_settings:
            mode_number = int(self._mode_key.split("_")[1]) if "_" in self._mode_key else 0
            mode_settings = battery_settings.get("mode_settings", {})
            if mode_number in mode_settings and self._setting_name in mode_settings[mode_number]:
                return mode_settings[mode_number][self._setting_name]
                
        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not self.coordinator.last_update_success:
            return False
            
        if self.coordinator.data is None:
            return False
            
        station_data = self.coordinator.data.get(self._station_id, {})
        if not station_data:
            return False
            
        battery_settings = station_data.get("battery_settings", {})
        
        # Check if we have mode_data in the response
        if "mode_data" in battery_settings:
            mode_data = battery_settings.get("mode_data", {})
            if self._mode_key in mode_data and self._setting_name in mode_data[self._mode_key]:
                return True
                
        # Check in mode_settings
        if "mode_settings" in battery_settings:
            mode_number = int(self._mode_key.split("_")[1]) if "_" in self._mode_key else 0
            mode_settings = battery_settings.get("mode_settings", {})
            if mode_number in mode_settings and self._setting_name in mode_settings[mode_number]:
                return True
                
        return False

def parse_timestamp(timestamp_str):
    """Parse timestamp string from the API."""
    if not timestamp_str:
        return None
    try:
        dt_object = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        return dt_object.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        _LOGGER.warning("Failed to parse timestamp: %s", timestamp_str)
        return None

def is_battery_charging(data):
    """Determine if the battery is charging based on energy flow metrics."""
    try:
        reflux_data = data.get("real_time_data", {}).get("reflux_station_data", {})
        
        # If both values are available, compare them directly
        bms_in_eq = int(reflux_data.get("bms_in_eq", 0) or 0)  # Energy into battery
        bms_out_eq = int(reflux_data.get("bms_out_eq", 0) or 0)  # Energy out of battery
        
        # Check the recent energy flows
        # Higher charge value than discharge in recent period indicates charging
        if bms_in_eq > bms_out_eq:
            return True
        
        # Look at the flows data if available
        flows = reflux_data.get("flows", [])
        for flow in flows:
            # Check for flows to battery (in=4) from other components
            if flow.get("in") == 4 and flow.get("v", 0) > 0:
                return True
            
        # Default to True (charging) if no clear discharge indicators
        return True
    except Exception as e:
        _LOGGER.debug("Error determining battery charging status: %s", e)
        return True 