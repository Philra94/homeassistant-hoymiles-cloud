"""API client for Hoymiles Cloud."""
import asyncio
import base64
import logging
import time
import hashlib
import json
from typing import Any, Dict, List, Optional

import aiohttp

from .const import (
    API_AUTH_URL,
    API_AUTH_PRE_INSP_URL,
    API_AUTH_V3_URL,
    API_USER_ME_URL,
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
        self._auth_method: Optional[str] = None
        self._last_auth_status: Optional[str] = None
        self._last_auth_message: Optional[str] = None

    def is_token_expired(self) -> bool:
        """Check if the token is expired."""
        return time.time() >= self._token_expires_at

    @property
    def auth_method(self) -> Optional[str]:
        """Return the last successful authentication method."""
        return self._auth_method

    @property
    def last_auth_status(self) -> Optional[str]:
        """Return the last authentication status code."""
        return self._last_auth_status

    @property
    def last_auth_message(self) -> Optional[str]:
        """Return the last authentication error message."""
        return self._last_auth_message

    def _set_auth_failure(self, status: Optional[str], message: Optional[str]) -> None:
        """Store the most recent authentication failure."""
        self._last_auth_status = str(status) if status is not None else None
        self._last_auth_message = message

    def _set_auth_success(self, method: str, token: Optional[str]) -> None:
        """Persist successful authentication state."""
        self._token = token
        self._token_expires_at = time.time() + self._token_valid_time
        self._auth_method = method
        self._last_auth_status = None
        self._last_auth_message = None

    def _json_headers(self, *, include_accept: bool = True) -> Dict[str, str]:
        """Build JSON request headers."""
        headers = {"Content-Type": "application/json"}
        if include_accept:
            headers["Accept"] = "application/json"
        return headers

    def _auth_headers(self, *, include_accept: bool = True) -> Dict[str, str]:
        """Build authenticated request headers."""
        headers = self._json_headers(include_accept=include_accept)
        if self._token:
            # The API expects the raw token, not a Bearer prefix.
            headers["Authorization"] = self._token
        return headers

    async def _authenticate_argon2(self) -> bool:
        """Authenticate using the modern browser flow (API v3).

        The web app always starts with ``/iam/pub/3/auth/pre-insp`` and then
        selects the hash format based on the returned salt field ``a``:

        - If ``a`` is present, compute an Argon2id hash from the password and
          salt, then submit that hex digest as ``ch``.
        - If ``a`` is ``null``, mimic the browser's fallback and submit
          ``ch = md5(password) + "." + base64(sha256(password))``.

        In both cases, send the returned nonce ``n`` back to
        ``/iam/pub/3/auth/login`` and use the resulting token directly in the
        ``Authorization`` header. To validate or adjust this flow, reproduce a
        real login in the browser network panel or run
        ``python3 scripts/test_login_flow.py`` and compare the request payloads.
        """
        hash_secret_raw = None
        Type = None
        try:
            from argon2.low_level import hash_secret_raw as _hash_secret_raw, Type as _Type

            hash_secret_raw = _hash_secret_raw
            Type = _Type
        except ImportError:
            _LOGGER.debug("argon2-cffi not available, will only use unsalted v3 auth")

        headers = self._json_headers()

        # Step 1: Pre-inspection — get server-provided salt and nonce
        try:
            async with self._session.post(
                API_AUTH_PRE_INSP_URL,
                headers=headers,
                json={"u": self._username},
            ) as response:
                pre_resp = await response.json()
        except Exception as e:
            _LOGGER.debug("Argon2 pre-inspection request failed: %s", e)
            return False

        if pre_resp.get("status") != "0":
            self._set_auth_failure(pre_resp.get("status"), pre_resp.get("message"))
            _LOGGER.debug(
                "Argon2 pre-inspection rejected: %s - %s",
                pre_resp.get("status"),
                pre_resp.get("message"),
            )
            return False

        pre_data = pre_resp.get("data", {})
        salt_b64 = pre_data.get("a")
        nonce = pre_data.get("n")
        if not nonce:
            self._set_auth_failure(None, "Argon2 pre-inspection returned incomplete data")
            _LOGGER.debug("Argon2 pre-inspection returned incomplete data: %s", pre_data)
            return False

        # Step 2: Build the browser-style credential hash for the returned variant.
        try:
            if salt_b64:
                if hash_secret_raw is None or Type is None:
                    self._set_auth_failure(
                        None,
                        "Argon2 support is unavailable for salted v3 authentication",
                    )
                    return False

                salt = base64.b64decode(salt_b64)
                raw_hash = hash_secret_raw(
                    secret=self._password.encode(),
                    salt=salt,
                    time_cost=3,
                    memory_cost=32768,
                    parallelism=1,
                    hash_len=32,
                    type=Type.ID,
                )
                ch = raw_hash.hex()
                auth_method = "argon2_v3"
            else:
                md5_password = hashlib.md5(self._password.encode()).hexdigest()
                sha256_password = hashlib.sha256(self._password.encode()).digest()
                ch = f"{md5_password}.{base64.b64encode(sha256_password).decode()}"
                auth_method = "sha256_v3"
        except Exception as e:
            _LOGGER.debug("Modern v3 hashing failed: %s", e)
            return False

        # Step 3: Login with Argon2 credentials
        try:
            async with self._session.post(
                API_AUTH_V3_URL,
                headers=headers,
                json={"u": self._username, "ch": ch, "n": nonce},
            ) as response:
                resp = await response.json()
        except Exception as e:
            _LOGGER.debug("Argon2 login request failed: %s", e)
            return False

        if resp.get("status") == "0" and resp.get("message") == "success":
            self._set_auth_success(auth_method, resp.get("data", {}).get("token"))
            _LOGGER.debug("Modern v3 authentication succeeded via %s", auth_method)
            return True

        self._set_auth_failure(resp.get("status"), resp.get("message"))
        _LOGGER.debug(
            "Argon2 authentication failed: %s - %s",
            resp.get("status"),
            resp.get("message"),
        )
        return False

    async def _authenticate_legacy(self) -> bool:
        """Authenticate using the legacy MD5 flow (API v0)."""
        headers = self._json_headers()
        md5_password = hashlib.md5(self._password.encode()).hexdigest()
        data = {
            "user_name": self._username,
            "password": md5_password,
        }
        try:
            async with self._session.post(
                API_AUTH_URL, headers=headers, json=data
            ) as response:
                resp = await response.json()
        except Exception as e:
            _LOGGER.debug("Legacy authentication request failed: %s", e)
            return False

        if resp.get("status") == "0" and resp.get("message") == "success":
            self._set_auth_success("legacy_md5_v0", resp.get("data", {}).get("token"))
            _LOGGER.debug("Legacy MD5 authentication succeeded")
            return True

        self._set_auth_failure(resp.get("status"), resp.get("message"))
        _LOGGER.error(
            "Authentication failed: %s - %s",
            resp.get("status"),
            resp.get("message"),
        )
        return False

    async def authenticate(self) -> bool:
        """Authenticate with the Hoymiles API.

        Tries the modern Argon2 v3 endpoint first, then falls back to
        the legacy MD5 v0 endpoint if Argon2 is unavailable or rejected.
        """
        try:
            self._auth_method = None
            self._last_auth_status = None
            self._last_auth_message = None
            if await self._authenticate_argon2():
                return True
            _LOGGER.debug("Argon2 auth failed or unavailable, trying legacy MD5 auth")
            return await self._authenticate_legacy()
        except Exception as e:
            _LOGGER.error("Error during authentication: %s", e)
            raise

    async def get_current_user(self) -> Dict[str, Any]:
        """Return the current authenticated user details."""
        if not self._token or self.is_token_expired():
            _LOGGER.debug("No valid token available, authenticating first")
            await self.authenticate()

        try:
            async with self._session.post(
                API_USER_ME_URL,
                headers=self._auth_headers(),
                json={},
            ) as response:
                resp = await response.json()
        except Exception as e:
            _LOGGER.error("Error getting current user: %s", e)
            raise

        if resp.get("status") == "0" and resp.get("message") == "success":
            return resp.get("data", {})

        _LOGGER.error(
            "Failed to get current user: %s - %s",
            resp.get("status"),
            resp.get("message"),
        )
        return {}

    async def get_stations(self) -> Dict[str, str]:
        """Get all stations for the authenticated user."""
        if not self._token or self.is_token_expired():
            _LOGGER.debug("No token available, authenticating first")
            await self.authenticate()

        data = {
            "page_size": 10,
            "page_num": 1,
        }
        
        try:
            _LOGGER.debug("Sending request to get stations with token: %s...", self._token[:20] if self._token else "None")
            async with self._session.post(
                API_STATIONS_URL, headers=self._auth_headers(), json=data
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
        if not self._token or self.is_token_expired():
            _LOGGER.debug("No token available, authenticating first")
            await self.authenticate()

        data = {
            "sid": int(station_id),
            "page_size": 1000,
            "page_num": 1,
            "show_warn": 0
        }
        
        try:
            _LOGGER.debug("Sending request to get microinverters with token: %s...", self._token[:20] if self._token else "None")
            async with self._session.post(
                API_MICROINVERTERS_URL, headers=self._auth_headers(), json=data
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
                                API_MICRO_DETAIL_URL, headers=self._auth_headers(), json=data
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
        if not self._token or self.is_token_expired():
            await self.authenticate()

        data = {
            "sid": int(station_id),
        }
        
        try:
            async with self._session.post(
                API_REAL_TIME_DATA_URL, headers=self._auth_headers(), json=data
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
        if not self._token or self.is_token_expired():
            await self.authenticate()

        data = {
            "sid": int(station_id),
            "type": 4  # PV indicators type
        }
        
        try:
            async with self._session.post(
                API_PV_INDICATORS_URL, headers=self._auth_headers(), json=data
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

        # The request needs to be specifically id as a string
        status_data = {
            "id": station_id
        }
        
        _LOGGER.debug("Requesting battery settings for station %s with data: %s", station_id, json.dumps(status_data))
        
        # First, check the status of settings to see if they're available
        try:
            status_response = await self._session.post(
                API_BATTERY_SETTINGS_STATUS_URL,
                headers=self._auth_headers(include_accept=False),
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
            
        if not self._token or self.is_token_expired():
            await self.authenticate()
        
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
                API_BATTERY_SETTINGS_WRITE_URL, headers=self._auth_headers(), json=data
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
            
        if not self._token or self.is_token_expired():
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
                API_BATTERY_SETTINGS_WRITE_URL, headers=self._auth_headers(), json=data
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
