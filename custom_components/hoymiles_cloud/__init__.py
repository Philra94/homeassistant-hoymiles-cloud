"""The Hoymiles Cloud Integration."""
import asyncio
import logging
from datetime import timedelta
import json

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, STORAGE_KEY, STORAGE_VERSION, BATTERY_MODE_CUSTOM, API_BATTERY_SETTINGS_WRITE_URL
from .hoymiles_api import HoymilesAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT, "custom_select"]

# Define a helper function to convert mode number to key
def _get_mode_key_for_num(mode_num):
    """Convert battery mode number to string key."""
    mode_keys = {
        1: "self_consumption_mode",
        2: "economy_mode",
        3: "backup_mode",
        4: "off_grid_mode",
        7: "peak_shaving_mode",
        8: "time_of_use_mode"
    }
    return mode_keys.get(mode_num, f"mode_{mode_num}")

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hoymiles Cloud from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    session = async_get_clientsession(hass)
    api = HoymilesAPI(session, username, password)

    # Initialize storage
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    stored_data = await store.async_load() or {}
    
    # Ensure we have station-specific data
    stored_data.setdefault("stations", {})
    
    # Verify authentication
    try:
        _LOGGER.debug("Attempting authentication for user: %s", username)
        auth_result = await api.authenticate()
        if not auth_result:
            _LOGGER.error("Authentication failed")
            return False
        _LOGGER.debug("Authentication successful")
    except Exception as e:
        _LOGGER.error("Authentication failed with exception: %s", e)
        return False

    # Fetch initial station data
    try:
        _LOGGER.debug("Attempting to get stations for account: %s", username)
        stations = await api.get_stations()
        _LOGGER.debug("API returned stations data: %s", stations)
        
        # Enhanced check for stations
        if not stations:
            _LOGGER.error("No stations found for this account (empty dictionary returned)")
            return False
            
        if not isinstance(stations, dict):
            _LOGGER.error("Invalid stations data type: %s, expected dict", type(stations))
            return False
            
        _LOGGER.info("Found %d station(s): %s", len(stations), list(stations.keys()))
        
        # Initialize storage for each station
        for station_id in stations:
            _LOGGER.debug("Initializing storage for station: %s (%s)", station_id, stations[station_id])
            if station_id not in stored_data["stations"]:
                stored_data["stations"][station_id] = {}
            
            # Initialize with default values for all modes if not present
            if "self_consumption_soc" not in stored_data["stations"][station_id]:
                stored_data["stations"][station_id]["self_consumption_soc"] = 50
            if "backup_soc" not in stored_data["stations"][station_id]:
                stored_data["stations"][station_id]["backup_soc"] = 100
            if "time_of_use_soc" not in stored_data["stations"][station_id]:
                stored_data["stations"][station_id]["time_of_use_soc"] = 0
            if "feed_in_priority_soc" not in stored_data["stations"][station_id]:
                stored_data["stations"][station_id]["feed_in_priority_soc"] = 70
            if "off_grid_soc" not in stored_data["stations"][station_id]:
                stored_data["stations"][station_id]["off_grid_soc"] = 30
            if "economic_mode_soc" not in stored_data["stations"][station_id]:
                stored_data["stations"][station_id]["economic_mode_soc"] = 30
            if "custom_mode_soc" not in stored_data["stations"][station_id]:
                stored_data["stations"][station_id]["custom_mode_soc"] = 10
        
        # Save initial data
        await store.async_save(stored_data)
        
    except Exception as e:
        _LOGGER.error("Failed to get station data: %s", e)
        return False

    async def async_update_data():
        """Fetch data from API."""
        try:
            async with async_timeout.timeout(30):
                _LOGGER.debug("=== Starting coordinator data update ===")
                
                # Check if token is still valid, refresh if needed
                if api.is_token_expired():
                    _LOGGER.debug("Token expired, refreshing...")
                    await api.authenticate()
                
                # Collect data from all stations
                data = {}
                for station_id in stations:
                    _LOGGER.debug("Updating data for station %s", station_id)
                    
                    # Get real-time data
                    real_time_data = await api.get_real_time_data(station_id)
                    
                    # Get PV indicators data
                    try:
                        pv_indicators = await api.get_pv_indicators(station_id)
                        _LOGGER.debug("Got PV indicators data for station %s", station_id)
                    except Exception as e:
                        _LOGGER.warning("Failed to get PV indicators data: %s", e)
                        pv_indicators = {}
                    
                    # Get battery settings
                    try:
                        _LOGGER.debug("Fetching battery settings for station %s", station_id)
                        battery_settings = await api.get_battery_settings(station_id)
                        _LOGGER.debug("Battery settings obtained: %s", "success" if battery_settings else "failed")
                    except Exception as e:
                        _LOGGER.warning("Failed to get battery settings: %s", e)
                        # Create default battery settings if they couldn't be retrieved
                        battery_settings = {"data": {"mode": 1, "reserve_soc": 20}}
                    
                    # Check if we are using the direct status API format
                    if "mode_data" in battery_settings and isinstance(battery_settings["mode_data"], dict):
                        _LOGGER.debug("Found mode_data in battery settings response")
                        current_mode = battery_settings.get("data", {}).get("mode", 1)
                        current_mode_key = f"k_{current_mode}"
                        
                        # Extract the reserve_soc for current mode from mode_data
                        if current_mode_key in battery_settings["mode_data"] and "reserve_soc" in battery_settings["mode_data"][current_mode_key]:
                            current_reserve_soc = battery_settings["mode_data"][current_mode_key]["reserve_soc"]
                            _LOGGER.debug("Current mode %s has reserve_soc: %s", current_mode, current_reserve_soc)
                            # Update the main data structure with the current mode's reserve_soc
                            battery_settings["data"]["reserve_soc"] = current_reserve_soc
                    
                    # Enhance battery settings with stored SOC values for all modes
                    station_stored_data = stored_data["stations"].get(station_id, {})
                    
                    # Add the stored SOC values to the data
                    enhanced_battery_settings = battery_settings.copy()
                    
                    # The API values should take precedence over stored values
                    # Extract SOC values from mode_data if available
                    api_mode_values = {}
                    should_save = False  # Initialize flag for saving data
                    
                    # Check if we have mode_data in the response
                    if "mode_data" in battery_settings and isinstance(battery_settings["mode_data"], dict):
                        mode_data = battery_settings["mode_data"]
                        
                        # Extract values for each mode from the response
                        for k_key, mode_settings in mode_data.items():
                            if k_key.startswith("k_") and "reserve_soc" in mode_settings:
                                mode_num = int(k_key.split("_")[1])
                                api_mode_values[mode_num] = mode_settings["reserve_soc"]
                                _LOGGER.debug("Found %s SOC in API: %s", k_key, mode_settings["reserve_soc"])
                    
                    # Create a dictionary to store all mode SOC values
                    all_modes_soc = {}
                    
                    # Populate with modes from API response
                    for mode_num, soc_value in api_mode_values.items():
                        mode_key = _get_mode_key_for_num(mode_num)
                        all_modes_soc[mode_key] = soc_value
                    
                    # Add backward compatibility for known modes
                    all_modes_soc["self_consumption"] = api_mode_values.get(1, station_stored_data.get("self_consumption_soc", 50))
                    all_modes_soc["backup"] = api_mode_values.get(3, station_stored_data.get("backup_soc", 100))
                    
                    # Store all modes in enhanced settings
                    enhanced_battery_settings["stored_soc"] = all_modes_soc
                    
                    # Update the mode_data to make it available in the UI
                    if "mode_data" in battery_settings and isinstance(battery_settings["mode_data"], dict):
                        enhanced_battery_settings["mode_data"] = battery_settings["mode_data"]
                    
                    # Update stored values if API values differ
                    for mode_num, soc_value in api_mode_values.items():
                        mode_key = _get_mode_key_for_num(mode_num)
                        stored_value = station_stored_data.get(f"{mode_key}_soc")
                        
                        if stored_value is None or soc_value != stored_value:
                            _LOGGER.debug("Updating stored %s_soc from %s to %s", 
                                          mode_key, stored_value, soc_value)
                            stored_data["stations"][station_id][f"{mode_key}_soc"] = soc_value
                            should_save = True
                    
                    # Save if any values were updated
                    if should_save:
                        await store.async_save(stored_data)
                    
                    data[station_id] = {
                        "real_time_data": real_time_data,
                        "battery_settings": enhanced_battery_settings,
                        "pv_indicators": pv_indicators
                    }
                
                _LOGGER.debug("=== Coordinator data update completed ===")
                return data
        except Exception as e:
            _LOGGER.error("Error updating data: %s", e)
            raise UpdateFailed(f"Error updating data: {e}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Store API, stations, and persistent storage in hass data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "stations": stations,
        "store": store,
        "stored_data": stored_data,
    }

    # Define a helper function to update stored SOC values
    async def async_update_soc(station_id, mode_name, value):
        """Update stored SOC value for a station and mode."""
        # Store the value with the mode name as key
        stored_data["stations"].setdefault(station_id, {})
        stored_data["stations"][station_id][f"{mode_name}_soc"] = value
        
        # Save to persistent storage
        await store.async_save(stored_data)
        _LOGGER.debug("Saved SOC value %s for station %s mode %s", value, station_id, mode_name)
    
    # Add the function to hass data for access by entities
    hass.data[DOMAIN][entry.entry_id]["update_soc"] = async_update_soc

    # Register custom services
    async def handle_set_custom_mode_schedule(call):
        """Handle the service call to set custom mode schedule."""
        station_id = call.data.get("entity_id").split("_")[1]
        
        # Format the time values
        charge_start = call.data.get("charge_start_time").replace(":", "")
        charge_start = f"{charge_start[:2]}:{charge_start[2:]}"
        
        charge_end = call.data.get("charge_end_time").replace(":", "")
        charge_end = f"{charge_end[:2]}:{charge_end[2:]}"
        
        discharge_start = call.data.get("discharge_start_time").replace(":", "")
        discharge_start = f"{discharge_start[:2]}:{discharge_start[2:]}"
        
        discharge_end = call.data.get("discharge_end_time").replace(":", "")
        discharge_end = f"{discharge_end[:2]}:{discharge_end[2:]}"
        
        # Get power and SOC values
        charge_power = int(call.data.get("charge_power"))
        discharge_power = int(call.data.get("discharge_power"))
        charge_soc = int(call.data.get("charge_soc"))
        discharge_soc = int(call.data.get("discharge_soc"))
        
        # Get current settings
        current_settings = await api.get_battery_settings(station_id)
        if not current_settings or "mode_data" not in current_settings:
            _LOGGER.error("Failed to get current battery settings")
            return
            
        # Get the k_8 data
        mode_data = current_settings.get("mode_data", {})
        k8_data = mode_data.get("k_8", {})
        
        # Ensure we have the time array
        if "time" not in k8_data or not k8_data["time"]:
            k8_data["time"] = [{}]
        
        # Update the settings
        k8_data["time"][0] = {
            "cs_time": charge_start,
            "ce_time": charge_end,
            "dcs_time": discharge_start,
            "dce_time": discharge_end,
            "c_power": charge_power,
            "dc_power": discharge_power,
            "charge_soc": charge_soc,
            "dis_charge_soc": discharge_soc
        }
        
        # Update with the full k_8 data
        mode_data["k_8"] = k8_data
        
        # Switch to custom mode and update settings
        success = await api.set_battery_mode(station_id, BATTERY_MODE_CUSTOM)
        if not success:
            _LOGGER.error("Failed to set battery mode to Custom Mode")
            return
            
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
            "Authorization": api._token,
        }
        
        data = {
            "action": 1013,
            "data": {
                "sid": int(station_id),
                "data": mode_data_payload
            },
        }
        
        try:
            async with api._session.post(
                API_BATTERY_SETTINGS_WRITE_URL, headers=headers, json=data
            ) as response:
                resp_text = await response.text()
                
                try:
                    resp = json.loads(resp_text)
                    
                    if resp.get("status") == "0" and resp.get("message") == "success":
                        _LOGGER.info("Successfully updated Custom Mode schedule")
                        # Update coordinator to refresh the data
                        await coordinator.async_request_refresh()
                    else:
                        _LOGGER.error(
                            "Failed to update Custom Mode: %s - %s", 
                            resp.get("status"), 
                            resp.get("message")
                        )
                except json.JSONDecodeError as e:
                    _LOGGER.error("Error decoding Custom Mode response: %s", e)
                    
        except Exception as e:
            _LOGGER.error("Error updating Custom Mode settings: %s", e)
    
    # Register the custom mode schedule service
    hass.services.async_register(
        DOMAIN, 
        "set_custom_mode_schedule", 
        handle_set_custom_mode_schedule
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for config entry changes
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id) 