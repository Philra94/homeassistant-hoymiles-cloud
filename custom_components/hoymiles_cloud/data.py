"""Pure data helpers for the Hoymiles Cloud integration."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


MODE_KEY_MAPPING = {
    1: "k_1",
    2: "k_2",
    3: "k_3",
    4: "k_4",
    7: "k_7",
    8: "k_8",
}


def build_empty_battery_settings(
    *,
    readable: bool = False,
    writable: bool = False,
    status: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Build a consistent battery settings payload."""
    return {
        "readable": readable,
        "writable": writable,
        "available_modes": [],
        "mode_data": {},
        "mode_settings": {},
        "data": {},
        "error_status": status,
        "error_message": message,
    }


def battery_settings_readable(battery_settings: dict[str, Any] | None) -> bool:
    """Return whether the battery settings endpoint is readable."""
    return bool(battery_settings and battery_settings.get("readable"))


def battery_settings_writable(battery_settings: dict[str, Any] | None) -> bool:
    """Return whether battery settings can be written."""
    return bool(battery_settings and battery_settings.get("writable"))


def get_supported_modes(battery_settings: dict[str, Any] | None) -> list[int]:
    """Return supported battery mode IDs from the payload."""
    if not battery_settings:
        return []

    available_modes = battery_settings.get("available_modes")
    if isinstance(available_modes, list):
        return [mode for mode in available_modes if isinstance(mode, int)]

    mode_data = battery_settings.get("mode_data", {})
    supported_modes: list[int] = []
    for key in mode_data:
        if key.startswith("k_"):
            try:
                supported_modes.append(int(key.split("_", 1)[1]))
            except ValueError:
                continue
    return sorted(set(supported_modes))


def get_mode_settings(
    battery_settings: dict[str, Any] | None,
    mode: int,
) -> dict[str, Any]:
    """Return settings for a battery mode."""
    if not battery_settings:
        return {}

    mode_key = MODE_KEY_MAPPING.get(mode)
    if not mode_key:
        return {}

    return deepcopy(battery_settings.get("mode_data", {}).get(mode_key, {}))


def get_pv_indicator_value(
    pv_indicators: dict[str, Any] | None,
    key: str,
) -> Any:
    """Return a PV indicator value by key."""
    items = pv_indicators.get("list", []) if pv_indicators else []
    for item in items:
        if item.get("key") == key:
            return item.get("val")
    return None


def discover_pv_channels(pv_indicators: dict[str, Any] | None) -> list[int]:
    """Return the discovered PV channel numbers for a station."""
    channels: set[int] = set()
    items = pv_indicators.get("list", []) if pv_indicators else []
    for item in items:
        key = item.get("key", "")
        prefix, _, suffix = key.partition("_pv_")
        if suffix in {"v", "i", "p"} and prefix.isdigit():
            channels.add(int(prefix))
    return sorted(channels)


def has_battery_telemetry(real_time_data: dict[str, Any] | None) -> bool:
    """Return whether real-time data contains battery telemetry."""
    reflux_data = (real_time_data or {}).get("reflux_station_data", {})
    return any(
        reflux_data.get(field) not in (None, "", "-")
        for field in ("bms_power", "bms_soc", "bms_in_eq", "bms_out_eq")
    )


def build_station_capabilities(
    *,
    real_time_data: dict[str, Any] | None,
    pv_indicators: dict[str, Any] | None,
    battery_settings: dict[str, Any] | None,
    microinverters_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Summarize station capabilities from the current API payloads."""
    pv_channels = discover_pv_channels(pv_indicators)
    battery_settings = battery_settings or {}

    return {
        "battery_telemetry": has_battery_telemetry(real_time_data),
        "battery_settings_readable": battery_settings_readable(battery_settings),
        "battery_settings_writable": battery_settings_writable(battery_settings),
        "pv_indicators_available": bool((pv_indicators or {}).get("list")),
        "pv_channels": pv_channels,
        "microinverter_details_available": bool(microinverters_data),
        "microinverter_detail_count": len(microinverters_data or {}),
        "supported_battery_modes": get_supported_modes(battery_settings),
    }
