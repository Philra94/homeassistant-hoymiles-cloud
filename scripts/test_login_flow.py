#!/usr/bin/env python3
"""Live verifier for the Hoymiles browser-style login flow.

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
    api_module = _load_module(
        f"{PACKAGE_NAME}.hoymiles_api",
        INTEGRATION_ROOT / "hoymiles_api.py",
    )
    return api_module.HoymilesAPI


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Test the browser-matched Hoymiles login flow."
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

    print("Testing Hoymiles browser-style login flow...")
    print(f"Username: {username}")

    async with aiohttp.ClientSession() as session:
        api = HoymilesAPI(session, username, password)
        authenticated = await api.authenticate()

        if not authenticated:
            print("Authentication: FAILED")
            print(f"Last method: {api.auth_method or '<none>'}")
            print(f"API status: {api.last_auth_status or '<none>'}")
            print(f"API message: {api.last_auth_message or '<none>'}")
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
