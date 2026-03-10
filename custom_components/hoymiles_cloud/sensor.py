"""Sensor platform for Hoymiles Cloud integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfMass,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import BATTERY_MODES, DOMAIN
from .data import (
    battery_settings_readable,
    discover_pv_channels,
    get_pv_indicator_value,
)

_LOGGER = logging.getLogger(__name__)


def safe_int_convert(value: Any) -> int | None:
    """Safely convert a value to int."""
    if value is None or value in {"", "-"}:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_float_convert(value: Any) -> float | None:
    """Safely convert a value to float."""
    if value is None or value in {"", "-"}:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_timestamp(timestamp_str: str | None) -> datetime | None:
    """Parse a naive local timestamp returned by the API."""
    if not timestamp_str:
        return None
    try:
        naive_dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        local_aware_dt = naive_dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_utc(local_aware_dt)
    except (ValueError, TypeError) as err:
        _LOGGER.warning("Failed to parse timestamp %s: %s", timestamp_str, err)
        return None


def is_battery_charging(station_data: dict[str, Any]) -> bool | None:
    """Determine whether the battery is charging based on live flows."""
    try:
        reflux_data = station_data.get("real_time_data", {}).get("reflux_station_data", {})
        bms_power = safe_float_convert(reflux_data.get("bms_power"))
        if bms_power is not None:
            return bms_power > 0

        for flow in reflux_data.get("flows", []):
            if flow.get("in") == 4 and safe_float_convert(flow.get("v")):
                return True
            if flow.get("out") == 4 and safe_float_convert(flow.get("v")):
                return False
    except Exception as err:  # pragma: no cover - defensive logging
        _LOGGER.debug("Error determining battery charging status: %s", err)
    return None


def has_pv_indicator(station_data: dict[str, Any], key: str) -> bool:
    """Return whether a PV indicator key is present."""
    return get_pv_indicator_value(station_data.get("pv_indicators", {}), key) is not None


def has_battery_telemetry(station_data: dict[str, Any]) -> bool:
    """Return whether battery telemetry is available for the station."""
    return bool(station_data.get("capabilities", {}).get("battery_telemetry"))


@dataclass
class HoymilesSensorDescription(SensorEntityDescription):
    """Class describing Hoymiles sensor entities."""

    value_fn: Callable[[dict[str, Any]], StateType] | None = None
    available_fn: Callable[[dict[str, Any]], bool] | None = None


SENSORS = [
    HoymilesSensorDescription(
        key="pv_power",
        name="PV Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: safe_float_convert(data.get("real_time_data", {}).get("real_power")),
    ),
    HoymilesSensorDescription(
        key="grid_power",
        name="Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: safe_float_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("grid_power")
        ),
    ),
    HoymilesSensorDescription(
        key="load_power",
        name="Load Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: safe_float_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("load_power")
        ),
    ),
    HoymilesSensorDescription(
        key="battery_power",
        name="Battery Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: safe_float_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("bms_power")
        ),
        available_fn=has_battery_telemetry,
    ),
    HoymilesSensorDescription(
        key="battery_flow_direction",
        name="Battery Flow Direction",
        icon="mdi:battery-charging",
        value_fn=lambda data: (
            "discharging"
            if is_battery_charging(data) is False
            else "charging"
            if is_battery_charging(data) is True
            else "unknown"
        ),
        available_fn=has_battery_telemetry,
    ),
    HoymilesSensorDescription(
        key="battery_soc",
        name="Battery State of Charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: safe_int_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("bms_soc")
        ),
        available_fn=has_battery_telemetry,
    ),
    HoymilesSensorDescription(
        key="co2_emission_reduction",
        name="CO2 Emission Reduction",
        native_unit_of_measurement=UnitOfMass.GRAMS,
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(data.get("real_time_data", {}).get("co2_emission_reduction")),
    ),
    HoymilesSensorDescription(
        key="plant_tree",
        name="Equivalent Trees Planted",
        value_fn=lambda data: safe_int_convert(data.get("real_time_data", {}).get("plant_tree")),
    ),
    HoymilesSensorDescription(
        key="today_energy",
        name="Today's Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(data.get("real_time_data", {}).get("today_eq")),
    ),
    HoymilesSensorDescription(
        key="month_energy",
        name="Month Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(data.get("real_time_data", {}).get("month_eq")),
    ),
    HoymilesSensorDescription(
        key="year_energy",
        name="Year Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(data.get("real_time_data", {}).get("year_eq")),
    ),
    HoymilesSensorDescription(
        key="total_energy",
        name="Total Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(data.get("real_time_data", {}).get("total_eq")),
    ),
    HoymilesSensorDescription(
        key="pv_to_load_energy_today",
        name="PV to Load Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("pv_to_load_eq")
        ),
    ),
    HoymilesSensorDescription(
        key="grid_import_energy_today",
        name="Grid Import Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("meter_b_in_eq")
        ),
    ),
    HoymilesSensorDescription(
        key="grid_export_energy_today",
        name="Grid Export Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("meter_b_out_eq")
        ),
    ),
    HoymilesSensorDescription(
        key="battery_charge_energy_today",
        name="Battery Charge Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("bms_in_eq")
        ),
        available_fn=has_battery_telemetry,
    ),
    HoymilesSensorDescription(
        key="battery_discharge_energy_today",
        name="Battery Discharge Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("bms_out_eq")
        ),
        available_fn=has_battery_telemetry,
    ),
    HoymilesSensorDescription(
        key="total_consumption_today",
        name="Total Consumption Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("use_eq_total")
        ),
    ),
    HoymilesSensorDescription(
        key="grid_import_total",
        name="Grid Import Total",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("mb_in_eq", {}).get("total_eq")
        ),
    ),
    HoymilesSensorDescription(
        key="grid_export_total",
        name="Grid Export Total",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("mb_out_eq", {}).get("total_eq")
        ),
    ),
    HoymilesSensorDescription(
        key="reported_inverter_count",
        name="Reported Inverter Count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: safe_int_convert(
            data.get("real_time_data", {}).get("reflux_station_data", {}).get("inv_num")
        ),
    ),
    HoymilesSensorDescription(
        key="last_update_time",
        name="Last Data Update Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: parse_timestamp(data.get("real_time_data", {}).get("data_time")),
    ),
    HoymilesSensorDescription(
        key="battery_settings_access",
        name="Battery Settings Access",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (
            "readable"
            if battery_settings_readable(data.get("battery_settings"))
            else data.get("battery_settings", {}).get("error_message")
            or "unavailable"
        ),
    ),
    HoymilesSensorDescription(
        key="pv_string_power",
        name="PV String Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: safe_float_convert(
            get_pv_indicator_value(data.get("pv_indicators", {}), "pv_p_total")
        ),
        available_fn=lambda data: has_pv_indicator(data, "pv_p_total"),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hoymiles Cloud sensor entries."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data["coordinator"]
    stations = runtime_data["stations"]

    entities: list[SensorEntity] = []
    for station_id, station_name in stations.items():
        station_data = coordinator.data.get(station_id, {}) if coordinator.data else {}

        for description in SENSORS:
            entities.append(
                HoymilesSensor(
                    coordinator=coordinator,
                    description=description,
                    station_id=station_id,
                    station_name=station_name,
                )
            )

        if battery_settings_readable(station_data.get("battery_settings", {})):
            entities.append(
                HoymilesBatteryModeSensor(
                    coordinator=coordinator,
                    station_id=station_id,
                    station_name=station_name,
                )
            )

        for channel in discover_pv_channels(station_data.get("pv_indicators", {})):
            entities.extend(
                [
                    HoymilesPVChannelSensor(
                        coordinator=coordinator,
                        station_id=station_id,
                        station_name=station_name,
                        channel=channel,
                        metric="v",
                    ),
                    HoymilesPVChannelSensor(
                        coordinator=coordinator,
                        station_id=station_id,
                        station_name=station_name,
                        channel=channel,
                        metric="i",
                    ),
                    HoymilesPVChannelSensor(
                        coordinator=coordinator,
                        station_id=station_id,
                        station_name=station_name,
                        channel=channel,
                        metric="p",
                    ),
                ]
            )

    async_add_entities(entities)


class HoymilesBaseSensor(CoordinatorEntity, SensorEntity):
    """Base sensor class for station-scoped Hoymiles entities."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the shared station fields."""
        super().__init__(coordinator)
        self._station_id = station_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station_id)},
            "name": station_name,
            "manufacturer": "Hoymiles",
            "model": "Solar Inverter System",
        }

    def _get_station_data(self) -> dict[str, Any]:
        """Return the station payload from the coordinator."""
        return self.coordinator.data.get(self._station_id, {}) if self.coordinator.data else {}


class HoymilesSensor(HoymilesBaseSensor):
    """Representation of a generic Hoymiles sensor."""

    entity_description: HoymilesSensorDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: HoymilesSensorDescription,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, station_id, station_name)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{station_id}_{description.key}"
        self._attr_name = f"{station_name} {description.name}"

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.entity_description.value_fn:
            return None
        try:
            return self.entity_description.value_fn(self._get_station_data())
        except Exception as err:  # pragma: no cover - defensive logging
            _LOGGER.error("Error getting sensor value for %s: %s", self.entity_description.key, err)
            return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False
        if self.entity_description.available_fn:
            return self.entity_description.available_fn(self._get_station_data())
        return bool(self._get_station_data())


class HoymilesBatteryModeSensor(HoymilesBaseSensor):
    """Sensor for displaying the current battery mode."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station_id: str,
        station_name: str,
    ) -> None:
        """Initialize the battery mode sensor."""
        super().__init__(coordinator, station_id, station_name)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_battery_mode"
        self._attr_name = f"{station_name} Battery Mode Status"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the current battery mode."""
        battery_settings = self._get_station_data().get("battery_settings", {})
        mode = battery_settings.get("data", {}).get("mode")
        if mode is None:
            return None
        return BATTERY_MODES.get(mode, f"Unknown ({mode})")

    @property
    def available(self) -> bool:
        """Return whether the battery mode sensor is available."""
        return self.coordinator.last_update_success and battery_settings_readable(
            self._get_station_data().get("battery_settings", {})
        )


class HoymilesPVChannelSensor(HoymilesBaseSensor):
    """Dynamic PV channel sensor discovered from indicator keys."""

    _METRIC_CONFIG = {
        "v": ("Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
        "i": ("Current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
        "p": ("Power", UnitOfPower.WATT, SensorDeviceClass.POWER),
    }

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station_id: str,
        station_name: str,
        channel: int,
        metric: str,
    ) -> None:
        """Initialize the PV channel sensor."""
        super().__init__(coordinator, station_id, station_name)
        label, unit, device_class = self._METRIC_CONFIG[metric]
        self._channel = channel
        self._metric = metric
        self._indicator_key = f"{channel}_pv_{metric}"
        self._attr_unique_id = f"{DOMAIN}_{station_id}_pv{channel}_{metric}"
        self._attr_name = f"{station_name} PV{channel} {label}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        """Return the current indicator value."""
        return safe_float_convert(
            get_pv_indicator_value(
                self._get_station_data().get("pv_indicators", {}),
                self._indicator_key,
            )
        )

    @property
    def available(self) -> bool:
        """Return whether this PV channel is present in the payload."""
        return self.coordinator.last_update_success and has_pv_indicator(
            self._get_station_data(),
            self._indicator_key,
        )
