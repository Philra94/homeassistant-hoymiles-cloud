"""Device helpers for Hoymiles station and child devices."""

from __future__ import annotations

from typing import Any, Callable

from .const import DOMAIN, METER_LOCATION_NAMES


def _text(value: Any, default: str | None = None) -> str | None:
    """Return a clean display string or the supplied default."""
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _via_station(station_id: str) -> tuple[str, str]:
    """Return the device identifier tuple for the parent station."""
    return (DOMAIN, station_id)


def _build_device_info(
    identifier: tuple[str, str],
    *,
    name: str,
    manufacturer: str = "Hoymiles",
    model: str | None = None,
    sw_version: str | None = None,
    hw_version: str | None = None,
    via_device: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """Build a Home Assistant compatible device-info dictionary."""
    info: dict[str, Any] = {
        "identifiers": {identifier},
        "name": name,
        "manufacturer": manufacturer,
    }
    if model:
        info["model"] = model
    if sw_version:
        info["sw_version"] = sw_version
    if hw_version:
        info["hw_version"] = hw_version
    if via_device:
        info["via_device"] = via_device
    return info


def build_station_device_info(
    station_id: str,
    station_name: str,
    station_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the top-level station device info."""
    station_info = station_info or {}
    classify = station_info.get("classify")
    if classify == 4:
        model = "Energy Storage Plant"
    else:
        model = "Solar Plant"
    return _build_device_info(
        (DOMAIN, station_id),
        name=_text(station_info.get("name"), station_name) or station_name,
        model=model,
    )


def build_dtu_device_info(
    station_id: str,
    station_name: str,
    dtu: dict[str, Any],
) -> dict[str, Any]:
    """Build the DTU device info."""
    serial = _text(dtu.get("sn") or dtu.get("dtu_sn") or dtu.get("id"), "unknown")
    return _build_device_info(
        (DOMAIN, f"dtu_{serial}"),
        name=f"{station_name} DTU {serial}",
        model=_text(dtu.get("model_no"), "DTU"),
        sw_version=_text(dtu.get("soft_ver")),
        hw_version=_text(dtu.get("hard_ver")),
        via_device=_via_station(station_id),
    )


def build_inverter_device_info(
    station_id: str,
    station_name: str,
    inverter: dict[str, Any],
) -> dict[str, Any]:
    """Build the inverter device info."""
    serial = _text(inverter.get("sn") or inverter.get("id"), "unknown")
    model = _text(inverter.get("model_no"), "Inverter")
    return _build_device_info(
        (DOMAIN, f"inverter_{serial}"),
        name=f"{station_name} Inverter {serial}",
        model=model,
        sw_version=_text(inverter.get("soft_ver") or inverter.get("sys_soft_ver")),
        hw_version=_text(inverter.get("hard_ver")),
        via_device=_via_station(station_id),
    )


def build_battery_device_info(
    station_id: str,
    station_name: str,
    battery: dict[str, Any],
) -> dict[str, Any]:
    """Build the battery device info."""
    serial = _text(battery.get("sn") or battery.get("id"), "unknown")
    capacity = _text(battery.get("cap"))
    model = f"Battery {capacity} kWh" if capacity else f"BMS Type {_text(battery.get('bms_type'), 'Unknown')}"
    return _build_device_info(
        (DOMAIN, f"battery_{serial}"),
        name=f"{station_name} Battery {serial}",
        model=model,
        sw_version=_text(battery.get("soft_ver")),
        hw_version=_text(battery.get("hard_ver")),
        via_device=_via_station(station_id),
    )


def build_meter_device_info(
    station_id: str,
    station_name: str,
    meter: dict[str, Any],
) -> dict[str, Any]:
    """Build the meter device info."""
    serial = _text(meter.get("sn") or meter.get("id"), "unknown")
    location = METER_LOCATION_NAMES.get(meter.get("location"), "Meter")
    model = _text(meter.get("model_no"), location)
    return _build_device_info(
        (DOMAIN, f"meter_{serial}"),
        name=f"{station_name} {location} {serial}",
        model=model,
        sw_version=_text(meter.get("soft_ver")),
        hw_version=_text(meter.get("hard_ver")),
        via_device=_via_station(station_id),
    )


def get_device_list(station_data: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Return the device list for one device kind."""
    return list((station_data.get("devices") or {}).get(kind, []))


def get_primary_device(
    station_data: dict[str, Any],
    kind: str,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any] | None:
    """Return the first matching device for a device kind."""
    for device in get_device_list(station_data, kind):
        if predicate is None or predicate(device):
            return device
    return None


def get_primary_dtu(station_data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first DTU for a station."""
    return get_primary_device(station_data, "dtus")


def get_primary_inverter(station_data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first inverter for a station."""
    return get_primary_device(station_data, "inverters")


def get_primary_battery(station_data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first battery for a station."""
    return get_primary_device(station_data, "batteries")


def get_primary_meter(
    station_data: dict[str, Any],
    *,
    location: int | None = None,
) -> dict[str, Any] | None:
    """Return the first matching meter for a station."""
    if location is None:
        return get_primary_device(station_data, "meters")
    return get_primary_device(
        station_data,
        "meters",
        predicate=lambda meter: meter.get("location") == location,
    )


def build_primary_inverter_device_info(
    station_id: str,
    station_name: str,
    station_data: dict[str, Any],
) -> dict[str, Any]:
    """Return the primary inverter device info or fall back to the station."""
    inverter = get_primary_inverter(station_data)
    if inverter:
        return build_inverter_device_info(station_id, station_name, inverter)
    return build_station_device_info(station_id, station_name, station_data.get("station_info"))


def build_primary_battery_device_info(
    station_id: str,
    station_name: str,
    station_data: dict[str, Any],
) -> dict[str, Any]:
    """Return the primary battery device info or fall back to the station."""
    battery = get_primary_battery(station_data)
    if battery:
        return build_battery_device_info(station_id, station_name, battery)
    return build_station_device_info(station_id, station_name, station_data.get("station_info"))


def build_primary_dtu_device_info(
    station_id: str,
    station_name: str,
    station_data: dict[str, Any],
) -> dict[str, Any]:
    """Return the primary DTU device info or fall back to the station."""
    dtu = get_primary_dtu(station_data)
    if dtu:
        return build_dtu_device_info(station_id, station_name, dtu)
    return build_station_device_info(station_id, station_name, station_data.get("station_info"))


def build_primary_meter_device_info(
    station_id: str,
    station_name: str,
    station_data: dict[str, Any],
    *,
    location: int | None = None,
) -> dict[str, Any]:
    """Return the primary meter device info or fall back to the station."""
    meter = get_primary_meter(station_data, location=location)
    if meter:
        return build_meter_device_info(station_id, station_name, meter)
    return build_station_device_info(station_id, station_name, station_data.get("station_info"))
