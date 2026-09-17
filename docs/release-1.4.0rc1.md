# 1.4.0rc1 — opt-in fast cloud power updates

This experimental prerelease implements the native burst polling requested in
#69, separately from the 1.3.1 maintenance candidate. It includes RC3's charger
connection guard. Neither release line is promoted to stable by this release.

## Enable and test

Enable beta versions in HACS, select v1.4.0rc1 and restart Home Assistant. In the
integration's options, enable **Enable fast cloud power updates (experimental)**.
It is disabled by default. The normal update interval still governs all other
cloud readings. Burst cadence follows the device/server delay; two-second updates
are not promised for every device or account.

- Station PV Power and hybrid EV Charger Power use the independent fast loop.
- Single-inverter PV channel power keeps its existing entity IDs.
- Each microinverter with a known serial gains AC Power. Multi-inverter stations
  gain explicitly addressed per-inverter PV port power sensors.
- Disconnected/stale samples are unavailable; genuine connected zero remains zero.
- Station and inverter errors back off independently. Ordinary PV data can take
  over on transport failure, with automatic recovery to burst. Explicit offline
  streams do not resurrect cached slow power.
- Energy counters, grid/load/battery semantics and device controls are unchanged.

Disabling the option stops burst polling and returns existing sensors to their
ordinary sources. Burst-only entities then become unavailable. Back up before
installing; restore RC3 and restart to roll back. RC2/RC3 tags remain unchanged.

## Evidence and limits

See [protocol and validation notes](https://github.com/Philra94/homeassistant-hoymiles-cloud/blob/v1.4.0rc1/docs/hoymiles-burst-api.md)
for pinned comparisons with ioBroker, the MS-A2 MQTT client and Homebridge.

170 standalone regression tests pass. Home Assistant 2026.9.2 lifecycle tests with 15
simulated stations covers option-off/on behavior, routing, scheduling, competing
slow updates, failures and unload, plus options and isolated two-account storage reloads. A bounded read-only real hybrid probe returned
three connected samples at a 10-second cadence with advancing timestamps and
usable PV power through the new poller. No device command was sent.

HMS `power`/`mis` mapping is source-validated and tested with synthetic payloads;
real HMS and multi-inverter comparisons remain outstanding. The configured live
account did not supply a microinverter scope. EU installer/web endpoints only;
consumer-specific MS-A2 endpoints and additional regions remain unsupported here.
Missing voltage/current/temperature fields are not invented or made faster.

Issue #69 remains open pending hardware testing. The separate #71/#72 triage and
1.3.1 stable-promotion gates also remain documented in the RC3 release notes.
