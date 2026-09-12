"""Diagnostics support for Hoymiles Cloud."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

try:
    from homeassistant.components.diagnostics import async_redact_data
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
except ImportError:  # pragma: no cover - enables pure unit tests without Home Assistant
    ConfigEntry = Any  # type: ignore[misc,assignment]
    HomeAssistant = Any  # type: ignore[misc,assignment]

    def async_redact_data(data: dict[str, Any], redact_keys: set[str]) -> dict[str, Any]:
        """Minimal fallback redactor for unit-test environments."""
        def _redact(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: ("**REDACTED**" if key in redact_keys else _redact(item))
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [_redact(item) for item in value]
            return value

        return _redact(data)

from .const import CONF_APP_VERSION, CONF_AUTH_MODE, DOMAIN
from .data import (
    get_allowed_battery_modes,
    get_backend_modes,
    get_supported_modes,
)

REDACT_KEYS = {
    "address",
    "addr",
    "authorization",
    "ch",
    "email",
    "lat",
    "latitude",
    "lng",
    "longitude",
    "password",
    "sn",
    "token",
    "u",
    "user_name",
    "username",
    "title",
    "url",
    "uri",
    "signed_url",
    "sd_uri",
    "entry_id",
    "station_id",
    "station_name",
    # Device and telemetry payloads carry serials/account identifiers under
    # several spellings. They are redacted so the newly added inventory and
    # indicator payloads stay safe to paste into an issue.
    "dtu_sn",
    "micro_sn",
    "device_sn",
    "mi_sn",
    "phone",
    "mobile",
    "user_id",
    "uid",
}

# Any key ending in one of these is redacted as well, so an unknown field in a
# telemetry payload cannot leak a serial or an address.
REDACT_KEY_SUFFIXES = (
    "_sn",
    "_addr",
    "_address",
    "_email",
    "_phone",
    "_mobile",
    "_lat",
    "_lng",
    "_latitude",
    "_longitude",
    "_url",
    "_uri",
)


def _is_sensitive_key(key: Any) -> bool:
    """Return whether a payload key must be redacted."""
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    if lowered in REDACT_KEYS:
        return True
    return lowered.endswith(REDACT_KEY_SUFFIXES)


def _redact_sensitive_keys(value: Any) -> Any:
    """Recursively redact sensitive keys, including suffix matches."""
    if isinstance(value, dict):
        return {
            key: ("**REDACTED**" if _is_sensitive_key(key) else _redact_sensitive_keys(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_keys(item) for item in value]
    return value


def _redact_schedule_shapes(value: Any) -> Any:
    """Redact bulky schedule arrays while leaving the shape understandable."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"date", "time", "date_windows", "periods", "draft_payload", "live_payload"}:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_schedule_shapes(item)
        return redacted
    if isinstance(value, list):
        return [_redact_schedule_shapes(item) for item in value]
    return value


def _station_summary(station_data: dict[str, Any]) -> dict[str, Any]:
    """Return a concise station diagnostics summary."""
    devices = station_data.get("devices", {})
    return {
        "station_info": {
            key: ("**REDACTED**" if key == "name" else value)
            for key, value in (station_data.get("station_info") or {}).items()
        },
        "device_inventory": {
            "dtus": devices.get("dtus", []),
            "inverters": devices.get("inverters", []),
            "batteries": devices.get("batteries", []),
            "meters": devices.get("meters", []),
            # HMS/HMT microinverters never appear under "inverters" (that
            # endpoint serves string/hybrid inverters), so omitting this key
            # made "no devices" reports impossible to tell apart from a
            # correctly discovered microinverter-only station - see issue #41.
            "microinverters": devices.get("microinverters", {}),
        },
        "device_counts": {
            "dtus": len(devices.get("dtus", []) or []),
            "inverters": len(devices.get("inverters", []) or []),
            "batteries": len(devices.get("batteries", []) or []),
            "meters": len(devices.get("meters", []) or []),
            "microinverters": len(devices.get("microinverters", {}) or {}),
        },
        # Raw telemetry feeds. These are the payloads that decide which PV,
        # grid and load entities exist, so a "missing entities" report cannot
        # be diagnosed without them.
        "real_time_data": station_data.get("real_time_data", {}),
        "live_data": station_data.get("live_data", {}),
        "pv_indicators": station_data.get("pv_indicators", {}),
        "grid_indicators": station_data.get("grid_indicators", {}),
        "load_indicators": station_data.get("load_indicators", {}),
        "energy_flow": station_data.get("energy_flow", {}),
        "setting_rules": station_data.get("setting_rules", {}),
        "battery_mode_gating": {
            "backend_modes": get_backend_modes(station_data.get("battery_settings")),
            "supported_modes": get_supported_modes(station_data.get("battery_settings")),
            "allowed_modes": get_allowed_battery_modes(
                station_data.get("battery_settings"),
                station_data.get("setting_rules"),
            ),
        },
        "capabilities": station_data.get("capabilities", {}),
        "battery_settings": _redact_schedule_shapes(station_data.get("battery_settings", {})),
        "relay_settings": _redact_schedule_shapes(station_data.get("relay_settings", {})),
        "eps_settings": station_data.get("eps_settings", {}),
        "eps_profit": station_data.get("eps_profit", {}),
        "ai_status": station_data.get("ai_status", {}),
        "firmware": station_data.get("firmware", {}),
        "schedule_editor": _redact_schedule_shapes(station_data.get("schedule_editor", {})),
        "data_shape": sorted(station_data.keys()),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for one Hoymiles config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime["coordinator"]
    api = runtime["api"]
    coordinator_data = coordinator.data or {}

    payload = {
        "config_entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "auth_mode": entry.data.get(CONF_AUTH_MODE),
            "app_version": entry.data.get(CONF_APP_VERSION),
            "options": dict(entry.options),
        },
        "auth": {
            "selected_mode": entry.data.get(CONF_AUTH_MODE),
            "auth_method": api.auth_method,
            "last_auth_attempt": api.last_auth_attempt,
            "last_auth_status": api.last_auth_status,
            "last_auth_message": api.last_auth_message,
            "last_auth_attempt_summary": api.last_auth_attempt_summary,
        },
        # Last outcome of every station-scoped list endpoint, so an empty
        # device list can be told apart from a denied one ("status": "3",
        # "No Permission").
        "device_fetch_status": getattr(api, "device_fetch_status", {}) or {},
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "station_count": len(coordinator_data),
            "stations": {
                f"station_{index}": _station_summary(deepcopy(station_data))
                for index, station_data in enumerate(coordinator_data.values(), 1)
            },
        },
    }

    return _redact_sensitive_keys(async_redact_data(payload, REDACT_KEYS))
