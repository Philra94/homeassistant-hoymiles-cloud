"""Select platform for Hoymiles Cloud integration."""
from __future__ import annotations

import logging
from typing import Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import BATTERY_MODES, DOMAIN
from .const import BATTERY_MODE_ECONOMY, BATTERY_MODE_TIME_OF_USE
from .data import battery_settings_writable, get_supported_modes
from .hoymiles_api import HoymilesAPI
from .schedule_editor import (
    build_device_info,
    get_economy_duration_type_options,
    get_economy_week_group_options,
    get_economy_window_options,
    get_mode_draft,
    get_schedule_mode_options,
    get_selected_editor_mode,
    get_station_data,
    get_tou_period_options,
    mode_has_editor,
)

_LOGGER = logging.getLogger(__name__)

MODE_OPTIONS = BATTERY_MODES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hoymiles Cloud select entities."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data["coordinator"]
    stations = runtime_data["stations"]
    api = runtime_data["api"]
    set_schedule_editor_selection = runtime_data["set_schedule_editor_selection"]

    entities = []
    for station_id, station_name in stations.items():
        station_data = coordinator.data.get(station_id, {}) if coordinator.data else {}
        battery_settings = station_data.get("battery_settings", {})
        if battery_settings_writable(battery_settings) and get_supported_modes(battery_settings):
            entities.append(
                HoymilesBatteryModeSelect(
                    coordinator=coordinator,
                    api=api,
                    station_id=station_id,
                    station_name=station_name,
                )
            )
        if station_data.get("schedule_editor", {}).get("available_modes"):
            entities.extend(
                [
                    HoymilesScheduleEditorModeSelect(
                        coordinator=coordinator,
                        station_id=station_id,
                        station_name=station_name,
                        set_selection=set_schedule_editor_selection,
                    ),
                    HoymilesTimeOfUsePeriodSelect(
                        coordinator=coordinator,
                        station_id=station_id,
                        station_name=station_name,
                        set_selection=set_schedule_editor_selection,
                    ),
                    HoymilesEconomyWindowSelect(
                        coordinator=coordinator,
                        station_id=station_id,
                        station_name=station_name,
                        set_selection=set_schedule_editor_selection,
                    ),
                    HoymilesEconomyWeekGroupSelect(
                        coordinator=coordinator,
                        station_id=station_id,
                        station_name=station_name,
                        set_selection=set_schedule_editor_selection,
                    ),
                    HoymilesEconomyDurationTypeSelect(
                        coordinator=coordinator,
                        station_id=station_id,
                        station_name=station_name,
                        set_selection=set_schedule_editor_selection,
                    ),
                ]
            )

    async_add_entities(entities)


class HoymilesBatteryModeSelect(CoordinatorEntity, SelectEntity):
    """Select entity for battery mode selection."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: HoymilesAPI,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._api = api
        self._station_id = station_id
        self._attr_unique_id = f"{DOMAIN}_{station_id}_battery_mode_select"
        self._attr_name = f"{station_name} Battery Mode"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = build_device_info(station_id, station_name)
        self._attr_options = self._get_current_options()

    def _get_station_data(self) -> dict:
        """Return the coordinator payload for this station."""
        return get_station_data(self.coordinator, self._station_id)

    def _get_current_options(self) -> list[str]:
        """Return supported mode options for this station."""
        battery_settings = self._get_station_data().get("battery_settings", {})
        return [
            MODE_OPTIONS[mode]
            for mode in get_supported_modes(battery_settings)
            if mode in MODE_OPTIONS
        ]

    @property
    def current_option(self) -> Optional[str]:
        """Return the current selected mode as a string."""
        battery_settings = self._get_station_data().get("battery_settings", {})
        mode = battery_settings.get("data", {}).get("mode")
        if mode is None:
            return None
        return MODE_OPTIONS.get(mode, f"Unknown ({mode})")

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        for mode_id, mode_name in MODE_OPTIONS.items():
            if mode_name != option:
                continue

            if not await self._api.set_battery_mode(self._station_id, mode_id):
                _LOGGER.error("Failed to set battery mode to %s (ID: %s)", option, mode_id)
                return

            await self.coordinator.async_request_refresh()
            self.async_write_ha_state()
            return

        _LOGGER.error("Unknown mode selected: %s", option)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False

        battery_settings = self._get_station_data().get("battery_settings", {})
        self._attr_options = self._get_current_options()
        return battery_settings_writable(battery_settings) and bool(self._attr_options)


class HoymilesScheduleEditorSelect(CoordinatorEntity, SelectEntity):
    """Base class for schedule editor selects."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station_id: str,
        station_name: str,
        set_selection,
    ) -> None:
        """Initialize shared schedule editor fields."""
        super().__init__(coordinator)
        self._station_id = station_id
        self._station_name = station_name
        self._set_selection = set_selection
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = build_device_info(station_id, station_name)

    def _get_station_data(self) -> dict:
        """Return the coordinator payload for this station."""
        return get_station_data(self.coordinator, self._station_id)

    @property
    def available(self) -> bool:
        """Return whether the entity is currently available."""
        return self.coordinator.last_update_success


class HoymilesScheduleEditorModeSelect(HoymilesScheduleEditorSelect):
    """Select entity for choosing which schedule mode is being edited."""

    def __init__(self, coordinator, station_id, station_name, set_selection) -> None:
        super().__init__(coordinator, station_id, station_name, set_selection)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_schedule_editor_mode"
        self._attr_name = f"{station_name} Schedule Editor Mode"

    @property
    def options(self) -> list[str]:
        """Return editable schedule mode labels."""
        return get_schedule_mode_options(self._get_station_data())

    @property
    def current_option(self) -> Optional[str]:
        """Return the selected editor mode label."""
        mode = get_selected_editor_mode(self._get_station_data())
        return MODE_OPTIONS.get(mode) if mode is not None else None

    async def async_select_option(self, option: str) -> None:
        """Switch the schedule editor mode."""
        for mode_id, mode_name in MODE_OPTIONS.items():
            if mode_name == option:
                await self._set_selection(self._station_id, selected_mode=mode_id)
                return
        _LOGGER.error("Unknown schedule editor mode selected: %s", option)

    @property
    def available(self) -> bool:
        """Return whether the selector should be shown."""
        return super().available and bool(self.options)


class HoymilesTimeOfUsePeriodSelect(HoymilesScheduleEditorSelect):
    """Select entity for the active Time-of-Use period row."""

    def __init__(self, coordinator, station_id, station_name, set_selection) -> None:
        super().__init__(coordinator, station_id, station_name, set_selection)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_time_of_use_active_period"
        self._attr_name = f"{station_name} Time of Use Active Period"

    @property
    def options(self) -> list[str]:
        """Return Time-of-Use period labels."""
        draft = get_mode_draft(self._get_station_data(), BATTERY_MODE_TIME_OF_USE)
        return get_tou_period_options(draft)

    @property
    def current_option(self) -> Optional[str]:
        """Return the selected Time-of-Use period label."""
        draft = get_mode_draft(self._get_station_data(), BATTERY_MODE_TIME_OF_USE)
        index = int(draft.get("selected_period_index", 0))
        options = self.options
        return options[index] if options and index < len(options) else None

    async def async_select_option(self, option: str) -> None:
        """Switch the active Time-of-Use period."""
        options = self.options
        if option in options:
            await self._set_selection(
                self._station_id,
                selected_mode=BATTERY_MODE_TIME_OF_USE,
                mode=BATTERY_MODE_TIME_OF_USE,
                key="selected_period_index",
                value=options.index(option),
            )

    @property
    def available(self) -> bool:
        """Return whether the selector is active for the selected mode."""
        return super().available and mode_has_editor(
            self._get_station_data(),
            BATTERY_MODE_TIME_OF_USE,
        )


class HoymilesEconomyWindowSelect(HoymilesScheduleEditorSelect):
    """Select entity for the active Economy date window."""

    def __init__(self, coordinator, station_id, station_name, set_selection) -> None:
        super().__init__(coordinator, station_id, station_name, set_selection)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_economy_active_window"
        self._attr_name = f"{station_name} Economy Active Date Window"

    @property
    def options(self) -> list[str]:
        """Return Economy date window labels."""
        draft = get_mode_draft(self._get_station_data(), BATTERY_MODE_ECONOMY)
        return get_economy_window_options(draft)

    @property
    def current_option(self) -> Optional[str]:
        """Return the selected Economy date window label."""
        draft = get_mode_draft(self._get_station_data(), BATTERY_MODE_ECONOMY)
        index = int(draft.get("selected_date_index", 0))
        options = self.options
        return options[index] if options and index < len(options) else None

    async def async_select_option(self, option: str) -> None:
        """Switch the active Economy date window."""
        options = self.options
        if option in options:
            await self._set_selection(
                self._station_id,
                selected_mode=BATTERY_MODE_ECONOMY,
                mode=BATTERY_MODE_ECONOMY,
                key="selected_date_index",
                value=options.index(option),
            )

    @property
    def available(self) -> bool:
        """Return whether the selector is active for the selected mode."""
        return super().available and mode_has_editor(
            self._get_station_data(),
            BATTERY_MODE_ECONOMY,
        )


class HoymilesEconomyWeekGroupSelect(HoymilesScheduleEditorSelect):
    """Select entity for the active Economy weekday group."""

    def __init__(self, coordinator, station_id, station_name, set_selection) -> None:
        super().__init__(coordinator, station_id, station_name, set_selection)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_economy_active_week_group"
        self._attr_name = f"{station_name} Economy Active Weekday Group"

    @property
    def options(self) -> list[str]:
        """Return Economy weekday group labels."""
        draft = get_mode_draft(self._get_station_data(), BATTERY_MODE_ECONOMY)
        return get_economy_week_group_options(draft)

    @property
    def current_option(self) -> Optional[str]:
        """Return the selected Economy weekday group label."""
        draft = get_mode_draft(self._get_station_data(), BATTERY_MODE_ECONOMY)
        index = int(draft.get("selected_week_group_index", 0))
        options = self.options
        return options[index] if options and index < len(options) else None

    async def async_select_option(self, option: str) -> None:
        """Switch the active Economy weekday group."""
        options = self.options
        if option in options:
            await self._set_selection(
                self._station_id,
                selected_mode=BATTERY_MODE_ECONOMY,
                mode=BATTERY_MODE_ECONOMY,
                key="selected_week_group_index",
                value=options.index(option),
            )

    @property
    def available(self) -> bool:
        """Return whether the selector is active for the selected mode."""
        return super().available and mode_has_editor(
            self._get_station_data(),
            BATTERY_MODE_ECONOMY,
        )


class HoymilesEconomyDurationTypeSelect(HoymilesScheduleEditorSelect):
    """Select entity for the active Economy duration type."""

    def __init__(self, coordinator, station_id, station_name, set_selection) -> None:
        super().__init__(coordinator, station_id, station_name, set_selection)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_economy_active_duration_type"
        self._attr_name = f"{station_name} Economy Active Duration Type"

    @property
    def options(self) -> list[str]:
        """Return Economy duration type labels."""
        return get_economy_duration_type_options()

    @property
    def current_option(self) -> Optional[str]:
        """Return the selected Economy duration type label."""
        draft = get_mode_draft(self._get_station_data(), BATTERY_MODE_ECONOMY)
        selected_type = int(draft.get("selected_duration_type", 1))
        options = self.options
        index = max(0, min(selected_type - 1, len(options) - 1))
        return options[index] if options else None

    async def async_select_option(self, option: str) -> None:
        """Switch the active Economy duration type."""
        options = self.options
        if option in options:
            await self._set_selection(
                self._station_id,
                selected_mode=BATTERY_MODE_ECONOMY,
                mode=BATTERY_MODE_ECONOMY,
                key="selected_duration_type",
                value=options.index(option) + 1,
            )

    @property
    def available(self) -> bool:
        """Return whether the selector is active for the selected mode."""
        return super().available and mode_has_editor(
            self._get_station_data(),
            BATTERY_MODE_ECONOMY,
        )