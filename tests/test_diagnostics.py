"""Tests for diagnostics helpers."""

import asyncio
from types import SimpleNamespace

from tests.module_loader import load_integration_module

diagnostics_module = load_integration_module("diagnostics")


class FakeCoordinator:
    """Minimal coordinator stand-in for diagnostics tests."""

    def __init__(self, data):
        self.data = data
        self.last_update_success = True


class FakeAPI:
    """Minimal API stand-in for diagnostics tests."""

    auth_method = "home_v3:sha256_v3"
    last_auth_attempt = "home_v3"
    last_auth_status = None
    last_auth_message = None
    last_auth_attempt_summary = "home_v3[home/2.8.0] (sha256_v3) -> ok"


def test_async_get_config_entry_diagnostics_redacts_sensitive_fields() -> None:
    """Diagnostics should redact sensitive keys and hide bulky schedules."""
    hass = SimpleNamespace(
        data={
            "hoymiles_cloud": {
                "entry-1": {
                    "coordinator": FakeCoordinator(
                        {
                            "123": {
                                "station_info": {"name": "Roof", "latitude": "1.23", "longitude": "4.56"},
                                "devices": {"batteries": [{"sn": "BAT-1"}], "dtus": [], "inverters": [], "meters": []},
                                "battery_settings": {"mode_data": {"k_8": {"time": [{"cs_time": "03:00"}]}}},
                                "schedule_editor": {"modes": {"8": {"draft_payload": {"time": [{"cs_time": "03:00"}]}}}},
                                "capabilities": {"has_battery": True},
                            }
                        }
                    ),
                    "api": FakeAPI(),
                }
            }
        }
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="roof@example.com",
        data={"auth_mode": "home_v3", "password": "secret"},
        options={"scan_interval": 60},
    )

    diagnostics = asyncio.run(diagnostics_module.async_get_config_entry_diagnostics(hass, entry))

    station = diagnostics["coordinator"]["stations"]["123"]
    assert station["station_info"]["latitude"] == "**REDACTED**"
    assert station["device_inventory"]["batteries"][0]["sn"] == "**REDACTED**"
    assert station["battery_settings"]["mode_data"]["k_8"]["time"] == "<redacted>"
    assert station["schedule_editor"]["modes"]["8"]["draft_payload"] == "<redacted>"


def _diagnostics_for(station_data: dict, api=None) -> dict:
    """Run diagnostics for a single fake station."""
    hass = SimpleNamespace(
        data={
            "hoymiles_cloud": {
                "entry-1": {
                    "coordinator": FakeCoordinator({"123": station_data}),
                    "api": api or FakeAPI(),
                }
            }
        }
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="roof@example.com",
        data={"auth_mode": "home_v3", "password": "secret"},
        options={},
    )
    return asyncio.run(diagnostics_module.async_get_config_entry_diagnostics(hass, entry))


def test_device_inventory_includes_microinverters() -> None:
    """Microinverters must be visible; they never appear under "inverters"."""
    diagnostics = _diagnostics_for(
        {
            "devices": {
                "dtus": [],
                "inverters": [],
                "batteries": [],
                "meters": [],
                "microinverters": {"42": {"id": 42, "model_no": "HMS-800-2T"}},
            }
        }
    )

    station = diagnostics["coordinator"]["stations"]["123"]
    inventory = station["device_inventory"]
    assert inventory["microinverters"]["42"]["model_no"] == "HMS-800-2T"
    assert station["device_counts"] == {
        "dtus": 0,
        "inverters": 0,
        "batteries": 0,
        "meters": 0,
        "microinverters": 1,
    }


def test_station_summary_includes_telemetry_payloads() -> None:
    """The indicator/telemetry feeds must be part of the export."""
    diagnostics = _diagnostics_for(
        {
            "real_time_data": {"reflux_station_data": {"bms_soc": 55}},
            "pv_indicators": {"list": [{"key": "1_pv_v", "val": "-"}]},
            "grid_indicators": {"list": [{"key": "grid_p", "val": 12}]},
            "load_indicators": {"list": [{"key": "load_p", "val": 34}]},
            "energy_flow": {"pv_eq": 1.5},
        }
    )

    station = diagnostics["coordinator"]["stations"]["123"]
    assert station["pv_indicators"]["list"][0]["key"] == "1_pv_v"
    assert station["real_time_data"]["reflux_station_data"]["bms_soc"] == 55
    assert station["grid_indicators"]["list"][0]["val"] == 12
    assert station["load_indicators"]["list"][0]["val"] == 34
    assert station["energy_flow"]["pv_eq"] == 1.5


def test_added_payloads_are_redacted() -> None:
    """Serials and addresses in the new payloads must not leak."""
    diagnostics = _diagnostics_for(
        {
            "devices": {
                "microinverters": {
                    "42": {"id": 42, "sn": "MI-SERIAL", "dtu_sn": "DTU-SERIAL"}
                }
            },
            "real_time_data": {
                "sn": "STATION-SERIAL",
                "address": "Somewhere 1",
                "micro_sn": "MI-SERIAL",
                "user_email": "roof@example.com",
            },
            "pv_indicators": {"list": [{"key": "1_pv_v", "val": 12, "device_sn": "X"}]},
        }
    )

    station = diagnostics["coordinator"]["stations"]["123"]
    micro = station["device_inventory"]["microinverters"]["42"]
    assert micro["sn"] == "**REDACTED**"
    assert micro["dtu_sn"] == "**REDACTED**"
    assert micro["id"] == 42
    real_time = station["real_time_data"]
    assert real_time["sn"] == "**REDACTED**"
    assert real_time["address"] == "**REDACTED**"
    assert real_time["micro_sn"] == "**REDACTED**"
    assert real_time["user_email"] == "**REDACTED**"
    assert station["pv_indicators"]["list"][0]["device_sn"] == "**REDACTED**"
    assert station["pv_indicators"]["list"][0]["val"] == 12


def test_diagnostics_include_device_fetch_status() -> None:
    """A denied device endpoint must be distinguishable from an empty one."""
    api = SimpleNamespace(
        auth_method="home_v3",
        last_auth_attempt="home_v3",
        last_auth_status=None,
        last_auth_message=None,
        last_auth_attempt_summary="ok",
        device_fetch_status={
            "123:inverters": {
                "endpoint": "inverters",
                "station_id": "123",
                "ok": False,
                "status": "3",
                "message": "No Permission",
            },
            "123:microinverters": {
                "endpoint": "microinverters",
                "station_id": "123",
                "ok": True,
                "status": "0",
                "message": "success",
                "total": 1,
                "count": 1,
            },
        },
    )

    diagnostics = _diagnostics_for({"devices": {}}, api=api)

    fetch_status = diagnostics["device_fetch_status"]
    assert fetch_status["123:inverters"]["ok"] is False
    assert fetch_status["123:inverters"]["message"] == "No Permission"
    assert fetch_status["123:microinverters"]["count"] == 1


def test_diagnostics_tolerate_api_without_fetch_status() -> None:
    """An older API object must not break the export."""
    diagnostics = _diagnostics_for({"devices": {}})

    assert diagnostics["device_fetch_status"] == {}
