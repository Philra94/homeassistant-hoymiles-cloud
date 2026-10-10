"""Idempotent entity discovery on coordinator updates."""

from __future__ import annotations

from typing import Any, Callable, Iterable

try:
    from homeassistant.helpers import device_registry as dr
except ImportError:  # Standalone tests and older non-HA tooling.
    dr = None


def resolve_via_device(coordinator: Any, entry: Any, entity: Any) -> None:
    """Resolve a parent inside this account before HA registers the entity.

    Older supported HA versions still require the identifier-based field.
    Creating the parent first also makes platform setup order irrelevant.
    """
    if dr is None or not hasattr(dr, "async_get_device_id_by_identifier"):
        return
    info = getattr(entity, "_attr_device_info", None)
    if not info or "via_device" not in info:
        return
    updated = dict(info)
    identifier = updated.pop("via_device")
    if identifier not in updated.get("identifiers", set()):
        registry = dr.async_get(coordinator.hass)
        parent = registry.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={identifier}
        )
        updated["via_device_id"] = parent.id
    entity._attr_device_info = updated



def register_discovery(
    coordinator: Any,
    entry: Any,
    add_entities: Callable[[list[Any]], None],
    build_entities: Callable[[], Iterable[Any]],
) -> None:
    """Add new unique IDs now and after future successful refreshes."""
    seen_ids: set[str] = set()

    def discover() -> None:
        new_entities = []
        pending_ids: set[str] = set()
        for entity in build_entities():
            unique_id = entity.unique_id
            if unique_id in seen_ids or unique_id in pending_ids:
                continue
            resolve_via_device(coordinator, entry, entity)
            pending_ids.add(unique_id)
            new_entities.append(entity)
        if new_entities:
            add_entities(new_entities)
            seen_ids.update(pending_ids)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


def invalidate_control_cache(coordinator: Any, station_id: str) -> None:
    """Force the next coordinator refresh to re-read device settings."""
    callback = getattr(coordinator, "invalidate_control_cache", None)
    if callback is not None:
        callback(station_id)
