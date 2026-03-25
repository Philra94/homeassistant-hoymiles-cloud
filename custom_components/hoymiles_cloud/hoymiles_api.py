"""API client for Hoymiles Cloud."""
import asyncio
import base64
import binascii
from copy import deepcopy
import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

import aiohttp

from .auth import AuthAttempt, choose_preferred_failure, summarize_auth_attempts
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
    BATTERY_MODE_ECONOMY,
    BATTERY_MODE_IDS,
    BATTERY_MODE_SELF_CONSUMPTION,
    BATTERY_MODE_TIME_OF_USE,
    BATTERY_MODE_BACKUP,
    BATTERY_MODES,
    AUTH_MODE_AUTO,
    AUTH_MODE_HOME_V3,
    AUTH_MODE_INSTALLER_V3,
    AUTH_MODE_LEGACY_V0,
    AUTH_MODE_WEB_V3,
    AUTH_MODE_TO_PROFILE,
    AUTH_PROFILE_DEFAULTS,
    CLIENT_PROFILE_HOME,
    CLIENT_PROFILE_INSTALLER,
    CLIENT_PROFILE_WEB,
)
from .data import (
    MODE_KEY_MAPPING,
    battery_settings_readable,
    build_empty_battery_settings,
    get_mode_settings,
)

_LOGGER = logging.getLogger(__name__)


DEFAULT_MODE_SETTINGS: dict[int, dict[str, Any]] = {
    BATTERY_MODE_SELF_CONSUMPTION: {"reserve_soc": 10},
    BATTERY_MODE_ECONOMY: {"reserve_soc": 10, "money_code": "$", "date": []},
    BATTERY_MODE_BACKUP: {"reserve_soc": 100},
    4: {},
    7: {"reserve_soc": 30, "max_soc": 70, "meter_power": 3000},
    BATTERY_MODE_TIME_OF_USE: {"reserve_soc": 10},
}

BATTERY_SETTINGS_ACTION_ID = 1013
BATTERY_SETTINGS_STATUS_RUNNING = 2
BATTERY_SETTINGS_STATUS_SUCCESS = 0
BATTERY_SETTINGS_MAX_POLLS = 10
BATTERY_SETTINGS_POLL_INTERVAL = 1.0


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
        self._last_auth_error_key: Optional[str] = None
        self._last_auth_attempt: Optional[str] = None
        self._last_auth_attempts: list[AuthAttempt] = []
        self._auth_mode_preference = AUTH_MODE_AUTO
        self._app_version_override: str | None = None
        self._active_client_profile = CLIENT_PROFILE_WEB
        self._active_app_version: str | None = None

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

    @property
    def last_auth_error_key(self) -> Optional[str]:
        """Return the normalized last authentication error key."""
        return self._last_auth_error_key

    @property
    def last_auth_attempt(self) -> Optional[str]:
        """Return the last attempted authentication strategy."""
        return self._last_auth_attempt

    @property
    def last_auth_attempts(self) -> list[AuthAttempt]:
        """Return all attempts from the most recent auth run."""
        return list(self._last_auth_attempts)

    @property
    def last_auth_attempt_summary(self) -> str:
        """Return a compact summary of the most recent auth run."""
        return summarize_auth_attempts(self._last_auth_attempts)

    def configure_auth(
        self,
        *,
        auth_mode: str = AUTH_MODE_AUTO,
        app_version: str | None = None,
    ) -> None:
        """Persist auth preferences for future login attempts."""
        self._auth_mode_preference = auth_mode
        self._app_version_override = app_version.strip() if app_version else None

    def _set_auth_failure(self, status: Optional[str], message: Optional[str]) -> None:
        """Store the most recent authentication failure."""
        self._last_auth_status = str(status) if status is not None else None
        self._last_auth_message = message

    def _set_auth_success(self, method: str, token: Optional[str]) -> None:
        """Persist successful authentication state."""
        self._token = token
        self._token_expires_at = time.time() + self._token_valid_time
        self._auth_method = method
        self._last_auth_attempt = method
        self._last_auth_status = None
        self._last_auth_message = None
        self._last_auth_error_key = None

    def _resolve_app_version(
        self,
        client_profile: str,
        app_version: str | None = None,
    ) -> str | None:
        """Return the effective app version for a client profile."""
        if app_version:
            return app_version
        if self._app_version_override and client_profile != CLIENT_PROFILE_WEB:
            return self._app_version_override
        return AUTH_PROFILE_DEFAULTS[client_profile]["app_version"]

    def _get_auth_mode_for_profile(self, client_profile: str) -> str:
        """Return the auth mode constant for a client profile."""
        for auth_mode, profile in AUTH_MODE_TO_PROFILE.items():
            if profile == client_profile:
                return auth_mode
        raise ValueError(f"Unsupported auth profile: {client_profile}")

    def _json_headers(
        self,
        *,
        include_accept: bool = True,
        client_profile: str = CLIENT_PROFILE_WEB,
        app_version: str | None = None,
    ) -> Dict[str, str]:
        """Build JSON request headers."""
        headers = {"Content-Type": "application/json"}
        if include_accept:
            headers["Accept"] = "application/json"
        profile_defaults = AUTH_PROFILE_DEFAULTS[client_profile]
        version = self._resolve_app_version(client_profile, app_version=app_version)
        user_agent = profile_defaults["user_agent"]
        if version:
            headers["User-Agent"] = f"{user_agent}/{version}"
            headers["App-Version"] = version
            headers["X-App-Version"] = version
            if profile_defaults["x_client_type"]:
                headers["X-Client-Type"] = profile_defaults["x_client_type"]
        else:
            headers["User-Agent"] = user_agent
        return headers

    def _auth_headers(self, *, include_accept: bool = True) -> Dict[str, str]:
        """Build authenticated request headers."""
        headers = self._json_headers(
            include_accept=include_accept,
            client_profile=self._active_client_profile,
            app_version=self._active_app_version,
        )
        if self._token:
            # The API expects the raw token, not a Bearer prefix.
            headers["Authorization"] = self._token
        return headers

    def _record_auth_failure(self, attempt: AuthAttempt) -> AuthAttempt:
        """Persist a failed auth attempt."""
        self._last_auth_attempt = attempt.method
        self._last_auth_status = attempt.status
        self._last_auth_message = attempt.message
        self._last_auth_error_key = attempt.error_key
        return attempt

    def _record_auth_success(self, attempt: AuthAttempt) -> bool:
        """Persist a successful auth attempt."""
        method = attempt.method if not attempt.variant else f"{attempt.method}:{attempt.variant}"
        self._set_auth_success(method, attempt.token)
        self._last_auth_attempt = attempt.method
        self._active_client_profile = attempt.client_profile
        self._active_app_version = attempt.app_version
        return True

    def _build_auth_attempts(self, auth_mode: str) -> list[tuple[str, str]]:
        """Return the sequence of auth modes and client profiles to try."""
        if auth_mode == AUTH_MODE_LEGACY_V0:
            return [(AUTH_MODE_LEGACY_V0, CLIENT_PROFILE_WEB)]
        if auth_mode in AUTH_MODE_TO_PROFILE:
            return [(auth_mode, AUTH_MODE_TO_PROFILE[auth_mode])]
        return [
            (AUTH_MODE_WEB_V3, CLIENT_PROFILE_WEB),
            (AUTH_MODE_INSTALLER_V3, CLIENT_PROFILE_INSTALLER),
            (AUTH_MODE_HOME_V3, CLIENT_PROFILE_HOME),
            (AUTH_MODE_LEGACY_V0, CLIENT_PROFILE_WEB),
        ]

    def _parse_pre_insp_response(
        self,
        payload: dict[str, Any],
    ) -> tuple[str | None, str | None, dict[str, Any]]:
        """Normalize pre-inspection responses across observed response shapes."""
        if "status" in payload or "data" in payload:
            status = str(payload.get("status")) if payload.get("status") is not None else None
            message = payload.get("message")
            data = payload.get("data")
            return status, message, data if isinstance(data, dict) else {}

        # Some browser captures appear to return the pre-inspection payload at the top level.
        if any(key in payload for key in ("a", "n", "u")):
            return "0", "success", payload

        return None, payload.get("message"), {}

    def _should_retry_unsalted_variant(self, status: str | None, message: str | None) -> bool:
        """Return whether an unsalted login failure looks hash-variant specific."""
        text = (message or "").lower()
        retry_markers = (
            "invalid credentials",
            "log in failed",
            "check your account and password",
        )
        return any(marker in text for marker in retry_markers) or status == "7"

    def _build_unsalted_v3_candidates(self) -> list[tuple[str, str]]:
        """Return the observed no-salt credential hash variants to try."""
        md5_password = hashlib.md5(self._password.encode()).hexdigest()
        sha256_password = hashlib.sha256(self._password.encode())
        return [
            (
                "sha256_v3",
                f"{md5_password}.{base64.b64encode(sha256_password.digest()).decode()}",
            ),
            (
                "sha256_hex_v3",
                sha256_password.hexdigest(),
            ),
        ]

    def _decode_v3_salt(self, salt_value: str) -> bytes:
        """Decode a v3 salt value from the observed browser/API formats."""
        normalized = salt_value.strip()
        try:
            # Browser captures showed a plain hex string for salted web logins.
            if len(normalized) % 2 == 0:
                return bytes.fromhex(normalized)
        except ValueError:
            pass

        try:
            return base64.b64decode(normalized, validate=True)
        except (binascii.Error, ValueError):
            return normalized.encode()

    async def _pre_inspect_v3(
        self,
        *,
        client_profile: str,
        method_name: str,
        headers: dict[str, str],
        app_version: str | None,
    ) -> AuthAttempt | tuple[dict[str, Any], str | None]:
        """Run v3 pre-inspection and return normalized data or a failed attempt."""
        try:
            async with self._session.post(
                API_AUTH_PRE_INSP_URL,
                headers=headers,
                json={"u": self._username},
            ) as response:
                pre_resp = await response.json()
        except Exception as e:
            _LOGGER.debug("Argon2 pre-inspection request failed: %s", e)
            return self._record_auth_failure(
                AuthAttempt(
                    method=method_name,
                    client_profile=client_profile,
                    success=False,
                    message=str(e),
                    app_version=app_version,
                )
            )

        status, message, pre_data = self._parse_pre_insp_response(pre_resp)
        if status not in (None, "0"):
            return self._record_auth_failure(
                AuthAttempt(
                    method=method_name,
                    client_profile=client_profile,
                    success=False,
                    status=status,
                    message=message,
                    app_version=app_version,
                )
            )

        nonce = pre_data.get("n")
        if not nonce:
            _LOGGER.debug(
                "Hoymiles pre-insp returned keys %s for %s",
                sorted(pre_data.keys()),
                method_name,
            )
            return self._record_auth_failure(
                AuthAttempt(
                    method=method_name,
                    client_profile=client_profile,
                    success=False,
                    message=(
                        "Argon2 pre-inspection returned incomplete data "
                        f"(keys: {sorted(pre_data.keys())})"
                    ),
                    app_version=app_version,
                )
            )

        return pre_data, nonce

    async def _login_v3_candidate(
        self,
        *,
        client_profile: str,
        method_name: str,
        headers: dict[str, str],
        app_version: str | None,
        credential_hash: str,
        nonce: str,
        variant_name: str,
    ) -> AuthAttempt:
        """Attempt a single v3 login candidate."""
        try:
            async with self._session.post(
                API_AUTH_V3_URL,
                headers=headers,
                json={"u": self._username, "ch": credential_hash, "n": nonce},
            ) as response:
                resp = await response.json()
        except Exception as e:
            _LOGGER.debug("Argon2 login request failed: %s", e)
            return self._record_auth_failure(
                AuthAttempt(
                    method=method_name,
                    client_profile=client_profile,
                    success=False,
                    message=str(e),
                    app_version=app_version,
                    variant=variant_name,
                )
            )

        if resp.get("status") == "0" and resp.get("message") == "success":
            return AuthAttempt(
                method=method_name,
                client_profile=client_profile,
                success=True,
                token=resp.get("data", {}).get("token"),
                app_version=app_version,
                variant=variant_name,
            )

        return self._record_auth_failure(
            AuthAttempt(
                method=method_name,
                client_profile=client_profile,
                success=False,
                status=str(resp.get("status")) if resp.get("status") is not None else None,
                message=resp.get("message"),
                app_version=app_version,
                variant=variant_name,
            )
        )

    async def _authenticate_v3(self, *, client_profile: str) -> AuthAttempt:
        """Authenticate using the modern browser flow (API v3).

        The web app always starts with ``/iam/pub/3/auth/pre-insp`` and then
        selects the hash format based on the returned salt field ``a``:

        - If ``a`` is present, compute an Argon2id hash from the password and
          salt, then submit that hex digest as ``ch``.
        - If ``a`` is ``null``, try the observed browser no-salt variants in
          sequence, including the dotted ``md5(password) + "." +
          base64(sha256(password))`` form and a plain ``sha256(password)``
          hex digest.

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

        method_name = self._get_auth_mode_for_profile(client_profile)
        app_version = self._resolve_app_version(client_profile)
        headers = self._json_headers(client_profile=client_profile, app_version=app_version)

        # Step 1: Pre-inspection — get server-provided salt and nonce
        pre_insp_result = await self._pre_inspect_v3(
            client_profile=client_profile,
            method_name=method_name,
            headers=headers,
            app_version=app_version,
        )
        if isinstance(pre_insp_result, AuthAttempt):
            return pre_insp_result

        pre_data, nonce = pre_insp_result
        salt_b64 = pre_data.get("a")

        # Step 2: Build the browser-style credential hash for the returned variant.
        try:
            if salt_b64:
                if hash_secret_raw is None or Type is None:
                    return self._record_auth_failure(
                        AuthAttempt(
                            method=method_name,
                            client_profile=client_profile,
                            success=False,
                            message="Argon2 support is unavailable for salted v3 authentication",
                            app_version=app_version,
                        )
                    )

                salt = self._decode_v3_salt(salt_b64)
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
                unsalted_candidates = self._build_unsalted_v3_candidates()
        except Exception as e:
            _LOGGER.debug("Modern v3 hashing failed: %s", e)
            return self._record_auth_failure(
                AuthAttempt(
                    method=method_name,
                    client_profile=client_profile,
                    success=False,
                    message=str(e),
                    app_version=app_version,
                )
            )

        # Step 3: Login with the derived credentials.
        if salt_b64:
            return await self._login_v3_candidate(
                client_profile=client_profile,
                method_name=method_name,
                headers=headers,
                app_version=app_version,
                credential_hash=ch,
                nonce=nonce,
                variant_name=auth_method,
            )

        last_failure: AuthAttempt | None = None
        for index, (variant_name, candidate_hash) in enumerate(unsalted_candidates):
            if index > 0:
                retry_pre_insp_result = await self._pre_inspect_v3(
                    client_profile=client_profile,
                    method_name=method_name,
                    headers=headers,
                    app_version=app_version,
                )
                if isinstance(retry_pre_insp_result, AuthAttempt):
                    return retry_pre_insp_result
                _, nonce = retry_pre_insp_result

            attempt = await self._login_v3_candidate(
                client_profile=client_profile,
                method_name=method_name,
                headers=headers,
                app_version=app_version,
                credential_hash=candidate_hash,
                nonce=nonce,
                variant_name=variant_name,
            )
            if attempt.success:
                return attempt
            last_failure = attempt
            if not self._should_retry_unsalted_variant(attempt.status, attempt.message):
                return attempt

        return last_failure or self._record_auth_failure(
            AuthAttempt(
                method=method_name,
                client_profile=client_profile,
                success=False,
                message="No unsalted v3 auth candidates were available",
                app_version=app_version,
            )
        )

    async def _authenticate_legacy(self) -> AuthAttempt:
        """Authenticate using the legacy MD5 flow (API v0)."""
        headers = self._json_headers(client_profile=CLIENT_PROFILE_WEB)
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
            return self._record_auth_failure(
                AuthAttempt(
                    method=AUTH_MODE_LEGACY_V0,
                    client_profile=CLIENT_PROFILE_WEB,
                    success=False,
                    message=str(e),
                )
            )

        if resp.get("status") == "0" and resp.get("message") == "success":
            return AuthAttempt(
                method=AUTH_MODE_LEGACY_V0,
                client_profile=CLIENT_PROFILE_WEB,
                success=True,
                token=resp.get("data", {}).get("token"),
            )

        return self._record_auth_failure(
            AuthAttempt(
                method=AUTH_MODE_LEGACY_V0,
                client_profile=CLIENT_PROFILE_WEB,
                success=False,
                status=str(resp.get("status")) if resp.get("status") is not None else None,
                message=resp.get("message"),
            )
        )

    async def authenticate(self, auth_mode: str | None = None) -> bool:
        """Authenticate with the Hoymiles API.

        Tries supported auth strategies while preserving the most informative
        failure if all strategies fail.
        """
        try:
            selected_auth_mode = auth_mode or self._auth_mode_preference
            self._auth_method = None
            self._last_auth_status = None
            self._last_auth_message = None
            self._last_auth_error_key = None
            self._last_auth_attempt = None
            self._last_auth_attempts = []
            self._active_client_profile = CLIENT_PROFILE_WEB
            self._active_app_version = None

            attempts: list[AuthAttempt] = []
            for attempt_mode, client_profile in self._build_auth_attempts(selected_auth_mode):
                if attempt_mode == AUTH_MODE_LEGACY_V0:
                    attempts.append(await self._authenticate_legacy())
                else:
                    attempts.append(await self._authenticate_v3(client_profile=client_profile))

            self._last_auth_attempts = attempts
            for attempt in attempts:
                if attempt.success:
                    return self._record_auth_success(attempt)

            preferred_failure = choose_preferred_failure(attempts)
            if preferred_failure is not None:
                self._record_auth_failure(preferred_failure)
            _LOGGER.warning("Hoymiles auth failed after attempts: %s", self.last_auth_attempt_summary)
            return False
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

        stations: Dict[str, str] = {}
        page_num = 1
        page_size = 100
        total = None

        try:
            while True:
                data = {
                    "page_size": page_size,
                    "page_num": page_num,
                }
                async with self._session.post(
                    API_STATIONS_URL, headers=self._auth_headers(), json=data
                ) as response:
                    resp_text = await response.text()
                    _LOGGER.debug("Stations response page %s: %s", page_num, resp_text)
                    resp = json.loads(resp_text)

                if resp.get("status") != "0" or resp.get("message") != "success":
                    _LOGGER.error(
                        "Failed to get stations: %s - %s",
                        resp.get("status"),
                        resp.get("message"),
                    )
                    return {}

                payload = resp.get("data", {})
                stations_data = payload.get("list", [])
                total = payload.get("total", total)

                if not stations_data and page_num == 1:
                    _LOGGER.warning("API returned success but stations list is empty")

                for station in stations_data:
                    station_id = str(station.get("id"))
                    station_name = station.get("name") or f"Station {station_id}"
                    stations[station_id] = station_name

                if not stations_data:
                    break

                if total is not None:
                    if len(stations) >= int(total):
                        break
                elif len(stations_data) < page_size:
                    break

                page_num += 1

            _LOGGER.debug("Returning stations dictionary: %s", stations)
            return stations
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
        try:
            response = await self._submit_battery_settings_command(
                API_BATTERY_SETTINGS_READ_URL,
                {
                    "action": BATTERY_SETTINGS_ACTION_ID,
                    "data": {"sid": int(station_id)},
                },
                log_label=f"battery settings read for station {station_id}",
            )
            final_response = await self._resolve_battery_settings_command(
                response,
                expect_result=True,
                command_label=f"battery settings read for station {station_id}",
            )
        except json.JSONDecodeError as err:
            _LOGGER.warning("Error decoding battery settings JSON: %s", err)
            return build_empty_battery_settings(message="Invalid battery settings response")
        except Exception as err:
            _LOGGER.warning("Error checking battery settings status: %s", err)
            return build_empty_battery_settings(message="Unable to read battery settings")

        return self._parse_battery_settings_response(final_response)

    def _default_mode_settings(self, mode: int) -> dict[str, Any]:
        """Return default settings for a battery mode."""
        return deepcopy(DEFAULT_MODE_SETTINGS.get(mode, {}))

    async def _submit_battery_settings_command(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        log_label: str,
    ) -> dict[str, Any]:
        """Submit a battery settings command and return the raw response."""
        async with self._session.post(
            url,
            headers=self._auth_headers(),
            json=payload,
        ) as response:
            resp_text = await response.text()

        _LOGGER.debug("%s response: %s", log_label, resp_text)
        return json.loads(resp_text)

    async def _poll_battery_settings_status(
        self,
        command_id: str,
        *,
        command_label: str,
    ) -> dict[str, Any]:
        """Poll the battery settings status endpoint until completion."""
        for attempt in range(BATTERY_SETTINGS_MAX_POLLS):
            response = await self._submit_battery_settings_command(
                API_BATTERY_SETTINGS_STATUS_URL,
                {"id": str(command_id)},
                log_label=f"{command_label} status poll {attempt + 1}",
            )
            if response.get("status") != "0" or response.get("message") != "success":
                return response

            status_data = response.get("data", {})
            if not isinstance(status_data, dict):
                return response

            if status_data.get("code") != BATTERY_SETTINGS_STATUS_RUNNING:
                return response

            await asyncio.sleep(BATTERY_SETTINGS_POLL_INTERVAL)

        return {
            "status": "timeout",
            "message": f"Timed out waiting for {command_label}",
            "data": {"code": BATTERY_SETTINGS_STATUS_RUNNING},
        }

    async def _resolve_battery_settings_command(
        self,
        response: dict[str, Any],
        *,
        expect_result: bool,
        command_label: str,
    ) -> dict[str, Any]:
        """Resolve a battery settings command that may return a job id."""
        if response.get("status") != "0" or response.get("message") != "success":
            return response

        data = response.get("data")
        if isinstance(data, (str, int)):
            return await self._poll_battery_settings_status(
                str(data),
                command_label=command_label,
            )

        if expect_result and isinstance(data, dict) and isinstance(data.get("data"), dict):
            return response

        return response

    def _parse_battery_settings_response(self, response: dict[str, Any]) -> dict[str, Any]:
        """Normalize a completed battery settings response."""
        if response.get("status") != "0" or response.get("message") != "success":
            return build_empty_battery_settings(
                status=str(response.get("status")),
                message=str(response.get("message")),
            )

        response_data = response.get("data", {})
        if not isinstance(response_data, dict):
            return build_empty_battery_settings(message="Missing battery settings data")

        status_code = response_data.get("code")
        if status_code not in (None, BATTERY_SETTINGS_STATUS_SUCCESS):
            return build_empty_battery_settings(
                message=response_data.get("message") or "Battery settings are still pending",
            )

        settings_payload = response_data.get("data")
        if not isinstance(settings_payload, dict):
            return build_empty_battery_settings(message="Missing battery settings payload")

        mode_data = settings_payload.get("data", {})
        if not isinstance(mode_data, dict):
            return build_empty_battery_settings(message="Invalid battery settings payload")

        current_mode = settings_payload.get("mode", BATTERY_MODE_SELF_CONSUMPTION)
        current_mode_key = MODE_KEY_MAPPING.get(current_mode)

        result = build_empty_battery_settings(readable=True, writable=True)
        result["data"] = {"mode": current_mode}
        result["mode_data"] = deepcopy(mode_data)
        result["available_modes"] = []

        if current_mode_key and current_mode_key in mode_data:
            result["data"]["reserve_soc"] = mode_data[current_mode_key].get("reserve_soc")

        for mode_id, k_mode in MODE_KEY_MAPPING.items():
            if k_mode in mode_data:
                result["available_modes"].append(mode_id)
                result["mode_settings"][mode_id] = deepcopy(mode_data[k_mode])

        _LOGGER.debug("Parsed battery settings: %s", json.dumps(result, indent=2))
        return result

    def _merge_mode_settings(
        self,
        base_settings: dict[str, Any],
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Recursively merge user updates into an existing mode payload."""
        merged = deepcopy(base_settings)
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._merge_mode_settings(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged

    async def _write_battery_mode_payload(
        self, station_id: str, mode: int, mode_settings: dict[str, Any]
    ) -> bool:
        """Write a full mode payload to the battery settings endpoint."""
        if not self._token or self.is_token_expired():
            await self.authenticate()

        payload_data: dict[str, Any] = {"mode": mode}
        if mode_settings:
            payload_data["data"] = mode_settings

        data = {
            "action": BATTERY_SETTINGS_ACTION_ID,
            "data": {
                "sid": int(station_id),
                "data": payload_data,
            },
        }

        _LOGGER.debug(
            "Writing battery mode payload for mode %s: %s",
            mode,
            json.dumps(data, indent=2),
        )

        try:
            response = await self._submit_battery_settings_command(
                API_BATTERY_SETTINGS_WRITE_URL,
                data,
                log_label=f"battery settings write for station {station_id} mode {mode}",
            )
            resp = await self._resolve_battery_settings_command(
                response,
                expect_result=False,
                command_label=f"battery settings write for station {station_id} mode {mode}",
            )
        except json.JSONDecodeError as err:
            _LOGGER.error("Error decoding battery settings response: %s", err)
            return False
        except Exception as err:
            _LOGGER.error("Error writing battery settings: %s", err)
            raise

        if resp.get("status") == "0" and resp.get("message") == "success":
            status_data = resp.get("data", {})
            if isinstance(status_data, dict) and status_data.get("code") not in (
                None,
                BATTERY_SETTINGS_STATUS_SUCCESS,
            ):
                _LOGGER.error(
                    "Battery settings write did not complete successfully: %s",
                    json.dumps(resp),
                )
                return False
            _LOGGER.info(
                "Successfully updated battery settings for mode %s on station %s",
                mode,
                station_id,
            )
            return True

        _LOGGER.error(
            "Failed to write battery settings: %s - %s",
            resp.get("status"),
            resp.get("message"),
        )
        return False

    async def _get_writable_mode_settings(
        self, station_id: str, mode: int
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Return current settings and a writable payload for a mode."""
        current_settings = await self.get_battery_settings(station_id)
        if not battery_settings_readable(current_settings):
            _LOGGER.warning(
                "Battery settings are not readable for station %s; writes are disabled",
                station_id,
            )
            return None, {}

        mode_settings = get_mode_settings(current_settings, mode) or self._default_mode_settings(mode)

        if mode == BATTERY_MODE_ECONOMY:
            mode_settings.setdefault("money_code", "$")
            mode_settings.setdefault("date", [])

        return current_settings, mode_settings

    async def set_battery_mode_settings(
        self,
        station_id: str,
        mode: int,
        settings: dict[str, Any],
        *,
        merge: bool = True,
    ) -> bool:
        """Update the payload for a battery mode and activate that mode."""
        if mode not in BATTERY_MODE_IDS:
            _LOGGER.error("Invalid battery mode: %s", mode)
            return False
        if not isinstance(settings, dict):
            _LOGGER.error("Battery mode settings must be a dictionary")
            return False

        _, current_mode_settings = await self._get_writable_mode_settings(station_id, mode)
        if not current_mode_settings and not settings and mode not in DEFAULT_MODE_SETTINGS:
            return False

        mode_settings = (
            self._merge_mode_settings(current_mode_settings, settings)
            if merge
            else deepcopy(settings)
        )

        if mode == BATTERY_MODE_ECONOMY:
            mode_settings.setdefault("money_code", "$")
            mode_settings.setdefault("date", [])

        return await self._write_battery_mode_payload(station_id, mode, mode_settings)

    async def set_battery_mode(self, station_id: str, mode: int) -> bool:
        """Set battery mode for a station."""
        if mode not in BATTERY_MODE_IDS:
            _LOGGER.error("Invalid battery mode: %s", mode)
            return False

        _, mode_settings = await self._get_writable_mode_settings(station_id, mode)
        if not mode_settings and mode not in DEFAULT_MODE_SETTINGS:
            return False

        _LOGGER.info(
            "Setting battery mode to %s for station ID: %s",
            BATTERY_MODES.get(mode),
            station_id,
        )
        return await self._write_battery_mode_payload(station_id, mode, mode_settings)

    async def set_reserve_soc(self, station_id: str, reserve_soc: int) -> bool:
        """Set battery reserve SOC for a station."""
        if not 0 <= reserve_soc <= 100:
            _LOGGER.error("Invalid reserve SOC value: %s", reserve_soc)
            return False

        current_settings = await self.get_battery_settings(station_id)
        if not battery_settings_readable(current_settings):
            _LOGGER.warning(
                "Skipping reserve SOC update because settings are unavailable for station %s",
                station_id,
            )
            return False

        current_mode = current_settings.get("data", {}).get(
            "mode", BATTERY_MODE_SELF_CONSUMPTION
        )
        return await self.set_battery_mode_settings(
            station_id,
            current_mode,
            {"reserve_soc": reserve_soc},
        )

    async def set_peak_shaving_settings(
        self,
        station_id: str,
        *,
        reserve_soc: int | None = None,
        max_soc: int | None = None,
        meter_power: int | None = None,
    ) -> bool:
        """Set Peak Shaving mode settings for a station."""
        updates: dict[str, Any] = {}
        if reserve_soc is not None:
            updates["reserve_soc"] = reserve_soc
        if max_soc is not None:
            updates["max_soc"] = max_soc
        if meter_power is not None:
            updates["meter_power"] = meter_power

        return await self.set_battery_mode_settings(
            station_id,
            7,
            updates,
        )
