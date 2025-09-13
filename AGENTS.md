# Repository Guidelines

## Project Structure & Module Organization
- Source: `custom_components/hoymiles_cloud/`
  - Core: `__init__.py`, `hoymiles_api.py`, `const.py`, `config_flow.py`
  - Platforms: `sensor.py`, `number.py`, `select.py`, `custom_select.py`
  - Meta: `manifest.json`, `services.yaml`, `translations/`, `icon`
- CI: `.github/workflows/` (code review automation)
- Docs: `README.md`
- Tests: not present; add under `tests/` mirroring module paths.

## Build, Test, and Development Commands
- Run locally (recommended): copy `custom_components/hoymiles_cloud` into your Home Assistant config’s `custom_components/` and restart Home Assistant.
- Optional validation (if you use pipx): `pipx run hassfest` to validate manifest and structure; `pipx run script.hacs` to check HACS metadata.
- Lint/format (optional but encouraged): `ruff check .` and `black custom_components/`.

## Coding Style & Naming Conventions
- Python 3.11+, 4‑space indentation, type hints where practical.
- Naming: modules `snake_case.py`; classes `PascalCase`; functions/vars `snake_case`; constants `UPPER_SNAKE_CASE` (see `const.py`).
- Home Assistant patterns: prefer `async` I/O, use `DataUpdateCoordinator`, avoid blocking calls in event loop, log via `_LOGGER`.

## Testing Guidelines
- Framework: `pytest` with `pytest-homeassistant-custom-component`.
- Location/naming: place tests in `tests/` as `test_*.py`; mirror package layout (e.g., `tests/test_config_flow.py`).
- Focus: config flow auth errors, API timeouts, coordinator refresh, entity values/availability.
- Command: `pytest -q` (configure deps in your env).

## Commit & Pull Request Guidelines
- Commits: short, imperative, scoped. Example: `feat(sensor): add grid export total`.
- PRs must include:
  - Clear description, linked issues, and reproduction/validation notes.
  - Screenshots/log excerpts for user-facing or UI changes.
  - Version bump in `manifest.json` for user-visible changes.
  - Updated `README.md`, `services.yaml`, and `translations/` when applicable.

## Security & Configuration Tips
- Never commit credentials or tokens; redact logs in issues/PRs.
- Use `aiohttp` timeouts; handle API errors gracefully and log context without sensitive data.
- Keep external API specifics centralized in `hoymiles_api.py` to simplify review and testing.
