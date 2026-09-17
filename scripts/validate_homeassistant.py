"""Optional smoke check against an installed Home Assistant (no cloud requests).

Run with an HA environment: python scripts/validate_homeassistant.py
The ordinary pytest suite intentionally does not require Home Assistant.
"""

from __future__ import annotations

import asyncio
import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

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
    station_count = 2
    fast_polling = False
    burst_connection = 1
    burst_watts = 900
    slow_started = None
    slow_release = None
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
        return {"station-a": "A", "station-b": "B", **{f"station-{i}": f"Station {i}" for i in range(2, self.station_count)}}

    async def get_real_time_data(self, station_id):
        if self.auth_failure:
            raise LiveDataAuthError("fake authorization failure")
        if self.slow_started is not None and station_id == "station-a":
            self.slow_started.set()
            await self.slow_release.wait()
        if station_id == self.fail_station:
            raise RuntimeError("fake telemetry outage")
        return {"real_power": 100}

    async def get_live_data(self, station_id):
        if self.auth_failure:
            raise LiveDataAuthError("fake authorization failure")
        if station_id == self.fail_station:
            raise RuntimeError("fake burst outage")
        return {"con": 1, "es": {"sp": 0}, "icon": {"pile": 1}}

    async def get_microinverters_by_stations(self, station_id):
        if not self.fast_polling:
            return {}
        micros = {"a": {"sn": "micro-a", "id": 1, "rule": {"port": 2}}}
        if station_id == "station-b":
            micros["b"] = {"sn": "micro-b", "id": 2, "rule": {"port": 4}}
        return micros

    async def get_burst_data(self, station_id, *, serials=None):
        if self.auth_failure:
            raise LiveDataAuthError("fake authorization failure")
        if serials:
            return {"con": self.burst_connection, "dly": 60000,
                    "mis": [{"sn": serial, "pac": 200 + index * 100,
                             **{f"p{port}": 100 + port * 10 + index * 100 for port in range(1, 5)}}
                            for index, serial in enumerate(serials)]}
        return {"con": self.burst_connection, "dly": 60000, "power": {"pv": self.burst_watts}}

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


def make_entry(username: str = "smoke@example.test") -> ConfigEntry:
    return ConfigEntry(
        data={"username": username, "password": "good"},
        discovery_keys={}, domain=DOMAIN, minor_version=1, options={"fast_polling": FakeAPI.fast_polling},
        source="user", title="Smoke", unique_id=username, version=1,
        subentries_data=[],
        state=ConfigEntryState.SETUP_IN_PROGRESS,
    )


async def validate_account_storage(hass: HomeAssistant) -> None:
    """Reload two entries and verify their persisted drafts stay independent."""
    previous = FakeAPI.fast_polling
    FakeAPI.fast_polling = False
    entries = [make_entry("first@example.test"), make_entry("second@example.test")]
    for entry in entries:
        hass.config_entries._entries[entry.entry_id] = entry
    with (
        patch("custom_components.hoymiles_cloud.HoymilesAPI", FakeAPI),
        patch("custom_components.hoymiles_cloud.async_get_clientsession", return_value=object()),
        patch.object(ConfigEntries, "async_forward_entry_setups", AsyncMock()),
        patch.object(ConfigEntries, "async_unload_platforms", AsyncMock(return_value=True)),
    ):
        async def setup(entry):
            token = current_entry.set(entry)
            try:
                assert await async_setup_entry(hass, entry)
            finally:
                current_entry.reset(token)
        for index, entry in enumerate(entries):
            await setup(entry)
            runtime = hass.data[DOMAIN][entry.entry_id]
            runtime["stored_data"]["stations"]["station-a"]["account_marker"] = index
            await runtime["store"].async_save(runtime["stored_data"])
        for entry in entries:
            assert await async_unload_entry(hass, entry)
        for index, entry in enumerate(entries):
            await setup(entry)
            assert hass.data[DOMAIN][entry.entry_id]["stored_data"]["stations"]["station-a"]["account_marker"] == index
        for entry in entries:
            assert await async_unload_entry(hass, entry)
    FakeAPI.fast_polling = previous


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
        options = config_flow.OptionsFlowHandler(entry)
        options.hass, options.handler = hass, entry.entry_id
        form = await options.async_step_init()
        defaults = form["data_schema"]({})
        assert defaults["fast_polling"] is FakeAPI.fast_polling
        changed = await options.async_step_init({**defaults, "fast_polling": not FakeAPI.fast_polling})
        assert changed["data"]["fast_polling"] is not FakeAPI.fast_polling
        entities: dict[str, list] = {}
        reauth_requests: list[str] = []

        def reauth(_entry, _hass):
            reauth_requests.append(entry.entry_id)

        async def forward(_manager, _entry, platforms):
            for platform in platforms:
                module = __import__(f"custom_components.hoymiles_cloud.{platform.value}", fromlist=["async_setup_entry"])
                entities[platform.value] = []
                await module.async_setup_entry(
                    hass, _entry, lambda additions, update_before_add=False, key=platform.value: entities[key].extend(additions)
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

            if FakeAPI.fast_polling:
                poller = hass.data[DOMAIN][entry.entry_id]["burst_poller"]
                for _ in range(100):
                    if "inverters" in poller.samples.get("station-a", {}):
                        break
                    await asyncio.sleep(0)
                else:
                    raise AssertionError("burst background loop did not start")
                pv = next(e for e in entities["sensor"] if e.unique_id == f"{DOMAIN}_station-a_pv_power")
                pv1 = next(e for e in entities["sensor"] if e.unique_id == f"{DOMAIN}_station-a_pv1_p")
                assert pv.native_value == 900 and pv.available
                assert pv1.native_value == 110 and pv1.available
                assert any(e.unique_id.endswith("micro_micro-a_ac_power") for e in entities["sensor"])
                for _ in range(100):
                    if "inverters" in poller.samples.get("station-b", {}):
                        break
                    await asyncio.sleep(0)
                multi_port = next(e for e in entities["sensor"] if e.unique_id == f"{DOMAIN}_station-b_micro_micro-b_pv4_power")
                assert multi_port.native_value == 240 and multi_port.available

                # A slow refresh in flight must publish the newest burst snapshot.
                FakeAPI.slow_started, FakeAPI.slow_release = asyncio.Event(), asyncio.Event()
                refresh = asyncio.create_task(coordinator.async_refresh())
                await FakeAPI.slow_started.wait()
                FakeAPI.burst_watts = 1200
                poller._due.clear()
                with patch.object(coordinator, "_schedule_refresh") as schedule:
                    await poller.poll_once("station-a")
                    schedule.assert_not_called()
                FakeAPI.slow_release.set()
                await refresh
                FakeAPI.slow_started = FakeAPI.slow_release = None
                assert pv.native_value == 1200, "slow response overwrote fresh burst"
                FakeAPI.burst_connection = 0
                poller._due.clear()
                await poller.poll_once("station-a")
                assert pv.native_value is None and not pv.available
                assert pv1.native_value is None and not pv1.available
                FakeAPI.burst_connection = 1
                poller._due.clear()
                await poller.poll_once("station-a")
                assert pv.available and pv.native_value == 1200
                # A transport failure permits the existing ordinary PV source.
                with patch.object(poller.api, "get_burst_data", side_effect=RuntimeError("fake network failure")):
                    poller._due.clear()
                    await poller.poll_once("station-a")
                assert pv.native_value == 100 and pv.available
                poller._due.clear()
                await poller.poll_once("station-a")
                assert pv.native_value == 1200

            FakeAPI.include_pv = True
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            assert len(entities["sensor"]) >= base_counts["sensor"], "late PV discovery failed"
            if not FakeAPI.fast_polling:
                assert len(entities["sensor"]) > base_counts["sensor"]
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
            if not FakeAPI.fast_polling:
                assert coordinator.data["station-b"]["live_data"] == {}
            assert coordinator.data["station-a"]["telemetry_available"]
            FakeAPI.fail_station = None

            FakeAPI.auth_failure = True
            if FakeAPI.fast_polling:
                poller._due.clear()
                await poller.poll_once("station-a")
                assert poller._auth_failed and not pv.available
                assert reauth_requests
            await coordinator.async_refresh()
            assert not coordinator.last_update_success, "auth failure did not fail the coordinator"
            assert reauth_requests, "HA did not request reauthentication"
            FakeAPI.auth_failure = False

            assert await async_unload_entry(hass, entry)
            assert entry.entry_id not in hass.data[DOMAIN]
            if FakeAPI.fast_polling:
                assert not poller._tasks, "burst tasks leaked after unload"

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

        await validate_account_storage(hass)
        await hass.async_stop()
    print("Home Assistant lifecycle smoke passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--station-count", type=int, default=2)
    parser.add_argument("--fast-polling", action="store_true")
    args = parser.parse_args()
    FakeAPI.station_count = max(2, args.station_count)
    FakeAPI.fast_polling = args.fast_polling
    asyncio.run(main())
