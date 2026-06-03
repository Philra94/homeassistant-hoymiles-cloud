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
    UnitOfFrequency,
    UnitOfMass,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import BATTERY_MODES, DOMAIN, METER_LOCATION_NAMES
from .data import (
    battery_settings_readable,
    discover_pv_channels,
    get_allowed_battery_modes,
    get_energy_flow_value,
    get_indicator_value,
    get_mode_settings,
    get_schedule_modes,
    get_supported_modes,
    get_pv_indicator_value,
)
from .device import (
    build_battery_device_info,
    build_dtu_device_info,
    build_inverter_device_info,
    build_meter_device_info,
    build_primary_battery_device_info,
    build_primary_inverter_device_info,
    build_station_device_info,
)
from .schedule_editor import (
    get_editor_state,
    get_mode_entry_count,
    get_mode_state,
    get_selected_editor_mode,
    get_selected_schedule_dirty,
    get_selected_schedule_validation,
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


def get_station_data(coordinator: DataUpdateCoordinator, station_id: str) -> dict[str, Any]:
    """Return one station payload from the coordinator."""
    return coordinator.data.get(station_id, {}) if coordinator.data else {}


def get_reflux_data(station_data: dict[str, Any]) -> dict[str, Any]:
    """Return the live reflux payload."""
    return station_data.get("real_time_data", {}).get("reflux_station_data", {})


def get_nested_energy_total(station_data: dict[str, Any], key: str, period: str) -> int | None:
    """Return one nested energy total from the reflux data."""
    return safe_int_convert(get_reflux_data(station_data).get(key, {}).get(period))


def is_battery_charging(station_data: dict[str, Any]) -> bool | None:
    """Determine whether the battery is charging based on live flows."""
    reflux_data = get_reflux_data(station_data)
    bms_power = safe_float_convert(reflux_data.get("bms_power"))
    if bms_power is not None:
        return bms_power > 0
    return None


def has_pv_indicator(station_data: dict[str, Any], key: str) -> bool:
    """Return whether a PV indicator key is present."""
    return get_pv_indicator_value(station_data.get("pv_indicators", {}), key) is not None


def has_grid_indicator(station_data: dict[str, Any], key: str) -> bool:
    """Return whether a grid indicator key is present."""
    return get_indicator_value(station_data.get("grid_indicators", {}), key) is not None


def has_battery_telemetry(station_data: dict[str, Any]) -> bool:
    """Return whether battery telemetry is available for the station."""
    return bool(station_data.get("capabilities", {}).get("battery_telemetry"))


def has_energy_flow(station_data: dict[str, Any]) -> bool:
    """Return whether energy-flow stats are available."""
    return bool(station_data.get("capabilities", {}).get("energy_flow_available"))


def has_eps_settings(station_data: dict[str, Any]) -> bool:
    """Return whether EPS settings are available."""
    return bool(station_data.get("capabilities", {}).get("eps_available"))


def has_eps_profit(station_data: dict[str, Any]) -> bool:
    """Return whether EPS profit metrics are available."""
    return bool(station_data.get("capabilities", {}).get("eps_profit_available"))


def get_station_device_info(station_id: str, station_name: str, station_data: dict[str, Any]) -> dict[str, Any]:
    """Return station device info."""
    return build_station_device_info(station_id, station_name, station_data.get("station_info"))


def get_battery_device_info(station_id: str, station_name: str, station_data: dict[str, Any]) -> dict[str, Any]:
    """Return aggregate battery device info."""
    return build_primary_battery_device_info(station_id, station_name, station_data)


def get_inverter_device_info(station_id: str, station_name: str, station_data: dict[str, Any]) -> dict[str, Any]:
    """Return aggregate inverter device info."""
    return build_primary_inverter_device_info(station_id, station_name, station_data)


def compute_self_consumption_rate(station_data: dict[str, Any]) -> float | None:
    """Return the PV self-consumption ratio in percent."""
    pv_to_load = safe_float_convert(get_energy_flow_value(station_data.get("energy_flow"), "p2l"))
    total_pv = safe_float_convert(station_data.get("real_time_data", {}).get("today_eq"))
    if pv_to_load is None or total_pv in (None, 0):
        return None
    return round((pv_to_load / total_pv) * 100, 2)


def compute_self_sufficiency_rate(station_data: dict[str, Any]) -> float | None:
    """Return the self-sufficiency ratio in percent."""
    load_from_pv = safe_float_convert(get_energy_flow_value(station_data.get("energy_flow"), "lfp")) or 0.0
    load_from_battery = safe_float_convert(get_energy_flow_value(station_data.get("energy_flow"), "lfb")) or 0.0
    load_from_grid = safe_float_convert(get_energy_flow_value(station_data.get("energy_flow"), "lfg")) or 0.0
    total_load = load_from_pv + load_from_battery + load_from_grid
    if total_load <= 0:
        return None
    return round((1 - (load_from_grid / total_load)) * 100, 2)


@dataclass
class HoymilesSensorDescription(SensorEntityDescription):
    """Declarative description for station or aggregate sensors."""

    value_fn: Callable[[dict[str, Any]], StateType] | None = None
    exists_fn: Callable[[dict[str, Any]], bool] | None = None
    device_info_fn: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None


STATION_SENSORS: list[HoymilesSensorDescription] = [
    HoymilesSensorDescription(
        key="pv_power",
        name="PV Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: safe_float_convert(data.get("real_time_data", {}).get("real_power")),
    ),
    HoymilesSensorDescription(
        key="grid_power",
        name="Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: safe_float_convert(get_reflux_data(data).get("grid_power")),
    ),
    HoymilesSensorDescription(
        key="load_power",
        name="Load Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: safe_float_convert(get_reflux_data(data).get("load_power")),
    ),
    HoymilesSensorDescription(
        key="battery_power",
        name="Battery Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=has_battery_telemetry,
        device_info_fn=get_battery_device_info,
        value_fn=lambda data: safe_float_convert(get_reflux_data(data).get("bms_power")),
    ),
    HoymilesSensorDescription(
        key="battery_flow_direction",
        name="Battery Flow Direction",
        icon="mdi:battery-charging",
        exists_fn=has_battery_telemetry,
        device_info_fn=get_battery_device_info,
        value_fn=lambda data: (
            "discharging"
            if is_battery_charging(data) is False
            else "charging"
            if is_battery_charging(data) is True
            else "unknown"
        ),
    ),
    HoymilesSensorDescription(
        key="battery_soc",
        name="Battery State of Charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=has_battery_telemetry,
        device_info_fn=get_battery_device_info,
        value_fn=lambda data: safe_int_convert(get_reflux_data(data).get("bms_soc")),
    ),
    HoymilesSensorDescription(
        key="co2_emission_reduction",
        name="CO2 Emission Reduction",
        native_unit_of_measurement=UnitOfMass.GRAMS,
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_float_convert(data.get("real_time_data", {}).get("co2_emission_reduction")),
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
        value_fn=lambda data: safe_int_convert(get_reflux_data(data).get("pv_to_load_eq")),
    ),
    HoymilesSensorDescription(
        key="grid_import_energy_today",
        name="Grid Import Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(get_reflux_data(data).get("meter_b_in_eq")),
    ),
    HoymilesSensorDescription(
        key="grid_export_energy_today",
        name="Grid Export Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(get_reflux_data(data).get("meter_b_out_eq")),
    ),
    HoymilesSensorDescription(
        key="battery_charge_energy_today",
        name="Battery Charge Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        exists_fn=has_battery_telemetry,
        device_info_fn=get_battery_device_info,
        value_fn=lambda data: safe_int_convert(get_reflux_data(data).get("bms_in_eq")),
    ),
    HoymilesSensorDescription(
        key="battery_discharge_energy_today",
        name="Battery Discharge Energy Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        exists_fn=has_battery_telemetry,
        device_info_fn=get_battery_device_info,
        value_fn=lambda data: safe_int_convert(get_reflux_data(data).get("bms_out_eq")),
    ),
    HoymilesSensorDescription(
        key="total_consumption_today",
        name="Total Consumption Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: safe_int_convert(get_reflux_data(data).get("use_eq_total")),
    ),
    HoymilesSensorDescription(
        key="grid_import_total",
        name="Grid Import Total",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: get_nested_energy_total(data, "mb_in_eq", "total_eq"),
    ),
    HoymilesSensorDescription(
        key="grid_export_total",
        name="Grid Export Total",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: get_nested_energy_total(data, "mb_out_eq", "total_eq"),
    ),
    HoymilesSensorDescription(
        key="grid_import_month",
        name="Grid Import Month",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: get_nested_energy_total(data, "mb_in_eq", "month_eq"),
    ),
    HoymilesSensorDescription(
        key="grid_import_year",
        name="Grid Import Year",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: get_nested_energy_total(data, "mb_in_eq", "year_eq"),
    ),
    HoymilesSensorDescription(
        key="grid_export_month",
        name="Grid Export Month",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: get_nested_energy_total(data, "mb_out_eq", "month_eq"),
    ),
    HoymilesSensorDescription(
        key="grid_export_year",
        name="Grid Export Year",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: get_nested_energy_total(data, "mb_out_eq", "year_eq"),
    ),
    HoymilesSensorDescription(
        key="pv_to_battery_today",
        name="PV to Battery Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        exists_fn=has_energy_flow,
        value_fn=lambda data: safe_float_convert(get_energy_flow_value(data.get("energy_flow"), "p2b")),
    ),
    HoymilesSensorDescription(
        key="pv_to_grid_today",
        name="PV to Grid Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        exists_fn=has_energy_flow,
        value_fn=lambda data: safe_float_convert(get_energy_flow_value(data.get("energy_flow"), "p2g")),
    ),
    HoymilesSensorDescription(
        key="pv_to_load_today",
        name="PV to Load Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        exists_fn=has_energy_flow,
        value_fn=lambda data: safe_float_convert(get_energy_flow_value(data.get("energy_flow"), "p2l")),
    ),
    HoymilesSensorDescription(
        key="load_from_pv",
        name="Load from PV",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        exists_fn=has_energy_flow,
        value_fn=lambda data: safe_float_convert(get_energy_flow_value(data.get("energy_flow"), "lfp")),
    ),
    HoymilesSensorDescription(
        key="load_from_battery",
        name="Load from Battery",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        exists_fn=has_energy_flow,
        value_fn=lambda data: safe_float_convert(get_energy_flow_value(data.get("energy_flow"), "lfb")),
    ),
    HoymilesSensorDescription(
        key="load_from_grid",
        name="Load from Grid",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        exists_fn=has_energy_flow,
        value_fn=lambda data: safe_float_convert(get_energy_flow_value(data.get("energy_flow"), "lfg")),
    ),
    HoymilesSensorDescription(
        key="ev_charger_power",
        name="EV Charger Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=lambda data: safe_float_convert(get_reflux_data(data).get("pile_power")) is not None,
        value_fn=lambda data: safe_float_convert(get_reflux_data(data).get("pile_power")),
    ),
    HoymilesSensorDescription(
        key="self_consumption_rate",
        name="Self Consumption Rate",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=has_energy_flow,
        value_fn=compute_self_consumption_rate,
    ),
    HoymilesSensorDescription(
        key="self_sufficiency_rate",
        name="Self Sufficiency Rate",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=has_energy_flow,
        value_fn=compute_self_sufficiency_rate,
    ),
    HoymilesSensorDescription(
        key="electricity_buy_price",
        name="Electricity Buy Price",
        exists_fn=has_eps_settings,
        suggested_display_precision=4,
        value_fn=lambda data: safe_float_convert(data.get("eps_settings", {}).get("details", {}).get("p")),
    ),
    HoymilesSensorDescription(
        key="electricity_sell_price",
        name="Electricity Sell Price",
        exists_fn=has_eps_settings,
        suggested_display_precision=4,
        value_fn=lambda data: safe_float_convert(data.get("eps_settings", {}).get("details", {}).get("sep")),
    ),
    HoymilesSensorDescription(
        key="today_profit",
        name="Today's Profit",
        exists_fn=has_eps_profit,
        suggested_display_precision=3,
        value_fn=lambda data: safe_float_convert(data.get("eps_profit", {}).get("today_profit")),
    ),
    HoymilesSensorDescription(
        key="monthly_profit",
        name="Monthly Profit",
        exists_fn=has_eps_profit,
        suggested_display_precision=3,
        value_fn=lambda data: safe_float_convert(data.get("eps_profit", {}).get("monthly_profit")),
    ),
    HoymilesSensorDescription(
        key="yearly_profit",
        name="Yearly Profit",
        exists_fn=has_eps_profit,
        suggested_display_precision=3,
        value_fn=lambda data: safe_float_convert(data.get("eps_profit", {}).get("yearly_profit")),
    ),
    HoymilesSensorDescription(
        key="total_profit",
        name="Total Profit",
        exists_fn=has_eps_profit,
        suggested_display_precision=3,
        value_fn=lambda data: safe_float_convert(data.get("eps_profit", {}).get("total_profit")),
    ),
    HoymilesSensorDescription(
        key="today_spend",
        name="Today's Spend",
        exists_fn=has_eps_profit,
        suggested_display_precision=3,
        value_fn=lambda data: safe_float_convert(data.get("eps_profit", {}).get("today_spend")),
    ),
    HoymilesSensorDescription(
        key="monthly_spend",
        name="Monthly Spend",
        exists_fn=has_eps_profit,
        suggested_display_precision=3,
        value_fn=lambda data: safe_float_convert(data.get("eps_profit", {}).get("monthly_spend")),
    ),
    HoymilesSensorDescription(
        key="yearly_spend",
        name="Yearly Spend",
        exists_fn=has_eps_profit,
        suggested_display_precision=3,
        value_fn=lambda data: safe_float_convert(data.get("eps_profit", {}).get("yearly_spend")),
    ),
    HoymilesSensorDescription(
        key="total_spend",
        name="Total Spend",
        exists_fn=has_eps_profit,
        suggested_display_precision=3,
        value_fn=lambda data: safe_float_convert(data.get("eps_profit", {}).get("total_spend")),
    ),
    HoymilesSensorDescription(
        key="ai_status",
        name="AI Mode Status",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data: bool(data.get("capabilities", {}).get("ai_available")),
        value_fn=lambda data: "active" if data.get("ai_status", {}).get("ai") == 1 else "inactive",
    ),
    HoymilesSensorDescription(
        key="ai_compound_mode",
        name="AI Compound Mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data: bool(data.get("capabilities", {}).get("ai_available")),
        value_fn=lambda data: data.get("ai_status", {}).get("compound_mode"),
    ),
    HoymilesSensorDescription(
        key="firmware_status",
        name="Firmware Status",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data: bool(data.get("capabilities", {}).get("firmware_available")),
        value_fn=lambda data: (
            "update_available"
            if safe_int_convert(data.get("firmware", {}).get("upgrade")) not in (None, 0)
            else "up_to_date"
        ),
    ),
    HoymilesSensorDescription(
        key="reported_inverter_count",
        name="Reported Inverter Count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: safe_int_convert(get_reflux_data(data).get("inv_num")),
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
            else data.get("battery_settings", {}).get("error_message") or "unavailable"
        ),
    ),
    HoymilesSensorDescription(
        key="pv_string_power",
        name="PV String Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=lambda data: has_pv_indicator(data, "pv_p_total"),
        device_info_fn=get_inverter_device_info,
        value_fn=lambda data: safe_float_convert(get_pv_indicator_value(data.get("pv_indicators", {}), "pv_p_total")),
    ),
]

GRID_INDICATOR_SPECS = [
    ("grid_frequency", "Grid Frequency", "frequency", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY, 2),
    ("grid_voltage_l1", "Grid Voltage L1", "v_a", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, 1),
    ("grid_voltage_l2", "Grid Voltage L2", "v_b", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, 1),
    ("grid_voltage_l3", "Grid Voltage L3", "v_c", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, 1),
    ("grid_current_l1", "Grid Current L1", "i_a", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, 2),
    ("grid_current_l2", "Grid Current L2", "i_b", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, 2),
    ("grid_current_l3", "Grid Current L3", "i_c", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, 2),
    ("grid_power_l1", "Grid Power L1", "p_a", UnitOfPower.WATT, SensorDeviceClass.POWER, 2),
    ("grid_power_l2", "Grid Power L2", "p_b", UnitOfPower.WATT, SensorDeviceClass.POWER, 2),
    ("grid_power_l3", "Grid Power L3", "p_c", UnitOfPower.WATT, SensorDeviceClass.POWER, 2),
    ("grid_power_factor_l1", "Grid Power Factor L1", "pf_a", None, None, 3),
    ("grid_power_factor_l2", "Grid Power Factor L2", "pf_b", None, None, 3),
    ("grid_power_factor_l3", "Grid Power Factor L3", "pf_c", None, None, 3),
    ("grid_state", "Grid State", "grid_state", None, None, None),
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
        station_data = get_station_data(coordinator, station_id)

        for description in STATION_SENSORS:
            if description.exists_fn and not description.exists_fn(station_data):
                continue
            entities.append(
                HoymilesAggregateSensor(
                    coordinator=coordinator,
                    description=description,
                    station_id=station_id,
                    station_name=station_name,
                )
            )

        if battery_settings_readable(station_data.get("battery_settings", {})):
            entities.append(HoymilesBatteryModeSensor(coordinator, station_id, station_name))

        if station_data.get("schedule_editor", {}).get("available_modes"):
            entities.extend(
                [
                    HoymilesScheduleEditorModeSensor(coordinator, station_id, station_name),
                    HoymilesScheduleSummarySensor(coordinator, station_id, station_name, 2),
                    HoymilesScheduleSummarySensor(coordinator, station_id, station_name, 8),
                    HoymilesScheduleCountSensor(coordinator, station_id, station_name, 2),
                    HoymilesScheduleCountSensor(coordinator, station_id, station_name, 8),
                    HoymilesScheduleEditorValidationSensor(coordinator, station_id, station_name),
                    HoymilesScheduleEditorDirtySensor(coordinator, station_id, station_name),
                ]
            )

        for channel in discover_pv_channels(station_data.get("pv_indicators", {})):
            entities.extend(
                [
                    HoymilesPVChannelSensor(coordinator, station_id, station_name, channel, "v"),
                    HoymilesPVChannelSensor(coordinator, station_id, station_name, channel, "i"),
                    HoymilesPVChannelSensor(coordinator, station_id, station_name, channel, "p"),
                ]
            )

        for entity_key, label, indicator_key, unit, device_class, precision in GRID_INDICATOR_SPECS:
            if has_grid_indicator(station_data, indicator_key):
                entities.append(
                    HoymilesGridIndicatorSensor(
                        coordinator,
                        station_id,
                        station_name,
                        entity_key,
                        label,
                        indicator_key,
                        unit,
                        device_class,
                        precision,
                    )
                )

        for inverter in station_data.get("devices", {}).get("inverters", []):
            entities.extend(
                [
                    HoymilesDeviceAttributeSensor(
                        coordinator,
                        station_id,
                        station_name,
                        "inverters",
                        inverter,
                        "model",
                        "Inverter Model",
                        "model_no",
                        build_inverter_device_info,
                    ),
                    HoymilesDeviceAttributeSensor(
                        coordinator,
                        station_id,
                        station_name,
                        "inverters",
                        inverter,
                        "firmware",
                        "Inverter Firmware Version",
                        "soft_ver",
                        build_inverter_device_info,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        enabled_default=False,
                    ),
                    HoymilesDeviceAttributeSensor(
                        coordinator,
                        station_id,
                        station_name,
                        "inverters",
                        inverter,
                        "hardware",
                        "Inverter Hardware Version",
                        "hard_ver",
                        build_inverter_device_info,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        enabled_default=False,
                    ),
                ]
            )

        for battery in station_data.get("devices", {}).get("batteries", []):
            entities.extend(
                [
                    HoymilesDeviceAttributeSensor(
                        coordinator,
                        station_id,
                        station_name,
                        "batteries",
                        battery,
                        "capacity",
                        "Battery Capacity",
                        "cap",
                        build_battery_device_info,
                    ),
                    HoymilesDeviceAttributeSensor(
                        coordinator,
                        station_id,
                        station_name,
                        "batteries",
                        battery,
                        "bms_type",
                        "Battery BMS Type",
                        "bms_type",
                        build_battery_device_info,
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                    HoymilesDeviceAttributeSensor(
                        coordinator,
                        station_id,
                        station_name,
                        "batteries",
                        battery,
                        "firmware",
                        "Battery Firmware Version",
                        "soft_ver",
                        build_battery_device_info,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        enabled_default=False,
                    ),
                    HoymilesDeviceAttributeSensor(
                        coordinator,
                        station_id,
                        station_name,
                        "batteries",
                        battery,
                        "hardware",
                        "Battery Hardware Version",
                        "hard_ver",
                        build_battery_device_info,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        enabled_default=False,
                    ),
                ]
            )

        for meter in station_data.get("devices", {}).get("meters", []):
            entities.extend(
                [
                    HoymilesDeviceAttributeSensor(
                        coordinator,
                        station_id,
                        station_name,
                        "meters",
                        meter,
                        "location",
                        "Meter Location",
                        "location",
                        build_meter_device_info,
                        value_transform=lambda value: METER_LOCATION_NAMES.get(value, str(value)),
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                    HoymilesDeviceAttributeSensor(
                        coordinator,
                        station_id,
                        station_name,
                        "meters",
                        meter,
                        "ct_gain",
                        "Meter CT Gain",
                        "ct_gain",
                        build_meter_device_info,
                        value_transform=safe_float_convert,
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ]
            )

        for dtu in station_data.get("devices", {}).get("dtus", []):
            entities.extend(
                [
                    HoymilesDeviceAttributeSensor(
                        coordinator,
                        station_id,
                        station_name,
                        "dtus",
                        dtu,
                        "serial",
                        "DTU Serial",
                        "sn",
                        build_dtu_device_info,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        enabled_default=False,
                    ),
                    HoymilesDeviceAttributeSensor(
                        coordinator,
                        station_id,
                        station_name,
                        "dtus",
                        dtu,
                        "device_type",
                        "DTU Device Type",
                        "type",
                        build_dtu_device_info,
                        entity_category=EntityCategory.DIAGNOSTIC,
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
        self._station_name = station_name

    def _get_station_data(self) -> dict[str, Any]:
        """Return the station payload from the coordinator."""
        return get_station_data(self.coordinator, self._station_id)


class HoymilesAggregateSensor(HoymilesBaseSensor):
    """Representation of a generic aggregate sensor."""

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
        station_data = self._get_station_data()
        self._attr_unique_id = f"{DOMAIN}_{station_id}_{description.key}"
        self._attr_name = f"{station_name} {description.name}"
        self._attr_device_info = (
            description.device_info_fn(station_id, station_name, station_data)
            if description.device_info_fn
            else get_station_device_info(station_id, station_name, station_data)
        )

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
        if self.entity_description.exists_fn:
            return self.entity_description.exists_fn(self._get_station_data())
        return bool(self._get_station_data())


class HoymilesBatteryModeSensor(HoymilesBaseSensor):
    """Sensor for displaying the current battery mode."""

    def __init__(self, coordinator: DataUpdateCoordinator, station_id: str, station_name: str) -> None:
        """Initialize the battery mode sensor."""
        super().__init__(coordinator, station_id, station_name)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_battery_mode"
        self._attr_name = f"{station_name} Battery Mode Status"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = get_battery_device_info(station_id, station_name, self._get_station_data())

    @property
    def native_value(self) -> str | None:
        """Return the current battery mode."""
        battery_settings = self._get_station_data().get("battery_settings", {})
        mode = battery_settings.get("data", {}).get("mode")
        if mode is None:
            return None
        return BATTERY_MODES.get(mode, f"Unknown ({mode})")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the supported battery modes for diagnostics."""
        station_data = self._get_station_data()
        battery_settings = station_data.get("battery_settings", {})
        setting_rules = station_data.get("setting_rules", {})
        return {
            "mode_id": battery_settings.get("data", {}).get("mode"),
            "supported_modes": get_supported_modes(battery_settings),
            "allowed_modes": get_allowed_battery_modes(battery_settings, setting_rules),
            "schedule_modes": get_schedule_modes(battery_settings),
        }

    @property
    def available(self) -> bool:
        """Return whether the battery mode sensor is available."""
        return self.coordinator.last_update_success and battery_settings_readable(
            self._get_station_data().get("battery_settings", {})
        )


class HoymilesDeviceAttributeSensor(HoymilesBaseSensor):
    """Diagnostic sensor for a specific child-device attribute."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station_id: str,
        station_name: str,
        device_kind: str,
        device: dict[str, Any],
        entity_key: str,
        label: str,
        state_key: str,
        device_info_builder: Callable[[str, str, dict[str, Any]], dict[str, Any]],
        *,
        value_transform: Callable[[Any], Any] | None = None,
        entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC,
        enabled_default: bool = True,
    ) -> None:
        """Initialize the device attribute sensor."""
        super().__init__(coordinator, station_id, station_name)
        self._device_kind = device_kind
        self._state_key = state_key
        self._value_transform = value_transform or (lambda value: value)
        self._entity_category = entity_category
        self._match_value = str(device.get("sn") or device.get("id") or "")
        self._attr_unique_id = f"{DOMAIN}_{station_id}_{device_kind}_{self._match_value}_{entity_key}"
        self._attr_name = f"{station_name} {label}"
        self._attr_entity_category = entity_category
        self._attr_entity_registry_enabled_default = enabled_default
        self._attr_device_info = device_info_builder(station_id, station_name, device)

    def _get_device(self) -> dict[str, Any] | None:
        """Return the current matching device payload."""
        for device in self._get_station_data().get("devices", {}).get(self._device_kind, []):
            if str(device.get("sn") or device.get("id") or "") == self._match_value:
                return device
        return None

    @property
    def native_value(self) -> StateType:
        """Return the device attribute value."""
        device = self._get_device()
        if not device:
            return None
        return self._value_transform(device.get(self._state_key))

    @property
    def available(self) -> bool:
        """Return whether the device attribute is available."""
        return self.coordinator.last_update_success and self._get_device() is not None


class HoymilesPVChannelSensor(HoymilesBaseSensor):
    """Dynamic PV channel sensor discovered from indicator keys."""

    _METRIC_CONFIG = {
        "v": ("Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, 1),
        "i": ("Current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, 2),
        "p": ("Power", UnitOfPower.WATT, SensorDeviceClass.POWER, 2),
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
        label, unit, device_class, precision = self._METRIC_CONFIG[metric]
        self._channel = channel
        self._metric = metric
        self._indicator_key = f"{channel}_pv_{metric}"
        self._attr_unique_id = f"{DOMAIN}_{station_id}_pv{channel}_{metric}"
        self._attr_name = f"{station_name} PV{channel} {label}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = precision
        self._attr_device_info = get_inverter_device_info(station_id, station_name, self._get_station_data())

    @property
    def native_value(self) -> float | None:
        """Return the current indicator value."""
        return safe_float_convert(
            get_pv_indicator_value(self._get_station_data().get("pv_indicators", {}), self._indicator_key)
        )

    @property
    def available(self) -> bool:
        """Return whether this PV channel is present in the payload."""
        return self.coordinator.last_update_success and has_pv_indicator(self._get_station_data(), self._indicator_key)


class HoymilesGridIndicatorSensor(HoymilesBaseSensor):
    """Sensor backed by grid indicator payload values."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station_id: str,
        station_name: str,
        entity_key: str,
        label: str,
        indicator_key: str,
        unit,
        device_class,
        suggested_display_precision: int | None,
    ) -> None:
        """Initialize the grid indicator sensor."""
        super().__init__(coordinator, station_id, station_name)
        self._indicator_key = indicator_key
        self._attr_unique_id = f"{DOMAIN}_{station_id}_{entity_key}"
        self._attr_name = f"{station_name} {label}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = SensorStateClass.MEASUREMENT if unit is not None else None
        self._attr_suggested_display_precision = suggested_display_precision
        self._attr_device_info = get_inverter_device_info(station_id, station_name, self._get_station_data())

    @property
    def native_value(self) -> StateType:
        """Return the current grid-indicator value."""
        value = get_indicator_value(self._get_station_data().get("grid_indicators", {}), self._indicator_key)
        if self._attr_native_unit_of_measurement is None:
            return value
        return safe_float_convert(value)

    @property
    def available(self) -> bool:
        """Return whether the indicator is present in the payload."""
        return self.coordinator.last_update_success and has_grid_indicator(self._get_station_data(), self._indicator_key)


class HoymilesScheduleEditorModeSensor(HoymilesBaseSensor):
    """Diagnostic sensor for the selected schedule editor mode."""

    def __init__(self, coordinator, station_id: str, station_name: str) -> None:
        super().__init__(coordinator, station_id, station_name)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_schedule_editor_mode_status"
        self._attr_name = f"{station_name} Current Schedule Editor Mode"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = get_station_device_info(station_id, station_name, self._get_station_data())

    @property
    def native_value(self) -> str | None:
        """Return the selected schedule editor mode."""
        mode = get_selected_editor_mode(self._get_station_data())
        return BATTERY_MODES.get(mode, f"Unknown ({mode})") if mode is not None else None

    @property
    def available(self) -> bool:
        """Return whether a schedule editor mode exists."""
        return self.coordinator.last_update_success and bool(
            self._get_station_data().get("schedule_editor", {}).get("available_modes")
        )


class HoymilesScheduleSummarySensor(HoymilesBaseSensor):
    """Sensor exposing a human-readable schedule summary for one mode."""

    def __init__(self, coordinator, station_id: str, station_name: str, mode: int) -> None:
        super().__init__(coordinator, station_id, station_name)
        mode_label = "economy" if mode == 2 else "time_of_use"
        self._mode = mode
        self._attr_unique_id = f"{DOMAIN}_{station_id}_{mode_label}_schedule_summary"
        self._attr_name = f"{station_name} {'Economy' if mode == 2 else 'Time of Use'} Schedule Summary"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = get_station_device_info(station_id, station_name, self._get_station_data())

    @property
    def native_value(self) -> str | None:
        """Return the schedule summary text."""
        return get_mode_state(self._get_station_data(), self._mode).get("summary")

    @property
    def available(self) -> bool:
        """Return whether the schedule mode is available."""
        return self.coordinator.last_update_success and bool(get_mode_state(self._get_station_data(), self._mode))


class HoymilesScheduleCountSensor(HoymilesBaseSensor):
    """Sensor exposing the number of schedule rows for one mode."""

    def __init__(self, coordinator, station_id: str, station_name: str, mode: int) -> None:
        super().__init__(coordinator, station_id, station_name)
        mode_label = "economy" if mode == 2 else "time_of_use"
        self._mode = mode
        self._attr_unique_id = f"{DOMAIN}_{station_id}_{mode_label}_schedule_count"
        self._attr_name = f"{station_name} {'Economy' if mode == 2 else 'Time of Use'} Schedule Count"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = get_station_device_info(station_id, station_name, self._get_station_data())

    @property
    def native_value(self) -> int:
        """Return the number of top-level schedule rows."""
        return get_mode_entry_count(self._get_station_data(), self._mode)

    @property
    def available(self) -> bool:
        """Return whether the schedule mode is available."""
        return self.coordinator.last_update_success and bool(get_mode_state(self._get_station_data(), self._mode))


class HoymilesScheduleEditorValidationSensor(HoymilesBaseSensor):
    """Sensor exposing current schedule draft validation state."""

    def __init__(self, coordinator, station_id: str, station_name: str) -> None:
        super().__init__(coordinator, station_id, station_name)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_schedule_editor_validation"
        self._attr_name = f"{station_name} Schedule Editor Validation Status"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = get_station_device_info(station_id, station_name, self._get_station_data())

    @property
    def native_value(self) -> str:
        """Return the current validation status."""
        return get_selected_schedule_validation(self._get_station_data())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the full validation error list for the selected mode."""
        editor_state = get_editor_state(self._get_station_data())
        return {
            "errors": editor_state.get("validation_errors", []),
            "selected_mode": editor_state.get("selected_mode"),
        }

    @property
    def available(self) -> bool:
        """Return whether schedule editor data is available."""
        return self.coordinator.last_update_success and bool(
            self._get_station_data().get("schedule_editor", {}).get("available_modes")
        )


class HoymilesScheduleEditorDirtySensor(HoymilesBaseSensor):
    """Sensor exposing whether the selected draft differs from the live payload."""

    def __init__(self, coordinator, station_id: str, station_name: str) -> None:
        super().__init__(coordinator, station_id, station_name)
        self._attr_unique_id = f"{DOMAIN}_{station_id}_schedule_editor_dirty"
        self._attr_name = f"{station_name} Schedule Editor Dirty State"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = get_station_device_info(station_id, station_name, self._get_station_data())

    @property
    def native_value(self) -> str:
        """Return clean or dirty for the selected schedule draft."""
        return "dirty" if get_selected_schedule_dirty(self._get_station_data()) else "clean"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose aggregate dirty information across schedule modes."""
        editor_state = get_editor_state(self._get_station_data())
        return {
            "dirty": editor_state.get("dirty", False),
            "selected_mode": editor_state.get("selected_mode"),
        }

    @property
    def available(self) -> bool:
        """Return whether schedule editor data is available."""
        return self.coordinator.last_update_success and bool(
            self._get_station_data().get("schedule_editor", {}).get("available_modes")
        )
