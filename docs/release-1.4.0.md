# 1.4.0 — control reliability and cloud telemetry

This stable release includes the functionality tested in 1.4.0rc6. Fast cloud
power updates remain experimental, opt-in and disabled by default.

## Changes since 1.3.1

- Keep cached battery/relay controls during transient read failures and pending
  jobs; serialize settings reads. Explicit permission denial still revokes access,
  and writes require fresh confirmation. Includes the proposal from PR #75 (#74).
- Retry transient login connection, timeout and non-JSON failures instead of
  requesting unchanged credentials. Adapted from PR #81; actual credential
  rejection still triggers reauthentication.
- Resolve parent devices within the owning account on modern Home Assistant (#79).
- Add optional burst power updates (#69) and explicitly addressed microinverter
  module power, voltage and current. Recover totals only from complete port data.
- Prefer explicit import/export energy counters (#80) and withhold contradictory
  placeholder grid readings rather than inventing measurements (#77/#78).
- Strengthen diagnostic redaction and avoid raw authentication exception details.
- Address the [HACS review](https://github.com/hacs/default/pull/10673): remove
  `aiohttp` from manifest requirements because Home Assistant supplies it. This
  correction was already in RC4–RC6 and is now included in a stable release.

## Upgrade and known limitations

Install 1.4.0 through HACS and restart Home Assistant. Until HACS default-store
acceptance, keep using the custom repository. Existing entity IDs are preserved.
Corrected grid-counter sources can cause a one-time total-increasing statistics
jump. History is not rewritten: compare the Energy-dashboard transition and repair
statistics if needed. Rollback to 1.3.1 restores old behavior, not historical data.

Missing vendor grid measurements and ambiguous legacy PV-channel mapping remain
open (#56/#77/#78). Battery-only telemetry (#32), installation-specific control
reports (#63/#76), and wider HMS lifecycle behavior still need matching hardware
validation. The #80 fix has synthetic coverage but no reporter hardware confirmation.
HMS users report power cadence improving after firmware updates; voltage/current
can remain slow and module chart results are cached for 240 seconds. No universal
hardware compatibility or resolution of these open reports is claimed.

## Validation

220 HA-free unit tests and Home Assistant 2026.9.2 synthetic lifecycle checks with
15 stations, fast polling off/on. HACS and Hassfest must pass on the release commit.
User feedback supports improved control availability and the device-link fix.
No new live-device writes or outage tests were performed for this promotion.
The optional Claude review bot has failed technically and is not a completed review.
