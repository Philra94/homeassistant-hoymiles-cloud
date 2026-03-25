"""Tests for pure Hoymiles data helpers."""
from tests.module_loader import load_integration_module

data_module = load_integration_module("data")
build_empty_battery_settings = data_module.build_empty_battery_settings
build_station_capabilities = data_module.build_station_capabilities
discover_pv_channels = data_module.discover_pv_channels
get_schedule_modes = data_module.get_schedule_modes


def test_discover_pv_channels_supports_more_than_two_inputs() -> None:
    """PV indicator discovery should not be limited to two strings."""
    pv_indicators = {
        "list": [
            {"key": "1_pv_v", "val": "42.1"},
            {"key": "2_pv_v", "val": "41.9"},
            {"key": "3_pv_p", "val": "350"},
            {"key": "4_pv_i", "val": "8.2"},
            {"key": "pv_p_total", "val": "1500"},
        ]
    }

    assert discover_pv_channels(pv_indicators) == [1, 2, 3, 4]


def test_build_station_capabilities_keeps_battery_telemetry_separate() -> None:
    """Battery telemetry should remain available when settings are denied."""
    capabilities = build_station_capabilities(
        real_time_data={"reflux_station_data": {"bms_power": "715.0", "bms_soc": "62"}},
        pv_indicators={"list": [{"key": "1_pv_v", "val": "42.1"}]},
        battery_settings=build_empty_battery_settings(
            readable=False,
            writable=False,
            status="3",
            message="No Permission.",
        ),
        microinverters_data={},
    )

    assert capabilities["battery_telemetry"] is True
    assert capabilities["battery_settings_readable"] is False
    assert capabilities["battery_settings_writable"] is False
    assert capabilities["pv_channels"] == [1]


def test_get_schedule_modes_only_returns_known_schedule_modes() -> None:
    """Only Economy and Time of Use should be flagged as schedule modes."""
    battery_settings = build_empty_battery_settings(readable=True, writable=True)
    battery_settings["available_modes"] = [1, 2, 7, 8]
    battery_settings["mode_data"] = {
        "k_1": {"reserve_soc": 10},
        "k_2": {"reserve_soc": 10, "date": []},
        "k_7": {"reserve_soc": 35, "max_soc": 70},
        "k_8": {"reserve_soc": 10, "time": []},
    }

    assert get_schedule_modes(battery_settings) == [2, 8]
