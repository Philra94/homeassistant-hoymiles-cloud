"""Entry-scoped storage helpers, importable without Home Assistant."""

from copy import deepcopy
from typing import Any


def entry_storage_key(base_key: str, entry_id: str) -> str:
    """Give each config entry an independent Store file."""
    return f"{base_key}_{entry_id}"


def migrate_legacy_stations(
    legacy: dict[str, Any] | None, station_ids: set[str]
) -> dict[str, Any]:
    """Copy only this entry's stations; leave the shared legacy file untouched."""
    source = (legacy or {}).get("stations", {})
    if not isinstance(source, dict):
        return {"stations": {}}
    return {"stations": {
        station_id: deepcopy(source[station_id])
        for station_id in station_ids
        if station_id in source and isinstance(source[station_id], dict)
    }}
