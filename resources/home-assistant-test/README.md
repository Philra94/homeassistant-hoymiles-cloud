# Home Assistant Test Harness

This directory contains a disposable Home Assistant setup for validating the
custom component in this repository against the real UI.

## Start

```bash
docker compose -f resources/home-assistant-test/docker-compose.yml up -d
```

## Stop

```bash
docker compose -f resources/home-assistant-test/docker-compose.yml down
```

## Mounted paths

- `resources/home-assistant-test/config` -> `/config`
- `custom_components` -> `/config/custom_components`

Do not place live credentials in `configuration.yaml`. Enter them through the
Home Assistant UI during testing.
