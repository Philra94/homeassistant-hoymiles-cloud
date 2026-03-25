"""Helpers shared by the schedule editor entity platforms."""
from __future__ import annotations

from typing import Any

from .const import (
    BATTERY_MODE_ECONOMY,
    BATTERY_MODE_TIME_OF_USE,
    BATTERY_MODES,
    DOMAIN,
)


def build_device_info(station_id: str, station_name: str) -> dict[str, Any]:
    """Return common device metadata for station-scoped entities."""
    return {
        "identifiers": {(DOMAIN, station_id)},
        "name": station_name,
        "manufacturer": "Hoymiles",
        "model": "Solar Inverter System",
    }


def get_station_data(coordinator, station_id: str) -> dict[str, Any]:
    """Return the coordinator payload for a station."""
    return coordinator.data.get(station_id, {}) if coordinator.data else {}


def get_editor_state(station_data: dict[str, Any]) -> dict[str, Any]:
    """Return the derived schedule editor state."""
    return station_data.get("schedule_editor", {})


def get_selected_editor_mode(station_data: dict[str, Any]) -> int | None:
    """Return the currently selected editor mode."""
    editor_state = get_editor_state(station_data)
    selected_mode = editor_state.get("selected_mode")
    return selected_mode if isinstance(selected_mode, int) else None


def get_mode_state(station_data: dict[str, Any], mode: int) -> dict[str, Any]:
    """Return the mode-specific editor state."""
    return get_editor_state(station_data).get("modes", {}).get(mode, {})


def get_mode_draft(station_data: dict[str, Any], mode: int) -> dict[str, Any]:
    """Return the mode-specific editable draft."""
    return get_mode_state(station_data, mode).get("draft", {})


def get_schedule_mode_options(station_data: dict[str, Any]) -> list[str]:
    """Return schedule mode labels for the station."""
    editor_state = get_editor_state(station_data)
    return [BATTERY_MODES.get(mode, f"Mode {mode}") for mode in editor_state.get("available_modes", [])]


def get_tou_period_options(draft: dict[str, Any]) -> list[str]:
    """Return selector labels for Time-of-Use periods."""
    periods = draft.get("periods", [])
    return [f"Period {index}" for index in range(1, len(periods) + 1)]


def get_selected_tou_period(draft: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Return the currently selected Time-of-Use period."""
    periods = draft.get("periods", [])
    if not periods:
        return 0, {}
    index = max(0, min(int(draft.get("selected_period_index", 0)), len(periods) - 1))
    return index, periods[index]


def get_economy_window_options(draft: dict[str, Any]) -> list[str]:
    """Return selector labels for Economy date windows."""
    windows = draft.get("date_windows", [])
    return [
        f"Window {index}: {window['start_date']}-{window['end_date']}"
        for index, window in enumerate(windows, start=1)
    ]


def get_selected_economy_window(draft: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Return the currently selected Economy date window."""
    windows = draft.get("date_windows", [])
    if not windows:
        return 0, {}
    index = max(0, min(int(draft.get("selected_date_index", 0)), len(windows) - 1))
    return index, windows[index]


def get_economy_week_group_options(draft: dict[str, Any]) -> list[str]:
    """Return selector labels for Economy weekday groups."""
    _, window = get_selected_economy_window(draft)
    groups = window.get("week_groups", [])
    return [group.get("label", f"Week group {index}") for index, group in enumerate(groups, start=1)]


def get_selected_economy_week_group(draft: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Return the currently selected Economy weekday group."""
    _, window = get_selected_economy_window(draft)
    groups = window.get("week_groups", [])
    if not groups:
        return 0, {}
    index = max(0, min(int(draft.get("selected_week_group_index", 0)), len(groups) - 1))
    return index, groups[index]


def get_economy_duration_type_options() -> list[str]:
    """Return selector labels for Economy duration types."""
    return ["Type 1", "Type 2", "Type 3"]


def get_selected_economy_duration(draft: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Return the currently selected Economy duration row."""
    selected_type = int(draft.get("selected_duration_type", 1))
    _, week_group = get_selected_economy_week_group(draft)
    durations = week_group.get("durations", [])
    index = max(0, min(selected_type - 1, len(durations) - 1)) if durations else 0
    return index, durations[index] if durations else {}


def is_mode_selected(station_data: dict[str, Any], mode: int) -> bool:
    """Return whether a schedule editor mode is currently selected."""
    return get_selected_editor_mode(station_data) == mode


def mode_has_editor(station_data: dict[str, Any], mode: int) -> bool:
    """Return whether this station exposes editor state for the given mode."""
    return bool(get_mode_state(station_data, mode))


def mode_supports_editor_controls(station_data: dict[str, Any], mode: int) -> bool:
    """Return whether this mode should expose its editor entities."""
    return mode_has_editor(station_data, mode) and is_mode_selected(station_data, mode)


def get_selected_schedule_summary(station_data: dict[str, Any]) -> str | None:
    """Return the summary for the selected editor mode."""
    selected_mode = get_selected_editor_mode(station_data)
    if selected_mode is None:
        return None
    return get_mode_state(station_data, selected_mode).get("summary")


def get_selected_schedule_validation(station_data: dict[str, Any]) -> str:
    """Return the validation status for the selected editor mode."""
    return get_editor_state(station_data).get("validation_status", "unavailable")


def get_selected_schedule_dirty(station_data: dict[str, Any]) -> bool:
    """Return whether the selected editor mode has unsaved changes."""
    selected_mode = get_selected_editor_mode(station_data)
    if selected_mode is None:
        return False
    return bool(get_mode_state(station_data, selected_mode).get("dirty"))


def get_mode_entry_count(station_data: dict[str, Any], mode: int) -> int:
    """Return the number of top-level schedule rows for a mode."""
    draft = get_mode_draft(station_data, mode)
    if mode == BATTERY_MODE_TIME_OF_USE:
        return len(draft.get("periods", []))
    if mode == BATTERY_MODE_ECONOMY:
        return len(draft.get("date_windows", []))
    return 0
