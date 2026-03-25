"""Button entities for the Hoymiles schedule editor."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN
from .schedule_editor import build_device_info, get_selected_editor_mode, get_station_data


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hoymiles schedule editor button platform."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data["coordinator"]
    stations = runtime_data["stations"]

    entities = []
    for station_id, station_name in stations.items():
        station_data = coordinator.data.get(station_id, {}) if coordinator.data else {}
        if not station_data.get("schedule_editor", {}).get("available_modes"):
            continue
        entities.extend(
            [
                HoymilesScheduleButton(
                    coordinator,
                    station_id,
                    station_name,
                    runtime_data["load_schedule_draft"],
                    "load_schedule_draft",
                    "Load Live Schedule Draft",
                ),
                HoymilesScheduleButton(
                    coordinator,
                    station_id,
                    station_name,
                    runtime_data["apply_schedule_draft"],
                    "apply_schedule_draft",
                    "Apply Schedule Draft",
                ),
                HoymilesScheduleButton(
                    coordinator,
                    station_id,
                    station_name,
                    runtime_data["reset_schedule_draft"],
                    "reset_schedule_draft",
                    "Discard Schedule Draft",
                ),
                HoymilesScheduleButton(
                    coordinator,
                    station_id,
                    station_name,
                    runtime_data["add_schedule_entry"],
                    "add_schedule_entry",
                    "Add Schedule Entry",
                ),
                HoymilesScheduleButton(
                    coordinator,
                    station_id,
                    station_name,
                    runtime_data["remove_schedule_entry"],
                    "remove_schedule_entry",
                    "Remove Schedule Entry",
                ),
            ]
        )

    async_add_entities(entities)


class HoymilesScheduleButton(CoordinatorEntity, ButtonEntity):
    """Button that operates on the currently selected schedule editor mode."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station_id: str,
        station_name: str,
        action,
        entity_key: str,
        label: str,
    ) -> None:
        """Initialize the schedule button."""
        super().__init__(coordinator)
        self._station_id = station_id
        self._action = action
        self._attr_unique_id = f"{DOMAIN}_{station_id}_{entity_key}"
        self._attr_name = f"{station_name} {label}"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = build_device_info(station_id, station_name)

    def _get_station_data(self) -> dict:
        """Return the current station payload."""
        return get_station_data(self.coordinator, self._station_id)

    async def async_press(self) -> None:
        """Invoke the schedule editor action for the selected mode."""
        mode = get_selected_editor_mode(self._get_station_data())
        if mode is None:
            return
        await self._action(self._station_id, mode)

    @property
    def available(self) -> bool:
        """Return whether any schedule editor mode is available."""
        return self.coordinator.last_update_success and get_selected_editor_mode(self._get_station_data()) is not None
