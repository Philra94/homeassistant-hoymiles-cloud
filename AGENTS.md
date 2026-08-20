# Repository Guidelines

Home Assistant custom integration (HACS) for the Hoymiles Cloud API. Single package: `custom_components/hoymiles_cloud/`.

## Commands (verified)

- **Setup (UV, preferred):** `uv sync` creates `.venv` with Home Assistant, the manifest requirements, and `pytest`. `pyproject.toml` is dev-env only (`package = false`); keep its `dependencies` in sync with `manifest.json` `requirements`.
- **Unit tests:** `uv run pytest -q` from the repo root (plain `pytest -q` works in any env with `pytest` + `aiohttp`). Tests pass **without Home Assistant installed** — `tests/module_loader.py` loads integration modules directly from disk. Running from another directory breaks the `from tests.module_loader import ...` imports.
- **Live auth test (no HA needed):** `uv run python scripts/test_login_flow.py --username "you@example.com" --try-matrix` (also uses the standalone loader; credentials via CLI/env only, never files).
- **Local HA instance (native, no Docker):** `uv run hass -c resources/home-assistant-test/config` serves `http://127.0.0.1:8123`. The config dir contains a `custom_components` symlink to the repo's `custom_components/`; restart `hass` to reload code. First boot is slow (one-time install of `default_config` discovery deps); later boots ~30s. Runtime files in the config dir are covered by its own `.gitignore`.
- **Local HA instance (Docker alternative):** `docker compose -f resources/home-assistant-test/docker-compose.yml up -d` mounts `custom_components/` read-only on the same port. See `.cursor/skills/home-assistant-testing/SKILL.md` for the UI validation checklist.
- **Optional validation:** `pipx run hassfest` (manifest/structure). There is no lint/format/test CI — only Claude PR-review bots in `.github/workflows/`.

## Architecture

- Entry point `__init__.py`: config-entry setup, `DataUpdateCoordinator`, service registration; `PLATFORMS` = sensor, binary_sensor, number, select, text, button, switch.
- **HA-free modules** (importable in tests via `module_loader`): `auth.py` (auth attempt classification), `hoymiles_api.py` (all Hoymiles HTTP + auth hashing), `chart_pb.py` (protobuf chart decoding), `const.py`, `data.py`, `device.py`, `diagnostics.py`, `models.py`, `schedule_editor.py`. Keep new logic in these modules so it stays unit-testable; platform modules (`sensor.py`, etc.) import HA unconditionally and cannot be loaded standalone. Any unavoidable HA import in a shared module must be guarded with `try/except ImportError` plus a fallback (see `diagnostics.py`).
- Auth: config flow auto-tries several strategies (browser v3, S-Miles Installer v3, S-Miles Home v3, legacy v0); argon2 hashing is an optional guarded import in `hoymiles_api.py`. Failure reasons are classified in `auth.py` — preserve specific Hoymiles error messages instead of flattening them.
- Battery writes follow an async job flow: read → write → job id → status poll. Payload formats for battery modes/schedules are documented in `docs/hoymiles-battery-mode-api.md` — read it before touching battery/schedule code.
- Controls must only be exposed when the account's payload shows them as writable; telemetry must keep working when settings access is denied.

## Conventions

- Python 3.11+, async I/O, log via `_LOGGER`; never commit credentials or tokens.
- Bump `version` in `custom_components/hoymiles_cloud/manifest.json` for user-visible changes. `hacs.json` pins minimum HA `2023.10.0`.
- Update `README.md`, `services.yaml`, and `translations/en.json` when adding services/entities.
- Tests live in `tests/test_*.py` using the standalone loader with fake aiohttp sessions (see `tests/test_hoymiles_api.py` for the `FakeSession`/`FakeRequest` pattern) — do not add `pytest-homeassistant-custom-component` fixtures; the suite deliberately avoids HA dependencies.
