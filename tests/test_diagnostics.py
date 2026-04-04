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
