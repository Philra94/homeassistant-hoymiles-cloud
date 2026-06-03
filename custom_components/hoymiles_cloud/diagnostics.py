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
}


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
        "station_info": station_data.get("station_info", {}),
        "device_inventory": {
            "dtus": devices.get("dtus", []),
            "inverters": devices.get("inverters", []),
            "batteries": devices.get("batteries", []),
            "meters": devices.get("meters", []),
        },
        "setting_rules": station_data.get("setting_rules", {}),
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
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "station_count": len(coordinator_data),
            "stations": {
                station_id: _station_summary(deepcopy(station_data))
                for station_id, station_data in coordinator_data.items()
            },
        },
    }

    return async_redact_data(payload, REDACT_KEYS)
