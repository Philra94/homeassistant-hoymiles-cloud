#!/usr/bin/env python3
"""Live verifier for the Hoymiles authentication flows.

This script uses the integration's real API client without importing the
Home Assistant package. Provide credentials via CLI args or environment
variables so they never need to be stored in the repository.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import json
import os
import pathlib
import sys
import types
from typing import Any

import aiohttp


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = REPO_ROOT / "custom_components" / "hoymiles_cloud"
PACKAGE_NAME = "custom_components.hoymiles_cloud"


def _load_module(module_name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module {module_name} from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_api_class():
    """Load the API module without importing Home Assistant."""
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(INTEGRATION_ROOT)]
    sys.modules[PACKAGE_NAME] = package

    _load_module(f"{PACKAGE_NAME}.const", INTEGRATION_ROOT / "const.py")
    _load_module(f"{PACKAGE_NAME}.auth", INTEGRATION_ROOT / "auth.py")
    api_module = _load_module(
        f"{PACKAGE_NAME}.hoymiles_api",
        INTEGRATION_ROOT / "hoymiles_api.py",
    )
    return api_module.HoymilesAPI


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Test Hoymiles authentication flows."
    )
    parser.add_argument(
        "--username",
        default=None,
        help="Hoymiles account email. Defaults to HOYMILES_USERNAME.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Hoymiles account password. Defaults to HOYMILES_PASSWORD.",
    )
    parser.add_argument(
        "--skip-user",
        action="store_true",
        help="Skip the post-login /iam/api/1/user/me validation step.",
    )
    parser.add_argument(
        "--skip-stations",
        action="store_true",
        help="Skip the post-login station list validation step.",
    )
    parser.add_argument(
        "--auth-mode",
        default="auto",
        choices=("auto", "web_v3", "installer_v3", "home_v3", "legacy_v0"),
        help="Authentication strategy to test. Defaults to auto.",
    )
    parser.add_argument(
        "--app-version",
        default=None,
        help="Override the app version used for installer/home auth attempts.",
    )
    parser.add_argument(
        "--auth-base-url",
        default=None,
        help=(
            "Advanced: override the auth backend host (e.g. a candidate S-Miles "
            "Home consumer backend discovered via a network trace), such as "
            "https://example.hoymiles.com."
        ),
    )
    parser.add_argument(
        "--dump-raw",
        action="store_true",
        help=(
            "Print the sanitized raw pre-inspection request/response for the "
            "selected profile/host, formatted for pasting into a GitHub issue."
        ),
    )
    parser.add_argument(
        "--mobile-app-version",
        dest="app_version",
        default=None,
        help="Deprecated alias for --app-version.",
    )
    parser.add_argument(
        "--try-matrix",
        action="store_true",
        help="Run a small auth/profile matrix instead of a single attempt.",
    )
    return parser


def resolve_credentials(args: argparse.Namespace) -> tuple[str, str]:
    """Resolve credentials from args, env, or a secure prompt."""
    username = args.username or os.getenv("HOYMILES_USERNAME")
    password = args.password or os.getenv("HOYMILES_PASSWORD")

    if not username:
        username = input("Hoymiles username: ").strip()
    if not password:
        password = getpass.getpass("Hoymiles password: ")

    if not username or not password:
        raise SystemExit("Username and password are required.")

    return username, password


def redact_token(token: str | None) -> str:
    """Return a short redacted token preview."""
    if not token:
        return "<missing>"
    if len(token) <= 12:
        return token
    return f"{token[:8]}...{token[-4:]}"


SENSITIVE_KEYS = ("a", "ch", "token", "salt", "password", "pwd")


def sanitize_payload(value: Any) -> Any:
    """Recursively mask password/salt/token-derived values for safe sharing."""
    if isinstance(value, dict):
        return {
            key: ("<redacted>" if key.lower() in SENSITIVE_KEYS else sanitize_payload(val))
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """Mask any auth-bearing headers before printing."""
    masked = {}
    for key, val in headers.items():
        masked[key] = "<redacted>" if key.lower() in ("authorization", "cookie") else val
    return masked


async def dump_raw_pre_insp(api: Any, session: "aiohttp.ClientSession", auth_mode: str) -> None:
    """Print the sanitized raw pre-inspection request/response for diagnostics.

    The pre-inspection call only sends the username, so its request body is safe
    to share once the email is masked. Its response reveals the salt field ``a``
    (or its absence), which is what distinguishes Hoymiles account families.
    """
    const = sys.modules[f"{PACKAGE_NAME}.const"]
    profile = const.AUTH_MODE_TO_PROFILE.get(auth_mode, const.CLIENT_PROFILE_WEB)
    url = api._auth_url(profile, const.AUTH_PATH_PRE_INSP_V3)  # noqa: SLF001
    print("\n=== RAW pre-insp dump (safe to paste into a GitHub issue) ===")
    if not url:
        print(f"Profile '{profile}' has no configured backend host (base_url is None).")
        print("Use --auth-base-url to point at a candidate host.")
        return

    headers = api._json_headers(client_profile=profile)  # noqa: SLF001
    print(f"POST {url}")
    print("Request headers:")
    print(json.dumps(sanitize_headers(headers), indent=2, sort_keys=True))
    print('Request body: {"u": "<redacted-email>"}')
    try:
        async with session.post(url, headers=headers, json={"u": api._username}) as response:  # noqa: SLF001
            body = await response.json(content_type=None)
            print(f"Response status (HTTP): {response.status}")
            print("Response body:")
            print(json.dumps(sanitize_payload(body), indent=2, sort_keys=True))
    except Exception as err:  # noqa: BLE001
        print(f"Pre-insp request failed: {err}")
    print(
        "\nNote: the follow-up /auth/login body is {u, ch, n} where 'ch' is a "
        "password-derived hash (redacted above). Share the login HTTP status and "
        "message from the attempt summary instead.\n"
    )


def summarize_user(user: dict[str, Any]) -> dict[str, Any]:
    """Return a small, stable subset of user data."""
    interesting_keys = (
        "id",
        "username",
        "nickname",
        "email",
        "phone",
        "country",
        "lang",
        "role",
    )
    return {key: user.get(key) for key in interesting_keys if key in user}


async def main() -> int:
    """Execute the live auth flow."""
    parser = build_parser()
    args = parser.parse_args()
    username, password = resolve_credentials(args)
    HoymilesAPI = load_api_class()

    print("Testing Hoymiles authentication flow...")
    print(f"Username: {username}")
    print(f"Auth mode: {args.auth_mode}")

    if args.auth_base_url:
        print(f"Auth base URL override: {args.auth_base_url}")

    async with aiohttp.ClientSession() as session:
        api = HoymilesAPI(session, username, password)
        api.configure_auth(
            auth_mode=args.auth_mode,
            app_version=args.app_version,
            auth_base_url=args.auth_base_url,
        )

        if args.dump_raw:
            await dump_raw_pre_insp(api, session, args.auth_mode)

        if args.try_matrix:
            matrix = [
                ("web_v3", None),
                ("installer_v3", args.app_version or "3.7.1"),
                ("home_v3", args.app_version or "2.8.0"),
                ("legacy_v0", None),
            ]
            overall_success = False
            print("Trying auth matrix...")
            for auth_mode, app_version in matrix:
                api.configure_auth(
                    auth_mode=auth_mode,
                    app_version=app_version,
                    auth_base_url=args.auth_base_url,
                )
                authenticated = await api.authenticate()
                status = "OK" if authenticated else "FAILED"
                detail = api.auth_method if authenticated else api.last_auth_attempt_summary
                version_suffix = f" (app_version={app_version})" if app_version else ""
                print(f"- {auth_mode}{version_suffix}: {status} -> {detail}")
                if authenticated:
                    overall_success = True
            return 0 if overall_success else 1

        authenticated = await api.authenticate()

        if not authenticated:
            print("Authentication: FAILED")
            print(f"Last strategy: {api.last_auth_attempt or '<none>'}")
            print(f"Last method: {api.auth_method or '<none>'}")
            print(f"Error key: {api.last_auth_error_key or '<none>'}")
            print(f"API status: {api.last_auth_status or '<none>'}")
            print(f"API message: {api.last_auth_message or '<none>'}")
            print(f"Attempts: {api.last_auth_attempt_summary}")
            return 1

        print("Authentication: OK")
        print(f"Method: {api.auth_method}")
        print(f"Token: {redact_token(getattr(api, '_token', None))}")

        if not args.skip_user:
            user = await api.get_current_user()
            print("User profile:")
            print(json.dumps(summarize_user(user), indent=2, sort_keys=True))

        if not args.skip_stations:
            stations = await api.get_stations()
            print(f"Stations found: {len(stations)}")
            print(json.dumps(stations, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
