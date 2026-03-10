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

## Suggested auth validation flow

1. Use the live auth script first to find a working profile/version combination:

```bash
python3 scripts/test_login_flow.py --username "you@example.com" --try-matrix
```

2. Start the disposable Home Assistant instance:

```bash
docker compose -f resources/home-assistant-test/docker-compose.yml up -d
```

3. Open `http://127.0.0.1:8123`, add or reconfigure the `Hoymiles Cloud`
   integration, and if needed apply the same `Authentication profile` and
   `App version override (advanced)` that worked in the script.

4. Inspect logs when troubleshooting:

```bash
docker logs homeassistant-hoymiles-test --since 10m
```

Relevant loggers:

- `custom_components.hoymiles_cloud.config_flow`
- `custom_components.hoymiles_cloud.hoymiles_api`
