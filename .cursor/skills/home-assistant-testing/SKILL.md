---
name: home-assistant-testing
description: Run a disposable Home Assistant container against this repository's custom component and verify the integration through the real UI with Playwright. Use when testing Home Assistant config flows, entity creation, onboarding, or end-to-end behavior of `custom_components/`.
---

# Home Assistant Testing

## Purpose

Use this skill to validate the custom integration end to end in a throwaway Home Assistant instance.

## Quick Start

1. Use the reusable files in `resources/home-assistant-test/`.
2. Start the container with Docker, mounting:
   - `resources/home-assistant-test/config` to `/config`
   - `custom_components` to `/config/custom_components`
3. Wait for Home Assistant to finish booting on `http://127.0.0.1:8123`.
4. Use the Playwright MCP browser tools to:
   - complete onboarding if needed
   - open Devices & Services
   - add the custom integration
   - enter credentials in the UI instead of storing them in files
5. Inspect logs and created entities before concluding the test.

## Container Workflow

Run the harness from the repository root:

```bash
docker compose -f resources/home-assistant-test/docker-compose.yml up -d
```

Stop and clean up when done:

```bash
docker compose -f resources/home-assistant-test/docker-compose.yml down
```

## Validation Checklist

- [ ] Home Assistant boots cleanly
- [ ] The custom component is discovered
- [ ] Config flow loads without a server error
- [ ] Credentials can be entered in the UI without being written to disk
- [ ] Setup succeeds or fails with a specific, actionable message
- [ ] Expected devices/entities appear under the integration
- [ ] Logs match the observed UI behavior

## Notes

- Prefer the real Home Assistant UI over direct file-based config when validating config flow behavior.
- Do not commit credentials or place them in `configuration.yaml`.
- If the browser MCP cannot launch because of a local Chrome conflict, resolve that before continuing UI automation.
- Keep this skill focused on disposable local testing; do not reuse the container as a long-lived development environment.
