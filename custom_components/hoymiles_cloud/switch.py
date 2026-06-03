"""Switch platform for Hoymiles Cloud integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN
from .data import relay_settings_readable, relay_settings_writable, relay_settings_enabled
from .device import build_station_device_info
from .hoymiles_api import HoymilesAPI


def get_station_data(coordinator: DataUpdateCoordinator, station_id: str) -> dict[str, Any]:
    """Return one station payload."""
    return coordinator.data.get(station_id, {}) if coordinator.data else {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hoymiles Cloud switches."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data["coordinator"]
    stations = runtime_data["stations"]
    api = runtime_data["api"]

    entities: list[SwitchEntity] = []
    for station_id, station_name in stations.items():
        station_data = get_station_data(coordinator, station_id)
        if relay_settings_readable(station_data.get("relay_settings")):
            entities.append(HoymilesRelaySwitch(coordinator, api, station_id, station_name))

    async_add_entities(entities)


class HoymilesRelaySwitch(CoordinatorEntity, SwitchEntity):
    """Switch for enabling or disabling relay / dry-contact automation."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: HoymilesAPI,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the relay switch."""
        super().__init__(coordinator)
        self._api = api
        self._station_id = station_id
        self._attr_unique_id = f"{DOMAIN}_{station_id}_relay_enabled"
        self._attr_name = f"{station_name} Relay Automation"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = build_station_device_info(
            station_id,
            station_name,
            get_station_data(coordinator, station_id).get("station_info"),
        )

    def _get_station_data(self) -> dict[str, Any]:
        """Return the current station payload."""
        return get_station_data(self.coordinator, self._station_id)

    @property
    def is_on(self) -> bool | None:
        """Return whether relay automation appears enabled."""
        return relay_settings_enabled(self._get_station_data().get("relay_settings"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable relay automation."""
        if await self._api.set_relay_enabled(self._station_id, True):
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable relay automation."""
        if await self._api.set_relay_enabled(self._station_id, False):
            await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        """Return whether the switch is available."""
        if not self.coordinator.last_update_success:
            return False
        relay_settings = self._get_station_data().get("relay_settings")
        return relay_settings_readable(relay_settings) and relay_settings_writable(relay_settings)
