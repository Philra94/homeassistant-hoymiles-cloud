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


def test_live_burst_sends_raw_authorization_without_cookies():
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
        assert headers["Authorization"] == "private-token"
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


def test_cached_live_uri_refreshes_expired_account_token():
    api, session = client([{"data": {"es": {"pp": 7}}}])
    api._live_uris["123"] = SIGNED
    api._token_expires_at = 0

    async def authenticate():
        api._token = "renewed-account-token"
        api._token_expires_at = 9999999999
        return True

    api.authenticate = authenticate
    assert asyncio.run(api.get_live_data("123")) == {"es": {"pp": 7}}
    assert len(session.requests) == 1
    assert session.requests[0]["kwargs"]["headers"]["Authorization"] == "renewed-account-token"


def test_burst_rejects_unsafe_destination_before_authentication():
    api, session = client([])
    api._token_expires_at = 0

    async def authenticate():
        pytest.fail("An unsafe burst destination must be rejected first")

    api.authenticate = authenticate
    with pytest.raises(module.LiveDataError):
        asyncio.run(api._post_live_burst("https://example.com/rds/api/0/burst/get?k=secret"))
    assert session.requests == []


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


def test_burst_accepts_hms_station_and_explicit_inverter_requests():
    api, session = client([
        {'status': '0', 'data': SIGNED},
        {'status': '0', 'data': {'con': 1, 'power': {'pv': 123}}},
        {'status': '0', 'data': {'con': 1, 'mis': [{'sn': 'A', 'pac': 100}]}},
    ])
    async def run():
        assert (await api.get_burst_data('123'))['power']['pv'] == 123
        assert (await api.get_burst_data('123', serials=['A']))['mis'][0]['pac'] == 100
    asyncio.run(run())
    assert session.requests[-1]['kwargs']['json'] == {'m': 3, 'mis': ['A'], 't': 1}
    assert len(session.requests) == 3


def test_burst_startup_metadata_does_not_cause_url_renewal():
    api, session = client([{'status': '0', 'data': SIGNED}, {'data': {'con': 1, 'dly': 5000}}])
    assert asyncio.run(api.get_burst_data('123')) == {'con': 1, 'dly': 5000}
    assert len(session.requests) == 2


def test_burst_uri_is_proactively_renewed(monkeypatch):
    api, session = client([{'status': '0', 'data': SIGNED}, {'data': {'power': {'pv': 0}}}])
    api._live_uris['123'] = SIGNED.replace('private-value', 'expired')
    api._live_uri_times['123'] = 10
    monkeypatch.setattr(module.time, 'monotonic', lambda: 300.)
    assert asyncio.run(api.get_burst_data('123')) == {'power': {'pv': 0}}
    assert len(session.requests) == 2


def test_concurrent_expired_token_requests_authenticate_once():
    api, _ = client([])
    api._token_expires_at = 0
    calls = []
    async def authenticate():
        calls.append(True)
        await asyncio.sleep(0)
        api._token_expires_at = 9999999999
        return True
    api.authenticate = authenticate
    async def run():
        await asyncio.gather(*(api._ensure_authenticated() for _ in range(15)))
    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize('second_status', [200, 401])
def test_burst_http_401_refreshes_credentials_once_then_recovers_or_requests_reauth(second_status):
    class StatusSession(FakeSession):
        def post(self, *args, **kwargs):
            request = super().post(*args, **kwargs)
            request._response.status = request._response._payload.pop('_http_status', 200)
            return request
    session = StatusSession([
        {'status': '0', 'data': SIGNED}, {'_http_status': 401},
        {'status': '0', 'data': SIGNED},
        {'_http_status': second_status, 'data': {'con': 1, 'power': {'pv': 100}}},
    ])
    api = HoymilesAPI(session, 'test@example.test', 'unused')
    api._token, api._token_expires_at = 'old', 9999999999
    refreshed = []
    async def authenticate():
        refreshed.append(True)
        api._token, api._token_expires_at = 'new', 9999999999
        return True
    api.authenticate = authenticate
    if second_status == 200:
        assert asyncio.run(api.get_burst_data('123'))['power']['pv'] == 100
    else:
        with pytest.raises(module.LiveDataAuthError):
            asyncio.run(api.get_burst_data('123'))
    assert refreshed == [True]
    assert session.requests[-1]['kwargs']['headers']['Authorization'] == 'new'


def test_burst_scopes_share_uri_without_serializing_their_http_requests():
    api, session = client([{'status': '0', 'data': SIGNED}])
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def post(uri, *, payload=None):
            if payload['m'] == 3:
                started.set()
                await release.wait()
                return {'data': {'con': 1, 'mis': []}}
            return {'data': {'con': 1, 'power': {'pv': 9}}}
        api._post_live_burst = post
        pending = asyncio.create_task(api.get_burst_data('123', serials=['A']))
        await started.wait()
        assert (await api.get_burst_data('123'))['power']['pv'] == 9
        assert not pending.done()
        release.set()
        await pending
    asyncio.run(run())
    assert len(session.requests) == 1
