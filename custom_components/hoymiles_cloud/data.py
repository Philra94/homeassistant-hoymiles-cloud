"""Pure data helpers for the Hoymiles Cloud integration."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from typing import Any

from .const import (
    BATTERY_MODE_ECONOMY,
    BATTERY_MODE_IDS,
    BATTERY_MODE_TIME_OF_USE,
    BATTERY_SCHEDULE_MODE_IDS,
)


MODE_KEY_MAPPING = {
    1: "k_1",
    2: "k_2",
    3: "k_3",
    4: "k_4",
    7: "k_7",
    8: "k_8",
}

ECONOMY_DURATION_TYPES = (1, 2, 3)
DEFAULT_WEEK_GROUPS = (
    [1, 2, 3, 4, 5],
    [6, 7],
)
DEFAULT_DATE_WINDOW = "01-01"
DEFAULT_TIME_VALUE = "00:00"


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce a value to int for schedule drafts."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce a value to float for schedule drafts."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _valid_mmdd(value: str | None) -> bool:
    """Return whether a string matches the observed MM-DD format."""
    if not value:
        return False
    try:
        datetime.strptime(f"2004-{value}", "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _valid_hhmm(value: str | None) -> bool:
    """Return whether a string matches the observed HH:MM format."""
    if not value:
        return False
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        return False
    return True


def _normalize_time_text(value: Any, *, allow_empty: bool = False) -> str:
    """Return a normalized HH:MM or empty time string."""
    if value in (None, "") and allow_empty:
        return ""
    text = str(value).strip() if value is not None else DEFAULT_TIME_VALUE
    return text if _valid_hhmm(text) else ("" if allow_empty else DEFAULT_TIME_VALUE)


def _weekday_label(week: list[int]) -> str:
    """Return a compact human-readable label for a weekday group."""
    if week == [1, 2, 3, 4, 5]:
        return "Mon-Fri"
    if week == [6, 7]:
        return "Sat-Sun"
    return ",".join(str(day) for day in week)


def _normalize_tou_period(period: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a Time-of-Use period row."""
    source = period or {}
    return {
        "cs_time": _normalize_time_text(source.get("cs_time")),
        "ce_time": _normalize_time_text(source.get("ce_time")),
        "c_power": _safe_int(source.get("c_power"), 0),
        "dcs_time": _normalize_time_text(source.get("dcs_time")),
        "dce_time": _normalize_time_text(source.get("dce_time")),
        "dc_power": _safe_int(source.get("dc_power"), 0),
        "charge_soc": _safe_int(source.get("charge_soc"), 0),
        "dis_charge_soc": _safe_int(source.get("dis_charge_soc"), 0),
    }


def _normalize_economy_duration(duration: dict[str, Any] | None, duration_type: int) -> dict[str, Any]:
    """Normalize an Economy duration row."""
    source = duration or {}
    allow_empty = duration_type == 2
    return {
        "type": duration_type,
        "start_time": _normalize_time_text(source.get("start_time"), allow_empty=allow_empty),
        "end_time": _normalize_time_text(source.get("end_time"), allow_empty=allow_empty),
        "in": _safe_float(source.get("in"), 0.0),
        "out": _safe_float(source.get("out"), 0.0),
    }


def _normalize_economy_week_group(group: dict[str, Any] | None, week: list[int]) -> dict[str, Any]:
    """Normalize an Economy weekday group."""
    source = group or {}
    durations_by_type = {
        _safe_int(duration.get("type"), 0): duration
        for duration in source.get("duration", [])
        if isinstance(duration, dict)
    }
    durations = [
        _normalize_economy_duration(durations_by_type.get(duration_type), duration_type)
        for duration_type in ECONOMY_DURATION_TYPES
    ]
    return {
        "week": list(source.get("week", week) or week),
        "label": _weekday_label(list(source.get("week", week) or week)),
        "durations": durations,
    }


def _normalize_economy_window(window: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize an Economy date window."""
    source = window or {}
    time_rows = source.get("time", [])
    normalized_groups: list[dict[str, Any]] = []
    for default_week in DEFAULT_WEEK_GROUPS:
        existing = next(
            (
                row
                for row in time_rows
                if isinstance(row, dict) and list(row.get("week", [])) == default_week
            ),
            None,
        )
        normalized_groups.append(_normalize_economy_week_group(existing, default_week))

    start_date = str(source.get("start_date", DEFAULT_DATE_WINDOW))
    end_date = str(source.get("end_date", "12-31"))
    return {
        "start_date": start_date if _valid_mmdd(start_date) else DEFAULT_DATE_WINDOW,
        "end_date": end_date if _valid_mmdd(end_date) else "12-31",
        "week_groups": normalized_groups,
    }


def build_time_of_use_draft(mode_settings: dict[str, Any] | None, stored_draft: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a normalized editable draft for Time-of-Use mode."""
    source = stored_draft if isinstance(stored_draft, dict) else mode_settings or {}
    periods = source.get("periods")
    if not isinstance(periods, list):
        periods = (source.get("time") if isinstance(source.get("time"), list) else None) or (mode_settings or {}).get("time", [])
    normalized_periods = [_normalize_tou_period(period) for period in periods if isinstance(period, dict)]
    if not normalized_periods:
        normalized_periods = [_normalize_tou_period(None)]
    selected_index = max(0, min(_safe_int(source.get("selected_period_index"), 0), len(normalized_periods) - 1))
    return {
        "mode": BATTERY_MODE_TIME_OF_USE,
        "selected_period_index": selected_index,
        "periods": normalized_periods,
    }


def build_economy_draft(mode_settings: dict[str, Any] | None, stored_draft: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a normalized editable draft for Economy mode."""
    live_settings = mode_settings or {}
    source = stored_draft if isinstance(stored_draft, dict) else live_settings
    windows = source.get("date_windows")
    if not isinstance(windows, list):
        windows = (source.get("date") if isinstance(source.get("date"), list) else None) or live_settings.get("date", [])
    normalized_windows = [_normalize_economy_window(window) for window in windows if isinstance(window, dict)]
    if not normalized_windows:
        normalized_windows = [_normalize_economy_window(None)]
    selected_date_index = max(0, min(_safe_int(source.get("selected_date_index"), 0), len(normalized_windows) - 1))
    selected_week_group_index = max(
        0,
        min(
            _safe_int(source.get("selected_week_group_index"), 0),
            len(normalized_windows[selected_date_index]["week_groups"]) - 1,
        ),
    )
    selected_duration_type = _safe_int(source.get("selected_duration_type"), 1)
    if selected_duration_type not in ECONOMY_DURATION_TYPES:
        selected_duration_type = 1
    return {
        "mode": BATTERY_MODE_ECONOMY,
        "money_code": str(source.get("money_code", live_settings.get("money_code", "$")) or "$"),
        "selected_date_index": selected_date_index,
        "selected_week_group_index": selected_week_group_index,
        "selected_duration_type": selected_duration_type,
        "date_windows": normalized_windows,
    }


def build_schedule_draft(mode: int, mode_settings: dict[str, Any] | None, stored_draft: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the normalized schedule draft for a battery mode."""
    if mode == BATTERY_MODE_ECONOMY:
        return build_economy_draft(mode_settings, stored_draft)
    if mode == BATTERY_MODE_TIME_OF_USE:
        return build_time_of_use_draft(mode_settings, stored_draft)
    return {}


def build_schedule_payload_from_draft(mode: int, draft: dict[str, Any]) -> dict[str, Any]:
    """Convert a normalized draft back into the Hoymiles payload shape."""
    if mode == BATTERY_MODE_TIME_OF_USE:
        return {
            "time": [deepcopy(period) for period in draft.get("periods", [])],
        }

    if mode == BATTERY_MODE_ECONOMY:
        windows = []
        for window in draft.get("date_windows", []):
            windows.append(
                {
                    "start_date": window["start_date"],
                    "end_date": window["end_date"],
                    "time": [
                        {
                            "week": list(group["week"]),
                            "duration": [
                                {
                                    "type": duration["type"],
                                    "start_time": duration["start_time"] or None,
                                    "end_time": duration["end_time"] or None,
                                    "in": duration["in"],
                                    "out": duration["out"],
                                }
                                for duration in group["durations"]
                            ],
                        }
                        for group in window["week_groups"]
                    ],
                }
            )
        return {
            "money_code": draft.get("money_code", "$"),
            "date": windows,
        }

    return {}


def get_schedule_draft(draft_state: dict[str, Any] | None, mode: int) -> dict[str, Any]:
    """Return the stored draft for a schedule mode."""
    if not draft_state:
        return {}
    mode_drafts = draft_state.get("modes", {})
    return deepcopy(mode_drafts.get(str(mode), {}))


def build_schedule_editor_state(
    battery_settings: dict[str, Any] | None,
    station_stored_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the derived schedule editor state for a station."""
    battery_settings = battery_settings or {}
    station_stored_data = station_stored_data or {}
    schedule_modes = get_schedule_modes(battery_settings)
    schedule_store = station_stored_data.get("schedule_editor", {})

    selected_mode = _safe_int(schedule_store.get("selected_mode"), get_current_battery_mode(battery_settings) or 0)
    if selected_mode not in schedule_modes:
        selected_mode = schedule_modes[0] if schedule_modes else None

    editor_modes: dict[int, dict[str, Any]] = {}
    for mode in schedule_modes:
        live_settings = get_mode_settings(battery_settings, mode)
        live_draft = build_schedule_draft(mode, live_settings)
        stored_draft = get_schedule_draft(schedule_store, mode)
        draft = build_schedule_draft(mode, live_settings, stored_draft)
        live_payload = build_schedule_payload_from_draft(mode, live_draft)
        draft_payload = build_schedule_payload_from_draft(mode, draft)
        validation_errors = validate_schedule_draft(mode, draft)
        editor_modes[mode] = {
            "live": live_draft,
            "draft": draft,
            "live_payload": live_payload,
            "draft_payload": draft_payload,
            "dirty": json.dumps(live_payload, sort_keys=True) != json.dumps(draft_payload, sort_keys=True),
            "validation_errors": validation_errors,
            "summary": summarize_schedule_draft(mode, draft),
        }

    selected_mode_state = editor_modes.get(selected_mode) if selected_mode is not None else None
    return {
        "available_modes": schedule_modes,
        "selected_mode": selected_mode,
        "modes": editor_modes,
        "dirty": any(mode_state["dirty"] for mode_state in editor_modes.values()),
        "validation_errors": selected_mode_state["validation_errors"] if selected_mode_state else [],
        "validation_status": "valid" if selected_mode_state and not selected_mode_state["validation_errors"] else (
            selected_mode_state["validation_errors"][0] if selected_mode_state and selected_mode_state["validation_errors"] else "unavailable"
        ),
    }


def summarize_schedule_draft(mode: int, draft: dict[str, Any]) -> str:
    """Return a compact schedule summary."""
    if mode == BATTERY_MODE_TIME_OF_USE:
        periods = draft.get("periods", [])
        if not periods:
            return "No periods configured"
        summary = []
        for index, period in enumerate(periods, start=1):
            summary.append(
                f"P{index} charge {period['cs_time']}-{period['ce_time']} @ {period['c_power']} / "
                f"discharge {period['dcs_time']}-{period['dce_time']} @ {period['dc_power']}"
            )
        return "; ".join(summary)

    if mode == BATTERY_MODE_ECONOMY:
        windows = draft.get("date_windows", [])
        if not windows:
            return "No date windows configured"
        summary = []
        for index, window in enumerate(windows, start=1):
            group_labels = ", ".join(group["label"] for group in window["week_groups"])
            summary.append(f"W{index} {window['start_date']}-{window['end_date']} ({group_labels})")
        return "; ".join(summary)

    return "Unsupported schedule mode"


def validate_schedule_draft(mode: int, draft: dict[str, Any]) -> list[str]:
    """Return validation errors for a normalized schedule draft."""
    errors: list[str] = []

    if mode == BATTERY_MODE_TIME_OF_USE:
        periods = draft.get("periods", [])
        if not periods:
            return ["At least one Time of Use period is required"]
        for index, period in enumerate(periods, start=1):
            for key in ("cs_time", "ce_time", "dcs_time", "dce_time"):
                if not _valid_hhmm(period.get(key)):
                    errors.append(f"Period {index} has an invalid {key}")
            for key in ("c_power", "dc_power"):
                if period.get(key, 0) < 0:
                    errors.append(f"Period {index} has a negative {key}")
            for key in ("charge_soc", "dis_charge_soc"):
                if not 0 <= _safe_int(period.get(key), -1) <= 100:
                    errors.append(f"Period {index} has an out-of-range {key}")
        return errors

    if mode == BATTERY_MODE_ECONOMY:
        windows = draft.get("date_windows", [])
        if not windows:
            return ["At least one Economy date window is required"]
        for index, window in enumerate(windows, start=1):
            if not _valid_mmdd(window.get("start_date")):
                errors.append(f"Date window {index} has an invalid start_date")
            if not _valid_mmdd(window.get("end_date")):
                errors.append(f"Date window {index} has an invalid end_date")
            for group in window.get("week_groups", []):
                if not group.get("week"):
                    errors.append(f"Date window {index} has an empty weekday group")
                for duration in group.get("durations", []):
                    duration_type = _safe_int(duration.get("type"), 0)
                    if duration_type not in ECONOMY_DURATION_TYPES:
                        errors.append(f"Date window {index} has an invalid duration type")
                        continue
                    if duration_type != 2:
                        if not _valid_hhmm(duration.get("start_time")):
                            errors.append(f"Date window {index} type {duration_type} has an invalid start_time")
                        if not _valid_hhmm(duration.get("end_time")):
                            errors.append(f"Date window {index} type {duration_type} has an invalid end_time")
                    for key in ("in", "out"):
                        if duration.get(key, 0) < 0:
                            errors.append(f"Date window {index} type {duration_type} has a negative {key}")
        return errors

    return ["Unsupported schedule mode"]


def update_schedule_editor_draft(
    schedule_editor_store: dict[str, Any],
    mode: int,
    field_path: tuple[Any, ...],
    value: Any,
) -> dict[str, Any]:
    """Return an updated stored draft with one field changed."""
    updated = deepcopy(schedule_editor_store or {})
    updated.setdefault("modes", {})
    draft = updated["modes"].setdefault(str(mode), {})
    target = draft
    for index, key in enumerate(field_path[:-1]):
        next_key = field_path[index + 1]
        if isinstance(key, int):
            while len(target) <= key:
                target.append({})
            target = target[key]
            continue
        if key not in target or not isinstance(target[key], list if isinstance(next_key, int) else dict):
            target[key] = [] if isinstance(next_key, int) else {}
        target = target[key]
    last_key = field_path[-1]
    if isinstance(last_key, int):
        while len(target) <= last_key:
            target.append({})
        target[last_key] = value
    else:
        target[last_key] = value
    return updated


def set_schedule_editor_selection(
    schedule_editor_store: dict[str, Any],
    *,
    selected_mode: int | None = None,
    mode: int | None = None,
    key: str | None = None,
    value: int | None = None,
) -> dict[str, Any]:
    """Return updated editor UI selection state."""
    updated = deepcopy(schedule_editor_store or {})
    if selected_mode is not None:
        updated["selected_mode"] = selected_mode
    if mode is not None and key is not None and value is not None:
        updated.setdefault("modes", {})
        updated["modes"].setdefault(str(mode), {})
        updated["modes"][str(mode)][key] = value
    return updated


def add_schedule_entry(schedule_editor_store: dict[str, Any], mode: int) -> dict[str, Any]:
    """Return updated draft storage with a new schedule row."""
    updated = deepcopy(schedule_editor_store or {})
    updated.setdefault("modes", {})
    mode_store = updated["modes"].setdefault(str(mode), {})
    if mode == BATTERY_MODE_TIME_OF_USE:
        mode_store.setdefault("periods", [])
        mode_store["periods"].append(_normalize_tou_period(None))
        mode_store["selected_period_index"] = len(mode_store["periods"]) - 1
        return updated
    if mode == BATTERY_MODE_ECONOMY:
        mode_store.setdefault("date_windows", [])
        mode_store["date_windows"].append(_normalize_economy_window(None))
        mode_store["selected_date_index"] = len(mode_store["date_windows"]) - 1
        mode_store.setdefault("selected_week_group_index", 0)
        mode_store.setdefault("selected_duration_type", 1)
    return updated


def remove_schedule_entry(schedule_editor_store: dict[str, Any], mode: int) -> dict[str, Any]:
    """Return updated draft storage with the selected schedule row removed."""
    updated = deepcopy(schedule_editor_store or {})
    mode_store = updated.get("modes", {}).get(str(mode), {})
    if mode == BATTERY_MODE_TIME_OF_USE:
        periods = mode_store.get("periods", [])
        if len(periods) <= 1:
            return updated
        index = max(0, min(_safe_int(mode_store.get("selected_period_index"), 0), len(periods) - 1))
        periods.pop(index)
        mode_store["selected_period_index"] = max(0, min(index, len(periods) - 1))
        return updated
    if mode == BATTERY_MODE_ECONOMY:
        windows = mode_store.get("date_windows", [])
        if len(windows) <= 1:
            return updated
        index = max(0, min(_safe_int(mode_store.get("selected_date_index"), 0), len(windows) - 1))
        windows.pop(index)
        mode_store["selected_date_index"] = max(0, min(index, len(windows) - 1))
        mode_store.setdefault("selected_week_group_index", 0)
        mode_store.setdefault("selected_duration_type", 1)
    return updated


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


def get_backend_modes(battery_settings: dict[str, Any] | None) -> list[int]:
    """Return all backend mode ids present in the raw payload."""
    if not battery_settings:
        return []

    mode_data = battery_settings.get("mode_data", {})
    supported_modes: list[int] = []
    for key in mode_data:
        if key.startswith("k_"):
            try:
                supported_modes.append(int(key.split("_", 1)[1]))
            except ValueError:
                continue
    return sorted(set(supported_modes))


def get_supported_modes(battery_settings: dict[str, Any] | None) -> list[int]:
    """Return known battery mode IDs supported by the integration."""
    if not battery_settings:
        return []

    available_modes = battery_settings.get("available_modes")
    if isinstance(available_modes, list):
        return [mode for mode in available_modes if isinstance(mode, int) and mode in BATTERY_MODE_IDS]

    return [mode for mode in get_backend_modes(battery_settings) if mode in BATTERY_MODE_IDS]


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


def get_current_battery_mode(battery_settings: dict[str, Any] | None) -> int | None:
    """Return the active battery mode id."""
    mode = (battery_settings or {}).get("data", {}).get("mode")
    return mode if isinstance(mode, int) else None


def mode_supports_schedule(mode: int) -> bool:
    """Return whether a battery mode uses a schedule payload."""
    return mode in BATTERY_SCHEDULE_MODE_IDS


def get_schedule_modes(battery_settings: dict[str, Any] | None) -> list[int]:
    """Return known schedule-bearing modes exposed by the current payload."""
    return [mode for mode in get_supported_modes(battery_settings) if mode_supports_schedule(mode)]


def mode_fields(battery_settings: dict[str, Any] | None, mode: int) -> list[str]:
    """Return the sorted top-level fields present in a mode payload."""
    return sorted(get_mode_settings(battery_settings, mode).keys())


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
        "backend_battery_modes": get_backend_modes(battery_settings),
        "battery_schedule_modes": get_schedule_modes(battery_settings),
    }
