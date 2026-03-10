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

    async with aiohttp.ClientSession() as session:
        api = HoymilesAPI(session, username, password)
        api.configure_auth(auth_mode=args.auth_mode, app_version=args.app_version)

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
                api.configure_auth(auth_mode=auth_mode, app_version=app_version)
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
