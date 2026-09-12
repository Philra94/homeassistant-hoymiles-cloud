"""Signed burst telemetry tests without contacting Hoymiles."""
import asyncio

import pytest

from tests.module_loader import load_integration_module
from tests.test_hoymiles_api import FakeSession

module = load_integration_module("hoymiles_api")
HoymilesAPI = module.HoymilesAPI
SIGNED = "https://eurt.hoymiles.com/rds/api/0/burst/get?sig=private-value"


def client(responses):
    session = FakeSession(responses)
    api = HoymilesAPI(session, "user@example.com", "secret")
    api._token = "private-token"
    api._token_expires_at = 9999999999
    return api, session


def test_live_burst_returns_raw_data_and_omits_auth_headers():
    payload = {"es": {"pp": 1, "gp": 2, "bp": 3, "lp": 4, "sp": 5}, "soc": 66, "flow": [], "con": 1, "t": 123, "dly": 10000}
    api, session = client([
        {"status": "0", "data": SIGNED},
        {"data": payload},
        {"data": payload},
    ])
    assert asyncio.run(api.get_live_data("123")) == payload
    assert asyncio.run(api.get_live_data("123")) == payload
    assert len(session.requests) == 3
    assert session.requests[0]["kwargs"]["json"] == {"sid": 123}
    for request in session.requests[1:]:
        assert request["kwargs"]["json"] == {"m": 0, "t": 1, "reflux": 0}
        headers = request["kwargs"]["headers"]
        assert "Authorization" not in headers
        assert "Cookie" not in headers
        assert request["kwargs"]["allow_redirects"] is False


def test_live_burst_renews_uri_once_after_failure():
    second = SIGNED.replace("private-value", "renewed")
    api, session = client([
        {"status": "0", "data": SIGNED},
        {"status": "500"},
        {"status": "0", "data": second},
        {"data": {"es": {"pp": 7}}},
    ])
    assert asyncio.run(api.get_live_data("123")) == {"es": {"pp": 7}}
    assert session.requests[3]["args"][0] == second


def test_expired_signed_uri_renews_without_account_auth_error():
    api, session = client([
        {"status": "0", "data": SIGNED},
        {"status": "401"},
        {"status": "0", "data": SIGNED.replace("private-value", "new")},
        {"data": {"es": {"sp": 88}}},
    ])
    assert asyncio.run(api.get_live_data("123")) == {"es": {"sp": 88}}
    assert len(session.requests) == 4


@pytest.mark.parametrize("uri", [
    "http://eurt.hoymiles.com/rds/api/0/burst/get?sig=x",
    "https://evil.example/rds/api/0/burst/get?sig=x",
    "https://eurt.hoymiles.com/other?sig=x",
    "https://eurt.hoymiles.com/rds/api/0/burst/get",
])
def test_live_uri_rejects_unsafe_targets_without_echoing_secret(uri):
    api, session = client([{"status": "0", "data": uri}])
    with pytest.raises(module.LiveDataError) as error:
        asyncio.run(api.get_live_data("123"))
    assert uri not in str(error.value)
    assert len(session.requests) == 1


def test_live_auth_denial_is_distinct():
    api, _ = client([{"status": "401", "message": "denied", "data": None}])
    with pytest.raises(module.LiveDataAuthError):
        asyncio.run(api.get_live_data("123"))


def test_live_station_permission_denial_is_not_account_auth_error():
    api, _ = client([{"status": "3", "message": "No Permission.", "data": None}])
    with pytest.raises(module.LiveDataError) as error:
        asyncio.run(api.get_live_data("123"))
    assert not isinstance(error.value, module.LiveDataAuthError)


def test_battery_write_does_not_submit_when_read_is_denied():
    api, session = client([{"status": "3", "message": "No Permission.", "data": None}])
    assert asyncio.run(api.set_battery_mode("123", 1)) is False
    assert len(session.requests) == 1


def test_authenticated_http_401_is_not_silently_decoded():
    class DeniedSession(FakeSession):
        def post(self, *args, **kwargs):
            request = super().post(*args, **kwargs)
            request._response.status = 401
            return request

    api = HoymilesAPI(DeniedSession([{}]), "user@example.com", "secret")
    api._token = "private-token"
    api._token_expires_at = 9999999999
    with pytest.raises(module.LiveDataAuthError):
        asyncio.run(api.get_station_details("123"))


def test_battery_writes_serialize_per_station_without_blocking_other_stations():
    api, _ = client([])
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    entered: list[str] = []
    settings = {
        "readable": True,
        "available_modes": [1],
        "mode_settings": {1: {"reserve_soc": 10}},
    }

    async def read_settings(station_id, mode):
        entered.append(station_id)
        if station_id == "A" and entered.count("A") == 1:
            first_entered.set()
            await release_first.wait()
        return settings, dict(settings["mode_settings"][1])

    async def apply(station_id, mode, payload):
        return True

    api._get_writable_mode_settings = read_settings
    api.apply_battery_mode_payload = apply

    async def run():
        first = asyncio.create_task(api.set_battery_mode_settings("A", 1, {"reserve_soc": 20}))
        await asyncio.wait_for(first_entered.wait(), 1)
        second = asyncio.create_task(api.set_battery_mode_settings("A", 1, {"reserve_soc": 30}))
        other = asyncio.create_task(api.set_battery_mode_settings("B", 1, {"reserve_soc": 40}))
        assert await asyncio.wait_for(other, 1) is True
        assert entered == ["A", "B"]
        release_first.set()
        assert await asyncio.wait_for(first, 1) is True
        assert await asyncio.wait_for(second, 1) is True
        assert entered == ["A", "B", "A"]

    asyncio.run(run())
