"""Tests for pure Hoymiles data helpers."""
from datetime import datetime, timedelta

import pytest

from tests.module_loader import load_integration_module

data_module = load_integration_module("data")
build_empty_battery_settings = data_module.build_empty_battery_settings
build_empty_relay_settings = data_module.build_empty_relay_settings
build_schedule_editor_state = data_module.build_schedule_editor_state
build_schedule_payload_from_draft = data_module.build_schedule_payload_from_draft
build_station_capabilities = data_module.build_station_capabilities
discover_pv_channels = data_module.discover_pv_channels
expected_pv_channels = data_module.expected_pv_channels
find_placeholder_pv_channels = data_module.find_placeholder_pv_channels
get_allowed_battery_modes = data_module.get_allowed_battery_modes
get_battery_flow_direction = data_module.get_battery_flow_direction
get_schedule_modes = data_module.get_schedule_modes
get_microinverter_port_count = data_module.get_microinverter_port_count
get_ev_charger_power = data_module.get_ev_charger_power
get_signed_battery_power = data_module.get_signed_battery_power
has_ev_charger = data_module.has_ev_charger
is_battery_charging = data_module.is_battery_charging
latest_module_values = data_module.latest_module_values
merge_missing_pv_channel_values = data_module.merge_missing_pv_channel_values
relay_settings_enabled = data_module.relay_settings_enabled
seed_missing_pv_channels = data_module.seed_missing_pv_channels
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


def test_find_placeholder_pv_channels_flags_all_placeholder_channels() -> None:
    """Channels whose v/i/p values are all placeholders should be flagged."""
    pv_indicators = {
        "list": [
            {"key": "pv_p_total", "val": "0"},
            {"key": "1_pv_v", "val": "-"},
            {"key": "1_pv_i", "val": "-"},
            {"key": "1_pv_p", "val": "-"},
        ]
    }

    assert find_placeholder_pv_channels(pv_indicators) == [1]


def test_find_placeholder_pv_channels_ignores_channels_with_real_values() -> None:
    """A channel with any numeric value must not be flagged."""
    pv_indicators = {
        "list": [
            {"key": "1_pv_v", "val": "42.1"},
            {"key": "1_pv_i", "val": "-"},
            {"key": "1_pv_p", "val": "350"},
        ]
    }

    assert find_placeholder_pv_channels(pv_indicators) == []


# --- Port-count derived channels (issue #39) ---------------------------------

# An HMS-800-2WB reported by the issue: two physical ports, but the indicators
# feed only ever returns keys for channel 1.
HMS_800_2WB = {
    "33820520": {
        "id": 33820520,
        "init_hard_no": "HMS-800-2WB",
        "rule": {"dev_type": 3, "port": 2},
    }
}
ONE_CHANNEL_FEED = {
    "pv_total": 1,
    "list": [
        {"key": "pv_p_total", "val": 26.1},
        {"key": "1_pv_v", "val": 32.7},
        {"key": "1_pv_i", "val": 0.8},
        {"key": "1_pv_p", "val": 26.1},
    ],
}


def test_get_microinverter_port_count_reads_rule_port() -> None:
    """The port count comes from rule.port in the detail payload."""
    assert get_microinverter_port_count(HMS_800_2WB["33820520"]) == 2
    assert get_microinverter_port_count({"rule": {"port": "4"}}) == 4


@pytest.mark.parametrize(
    "micro",
    [
        None,
        {},
        {"rule": None},
        {"rule": {}},
        {"rule": {"port": 0}},
        {"rule": {"port": -1}},
        {"rule": {"port": "two"}},
        {"rule": {"port": True}},
    ],
)
def test_get_microinverter_port_count_rejects_unusable_values(micro) -> None:
    """Anything that is not a positive integer port count yields None."""
    assert get_microinverter_port_count(micro) is None


def test_expected_pv_channels_from_single_microinverter() -> None:
    """A single two-port microinverter implies channels 1 and 2."""
    assert expected_pv_channels(HMS_800_2WB) == [1, 2]


def test_expected_pv_channels_declines_multi_microinverter_stations() -> None:
    """Channel-to-port mapping is unknown with several devices (#56)."""
    microinverters = {
        "1": {"rule": {"port": 2}},
        "2": {"rule": {"port": 2}},
    }

    assert expected_pv_channels(microinverters) == []


def test_expected_pv_channels_without_port_count() -> None:
    """A detail payload that states no port count claims nothing."""
    assert expected_pv_channels({"1": {}}) == []
    assert expected_pv_channels({}) == []
    assert expected_pv_channels(None) == []


def test_seed_missing_pv_channels_adds_the_omitted_channel() -> None:
    """The channel the feed never reports becomes a fillable placeholder."""
    seeded = seed_missing_pv_channels(ONE_CHANNEL_FEED, HMS_800_2WB)

    assert discover_pv_channels(seeded) == [1, 2]
    # Channel 1 keeps its real values; only channel 2 is a placeholder.
    assert find_placeholder_pv_channels(seeded) == [2]


def test_seed_missing_pv_channels_does_not_mutate_the_feed() -> None:
    """Seeding returns a copy, leaving the fetched payload untouched."""
    seed_missing_pv_channels(ONE_CHANNEL_FEED, HMS_800_2WB)

    assert discover_pv_channels(ONE_CHANNEL_FEED) == [1]


def test_seed_missing_pv_channels_is_a_noop_when_the_feed_is_complete() -> None:
    """A feed already reporting every port is returned unchanged."""
    feed = {
        "list": [
            {"key": "1_pv_p", "val": 26.1},
            {"key": "2_pv_p", "val": 30.4},
        ]
    }

    assert seed_missing_pv_channels(feed, HMS_800_2WB) is feed


def test_seed_missing_pv_channels_ignores_an_empty_feed() -> None:
    """A failed indicators fetch must not invent channels."""
    assert seed_missing_pv_channels({}, HMS_800_2WB) == {}
    assert seed_missing_pv_channels(None, HMS_800_2WB) == {}
    assert seed_missing_pv_channels({"list": []}, HMS_800_2WB) == {"list": []}


def test_seeded_channel_is_filled_by_module_data() -> None:
    """End to end: an omitted channel is seeded and then filled (#39)."""
    seeded = seed_missing_pv_channels(ONE_CHANNEL_FEED, HMS_800_2WB)

    merged = merge_missing_pv_channel_values(
        seeded,
        {2: {"MODULE_V": 33.1, "MODULE_I": 0.9, "MODULE_POWER": 29.8}},
    )

    values = {item["key"]: item["val"] for item in merged["list"]}
    assert values["2_pv_v"] == 33.1
    assert values["2_pv_i"] == 0.9
    assert values["2_pv_p"] == 29.8
    # Channel 1's real readings are left alone.
    assert values["1_pv_p"] == 26.1


def test_merge_replaces_placeholder_channel_values() -> None:
    """Placeholder v/i/p values should be replaced with module data."""
    pv_indicators = {
        "list": [
            {"key": "pv_p_total", "val": "0"},
            {"key": "1_pv_v", "val": "-"},
            {"key": "1_pv_i", "val": "-"},
            {"key": "1_pv_p", "val": "-"},
        ]
    }

    merged = merge_missing_pv_channel_values(
        pv_indicators,
        {1: {"MODULE_V": 35.3, "MODULE_I": 3.98, "MODULE_POWER": 140.8}},
    )

    values = {item["key"]: item["val"] for item in merged["list"]}
    assert values["1_pv_v"] == 35.3
    assert values["1_pv_i"] == 3.98
    assert values["1_pv_p"] == 140.8
    assert values["pv_p_total"] == 140.8


def test_merge_preserves_numeric_indicator_values() -> None:
    """Numeric indicator values must never be overwritten."""
    pv_indicators = {
        "list": [
            {"key": "1_pv_v", "val": "42.1"},
            {"key": "1_pv_i", "val": "8.2"},
            {"key": "1_pv_p", "val": "350"},
            {"key": "pv_p_total", "val": "1500"},
        ]
    }

    merged = merge_missing_pv_channel_values(
        pv_indicators,
        {1: {"MODULE_V": 35.3, "MODULE_I": 3.98, "MODULE_POWER": 140.8}},
    )

    values = {item["key"]: item["val"] for item in merged["list"]}
    assert values["1_pv_v"] == "42.1"
    assert values["1_pv_i"] == "8.2"
    assert values["1_pv_p"] == "350"
    assert values["pv_p_total"] == "1500"


def test_merge_skips_none_module_values() -> None:
    """A None module value must leave the placeholder untouched."""
    pv_indicators = {"list": [{"key": "1_pv_v", "val": "-"}]}

    merged = merge_missing_pv_channel_values(pv_indicators, {1: {"MODULE_V": None}})

    assert merged["list"][0]["val"] == "-"


def test_merge_does_not_mutate_input() -> None:
    pv_indicators = {"list": [{"key": "1_pv_v", "val": "-"}]}

    merge_missing_pv_channel_values(pv_indicators, {1: {"MODULE_V": 35.3}})

    assert pv_indicators["list"][0]["val"] == "-"


def test_merge_sums_module_power_across_channels() -> None:
    pv_indicators = {
        "list": [
            {"key": "1_pv_p", "val": "-"},
            {"key": "2_pv_p", "val": "-"},
            {"key": "pv_p_total", "val": "-"},
        ]
    }

    merged = merge_missing_pv_channel_values(
        pv_indicators,
        {
            1: {"MODULE_V": None, "MODULE_I": None, "MODULE_POWER": 140.8},
            2: {"MODULE_V": None, "MODULE_I": None, "MODULE_POWER": 59.2},
        },
    )

    values = {item["key"]: item["val"] for item in merged["list"]}
    assert values["pv_p_total"] == pytest.approx(200.0)


def test_merge_handles_empty_inputs() -> None:
    assert merge_missing_pv_channel_values(None, {1: {"MODULE_V": 1.0}}) == {}
    assert merge_missing_pv_channel_values({"list": []}, {}) == {"list": []}


def _chart(x_axis, series):
    """Build a decoded-chart mapping the way chart_pb returns it."""
    return {
        "x_axis": list(x_axis),
        "series": [{"type": name, "data": list(data)} for name, data in series],
        "type": "LINE",
    }


def test_latest_module_values_returns_freshest_sample() -> None:
    """A sample from the current slot is reported as-is."""
    chart = _chart(
        ["11:40", "11:45"],
        [("MODULE_POWER", [100.0, 140.8]), ("MODULE_V", [30.0, 35.3])],
    )

    values = latest_module_values(chart, now=datetime(2026, 8, 20, 11, 47))

    assert values["MODULE_POWER"] == pytest.approx(140.8)
    assert values["MODULE_V"] == pytest.approx(35.3)
    assert values["MODULE_I"] is None


def test_latest_module_values_zeroes_stale_samples() -> None:
    """A series that stopped growing at sunset must report zero, not the peak."""
    chart = _chart(["20:35", "20:40"], [("MODULE_POWER", [40.0, 12.5])])

    values = latest_module_values(chart, now=datetime(2026, 8, 20, 23, 30))

    assert values["MODULE_POWER"] == 0.0


def test_latest_module_values_respects_custom_max_age() -> None:
    """The freshness window is configurable."""
    chart = _chart(["11:00"], [("MODULE_POWER", [40.0])])
    now = datetime(2026, 8, 20, 11, 30)

    assert latest_module_values(chart, now=now, max_age=timedelta(minutes=60))[
        "MODULE_POWER"
    ] == pytest.approx(40.0)
    assert (
        latest_module_values(chart, now=now, max_age=timedelta(minutes=15))[
            "MODULE_POWER"
        ]
        == 0.0
    )


def test_latest_module_values_accepts_future_slot() -> None:
    """Clock skew against the cloud must not zero out a live sample."""
    chart = _chart(["11:45"], [("MODULE_POWER", [140.8])])

    values = latest_module_values(chart, now=datetime(2026, 8, 20, 11, 43))

    assert values["MODULE_POWER"] == pytest.approx(140.8)


def test_latest_module_values_without_labels_keeps_sample() -> None:
    """Hardware answering without an x_axis keeps the previous behaviour."""
    chart = {"x_axis": [], "series": [{"type": "MODULE_POWER", "data": [140.8]}]}

    values = latest_module_values(chart, now=datetime(2026, 8, 20, 23, 30))

    assert values["MODULE_POWER"] == pytest.approx(140.8)


def test_latest_module_values_handles_unparsable_labels() -> None:
    """Unexpected slot labels must not raise."""
    chart = _chart(["not-a-time"], [("MODULE_POWER", [140.8])])

    values = latest_module_values(chart, now=datetime(2026, 8, 20, 23, 30))

    assert values["MODULE_POWER"] == pytest.approx(140.8)


def test_latest_module_values_uses_series_length_for_labels() -> None:
    """Freshness follows the series length, not the x_axis length."""
    chart = _chart(
        ["06:00", "06:05", "06:10", "06:15"],
        [("MODULE_POWER", [10.0, 20.0])],
    )

    values = latest_module_values(chart, now=datetime(2026, 8, 20, 6, 30))

    assert values["MODULE_POWER"] == 0.0


def test_latest_module_values_rounds_per_quota() -> None:
    """Float32 noise is rounded to display precision."""
    chart = _chart(
        ["11:45"],
        [
            ("MODULE_POWER", [140.8499984741211]),
            ("MODULE_V", [35.34999847412109]),
            ("MODULE_I", [3.9849998950958252]),
        ],
    )

    values = latest_module_values(chart, now=datetime(2026, 8, 20, 11, 47))

    assert values == {"MODULE_POWER": 140.8, "MODULE_V": 35.3, "MODULE_I": 3.98}


def test_latest_module_values_handles_missing_chart() -> None:
    """A failed decode yields no values rather than raising."""
    assert latest_module_values(None, now=datetime(2026, 8, 20, 11, 47)) == {
        "MODULE_POWER": None,
        "MODULE_V": None,
        "MODULE_I": None,
    }


def _station(reflux: dict | None) -> dict:
    """Build a minimal station payload carrying the reflux data."""
    return {"real_time_data": {"reflux_station_data": reflux if reflux is not None else {}}}


def test_battery_flow_direction_charging() -> None:
    """``in: 10`` marks the battery as the flow target, i.e. charging."""
    station = _station({"bms_power": "812.0", "flows": [{"out": 4, "in": 10}]})

    assert get_battery_flow_direction(station) == -1
    assert is_battery_charging(station) is True
    assert get_signed_battery_power(station) == -812.0


def test_battery_flow_direction_discharging() -> None:
    """``out: 10`` marks the battery as the flow source, i.e. discharging."""
    station = _station({"bms_power": "450.5", "flows": [{"out": 10, "in": 1}]})

    assert get_battery_flow_direction(station) == 1
    assert is_battery_charging(station) is False
    assert get_signed_battery_power(station) == 450.5


def test_battery_flow_without_battery_node_is_unknown() -> None:
    """An idle battery has no flow entry, so the direction stays unknown."""
    station = _station({"bms_power": "0", "flows": [{"out": 4, "in": 1}, {"out": 2, "in": 1}]})

    assert get_battery_flow_direction(station) is None
    # The legacy ``bms_power > 0`` fallback must not claim "charging" here.
    assert is_battery_charging(station) is None
    assert get_signed_battery_power(station) == 0.0


def test_battery_flow_empty_list_is_unknown() -> None:
    """An empty flow array is still flow data, so no fallback is applied."""
    station = _station({"bms_power": "120", "flows": []})

    assert is_battery_charging(station) is None


def test_battery_charging_falls_back_without_flow_data() -> None:
    """Accounts that never report flows keep the legacy magnitude fallback."""
    station = _station({"bms_power": "120"})

    assert get_battery_flow_direction(station) is None
    assert is_battery_charging(station) is True
    assert get_signed_battery_power(station) == 120.0


def test_battery_charging_falls_back_to_discharging_without_flow_data() -> None:
    """A non-positive magnitude without flow data reports discharging."""
    station = _station({"bms_power": "-30"})

    assert is_battery_charging(station) is False
    assert get_signed_battery_power(station) == -30.0


def test_battery_helpers_handle_missing_bms_power() -> None:
    """Missing or placeholder power yields unknown values, not zero."""
    assert get_signed_battery_power(_station({})) is None
    assert is_battery_charging(_station({})) is None
    assert get_signed_battery_power(_station({"bms_power": "-"})) is None
    assert is_battery_charging(_station({"bms_power": ""})) is None
    assert get_signed_battery_power({}) is None
    assert get_signed_battery_power(None) is None


def test_battery_flow_direction_handles_malformed_flows() -> None:
    """Non-list or non-dict flow payloads never raise."""
    non_list = _station({"bms_power": "75", "flows": {"out": 10}})
    assert get_battery_flow_direction(non_list) is None
    # A malformed ``flows`` value counts as "no flow data", so the fallback applies.
    assert is_battery_charging(non_list) is True
    assert get_signed_battery_power(non_list) == 75.0

    junk_entries = _station({"bms_power": "75", "flows": ["nonsense", None, {"out": 10, "in": 1}]})
    assert get_battery_flow_direction(junk_entries) == 1
    assert get_signed_battery_power(junk_entries) == 75.0


def test_negative_value_rejected_for_total_increasing_counters() -> None:
    """A negative counter reading must be withheld, not published.

    Home Assistant reads a drop in a total_increasing sensor as a meter reset,
    so publishing a negative would make the next normal reading land as one
    huge delta and permanently inflate long-term statistics (issue #54).
    """
    assert data_module.is_invalid_total_increasing(-3461, True) is True
    assert data_module.is_invalid_total_increasing(-0.5, True) is True


def test_zero_and_positive_values_pass_through() -> None:
    """Only negatives are rejected; zero is a legitimate counter value."""
    assert data_module.is_invalid_total_increasing(0, True) is False
    assert data_module.is_invalid_total_increasing(3461, True) is False
    assert data_module.is_invalid_total_increasing(0.0, True) is False


def test_negative_measurements_are_left_alone() -> None:
    """Signed measurements must pass through untouched.

    battery_power is legitimately negative while charging; a blanket
    no-negatives rule would undo that.
    """
    assert data_module.is_invalid_total_increasing(-1200, False) is False


def test_non_numeric_values_are_not_rejected() -> None:
    """Unknown/None readings are handled elsewhere and must not be swallowed."""
    assert data_module.is_invalid_total_increasing(None, True) is False
    assert data_module.is_invalid_total_increasing("-5", True) is False
    assert data_module.is_invalid_total_increasing(False, True) is False


def _station_with_reflux(**reflux: object) -> dict:
    """Build a station payload carrying the given reflux fields."""
    return {"real_time_data": {"reflux_station_data": reflux}}


def test_ev_charger_hidden_when_no_pile_is_advertised() -> None:
    """A station without a charging pile must not get the sensor.

    pile_power is emitted regardless of whether a charger exists, and on a
    station without one it mirrored PV power (issue #64). The icon flags are
    what the vendor app gates the charging-pile node on.
    """
    station = _station_with_reflux(pile_power="742", icon_plug=0, icon_ai_plug=0)

    assert has_ev_charger(station) is False


def test_ev_charger_power_reports_zero_while_no_pile_is_connected() -> None:
    """The mirrored value is replaced by 0 W, not published or dropped."""
    station = _station_with_reflux(pile_power="742", icon_plug=0, icon_ai_plug=0)

    assert get_ev_charger_power(station) == 0.0


def test_ev_charger_exposed_when_a_pile_is_advertised() -> None:
    """Either icon flag is enough to treat pile_power as charger telemetry."""
    plain = _station_with_reflux(pile_power="3600", icon_plug=1, icon_ai_plug=0)
    ai = _station_with_reflux(pile_power="3600", icon_plug="0", icon_ai_plug="1")

    assert has_ev_charger(plain) is True
    assert get_ev_charger_power(plain) == 3600.0
    assert has_ev_charger(ai) is True
    assert get_ev_charger_power(ai) == 3600.0


def test_ev_charger_keeps_legacy_behaviour_without_icon_flags() -> None:
    """Payloads that carry neither flag must not lose the entity."""
    station = _station_with_reflux(pile_power="3600")

    assert has_ev_charger(station) is True
    assert get_ev_charger_power(station) == 3600.0


def test_ev_charger_absent_without_pile_power() -> None:
    """No pile_power at all means there is nothing to report."""
    assert has_ev_charger(_station_with_reflux(icon_plug=1)) is False
    assert has_ev_charger(_station_with_reflux(pile_power="-")) is False
    assert get_ev_charger_power(_station_with_reflux()) is None


def test_capabilities_report_ev_charger_availability() -> None:
    """Diagnostics should show whether the charger sensor was created."""
    real_time_data = {"reflux_station_data": {"pile_power": "742", "icon_plug": 0}}

    capabilities = build_station_capabilities(
        real_time_data=real_time_data,
        pv_indicators={},
        battery_settings={},
        microinverters_data={},
    )

    assert capabilities["ev_charger_available"] is False
