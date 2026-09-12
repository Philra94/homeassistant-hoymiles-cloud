# 1.3.1rc1 — release candidate for 1.3.1

This is a prerelease, based on v1.3.0, intended for installation testing before a
stable 1.3.1 release. It retains the existing battery power sign convention and
entity identifiers.

## Changes

- Integrate Claude's PV discovery fix from `79dd4fe` (PR #67). A single
  microinverter's declared `rule.port` can seed missing PV channels for the
  existing module-data fallback. Multi-device mappings are not guessed.
- Integrate Claude's charger capability work from `cbf1628`, then replace its
  legacy wattage fallback with signed burst telemetry. A numeric `pile_power`
  value alone no longer establishes that a charger exists or is consuming power.
- Obtain a signed stream URL through `get_sd_uri`, poll the observed EU burst
  endpoint without account headers/cookies, and renew an expired URL once.
  Publish charger `es.sp` only from valid recent telemetry, preserving real zero
  and marking failed/missing data unavailable.
- Retain v1.3.0's async battery write/status/readback flow and harden it further:
  denied reads and unsupported modes block commands; unreadable readback cannot
  claim a successful application or trigger a duplicate fallback write.
- Run Argon2 password hashing off the event loop.
- Isolate station refresh failures, bound request concurrency, and cache slower
  inventory and control reads. Successful control changes invalidate the cache.
- Discover optional entities after initial setup and remove discovery listeners
  when unloading.
- Stop deriving grid connection from the mere presence of a telemetry dictionary.
  Without an explicit supported signal the state is unknown.
- Move persistent drafts to per-entry storage, copying only that account's
  stations from the legacy file without deleting it.
- Add same-account reauthentication and additional diagnostics redaction.

## Upgrade and rollback

Extract `custom_components/hoymiles_cloud` from the candidate archive into your
Home Assistant configuration's `custom_components` directory and restart.
Existing entities keep their unique IDs. The charger sensor may change from a
misleading number to unavailable when the account cannot supply live data.
Automations should handle unavailable states.

To roll back, restore v1.3.0's integration directory and restart. Legacy storage
is retained, but edits made in the new per-entry draft store are not copied back
into the old shared store. Use your configuration backup when preserving those
edits matters.

## Validation scope

The standalone regression suite and an optional script against real Home
Assistant validate local behavior with fake cloud responses. Exact results are
recorded in the GitHub prerelease description after final checks. The public
portal and issue #64 establish the observed endpoint shape; no authenticated
hardware write or numerical comparison against the user's station was performed.

Before promoting to stable, test a real station with a connected and disconnected
EV charger, a battery mode/settings write and readback, token expiry, and an HA
restart with multiple configured accounts.

## Known limits

- Burst URL validation currently accepts the observed `eurt.hoymiles.com` host.
  Other regions require verified endpoint evidence.
- Live polling follows the configured integration interval (60 seconds by
  default); this does not promise the portal's ten-second refresh cadence.
- Aggregate PV/grid/battery/load sensors keep their established source and sign
  conventions. Compact burst fields are not substituted wholesale because their
  meanings, especially load accounting, differ between payload families.
- Temperature, AI mode 9 controls, complete alarm coverage, cloud history backfill,
  and multi-microinverter port mappings remain outside this candidate.
- This candidate does not claim Home Assistant Quality Scale certification or
  comprehensive hardware compatibility.

Related: [#39](https://github.com/Philra94/homeassistant-hoymiles-cloud/issues/39),
[#56](https://github.com/Philra94/homeassistant-hoymiles-cloud/issues/56),
[#59](https://github.com/Philra94/homeassistant-hoymiles-cloud/issues/59),
[#64](https://github.com/Philra94/homeassistant-hoymiles-cloud/issues/64),
[#67](https://github.com/Philra94/homeassistant-hoymiles-cloud/pull/67).
