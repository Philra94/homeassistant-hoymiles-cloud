# Repository Guidelines

Home Assistant custom integration (HACS) for the Hoymiles Cloud API. Single
package: `custom_components/hoymiles_cloud/`.

## Commands

- **Unit tests:** `pytest -q` from the repo root, in any environment that has
  `pytest` and `aiohttp`. The suite passes **without Home Assistant installed** —
  `tests/module_loader.py` loads integration modules directly from disk. Running
  from another directory breaks the `from tests.module_loader import ...` imports.
- **Live auth test (no HA needed):** `python scripts/test_login_flow.py --username "you@example.com" --try-matrix`
  (also uses the standalone loader; credentials via CLI/env only, never files).
- **Local HA instance (Docker):** `docker compose -f resources/home-assistant-test/docker-compose.yml up -d`
  mounts `custom_components/` read-only and serves `http://127.0.0.1:8123`. See
  `.cursor/skills/home-assistant-testing/SKILL.md` for the UI validation checklist.
- **Local HA instance (native):** install Home Assistant into a virtualenv, link
  the package into the test config (`ln -s "$PWD/custom_components" resources/home-assistant-test/config/custom_components`),
  then run `hass -c resources/home-assistant-test/config`. Restart `hass` to
  reload code. Runtime files in the config dir are covered by its own `.gitignore`.
- **Optional validation:** `pipx run hassfest` (manifest/structure). There is no
  lint/format/test CI — only Claude PR-review bots in `.github/workflows/`.

## Architecture

- Entry point `__init__.py`: config-entry setup, `DataUpdateCoordinator`, service
  registration; `PLATFORMS` = sensor, binary_sensor, number, select, text, button, switch.
- **HA-free modules** (importable in tests via `module_loader`): `auth.py` (auth
  attempt classification), `hoymiles_api.py` (all Hoymiles HTTP + auth hashing),
  `chart_pb.py` (protobuf chart decoding), `const.py`, `data.py`, `device.py`,
  `diagnostics.py`, `models.py`, `schedule_editor.py`. Keep new logic in these
  modules so it stays unit-testable; platform modules (`sensor.py`, etc.) import
  HA unconditionally and cannot be loaded standalone. Any unavoidable HA import
  in a shared module must be guarded with `try/except ImportError` plus a
  fallback (see `diagnostics.py`).
- Auth: config flow auto-tries several strategies (browser v3, S-Miles Installer
  v3, S-Miles Home v3, legacy v0); argon2 hashing is an optional guarded import
  in `hoymiles_api.py`. Failure reasons are classified in `auth.py` — preserve
  specific Hoymiles error messages instead of flattening them.
- Battery writes follow an async job flow: read → write → job id → status poll.
  Payload formats for battery modes/schedules are documented in
  `docs/hoymiles-battery-mode-api.md` — read it before touching battery/schedule code.
- Per-port PV data can come from the module day-chart endpoint when the
  indicators feed returns placeholders; see `docs/hoymiles-module-data-api.md`.
- Controls must only be exposed when the account's payload shows them as
  writable; telemetry must keep working when settings access is denied.

## Coding Style & Conventions

- Python 3.11+, 4-space indentation, type hints where practical, async I/O,
  log via `_LOGGER`; never block the event loop.
- Naming: modules `snake_case.py`; classes `PascalCase`; functions/vars
  `snake_case`; constants `UPPER_SNAKE_CASE` (see `const.py`).
- Anything that runs on every coordinator poll must log failures at `debug`, or
  warn only on the first failure of an outage — repeated warnings fill user logs.
- Bump `version` in `custom_components/hoymiles_cloud/manifest.json` for
  user-visible changes. `hacs.json` pins minimum HA `2023.10.0`.
- Update `README.md`, `services.yaml`, and `translations/en.json` when adding
  services/entities.
- Tests live in `tests/test_*.py` using the standalone loader with fake aiohttp
  sessions (see `tests/test_hoymiles_api.py` for the `FakeSession`/`FakeRequest`
  pattern) — do not add `pytest-homeassistant-custom-component` fixtures; the
  suite deliberately avoids HA dependencies. Tests must not depend on the wall
  clock: inject a fixed `now` rather than calling `datetime.now()`.

## Commit & Pull Request Guidelines

- Commits: short, imperative, scoped. Example: `feat(sensor): add grid export total`.
- PRs must include:
  - Clear description, linked issues, and reproduction/validation notes.
  - Screenshots/log excerpts for user-facing or UI changes.
  - Version bump in `manifest.json` for user-visible changes.
  - Updated `README.md`, `services.yaml`, and `translations/` when applicable.
- Keep PRs scoped: unrelated refactors and documentation rewrites belong in
  their own PR.

## Security & Configuration Tips

- Never commit credentials or tokens; redact logs in issues/PRs.
- Use `aiohttp` timeouts; handle API errors gracefully and log context without
  sensitive data.
- Keep external API specifics centralized in `hoymiles_api.py` to simplify
  review and testing.
