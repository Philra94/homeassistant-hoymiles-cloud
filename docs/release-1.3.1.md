# 1.3.1 — Stable telemetry and reliability fixes

Promotes **1.3.1rc3** to stable. Integration code is identical to RC3 except for
the manifest version; this release does not include the experimental 1.4.0 burst
PV feature. RC tags remain unchanged.

## Changes since 1.3.0

- Correct EV charger power using authenticated burst `es.sp` telemetry instead
  of the legacy field that can mirror PV production. Disconnected/unverified
  streams are unavailable; a connected, valid zero remains zero.
- Discover missing PV channels from the declared port count on single
  microinverters, filling them through the existing module-data fallback.
- Serialize battery writes, require readable settings and readback verification,
  and retain schedule drafts if verification fails.
- Isolate station failures, bound requests, cache slower settings, and discover
  optional entities when data appears after initial setup.
- Keep schedule drafts per account, support same-account reauthentication, move
  Argon2 hashing off the event loop, and strengthen diagnostics redaction.

## Validation

- 135 standalone regression tests pass.
- Home Assistant 2026.9.2 lifecycle smoke passes with 15 simulated stations.
- RC2 hardware reports confirm charger readings in disconnected, idle and
  charging states (#64), and PV channels on HMS-800-2WB/HMS-1600-4WB (#39).
- RC3's connected-stream guard is covered by regression tests; a read-only live
  probe returned connected hybrid telemetry with a 10-second server delay.

These results are not comprehensive hardware certification. Real-device testing
of the added disconnection guard, battery write/readback, extended token expiry
and multiple-account restarts remains limited. No new hardware test is claimed
by changing the release status to stable.

## Known limitations

- #71 (15-system installer setup) and #72 (missing PV2 on another model) remain
  open and lack an exact tested candidate version/complete diagnostic evidence.
  The simulated 15-station check does not establish a fix for installer accounts.
- #69's dedicated fast PV polling is not included. The configured integration
  interval and established station PV source remain in use.
- Multi-microinverter station-channel mapping, consumer-specific burst endpoints
  and non-EU stream hosts remain outside this release's validated scope.

## Upgrade and rollback

Update to v1.3.1 through HACS (beta versions are not required), then restart Home
Assistant. For manual installation, extract the archive's
`custom_components/hoymiles_cloud` folder into the HA configuration directory.
Existing entity IDs and battery power sign conventions are unchanged.

Keep a configuration backup. To roll back, restore v1.3.0's integration files and
restart. New per-account schedule-draft edits are not copied back into legacy
shared storage; restore the backup if those edits need to be preserved.
