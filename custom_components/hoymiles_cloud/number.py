"""Number platform for Hoymiles Cloud integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import BATTERY_MODE_PEAK_SHAVING, BATTERY_MODES, DOMAIN
from .data import battery_settings_writable, get_mode_settings, get_supported_modes
from .hoymiles_api import HoymilesAPI


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hoymiles number platform."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data["coordinator"]
    stations = runtime_data["stations"]
    api = runtime_data["api"]
    update_soc = runtime_data["update_soc"]

    entities = []
    for station_id, station_name in stations.items():
        station_data = coordinator.data.get(station_id, {}) if coordinator.data else {}
        battery_settings = station_data.get("battery_settings", {})
        if not battery_settings_writable(battery_settings):
            continue

        supported_modes = get_supported_modes(battery_settings)
        for mode in supported_modes:
            mode_settings = get_mode_settings(battery_settings, mode)
            if "reserve_soc" in mode_settings:
                entities.append(
                    HoymilesBatteryReserveSOC(
                        coordinator=coordinator,
                        api=api,
                        station_id=station_id,
                        station_name=station_name,
                        mode=mode,
                        update_soc_callback=update_soc,
                    )
                )

        peak_settings = get_mode_settings(battery_settings, BATTERY_MODE_PEAK_SHAVING)
        if peak_settings:
            if "max_soc" in peak_settings:
                entities.append(
                    HoymilesPeakShavingMaxSOC(
                        coordinator=coordinator,
                        api=api,
                        station_id=station_id,
                        station_name=station_name,
                    )
                )
            if "meter_power" in peak_settings:
                entities.append(
                    HoymilesPeakShavingMeterPower(
                        coordinator=coordinator,
                        api=api,
                        station_id=station_id,
                        station_name=station_name,
                    )
                )

    async_add_entities(entities)


class HoymilesBatteryNumberEntity(CoordinatorEntity, NumberEntity):
    """Base class for battery configuration numbers."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: HoymilesAPI,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the shared number entity fields."""
        super().__init__(coordinator)
        self._api = api
        self._station_id = station_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station_id)},
            "name": station_name,
            "manufacturer": "Hoymiles",
            "model": "Solar Inverter System",
        }
        self._attr_entity_category = EntityCategory.CONFIG

    def _get_station_data(self) -> dict:
        """Return the coordinator payload for this station."""
        return self.coordinator.data.get(self._station_id, {}) if self.coordinator.data else {}

    def _get_battery_settings(self) -> dict:
        """Return the current battery settings payload."""
        return self._get_station_data().get("battery_settings", {})

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and battery_settings_writable(
            self._get_battery_settings()
        )


class HoymilesBatteryReserveSOC(HoymilesBatteryNumberEntity):
    """Representation of a Hoymiles battery reserve SOC number control."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: HoymilesAPI,
        station_id: str,
        station_name: str,
        mode: int,
        update_soc_callback,
    ) -> None:
        """Initialize the reserve SOC control."""
        super().__init__(coordinator, api, station_id, station_name)
        self._mode = mode
        self._mode_name = BATTERY_MODES.get(mode, f"Mode {mode}")
        self._update_soc = update_soc_callback
        self._attr_unique_id = f"{DOMAIN}_{station_id}_battery_reserve_soc_{mode}"
        self._attr_name = f"{station_name} Battery Reserve SOC ({self._mode_name})"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_mode = NumberMode.SLIDER
        self._attr_native_unit_of_measurement = PERCENTAGE

    def _get_storage_key(self) -> str:
        """Return the persistent storage key for this mode."""
        if self._mode == 1:
            return "self_consumption"
        if self._mode == 3:
            return "backup"
        return BATTERY_MODES.get(self._mode, f"mode_{self._mode}").lower().replace(" ", "_")

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        mode_settings = get_mode_settings(self._get_battery_settings(), self._mode)
        reserve_soc = mode_settings.get("reserve_soc")
        return int(reserve_soc) if reserve_soc is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        if not await self._api.set_battery_mode_settings(
            self._station_id,
            self._mode,
            {"reserve_soc": int(value)},
        ):
            return

        await self._update_soc(self._station_id, self._get_storage_key(), int(value))
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class HoymilesPeakShavingMaxSOC(HoymilesBatteryNumberEntity):
    """Entity for controlling Peak Shaving Mode's max_soc parameter."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: HoymilesAPI,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the max SOC control."""
        super().__init__(coordinator, api, station_id, station_name)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_peak_shaving_max_soc"
        self._attr_name = f"{station_name} Peak Shaving Max SOC"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_mode = NumberMode.SLIDER
        self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        value = get_mode_settings(
            self._get_battery_settings(), BATTERY_MODE_PEAK_SHAVING
        ).get("max_soc")
        return int(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the max SOC value."""
        current_settings = get_mode_settings(
            self._get_battery_settings(), BATTERY_MODE_PEAK_SHAVING
        )
        if not await self._api.set_peak_shaving_settings(
            self._station_id,
            reserve_soc=current_settings.get("reserve_soc"),
            max_soc=int(value),
            meter_power=current_settings.get("meter_power"),
        ):
            return

        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class HoymilesPeakShavingMeterPower(HoymilesBatteryNumberEntity):
    """Entity for controlling Peak Shaving Mode's meter_power parameter."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: HoymilesAPI,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the meter power control."""
        super().__init__(coordinator, api, station_id, station_name)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_peak_shaving_meter_power"
        self._attr_name = f"{station_name} Peak Shaving Meter Power"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 10000
        self._attr_native_step = 100
        self._attr_mode = NumberMode.BOX
        self._attr_native_unit_of_measurement = "W"

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        value = get_mode_settings(
            self._get_battery_settings(), BATTERY_MODE_PEAK_SHAVING
        ).get("meter_power")
        return int(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the meter power value."""
        current_settings = get_mode_settings(
            self._get_battery_settings(), BATTERY_MODE_PEAK_SHAVING
        )
        if not await self._api.set_peak_shaving_settings(
            self._station_id,
            reserve_soc=current_settings.get("reserve_soc"),
            max_soc=current_settings.get("max_soc"),
            meter_power=int(value),
        ):
            return

        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()