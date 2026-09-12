"""Optional smoke check against an installed Home Assistant (no cloud requests).

Run with an HA environment: python scripts/validate_homeassistant.py
The ordinary pytest suite intentionally does not require Home Assistant.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntry, ConfigEntries, ConfigEntryState, current_entry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er, frame

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.hoymiles_cloud import (  # noqa: E402
    PLATFORMS,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.hoymiles_cloud import config_flow  # noqa: E402
from custom_components.hoymiles_cloud.const import DOMAIN  # noqa: E402
from custom_components.hoymiles_cloud.hoymiles_api import LiveDataAuthError  # noqa: E402


class FakeAPI:
    """Deterministic transport stub used with real HA coordinator and entities."""

    fail_station: str | None = None
    auth_failure = False
    include_pv = False
    last_auth_status = "1"
    last_auth_message = "ok"
    last_auth_attempt_summary = "fake"
    last_auth_error_key = None

    def __init__(self, session, username, password):
        self.username = username
        self.password = password

    def configure_auth(self, **kwargs):
        pass

    async def authenticate(self):
        return self.password == "good"

    def is_token_expired(self):
        return False

    async def get_stations(self):
        return {"station-a": "A", "station-b": "B"}

    async def get_real_time_data(self, station_id):
        if station_id == self.fail_station:
            raise RuntimeError("fake telemetry outage")
        return {"pv_power": 100}

    async def get_live_data(self, station_id):
        if self.auth_failure:
            raise LiveDataAuthError("fake authorization failure")
        if station_id == self.fail_station:
            raise RuntimeError("fake burst outage")
        return {"es": {"sp": 0}, "icon": {"pile": 1}}

    async def get_pv_indicators(self, station_id):
        if self.include_pv:
            return {"list": [{"key": "1_pv_p", "val": 80},
                             {"key": "1_pv_v", "val": 30},
                             {"key": "1_pv_i", "val": 2}]}
        return {}

    async def set_battery_mode_settings(self, station_id, mode, settings, *, merge=True):
        return True

    def __getattr__(self, name):
        async def empty(*args, **kwargs):
            return [] if name.startswith("get_") and name[4:] in {
                "dtus", "inverters", "batteries", "meters"
            } else {}
        return empty


def make_entry() -> ConfigEntry:
    return ConfigEntry(
        data={"username": "smoke@example.test", "password": "good"},
        discovery_keys={}, domain=DOMAIN, minor_version=1, options={},
        source="user", title="Smoke", unique_id="smoke@example.test", version=1,
        subentries_data=[],
        state=ConfigEntryState.SETUP_IN_PROGRESS,
    )


async def main() -> None:
    with TemporaryDirectory(prefix="hoymiles-ha-smoke-") as config_dir:
        hass = HomeAssistant(config_dir)
        hass.config_entries = ConfigEntries(hass, {})
        frame.async_setup(hass)
        hass.data[dr.DATA_REGISTRY] = dr.DeviceRegistry(hass)
        await dr.async_get(hass).async_load(load_empty=True)
        await er.async_get(hass).async_load(load_empty=True)
        entry = make_entry()
        # Register without async_add's automatic integration loader setup; this
        # script drives the integration entry directly under patched transport.
        hass.config_entries._entries[entry.entry_id] = entry
        entities: dict[str, list] = {}
        reauth_requests: list[str] = []

        def reauth(_entry, _hass):
            reauth_requests.append(entry.entry_id)

        async def forward(_manager, _entry, platforms):
            for platform in platforms:
                module = __import__(f"custom_components.hoymiles_cloud.{platform.value}", fromlist=["async_setup_entry"])
                entities[platform.value] = []
                await module.async_setup_entry(
                    hass, entry, lambda additions, update_before_add=False, key=platform.value: entities[key].extend(additions)
                )

        async def unload(_manager, _entry, platforms):
            return True

        with (
            patch("custom_components.hoymiles_cloud.HoymilesAPI", FakeAPI),
            patch("custom_components.hoymiles_cloud.async_get_clientsession", return_value=object()),
            patch.object(ConfigEntries, "async_forward_entry_setups", forward),
            patch.object(ConfigEntries, "async_unload_platforms", unload),
            patch.object(ConfigEntry, "async_start_reauth_if_available", reauth),
        ):
            context_token = current_entry.set(entry)
            try:
                assert await async_setup_entry(hass, entry)
            finally:
                current_entry.reset(context_token)
            coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
            assert coordinator.data["station-a"]["telemetry_available"]
            assert set(entities) == {platform.value for platform in PLATFORMS}
            base_counts = {key: len(value) for key, value in entities.items()}
            assert entities["sensor"], "real sensor entities were not constructed"

            FakeAPI.include_pv = True
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            assert len(entities["sensor"]) > base_counts["sensor"], "late PV discovery failed"
            once = len(entities["sensor"])
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            assert len(entities["sensor"]) == once, "discovery duplicated entities"

            # A successful write followed by an unreadable settings response
            # must retain the user's draft even if the old coordinator data
            # had readable settings. This checks an awaited refresh occurs.
            runtime = hass.data[DOMAIN][entry.entry_id]
            station = coordinator.data["station-a"]
            station["battery_settings"] = {"readable": True}
            station["schedule_editor"] = {
                "modes": {8: {"validation_errors": [], "draft": {"periods": []}}}
            }
            draft_store = runtime["stored_data"]["stations"]["station-a"]["schedule_editor"]
            draft_store["modes"]["8"] = {"periods": []}
            try:
                await runtime["apply_schedule_draft"]("station-a", 8)
            except HomeAssistantError as err:
                assert "draft was retained" in str(err)
            else:
                raise AssertionError("schedule draft cleared without fresh settings")
            assert "8" in draft_store["modes"]

            FakeAPI.fail_station = "station-b"
            await coordinator.async_refresh()
            assert not coordinator.data["station-b"]["telemetry_available"]
            assert coordinator.data["station-b"]["live_data"] == {}
            assert coordinator.data["station-a"]["telemetry_available"]
            FakeAPI.fail_station = None

            FakeAPI.auth_failure = True
            await coordinator.async_refresh()
            assert not coordinator.last_update_success, "auth failure did not fail the coordinator"
            assert reauth_requests, "HA did not request reauthentication"
            FakeAPI.auth_failure = False

            assert await async_unload_entry(hass, entry)
            assert entry.entry_id not in hass.data[DOMAIN]

        reloads: list[str] = []

        async def reload(_manager, entry_id):
            reloads.append(entry_id)
            return True

        with (
            patch("custom_components.hoymiles_cloud.config_flow.HoymilesAPI", FakeAPI),
            patch("custom_components.hoymiles_cloud.config_flow.async_get_clientsession", return_value=object()),
            patch.object(ConfigEntries, "async_reload", reload),
        ):
            flow = config_flow.ConfigFlow()
            flow.hass = hass
            flow.context = {"entry_id": entry.entry_id}
            form = await flow.async_step_reauth(dict(entry.data))
            assert form["type"] == "form"
            mismatch = await flow.async_step_reauth_confirm({
                "username": "different@example.test", "password": "good",
                "auth_mode": "auto", "app_version": "",
            })
            assert mismatch["errors"]["base"] == "account_mismatch"
            assert not reloads
            success = await flow.async_step_reauth_confirm({
                "username": "smoke@example.test", "password": "good",
                "auth_mode": "auto", "app_version": "",
            })
            assert success["type"] == "abort" and success["reason"] == "reauth_successful"
            assert reloads == [entry.entry_id], "reauth should reload exactly once"

        await hass.async_stop()
    print("Home Assistant lifecycle smoke passed")


if __name__ == "__main__":
    asyncio.run(main())
