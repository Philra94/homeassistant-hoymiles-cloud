"""Text entities for the Hoymiles schedule editor."""
from __future__ import annotations

from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import BATTERY_MODE_ECONOMY, BATTERY_MODE_TIME_OF_USE, DOMAIN
from .schedule_editor import (
    build_device_info,
    get_mode_draft,
    get_selected_economy_duration,
    get_selected_economy_week_group,
    get_selected_economy_window,
    get_selected_tou_period,
    get_station_data,
    mode_has_editor,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hoymiles schedule editor text platform."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data["coordinator"]
    stations = runtime_data["stations"]
    set_schedule_editor_field = runtime_data["set_schedule_editor_field"]

    entities = []
    for station_id, station_name in stations.items():
        station_data = coordinator.data.get(station_id, {}) if coordinator.data else {}
        if not station_data.get("schedule_editor", {}).get("available_modes"):
            continue
        entities.extend(
            [
                HoymilesScheduleTextEntity(
                    coordinator,
                    station_id,
                    station_name,
                    set_schedule_editor_field,
                    BATTERY_MODE_TIME_OF_USE,
                    "time_of_use_charge_start",
                    "Time of Use Charge Start",
                    _tou_period_path,
                    "cs_time",
                ),
                HoymilesScheduleTextEntity(
                    coordinator,
                    station_id,
                    station_name,
                    set_schedule_editor_field,
                    BATTERY_MODE_TIME_OF_USE,
                    "time_of_use_charge_end",
                    "Time of Use Charge End",
                    _tou_period_path,
                    "ce_time",
                ),
                HoymilesScheduleTextEntity(
                    coordinator,
                    station_id,
                    station_name,
                    set_schedule_editor_field,
                    BATTERY_MODE_TIME_OF_USE,
                    "time_of_use_discharge_start",
                    "Time of Use Discharge Start",
                    _tou_period_path,
                    "dcs_time",
                ),
                HoymilesScheduleTextEntity(
                    coordinator,
                    station_id,
                    station_name,
                    set_schedule_editor_field,
                    BATTERY_MODE_TIME_OF_USE,
                    "time_of_use_discharge_end",
                    "Time of Use Discharge End",
                    _tou_period_path,
                    "dce_time",
                ),
                HoymilesScheduleTextEntity(
                    coordinator,
                    station_id,
                    station_name,
                    set_schedule_editor_field,
                    BATTERY_MODE_ECONOMY,
                    "economy_start_date",
                    "Economy Start Date",
                    _economy_window_path,
                    "start_date",
                ),
                HoymilesScheduleTextEntity(
                    coordinator,
                    station_id,
                    station_name,
                    set_schedule_editor_field,
                    BATTERY_MODE_ECONOMY,
                    "economy_end_date",
                    "Economy End Date",
                    _economy_window_path,
                    "end_date",
                ),
                HoymilesScheduleTextEntity(
                    coordinator,
                    station_id,
                    station_name,
                    set_schedule_editor_field,
                    BATTERY_MODE_ECONOMY,
                    "economy_duration_start",
                    "Economy Duration Start",
                    _economy_duration_path,
                    "start_time",
                ),
                HoymilesScheduleTextEntity(
                    coordinator,
                    station_id,
                    station_name,
                    set_schedule_editor_field,
                    BATTERY_MODE_ECONOMY,
                    "economy_duration_end",
                    "Economy Duration End",
                    _economy_duration_path,
                    "end_time",
                ),
            ]
        )

    async_add_entities(entities)


def _tou_period_path(draft: dict[str, Any]) -> tuple[Any, ...]:
    index, _ = get_selected_tou_period(draft)
    return ("periods", index)


def _economy_window_path(draft: dict[str, Any]) -> tuple[Any, ...]:
    index, _ = get_selected_economy_window(draft)
    return ("date_windows", index)


def _economy_duration_path(draft: dict[str, Any]) -> tuple[Any, ...]:
    window_index, _ = get_selected_economy_window(draft)
    week_index, _ = get_selected_economy_week_group(draft)
    duration_index, _ = get_selected_economy_duration(draft)
    return ("date_windows", window_index, "week_groups", week_index, "durations", duration_index)


class HoymilesScheduleTextEntity(CoordinatorEntity, TextEntity):
    """Text entity backed by the normalized schedule editor draft."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station_id: str,
        station_name: str,
        set_schedule_editor_field,
        mode: int,
        entity_key: str,
        label: str,
        base_path_fn,
        field_name: str,
    ) -> None:
        """Initialize the schedule editor text entity."""
        super().__init__(coordinator)
        self._station_id = station_id
        self._set_schedule_editor_field = set_schedule_editor_field
        self._mode = mode
        self._base_path_fn = base_path_fn
        self._field_name = field_name
        self._attr_unique_id = f"{DOMAIN}_{station_id}_{entity_key}"
        self._attr_name = f"{station_name} {label}"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = build_device_info(station_id, station_name)
        self._attr_native_max = 5
        self._attr_pattern = r"[0-9:\-]*"

    def _get_station_data(self) -> dict[str, Any]:
        """Return the current station payload."""
        return get_station_data(self.coordinator, self._station_id)

    def _get_value(self) -> str | None:
        """Return the text value for the selected draft field."""
        draft = get_mode_draft(self._get_station_data(), self._mode)
        current = draft
        for key in (*self._base_path_fn(draft), self._field_name):
            current = current[key]
        return str(current)

    @property
    def native_value(self) -> str | None:
        """Return the current text field value."""
        return self._get_value()

    async def async_set_value(self, value: str) -> None:
        """Persist an updated text field value."""
        draft = get_mode_draft(self._get_station_data(), self._mode)
        path = (*self._base_path_fn(draft), self._field_name)
        await self._set_schedule_editor_field(self._station_id, self._mode, path, value.strip())

    @property
    def available(self) -> bool:
        """Return whether this control is active for the selected mode."""
        return self.coordinator.last_update_success and mode_has_editor(
            self._get_station_data(),
            self._mode,
        )
