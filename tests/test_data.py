"""Tests for pure Hoymiles data helpers."""
from tests.module_loader import load_integration_module

data_module = load_integration_module("data")
build_empty_battery_settings = data_module.build_empty_battery_settings
build_empty_relay_settings = data_module.build_empty_relay_settings
build_schedule_editor_state = data_module.build_schedule_editor_state
build_schedule_payload_from_draft = data_module.build_schedule_payload_from_draft
build_station_capabilities = data_module.build_station_capabilities
discover_pv_channels = data_module.discover_pv_channels
get_allowed_battery_modes = data_module.get_allowed_battery_modes
get_schedule_modes = data_module.get_schedule_modes
relay_settings_enabled = data_module.relay_settings_enabled
validate_schedule_draft = data_module.validate_schedule_draft


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
        relay_settings=build_empty_relay_settings(
            readable=True,
            writable=True,
        ),
        devices={"batteries": [{"sn": "BAT-1"}], "meters": [{"location": 2}], "dtus": [], "inverters": []},
        setting_rules={"ctl_mode_set": [1, 8]},
        eps_settings={"details": {"p": "0.31", "sep": "0.11"}},
        ai_status={"ai": 1},
        microinverters_data={},
    )

    assert capabilities["battery_telemetry"] is True
    assert capabilities["battery_settings_readable"] is False
    assert capabilities["battery_settings_writable"] is False
    assert capabilities["relay_settings_readable"] is True
    assert capabilities["has_battery"] is True
    assert capabilities["has_meter"] is True
    assert capabilities["eps_available"] is True
    assert capabilities["ai_available"] is True
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


def test_build_schedule_editor_state_marks_tou_draft_dirty() -> None:
    """Stored schedule edits should be reflected in the derived editor state."""
    battery_settings = build_empty_battery_settings(readable=True, writable=True)
    battery_settings["available_modes"] = [2, 8]
    battery_settings["mode_data"] = {
        "k_2": {
            "reserve_soc": 10,
            "money_code": "$",
            "date": [
                {
                    "start_date": "01-01",
                    "end_date": "12-31",
                    "time": [
                        {"week": [1, 2, 3, 4, 5], "duration": []},
                        {"week": [6, 7], "duration": []},
                    ],
                }
            ],
        },
        "k_8": {
            "reserve_soc": 10,
            "time": [
                {
                    "cs_time": "03:00",
                    "ce_time": "05:00",
                    "c_power": 100,
                    "dcs_time": "05:00",
                    "dce_time": "03:00",
                    "dc_power": 100,
                    "charge_soc": 90,
                    "dis_charge_soc": 10,
                }
            ],
        },
    }
    battery_settings["data"] = {"mode": 8}

    editor = build_schedule_editor_state(
        battery_settings,
        {
            "schedule_editor": {
                "selected_mode": 8,
                "modes": {
                    "8": {
                        "periods": [
                            {
                                "cs_time": "04:00",
                                "ce_time": "05:00",
                                "c_power": 100,
                                "dcs_time": "05:00",
                                "dce_time": "03:00",
                                "dc_power": 100,
                                "charge_soc": 90,
                                "dis_charge_soc": 10,
                            }
                        ]
                    }
                },
            }
        },
    )

    assert editor["selected_mode"] == 8
    assert editor["dirty"] is True
    assert editor["modes"][8]["dirty"] is True
    assert "04:00-05:00" in editor["modes"][8]["summary"]


def test_build_schedule_payload_from_economy_draft_preserves_full_shape() -> None:
    """Economy drafts should serialize back into the nested date/time/duration shape."""
    draft = {
        "money_code": "$",
        "date_windows": [
            {
                "start_date": "01-01",
                "end_date": "12-31",
                "week_groups": [
                    {
                        "week": [1, 2, 3, 4, 5],
                        "label": "Mon-Fri",
                        "durations": [
                            {"type": 1, "start_time": "00:00", "end_time": "01:00", "in": 1.0, "out": 2.0},
                            {"type": 2, "start_time": "", "end_time": "", "in": 0.0, "out": 0.0},
                            {"type": 3, "start_time": "02:00", "end_time": "03:00", "in": 3.0, "out": 4.0},
                        ],
                    },
                    {
                        "week": [6, 7],
                        "label": "Sat-Sun",
                        "durations": [
                            {"type": 1, "start_time": "00:00", "end_time": "01:00", "in": 1.0, "out": 2.0},
                            {"type": 2, "start_time": "", "end_time": "", "in": 0.0, "out": 0.0},
                            {"type": 3, "start_time": "02:00", "end_time": "03:00", "in": 3.0, "out": 4.0},
                        ],
                    },
                ],
            }
        ],
    }

    payload = build_schedule_payload_from_draft(2, draft)

    assert payload["money_code"] == "$"
    assert payload["date"][0]["time"][0]["duration"][1]["start_time"] is None
    assert payload["date"][0]["time"][0]["duration"][2]["type"] == 3


def test_validate_schedule_draft_reports_invalid_times() -> None:
    """Invalid draft values should surface as validation errors."""
    errors = validate_schedule_draft(
        8,
        {
            "periods": [
                {
                    "cs_time": "99:00",
                    "ce_time": "05:00",
                    "c_power": 100,
                    "dcs_time": "05:00",
                    "dce_time": "03:00",
                    "dc_power": 100,
                    "charge_soc": 90,
                    "dis_charge_soc": 10,
                }
            ]
        },
    )

    assert errors
    assert "invalid cs_time" in errors[0]


def test_get_allowed_battery_modes_honors_ctl_mode_set() -> None:
    """Station rules should restrict selectable battery modes when present."""
    battery_settings = build_empty_battery_settings(readable=True, writable=True)
    battery_settings["available_modes"] = [1, 2, 5, 8]

    assert get_allowed_battery_modes(battery_settings, {"ctl_mode_set": [2, 8]}) == [2, 8]


def test_relay_settings_enabled_detects_nested_modes() -> None:
    """Relay enablement should inspect nested k_2 / k_3 modes."""
    relay_settings = build_empty_relay_settings(readable=True, writable=True)
    relay_settings["data"] = {
        "mode": 0,
        "data": {
            "k_2": {"mode": 2},
            "k_3": {"mode": 0},
        },
    }

    assert relay_settings_enabled(relay_settings) is True
