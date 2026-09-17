# 1.3.1rc3 — connected-stream validation

RC3 includes RC2 and stops publishing cached charger power when the burst
response does not explicitly report `con:1`. Disconnected or unverified streams
are unavailable; a connected stream reporting zero still publishes 0 W.
No entity identifiers or battery control behavior change.

## Validation

- 135 standalone regression tests pass.
- Home Assistant 2026.9.2 lifecycle smoke passes with 15 simulated stations,
  including late discovery, station failure, reauthentication and unload.
- A bounded read-only probe with the patched API client returned connected hybrid
  telemetry with a 10-second server delay. No device command was issued.
- RC2's original hardware validation is now complete for the reported charger:
  issue #64 confirms disconnected, connected-idle and charging comparisons.
  Issue #39 confirms PV channels on HMS-800-2WB and HMS-1600-4WB.

## Triage and stable promotion

Issue #72 does not identify an exact installed version. The reported top-level
`pv2:0` cannot gate RC2/RC3's fallback: it uses the separate PV indicator feed and
single-microinverter `rule.port`. A regression test covers this distinction.
Hardware diagnostics from the exact candidate are still needed to determine why
that HMS-1000-2WB installation has no second channel. No fix for #72 is claimed.

Issue #71 likewise lacks an exact version and traceback. The 15-station smoke
passes, but simulated transport cannot establish installer-account permissions,
latency, or response shapes. No fix for #71 is claimed.

Keep this release a prerelease until these reports are classified and the
remaining hardware write/readback, long-running authentication and multi-account
restart validation is recorded. The connection guard is covered by deterministic
tests but has not been exercised through a real device disconnect in HA.

## Installation and scope

Enable beta versions in HACS and select v1.3.1rc3, then restart Home Assistant.
Alternatively extract the attached archive into the HA configuration directory.
Preserve a configuration backup. The rollback/storage notes from RC1 still apply.
RC1 and RC2 are unchanged. Stable remains v1.3.0 until promotion is justified.

Fast PV polling (#69), consumer-specific endpoints and multi-device PV channel
mapping are not included. They belong to the separate 1.4.0 candidate.
