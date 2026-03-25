# Hoymiles Cloud Integration for Home Assistant

This custom integration for Home Assistant allows you to monitor and control your Hoymiles solar inverter system through the Hoymiles Cloud API.

## Features

- **Data Monitoring:**
  - Solar PV power generation
  - Battery power (charge/discharge)
  - Battery state of charge
  - Grid power import/export
  - Load power consumption
  - Daily and total energy generation
  - Dynamic PV channel discovery based on the indicators returned by the account
  - Reported inverter count and battery settings access diagnostics
  
- **Control Functions:**
  - Set battery operation mode when the account exposes writable battery settings
  - Configure battery reserve state of charge for the modes returned by the account
  - Peak Shaving Mode specific settings (`max_soc`, `meter_power`) when supported
  - Advanced battery mode payload updates through Home Assistant services for Economy and Time of Use schedules

## Development Status

This integration focuses on safe production use:
- Read-only telemetry should still work even if the account cannot access battery settings
- Controls are only exposed when the Hoymiles account returns writable settings data
- Battery setting reads and writes now follow the observed async Hoymiles `read/write -> job id -> status poll` flow
- Station discovery supports accounts with more than one page of stations
- Authentication now preserves more specific Hoymiles failure reasons instead of flattening them into a generic login error

Not all available Hoymiles API fields are exposed as entities yet, but unsupported or permission-denied controls should now stay out of Home Assistant instead of showing misleading defaults.

## Installation

### HACS (Recommended)

1. Make sure you have [HACS](https://hacs.xyz/) installed
2. Go to HACS → Integrations → Plus Icon → "Add Custom Repository"
3. Enter the URL: `https://github.com/Philra94/homeassistant-hoymiles-cloud`
4. Select category: "Integration"
5. Click "Add"
6. Find and install "Hoymiles Cloud"
7. Restart Home Assistant

### Manual Installation

1. Download this repository
2. Copy the `custom_components/hoymiles_cloud` directory to your Home Assistant `custom_components` directory
3. Restart Home Assistant

## Configuration

1. Go to Home Assistant → Settings → Devices & Services → Add Integration
2. Search for "Hoymiles Cloud"
3. Enter your Hoymiles Cloud login credentials
4. Click "Submit"

The integration currently auto-tries multiple authentication strategies:
- browser-compatible v3 login
- an `S-Miles Installer` v3 retry with app-version metadata
- an `S-Miles Home` v3 retry with app-version metadata
- legacy v0 login fallback

If Hoymiles rejects an account with a more specific message, the config flow should now surface that reason instead of only showing a generic authentication failure.

## Usage

After configuration, the integration will create:

- A device for each Hoymiles station with sensors for power, energy, and battery levels
- Controls for battery mode and reserve capacity settings only when the account exposes writable battery settings

The integration creates PV input sensors from the indicator keys returned by the API. If a system has more than two PV inputs and Hoymiles exposes them in the indicators payload, matching Home Assistant sensors will be created automatically.

The sensors will update every minute by default, but this can be changed in the integration options.

### Advanced battery services

For structured battery settings that are awkward to model as individual entities, the integration also registers two services:

- `hoymiles_cloud.set_battery_mode`
- `hoymiles_cloud.set_battery_mode_settings`

`set_battery_mode_settings` accepts a raw settings dictionary and merges it into the live Hoymiles mode payload by default. This is the recommended path for advanced Economy (`mode: 2`) and Time of Use (`mode: 8`) schedule updates because the backend expects the full mode payload to be preserved.

## Notes

- The integration uses the modern Hoymiles v3 authentication flow with the observed browser-compatible hashing fallback.
- Some accounts appear to require a different Hoymiles client/account family. If Hoymiles responds with messages like `Can only login to the S-Miles Home.` or `Your app version is low. Please update to the latest version.`, the integration now exposes those outcomes more clearly in the config flow and logs while still keeping the user-facing setup flow simple.
- Some accounts expose live battery telemetry but deny access to battery settings. In that case the integration keeps the telemetry sensors and hides the unsupported controls.
- Economy and Time-of-Use schedules are exposed through services instead of many per-slot entities because Hoymiles expects structured payloads and full schedule arrays.
- API endpoints and payload structures are based on observed Hoymiles Cloud behavior and may still vary by region, account role, and hardware family.

## Contributing

Contributions are welcome! If you have recommendations, improvements, or additions to this repository, please feel free to:
- Open an issue with your suggestions
- Create a pull request with your changes
- Share your feedback on what could be improved

Please note that this code was developed with the assistance of AI, which may explain why some parts are not always the prettiest or most straightforward. Your help in improving and refining the codebase would be greatly appreciated.

## Troubleshooting

- Check Home Assistant logs for details about any errors
- Verify your Hoymiles Cloud credentials
- If setup fails, note the exact Hoymiles message shown in the logs or config flow. Messages about `S-Miles Home` or app version requirements usually indicate an account/client compatibility issue rather than a wrong password.
- The integration logs now include all attempted auth profiles and their returned status/message. Useful loggers are `custom_components.hoymiles_cloud.config_flow` and `custom_components.hoymiles_cloud.hoymiles_api`.
- If a browser login works but the integration still fails, the most helpful follow-up is a sanitized network trace of the v3 login flow: the full `/iam/pub/3/auth/pre-insp` response body, the `/iam/pub/3/auth/login` request body, and the relevant request headers with secrets masked.
- Ensure your Home Assistant instance has internet access to reach the Hoymiles Cloud API

### Auth test script

You can test live authentication outside Home Assistant without saving credentials in the repository:

```bash
python3 scripts/test_login_flow.py --username "you@example.com" --try-matrix
```

Target a single profile:

```bash
python3 scripts/test_login_flow.py --username "you@example.com" --auth-mode home_v3
```

Override the app version for installer/home testing:

```bash
python3 scripts/test_login_flow.py --username "you@example.com" --auth-mode installer_v3 --app-version 3.7.1
```

## Support

For bugs or feature requests, please [open an issue on GitHub](https://github.com/Philra94/homeassistant-hoymiles-cloud/issues).

## Disclaimer

This integration is not affiliated with, endorsed by, or connected to Hoymiles Power Electronics Inc. This is a third-party integration developed for personal use. 