"""Tests for device-discovery diagnostics and the PV module-data fallback gate.

These cover the evidence needed to triage "devices/entities are missing"
reports (issues #41, #46, #47, #32): the diagnostics device inventory, the
per-endpoint fetch status that tells an empty list apart from a denied one,
and the relaxed module-data fallback gate.
"""

import asyncio

from tests.module_loader import load_integration_module
from tests.test_hoymiles_api import FakeSession

HoymilesAPI = load_integration_module("hoymiles_api").HoymilesAPI


def _authed_api(responses: list[dict]) -> HoymilesAPI:
    """Return an API client with a valid token and queued fake responses."""
    api = HoymilesAPI(FakeSession(responses), "user@example.com", "secret")
    api._token = "token"
    api._token_expires_at = 9999999999
    return api


def test_device_fetch_status_distinguishes_empty_from_denied() -> None:
    """An empty inverter list must look different from a denied one."""
    api = _authed_api(
        [{"status": "0", "message": "success", "data": {"total": 0, "list": []}}]
    )

    assert asyncio.run(api.get_inverters("77")) == []

    empty = api.device_fetch_status["77:inverters"]
    assert empty["ok"] is True
    assert empty["status"] == "0"
    assert empty["count"] == 0

    api = _authed_api([{"status": "3", "message": "No Permission"}])

    assert asyncio.run(api.get_inverters("77")) == []

    denied = api.device_fetch_status["77:inverters"]
    assert denied["ok"] is False
    assert denied["status"] == "3"
    assert denied["message"] == "No Permission"


def test_device_fetch_status_records_total_and_endpoint_label() -> None:
    """Each device family reports under its own endpoint label."""
    api = _authed_api(
        [
            {
                "status": "0",
                "message": "success",
                "data": {"total": 1, "list": [{"id": 5, "sn": "DTU-1"}]},
            }
        ]
    )

    assert asyncio.run(api.get_dtus("77")) == [{"id": 5, "sn": "DTU-1"}]

    entry = api.device_fetch_status["77:dtus"]
    assert entry["endpoint"] == "dtus"
    assert entry["station_id"] == "77"
    assert entry["total"] == 1
    assert entry["count"] == 1


def test_device_fetch_failure_warns_once_per_outage(caplog) -> None:
    """Repeated denials must not warn on every static refresh."""
    denied = {"status": "3", "message": "No Permission"}
    api = _authed_api([denied, denied, denied])

    with caplog.at_level("DEBUG"):
        for _ in range(3):
            asyncio.run(api.get_meters("77"))

    warnings = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "meters" in record.getMessage()
    ]
    assert len(warnings) == 1

    # A recovery re-arms the warning for the next outage.
    api._session = FakeSession(
        [
            {"status": "0", "message": "success", "data": {"total": 0, "list": []}},
            denied,
        ]
    )
    caplog.clear()
    with caplog.at_level("DEBUG"):
        asyncio.run(api.get_meters("77"))
        asyncio.run(api.get_meters("77"))

    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


def test_microinverter_fetch_status_records_denial() -> None:
    """A denied microinverter list is recorded, not silently empty."""
    api = _authed_api([{"status": "3", "message": "No Permission"}])

    assert asyncio.run(api.get_microinverters_by_stations("77")) == {}

    entry = api.device_fetch_status["77:microinverters"]
    assert entry["ok"] is False
    assert entry["status"] == "3"
    assert entry["message"] == "No Permission"


def test_microinverter_fetch_status_records_success_counts() -> None:
    """A successful microinverter list records its total and count."""
    api = _authed_api(
        [
            {
                "status": "0",
                "message": "success",
                "data": {"total": 1, "list": [{"id": 42}]},
            },
            {"status": "0", "message": "success", "data": {"id": 42, "sn": "MI-1"}},
        ]
    )

    micros = asyncio.run(api.get_microinverters_by_stations("77"))

    assert micros == {"42": {"id": 42, "sn": "MI-1"}}
    entry = api.device_fetch_status["77:microinverters"]
    assert entry["ok"] is True
    assert entry["total"] == 1
    assert entry["count"] == 1


def test_indicator_fetch_status_records_denial() -> None:
    """A denied PV indicator call is visible in the fetch status."""
    api = _authed_api([{"status": "3", "message": "No Permission"}])

    assert asyncio.run(api.get_pv_indicators("77")) == {}

    entry = api.device_fetch_status["77:pv_indicators"]
    assert entry["ok"] is False
    assert entry["status"] == "3"

