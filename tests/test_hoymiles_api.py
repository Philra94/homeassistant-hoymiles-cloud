"""Tests for the Hoymiles API client."""
import asyncio

from tests.module_loader import load_integration_module

auth_module = load_integration_module("auth")
HoymilesAPI = load_integration_module("hoymiles_api").HoymilesAPI
AUTH_ERROR_APP_UPDATE_REQUIRED = auth_module.AUTH_ERROR_APP_UPDATE_REQUIRED
AUTH_ERROR_S_MILES_HOME_REQUIRED = auth_module.AUTH_ERROR_S_MILES_HOME_REQUIRED
auth_error_to_config_error = auth_module.auth_error_to_config_error


class FakeResponse:
    """Minimal aiohttp-like response wrapper for tests."""

    def __init__(self, payload: dict):
        self._payload = payload

    async def text(self) -> str:
        import json

        return json.dumps(self._payload)

    async def json(self) -> dict:
        return self._payload


class FakeRequest:
    """Object that works as both awaitable and async context manager."""

    def __init__(self, payload: dict):
        self._response = FakeResponse(payload)

    def __await__(self):
        async def _result():
            return self._response

        return _result().__await__()

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    """Simple fake session with queued responses."""

    def __init__(self, responses: list[dict]):
        self._responses = responses
        self.requests: list[dict] = []

    def post(self, *args, **kwargs):  # noqa: ANN002, ANN003 - test double
        if not self._responses:
            raise AssertionError("No fake responses left")
        self.requests.append({"args": args, "kwargs": kwargs})
        return FakeRequest(self._responses.pop(0))


def test_get_stations_paginates_all_pages() -> None:
    """The client should fetch more than the first 10 stations."""
    api = HoymilesAPI(
        FakeSession(
            [
                {
                    "status": "0",
                    "message": "success",
                    "data": {
                        "total": 3,
                        "list": [
                            {"id": 1, "name": "Roof"},
                            {"id": 2, "name": "Garage"},
                        ],
                    },
                },
                {
                    "status": "0",
                    "message": "success",
                    "data": {
                        "total": 3,
                        "list": [
                            {"id": 3, "name": "Shed"},
                        ],
                    },
                },
            ]
        ),
        "user@example.com",
        "secret",
    )
    api._token = "token"
    api._token_expires_at = 9999999999

    stations = asyncio.run(api.get_stations())

    assert stations == {"1": "Roof", "2": "Garage", "3": "Shed"}


def test_get_battery_settings_permission_denied_returns_capabilities() -> None:
    """Permission errors should not be converted into fake mode defaults."""
    api = HoymilesAPI(
        FakeSession(
            [
                {
                    "status": "3",
                    "message": "No Permission.",
                    "data": None,
                }
            ]
        ),
        "user@example.com",
        "secret",
    )
    api._token = "token"
    api._token_expires_at = 9999999999

    battery_settings = asyncio.run(api.get_battery_settings("123"))

    assert battery_settings["readable"] is False
    assert battery_settings["writable"] is False
    assert battery_settings["data"] == {}
    assert battery_settings["error_status"] == "3"
    assert battery_settings["error_message"] == "No Permission."


def test_get_battery_settings_success_exposes_available_modes() -> None:
    """Successful responses should preserve the full mode shape."""
    api = HoymilesAPI(
        FakeSession(
            [
                {
                    "status": "0",
                    "message": "success",
                    "data": {
                        "data": {
                            "mode": 7,
                            "data": {
                                "k_1": {"reserve_soc": 20},
                                "k_7": {
                                    "reserve_soc": 30,
                                    "max_soc": 70,
                                    "meter_power": 3000,
                                },
                            },
                        }
                    },
                }
            ]
        ),
        "user@example.com",
        "secret",
    )
    api._token = "token"
    api._token_expires_at = 9999999999

    battery_settings = asyncio.run(api.get_battery_settings("123"))

    assert battery_settings["readable"] is True
    assert battery_settings["writable"] is True
    assert battery_settings["available_modes"] == [1, 7]
    assert battery_settings["data"]["mode"] == 7
    assert battery_settings["data"]["reserve_soc"] == 30


def test_authenticate_preserves_s_miles_home_failure_details() -> None:
    """Auto auth should keep the most useful account-type failure."""
    session = FakeSession(
        [
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce1"}},
            {"status": "1", "message": "Can only login to the S-Miles Home."},
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce2"}},
            {"status": "1", "message": "Invalid credentials"},
            {"status": "1", "message": "Invalid credentials"},
        ]
    )
    api = HoymilesAPI(session, "user@example.com", "secret")

    authenticated = asyncio.run(api.authenticate())

    assert authenticated is False
    assert api.last_auth_error_key == AUTH_ERROR_S_MILES_HOME_REQUIRED
    assert api.last_auth_message == "Can only login to the S-Miles Home."
    assert auth_error_to_config_error(api.last_auth_error_key) == "s_miles_home_required"


def test_authenticate_classifies_version_gated_failures() -> None:
    """Auto auth should surface app-version-gated responses clearly."""
    session = FakeSession(
        [
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce1"}},
            {"status": "1", "message": "Your app version is low. Please update to the latest version."},
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce2"}},
            {"status": "1", "message": "Invalid credentials"},
            {"status": "1", "message": "Invalid credentials"},
        ]
    )
    api = HoymilesAPI(session, "user@example.com", "secret")

    authenticated = asyncio.run(api.authenticate())

    assert authenticated is False
    assert api.last_auth_error_key == AUTH_ERROR_APP_UPDATE_REQUIRED
    assert auth_error_to_config_error(api.last_auth_error_key) == "app_update_required"


def test_mobile_profile_headers_include_version_metadata() -> None:
    """Mobile-profile requests should include explicit version headers."""
    api = HoymilesAPI(FakeSession([]), "user@example.com", "secret")

    headers = api._json_headers(client_profile="mobile", app_version="3.7.0")

    assert headers["User-Agent"] == "S-Miles Home/3.7.0"
    assert headers["App-Version"] == "3.7.0"
    assert headers["X-App-Version"] == "3.7.0"
    assert headers["X-Client-Type"] == "mobile"
