# 1.3.1rc2 — release candidate for 1.3.1

RC2 fixes the missing Authorization header that caused RC1 burst requests to
fail with HTTP 400 and prevented live charger telemetry from being obtained
(issue #64). It includes the other changes from [RC1](release-1.3.1rc1.md).

Burst requests now send the raw account token, with no Bearer prefix. The
destination is validated before authentication, cookies remain isolated, and
redirects remain disabled. Cached stream URLs also use a refreshed account
token when needed. Regression tests enforce this corrected request contract.
RC1's statement that burst requests need no account headers was incorrect.

## Validation

- 129 regression tests pass.
- Home Assistant 2026.9.2 lifecycle smoke passes with fake cloud transport.
- The patched API client independently fetched live hybrid data successfully
  using its real authenticated request path and isolated burst session.

A bounded read-only cloud test returned HTTP 400 without Authorization and four
HTTP 200 responses with it. Authorized hybrid responses reported `con:1` and a
10-second delay; timestamps advanced and power values changed. No Home Assistant
installation, configuration, device setting or battery control was changed.
Credentials, identifiers, signed URLs and raw responses are excluded.

This validates the cloud request contract, not charger behavior in every state
or end-to-end Home Assistant entity updates. Disconnected, idle and charging
comparisons remain required before promotion to stable.

## Known limits and installation

Dedicated fast polling requested in #69 is not included. Burst requests still
follow the configured integration interval, and station PV Power still uses the
ordinary telemetry endpoint. HMS per-inverter `mis` and station `power` payloads
need separate implementation and hardware validation. The observed hybrid
10-second cadence must not be advertised as universal 2-second updates.

Select `v1.3.1rc2` with beta versions enabled in HACS, or replace
`custom_components/hoymiles_cloud` using the attached archive, then restart
Home Assistant. Keep a configuration backup. Existing entity identifiers are
unchanged. RC1 remains immutable; rollback and draft-storage considerations in
its notes still apply. Latest stable remains v1.3.0.
