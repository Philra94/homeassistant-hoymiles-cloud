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
                    "data": "job-123",
                },
                {
                    "status": "0",
                    "message": "success",
                    "data": {
                        "code": 0,
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
    assert api._session.requests[0]["kwargs"]["json"] == {"action": 1013, "data": {"sid": 123}}
    assert api._session.requests[1]["kwargs"]["json"] == {"id": "job-123"}


def test_set_battery_mode_polls_write_job_until_complete() -> None:
    """Battery mode writes should follow the async write -> status polling flow."""
    session = FakeSession(
        [
            {
                "status": "0",
                "message": "success",
                "data": "read-job",
            },
            {
                "status": "0",
                "message": "success",
                "data": {
                    "code": 0,
                    "data": {
                        "mode": 1,
                        "data": {
                            "k_1": {"reserve_soc": 10},
                        },
                    },
                },
            },
            {
                "status": "0",
                "message": "success",
                "data": "write-job",
            },
            {
                "status": "0",
                "message": "success",
                "data": {"code": 2, "data": []},
            },
            {
                "status": "0",
                "message": "success",
                "data": {"code": 0, "data": []},
            },
        ]
    )
    api = HoymilesAPI(session, "user@example.com", "secret")
    api._token = "token"
    api._token_expires_at = 9999999999

    success = asyncio.run(api.set_battery_mode("123", 1))

    assert success is True
    assert session.requests[2]["kwargs"]["json"] == {
        "action": 1013,
        "data": {"sid": 123, "data": {"mode": 1, "data": {"reserve_soc": 10}}},
    }
    assert session.requests[3]["kwargs"]["json"] == {"id": "write-job"}
    assert session.requests[4]["kwargs"]["json"] == {"id": "write-job"}


def test_set_battery_mode_settings_merges_into_existing_schedule_payload() -> None:
    """Advanced mode updates should preserve schedule data by default."""
    session = FakeSession(
        [
            {
                "status": "0",
                "message": "success",
                "data": "read-job",
            },
            {
                "status": "0",
                "message": "success",
                "data": {
                    "code": 0,
                    "data": {
                        "mode": 8,
                        "data": {
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
                            }
                        },
                    },
                },
            },
            {
                "status": "0",
                "message": "success",
                "data": "write-job",
            },
            {
                "status": "0",
                "message": "success",
                "data": {"code": 0, "data": []},
            },
        ]
    )
    api = HoymilesAPI(session, "user@example.com", "secret")
    api._token = "token"
    api._token_expires_at = 9999999999

    success = asyncio.run(
        api.set_battery_mode_settings("123", 8, {"reserve_soc": 15})
    )

    assert success is True
    assert session.requests[2]["kwargs"]["json"] == {
        "action": 1013,
        "data": {
            "sid": 123,
            "data": {
                "mode": 8,
                "data": {
                    "reserve_soc": 15,
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
            },
        },
    }


def test_authenticate_preserves_s_miles_home_failure_details() -> None:
    """Auto auth should keep the most useful account-type failure."""
    session = FakeSession(
        [
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce1"}},
            {"status": "1", "message": "Invalid credentials"},
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce2"}},
            {"status": "1", "message": "Invalid credentials"},
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce3"}},
            {"status": "1", "message": "Can only login to the S-Miles Home."},
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
            {"status": "1", "message": "Invalid credentials"},
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce2"}},
            {"status": "1", "message": "Your app version is low. Please update to the latest version."},
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce3"}},
            {"status": "1", "message": "Invalid credentials"},
            {"status": "1", "message": "Invalid credentials"},
        ]
    )
    api = HoymilesAPI(session, "user@example.com", "secret")

    authenticated = asyncio.run(api.authenticate())

    assert authenticated is False
    assert api.last_auth_error_key == AUTH_ERROR_APP_UPDATE_REQUIRED
    assert auth_error_to_config_error(api.last_auth_error_key) == "app_update_required"


def test_installer_profile_headers_include_version_metadata() -> None:
    """Installer-profile requests should include explicit version headers."""
    api = HoymilesAPI(FakeSession([]), "user@example.com", "secret")

    headers = api._json_headers(client_profile="installer", app_version="3.7.1")

    assert headers["User-Agent"] == "S-Miles Installer/3.7.1"
    assert headers["App-Version"] == "3.7.1"
    assert headers["X-App-Version"] == "3.7.1"
    assert headers["X-Client-Type"] == "mobile"


def test_home_profile_headers_include_version_metadata() -> None:
    """Home-profile requests should include explicit version headers."""
    api = HoymilesAPI(FakeSession([]), "user@example.com", "secret")

    headers = api._json_headers(client_profile="home", app_version="2.8.0")

    assert headers["User-Agent"] == "S-Miles Home/2.8.0"
    assert headers["App-Version"] == "2.8.0"
    assert headers["X-App-Version"] == "2.8.0"
    assert headers["X-Client-Type"] == "mobile"


def test_decode_v3_salt_prefers_hex_browser_format() -> None:
    """Salt values observed in the browser should decode from hex."""
    api = HoymilesAPI(FakeSession([]), "user@example.com", "secret")

    salt = api._decode_v3_salt("d5e3f019748d7a36d69840fdfd873d15")

    assert salt == bytes.fromhex("d5e3f019748d7a36d69840fdfd873d15")


def test_decode_v3_salt_still_accepts_base64() -> None:
    """Legacy assumptions about base64 salts should remain supported."""
    api = HoymilesAPI(FakeSession([]), "user@example.com", "secret")

    salt = api._decode_v3_salt("YWJjZA==")

    assert salt == b"abcd"


def test_configured_auth_preferences_affect_future_attempts() -> None:
    """Configured auth preferences should affect subsequent authenticate calls."""
    session = FakeSession(
        [
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce1"}},
            {"status": "0", "message": "success", "data": {"token": "token-123"}},
        ]
    )
    api = HoymilesAPI(session, "user@example.com", "secret")
    api.configure_auth(auth_mode="home_v3", app_version="2.8.0")

    authenticated = asyncio.run(api.authenticate())

    assert authenticated is True
    assert api.auth_method == "home_v3:sha256_v3"
    assert api.last_auth_attempt == "home_v3"
    assert session.requests[0]["kwargs"]["headers"]["User-Agent"] == "S-Miles Home/2.8.0"


def test_unsalted_v3_retries_with_sha256_hex_variant() -> None:
    """Unsalted v3 auth should retry a browser-like SHA-256 hex variant."""
    session = FakeSession(
        [
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce1"}},
            {"status": "1", "message": "Log in failed. Please check your account and password.#7"},
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce2"}},
            {"status": "0", "message": "success", "data": {"token": "token-hex"}},
        ]
    )
    api = HoymilesAPI(session, "user@example.com", "secret")
    api.configure_auth(auth_mode="web_v3")

    authenticated = asyncio.run(api.authenticate())

    assert authenticated is True
    assert api.auth_method == "web_v3:sha256_hex_v3"
    first_login_payload = session.requests[1]["kwargs"]["json"]
    second_login_payload = session.requests[3]["kwargs"]["json"]
    assert "." in first_login_payload["ch"]
    assert len(second_login_payload["ch"]) == 64
    assert "." not in second_login_payload["ch"]


def test_pre_insp_accepts_top_level_payload_shape() -> None:
    """Top-level pre-inspection payloads should be treated as a successful response."""
    session = FakeSession(
        [
            {"u": "user@example.com", "n": "nonce-top"},
            {"status": "0", "message": "success", "data": {"token": "token-top"}},
        ]
    )
    api = HoymilesAPI(session, "user@example.com", "secret")
    api.configure_auth(auth_mode="web_v3")

    authenticated = asyncio.run(api.authenticate())

    assert authenticated is True
    assert api.auth_method == "web_v3:sha256_v3"


def test_auth_attempt_summary_lists_all_attempts() -> None:
    """Failed auth runs should keep a readable attempt summary."""
    session = FakeSession(
        [
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce1"}},
            {"status": "1", "message": "Invalid credentials"},
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce2"}},
            {"status": "1", "message": "Your app version is low. Please update to the latest version."},
            {"status": "0", "message": "success", "data": {"a": None, "n": "nonce3"}},
            {"status": "1", "message": "Can only login to the S-Miles Home."},
            {"status": "1", "message": "Invalid credentials"},
        ]
    )
    api = HoymilesAPI(session, "user@example.com", "secret")

    authenticated = asyncio.run(api.authenticate())

    assert authenticated is False
    assert "web_v3[web]" in api.last_auth_attempt_summary
    assert "installer_v3[installer/3.7.1]" in api.last_auth_attempt_summary
    assert "home_v3[home/2.8.0]" in api.last_auth_attempt_summary
    assert "legacy_v0[web]" in api.last_auth_attempt_summary
    assert "sha256_v3" in api.last_auth_attempt_summary
