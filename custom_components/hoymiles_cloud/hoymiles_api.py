"""API client for Hoymiles Cloud."""
import asyncio
import logging
import time
import hashlib
import json
from typing import Any, Dict, List, Optional

import aiohttp

from .const import (
    API_AUTH_URL,
    API_STATIONS_URL,
    API_REAL_TIME_DATA_URL,
    API_MICROINVERTERS_URL,
    API_MICRO_DETAIL_URL,
    API_PV_INDICATORS_URL,
    API_BATTERY_SETTINGS_READ_URL,
    API_BATTERY_SETTINGS_WRITE_URL,
    API_BATTERY_SETTINGS_STATUS_URL,
    BATTERY_MODE_SELF_CONSUMPTION,
    BATTERY_MODE_TIME_OF_USE,
    BATTERY_MODE_BACKUP,
    BATTERY_MODES,
)

_LOGGER = logging.getLogger(__name__)


class HoymilesAPI:
    """Hoymiles Cloud API client."""

    def __init__(
        self, session: aiohttp.ClientSession, username: str, password: str
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._username = username
        self._password = password  # Store password directly - will be hashed when needed
        self._token = None
        self._token_expires_at = 0
        self._token_valid_time = 7200  # Default token validity in seconds

    def is_token_expired(self) -> bool:
        """Check if the token is expired."""
        return time.time() >= self._token_expires_at

    async def authenticate(self) -> bool:
        """Authenticate with the Hoymiles API."""
        try:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            
            # Based on testing, MD5 hashing of the password is sufficient for authentication
            md5_password = hashlib.md5(self._password.encode()).hexdigest()
            
            # If MD5 doesn't work, you can try the combined hash format from HAR analysis:
            # second_part = "detsiHMyw54xS3UBlJCzLHzPgKv6VTDCrt3QxlyUigg="
            # hashed_password = f"{md5_password}.{second_part}"
            
            data = {
                "user_name": self._username,
                "password": md5_password,
            }
            
            async with self._session.post(
                API_AUTH_URL, headers=headers, json=data
            ) as response:
                resp = await response.json()
                
                if resp.get("status") == "0" and resp.get("message") == "success":
                    self._token = resp.get("data", {}).get("token")
                    self._token_expires_at = time.time() + self._token_valid_time
                    return True
                else:
                    _LOGGER.error(
                        "Authentication failed: %s - %s", 
                        resp.get("status"), 
                        resp.get("message")
                    )
                    return False
        except Exception as e:
            _LOGGER.error("Error during authentication: %s", e)
            raise

    async def get_stations(self) -> Dict[str, str]:
        """Get all stations for the authenticated user."""
        if not self._token:
            _LOGGER.debug("No token available, authenticating first")
            await self.authenticate()
            
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": self._token,
        }
        
        data = {
            "page_size": 10,
            "page_num": 1,
        }
        
        try:
            _LOGGER.debug("Sending request to get stations with token: %s...", self._token[:20] if self._token else "None")
            async with self._session.post(
                API_STATIONS_URL, headers=headers, json=data
            ) as response:
                resp_text = await response.text()
                _LOGGER.debug("Full stations response: %s", resp_text)
                
                resp = json.loads(resp_text)
                
                if resp.get("status") == "0" and resp.get("message") == "success":
                    stations = {}
                    stations_data = resp.get("data", {}).get("list", [])
                    _LOGGER.debug("Raw stations data: %s", stations_data)
                    
                    if not stations_data:
                        _LOGGER.warning("API returned success but stations list is empty")
                        
                    for station in stations_data:
                        station_id = str(station.get("id"))
                        station_name = station.get("name")
                        _LOGGER.debug("Adding station: %s - %s", station_id, station_name)
                        stations[station_id] = station_name
                        
                    _LOGGER.debug("Returning stations dictionary: %s", stations)
                    return stations
                else:
                    _LOGGER.error(
                        "Failed to get stations: %s - %s", 
                        resp.get("status"), 
                        resp.get("message")
                    )
                    return {}
        except Exception as e:
            _LOGGER.error("Error getting stations: %s", e)
            raise

    async def get_microinverters_by_stations(self, station_id: str) -> Dict[str, str]:
        """Get all microinverters with detail for a station."""
        if not self._token:
            _LOGGER.debug("No token available, authenticating first")
            await self.authenticate()
            
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": self._token,
        }
        
        data = {
            "sid": int(station_id),
            "page_size": 1000,
            "page_num": 1,
            "show_warn": 0
        }
        
        try:
            _LOGGER.debug("Sending request to get microinverters with token: %s...", self._token[:20] if self._token else "None")
            async with self._session.post(
                API_MICROINVERTERS_URL, headers=headers, json=data
            ) as response:
                resp_text = await response.text()
                _LOGGER.debug("Full microinverters response: %s", resp_text)
                
                resp = json.loads(resp_text)
                
                if resp.get("status") == "0" and resp.get("message") == "success":
                    microinverters = {}
                    microinverters_data = resp.get("data", {}).get("list", [])
                    _LOGGER.debug("Raw microinverters data: %s", microinverters_data)
                    
                    if not microinverters_data:
                        _LOGGER.warning("API returned success but microinverters list is empty")
                        
                    for microinverter in microinverters_data:
                        microinverter_id = str(microinverter.get("id"))

                        data = {
                            "id": int(microinverter_id),
                            "sid": int(station_id),
                        }

                        try:
                            _LOGGER.debug("Sending request to get microinverters detail with token: %s...", self._token[:20] if self._token else "None")
                            async with self._session.post(
                                API_MICRO_DETAIL_URL, headers=headers, json=data
                            ) as response:
                                resp_text = await response.text()
                                _LOGGER.debug("Full microinverter %s single detail response: %s", microinverter_id, resp_text)
                                
                                resp = json.loads(resp_text)
                                
                                if resp.get("status") == "0" and resp.get("message") == "success":
                                    microinverter_single = {}
                                    microinverter_single_data = resp.get("data", {})
                                    _LOGGER.debug("Raw single microinverter id %s data: %s", microinverter_id, microinverter_single_data)
                                    
                                    if not microinverter_single_data:
                                        _LOGGER.warning("API returned success but microinverter %s single data is empty", microinverter_id)
                                        
                                    _LOGGER.debug("Adding microinverters: %s - %s", microinverter_id, microinverter_single_data)
                                    microinverters[microinverter_id] = microinverter_single_data

                                else:
                                    microinverters[microinverter_id] = {}
                                    _LOGGER.error(
                                        "Failed to get microinverters details: %s - %s", 
                                        resp.get("status"), 
                                        resp.get("message")
                                    )

                        except Exception as e:
                            _LOGGER.error("Error getting detail of microinverter: %s", e)
                            raise

                    _LOGGER.debug("Returning microinverters dictionary: %s", microinverters)
                    return microinverters
                else:
                    _LOGGER.error(
                        "Failed to get microinverters: %s - %s", 
                        resp.get("status"), 
                        resp.get("message")
                    )
                    return {}
        except Exception as e:
            _LOGGER.error("Error getting microinverters: %s", e)
            raise

    async def get_real_time_data(self, station_id: str) -> Dict[str, Any]:
        """Get real-time data for a station."""
        if not self._token:
            await self.authenticate()
            
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": self._token,
        }
        
        data = {
            "sid": int(station_id),
        }
        
        try:
            async with self._session.post(
                API_REAL_TIME_DATA_URL, headers=headers, json=data
            ) as response:
                # Log raw text to better diagnose field availability across accounts/devices
                resp_text = await response.text()
                try:
                    resp = json.loads(resp_text)
                except json.JSONDecodeError:
                    _LOGGER.debug("Real-time data non-JSON response: %s", resp_text)
                    raise
                _LOGGER.debug("Real-time data response: %s", json.dumps(resp, ensure_ascii=False))
                
                if resp.get("status") == "0" and resp.get("message") == "success":
                    return resp.get("data", {})
                else:
                    _LOGGER.error(
                        "Failed to get real-time data: %s - %s", 
                        resp.get("status"), 
                        resp.get("message")
                    )
                    return {}
        except Exception as e:
            _LOGGER.error("Error getting real-time data: %s", e)
            raise

    async def get_pv_indicators(self, station_id: str) -> Dict[str, Any]:
        """Get PV indicators data for a station."""
        if not self._token:
            await self.authenticate()
            
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": self._token,
        }
        
        data = {
            "sid": int(station_id),
            "type": 4  # PV indicators type
        }
        
        try:
            async with self._session.post(
                API_PV_INDICATORS_URL, headers=headers, json=data
            ) as response:
                resp = await response.json()
                
                if resp.get("status") == "0" and resp.get("message") == "success":
                    return resp.get("data", {})
                else:
                    _LOGGER.error(
                        "Failed to get PV indicators data: %s - %s", 
                        resp.get("status"), 
                        resp.get("message")
                    )
                    return {}
        except Exception as e:
            _LOGGER.error("Error getting PV indicators data: %s", e)
            raise

    async def get_battery_settings(self, station_id: str) -> Dict[str, Any]:
        """Get battery settings for a station."""
        if self.is_token_expired():
            await self.authenticate()

        # The Authorization header must be just the token, no Bearer prefix
        headers = {
            "Content-Type": "application/json",
            "Authorization": self._token,
        }
        
        # The request needs to be specifically id as a string
        status_data = {
            "id": station_id
        }
        
        _LOGGER.debug("Requesting battery settings for station %s with data: %s", station_id, json.dumps(status_data))
        
        # First, check the status of settings to see if they're available
        try:
            status_response = await self._session.post(
                API_BATTERY_SETTINGS_STATUS_URL,
                headers=headers,
                json=status_data,
            )
            resp_text = await status_response.text()
            _LOGGER.debug("Raw setting status response: %s", resp_text)
            
            try:
                status_data = json.loads(resp_text)
                
                # If status is success and we have data with actual battery settings
                if (status_data.get("status") == "0" and 
                    status_data.get("message") == "success" and
                    status_data.get("data") and 
                    status_data.get("data", {}).get("data") and 
                    isinstance(status_data["data"]["data"], dict)):
                    
                    _LOGGER.debug("Successfully received battery settings")
                    
                    # Extract mode data from the response
                    mode_data = status_data["data"]["data"].get("data", {})
                    current_mode = status_data["data"]["data"].get("mode", 1)
                    
                    # Create result structure with full mode data
                    result = {
                        "data": {
                            "mode": current_mode,
                        },
                        "mode_data": mode_data  # Store the full mode data for access to all k_* values
                    }
                    
                    # Add reserve_soc for current mode to the main data
                    # Map mode IDs to their respective keys in the API response
                    mode_key_mapping = {
                        1: "k_1",  # Self-Consumption Mode
                        2: "k_2",  # Economy Mode
                        3: "k_3",  # Backup Mode
                        4: "k_4",  # Off-Grid Mode
                        7: "k_7",  # Peak Shaving Mode
                        8: "k_8",  # Time of Use Mode
                    }
                    
                    # Get the current mode key (k_1, k_2, etc.)
                    current_mode_key = mode_key_mapping.get(current_mode)
                    
                    # If we have settings for the current mode, extract reserve_soc
                    if current_mode_key and current_mode_key in mode_data:
                        result["data"]["reserve_soc"] = mode_data[current_mode_key].get("reserve_soc", 20)
                    
                    # Add a direct mapping of mode constants to their settings for easier access
                    result["mode_settings"] = {}
                    
                    # Add all mode settings to result
                    for mode_id, k_mode in mode_key_mapping.items():
                        if k_mode in mode_data:
                            result["mode_settings"][mode_id] = {
                                "reserve_soc": mode_data[k_mode].get("reserve_soc", 20)
                            }
                    
                    _LOGGER.debug("Parsed battery settings: %s", json.dumps(result, indent=2))
                    return result
                
                # Check for specific error messages
                if status_data.get("status") != "0":
                    # Handle "No Permission" error gracefully - this typically means no battery is connected
                    if status_data.get("status") == "3" and "No Permission" in str(status_data.get("message", "")):
                        _LOGGER.info("No battery detected for station %s (API error 3 - No Permission). Using default settings.", station_id)
                    else:
                        _LOGGER.error("API error: %s - %s", status_data.get("status"), status_data.get("message"))
                
            except json.JSONDecodeError as e:
                _LOGGER.warning("Error decoding status response JSON: %s", e)
            
        except Exception as e:
            _LOGGER.warning("Error checking battery settings status: %s", e)
        
        # If we can't get the settings, return a default value
        _LOGGER.debug("Could not retrieve battery settings for station %s (likely no battery connected), using defaults", station_id)
        return {"data": {"mode": 1, "reserve_soc": 20}}

    async def set_battery_mode(self, station_id: str, mode: int) -> bool:
        """Set battery mode for a station."""
        valid_modes = [1, 2, 3, 4, 7, 8]  # Self-Consumption, Economy, Backup, Off-Grid, Peak Shaving, Time of Use
        if mode not in valid_modes:
            _LOGGER.error("Invalid battery mode: %s", mode)
            return False
            
        if not self._token:
            await self.authenticate()
            
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": self._token,
        }
        
        # Prepare mode data with nested structure
        mode_data = {
            "mode": mode,
            "data": {}
        }
        
        # Add mode-specific settings
        if mode == 1:  # Self-Consumption Mode
            # Default SOC for Self Consumption is 10%
            mode_data["data"]["reserve_soc"] = 10
            _LOGGER.debug("Setting Self-Consumption Mode with reserve_soc: 10")
            
        elif mode == 2:  # Economy Mode
            # Economy mode needs minimum reserve_soc
            mode_data["data"]["reserve_soc"] = 0
            mode_data["data"]["money_code"] = "$"
            mode_data["data"]["date"] = []
            _LOGGER.debug("Setting Economy Mode with default settings")
            
        elif mode == 3:  # Backup Mode
            # Backup mode typically uses a high reserve SOC (100%)
            mode_data["data"]["reserve_soc"] = 100
            _LOGGER.debug("Setting Backup Mode with reserve_soc: 100")
            
        elif mode == 4:  # Off-Grid Mode
            # Off-Grid mode settings
            mode_data["data"] = {}
            _LOGGER.debug("Setting Off-Grid Mode with default settings")
            
        elif mode == 7:  # Peak Shaving Mode
            # Peak Shaving Mode settings
            mode_data["data"]["reserve_soc"] = 30
            mode_data["data"]["max_soc"] = 70
            mode_data["data"]["meter_power"] = 3000
            _LOGGER.debug("Setting Peak Shaving Mode with reserve_soc: 30, max_soc: 70, meter_power: 3000")
            
        elif mode == 8:  # Time of Use Mode
            # Do NOT send any time schedule – only change the mode
            mode_data["data"]["reserve_soc"] = 10
            _LOGGER.debug("Setting Time of Use Mode WITHOUT time schedule")
        
        # Try to preserve any existing settings for the mode we're switching to
        try:
            current_settings = await self.get_battery_settings(station_id)
            if current_settings and "data" in current_settings:
                # Only preserve settings if we have any
                if "data" in current_settings.get("data", {}):
                    _LOGGER.debug("Trying to preserve existing settings when changing mode")
        except Exception as e:
            _LOGGER.warning("Error checking current settings during mode change: %s", e)
        
        data = {
            "action": 1013,
            "data": {
                "sid": int(station_id),
                "data": mode_data
            },
        }
        
        _LOGGER.debug("Setting battery mode to %s with data: %s", mode, json.dumps(data, indent=2))
        _LOGGER.info("API URL: %s", API_BATTERY_SETTINGS_WRITE_URL)
        _LOGGER.info("Setting battery mode to %s for station ID: %s", BATTERY_MODES.get(mode), station_id)
        
        try:
            async with self._session.post(
                API_BATTERY_SETTINGS_WRITE_URL, headers=headers, json=data
            ) as response:
                resp_text = await response.text()
                _LOGGER.debug("Set battery mode response: %s", resp_text)
                
                try:
                    resp = json.loads(resp_text)
                    
                    if resp.get("status") == "0" and resp.get("message") == "success":
                        request_id = resp.get("data")
                        _LOGGER.info("Successfully set battery mode to %s (%s) (request ID: %s)", 
                                    BATTERY_MODES.get(mode), mode, request_id)
                        return True
                    else:
                        _LOGGER.error(
                            "Failed to set battery mode: %s - %s", 
                            resp.get("status"), 
                            resp.get("message")
                        )
                        return False
                except json.JSONDecodeError as e:
                    _LOGGER.error("Error decoding battery mode response: %s, Raw response: %s", e, resp_text)
                    return False
        except Exception as e:
            _LOGGER.error("Error setting battery mode: %s", e)
            raise

    async def set_reserve_soc(self, station_id: str, reserve_soc: int) -> bool:
        """Set battery reserve SOC for a station."""
        if not 0 <= reserve_soc <= 100:
            _LOGGER.error("Invalid reserve SOC value: %s", reserve_soc)
            return False
            
        if not self._token:
            await self.authenticate()
            
        _LOGGER.debug("=== START SOC UPDATE OPERATION FOR %s%% ===", reserve_soc)
        
        # First get current settings to maintain the mode
        try:
            current_settings = await self.get_battery_settings(station_id)
            _LOGGER.debug("Current battery settings before update: %s", json.dumps(current_settings, indent=2))
            # Default to Self Consumption mode if settings can't be retrieved
            current_mode = BATTERY_MODE_SELF_CONSUMPTION
            
            if current_settings and "data" in current_settings:
                current_mode = current_settings.get("data", {}).get("mode", BATTERY_MODE_SELF_CONSUMPTION)
        except Exception as e:
            _LOGGER.warning("Could not get current battery mode: %s", e)
            # Default to Self Consumption mode
            current_mode = BATTERY_MODE_SELF_CONSUMPTION
            
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": self._token,
        }
        
        # Based on the API capture, we should use the nested structure:
        # {mode:1, data:{reserve_soc:50}}
        mode_data = {
            "mode": current_mode,
            "data": {
                "reserve_soc": reserve_soc
            }
        }
        
        # For Time of Use mode, we need to maintain the time periods
        if current_mode == BATTERY_MODE_TIME_OF_USE:
            try:
                if current_settings and "data" in current_settings:
                    time_periods = current_settings.get("data", {}).get("data", {}).get("time_periods", [])
                    mode_data["data"]["time_periods"] = time_periods
            except Exception:
                # If we can't get time periods, just use an empty list as default
                mode_data["data"]["time_periods"] = []
        
        data = {
            "action": 1013,
            "data": {
                "sid": int(station_id),
                "data": mode_data
            },
        }
        
        _LOGGER.debug("SOC update - Sending request with data: %s", json.dumps(data, indent=2))
        
        try:
            async with self._session.post(
                API_BATTERY_SETTINGS_WRITE_URL, headers=headers, json=data
            ) as response:
                resp_text = await response.text()
                _LOGGER.debug("SOC update - Response: %s", resp_text)
                
                try:
                    resp = json.loads(resp_text)
                    
                    if resp.get("status") == "0" and resp.get("message") == "success":
                        request_id = resp.get("data")
                        _LOGGER.info("Successfully sent battery SOC update to %s%% (request ID: %s)", reserve_soc, request_id)
                        
                        # Wait a moment for settings to be applied
                        await asyncio.sleep(3)
                        
                        # Verify the change
                        try:
                            updated_settings = await self.get_battery_settings(station_id)
                            _LOGGER.debug("Battery settings after update: %s", json.dumps(updated_settings, indent=2))
                        except Exception as e:
                            _LOGGER.warning("Could not verify SOC update: %s", e)
                        
                        _LOGGER.debug("=== END SOC UPDATE OPERATION ===")
                        return True
                    else:
                        _LOGGER.error(
                            "Failed to set reserve SOC: %s - %s", 
                            resp.get("status"), 
                            resp.get("message")
                        )
                        _LOGGER.debug("=== END SOC UPDATE OPERATION ===")
                        return False
                except json.JSONDecodeError as e:
                    _LOGGER.error("Error decoding SOC response: %s, Raw response: %s", e, resp_text)
                    _LOGGER.debug("=== END SOC UPDATE OPERATION ===")
                    return False
        except Exception as e:
            _LOGGER.error("Error setting reserve SOC: %s", e)
            _LOGGER.debug("=== END SOC UPDATE OPERATION ===")
            raise 
