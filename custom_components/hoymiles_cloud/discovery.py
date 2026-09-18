"""Idempotent entity discovery on coordinator updates."""

from __future__ import annotations

from typing import Any, Callable, Iterable


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
