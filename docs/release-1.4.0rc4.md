# 1.4.0rc4 — Home Assistant device-link compatibility

Addresses #79: before adding entities on modern Home Assistant, resolve each
parent station within its config entry and pass via_device_id instead of the
deprecated via_device identifier. Create the parent first so discovery and platform
setup order do not affect the link. Identical identifiers in different accounts
resolve to different parent devices. Self-parent references are omitted.

Older Home Assistant versions without the new registry helper retain the legacy
field. Existing device identifiers and entity IDs are unchanged. This continues
the 1.4.0 RC line and includes RC2 privacy and RC3 control-cache/readback fixes.
Previous release tags and artifacts are unchanged.

Validation: 180 standalone tests pass, including account scoping, self-reference
and legacy compatibility. Home Assistant 2026.9.2 lifecycle validation with 15
synthetic stations exercises real registry creation for two accounts. No live
credentials or device commands were used. Legacy compatibility is unit-tested,
not validated on a full 2023.10 runtime.

#77/#78 report zero indicator values with multiple stations. The inspected API
path sends an explicit station ID for each request and returns its payload without
replacing measurements. This is insufficient to reproduce or solve the report;
no multi-station telemetry fix is claimed. Read-only cloud polling does not itself
issue battery write commands (#74's new question). Explicit user actions remain
the write path. #63/#76 and real HMS validation for #69 remain outstanding.

Install with HACS beta versions enabled and restart Home Assistant. Fast polling
remains off by default. To roll back, reinstall RC3 and restart; the old device-link
warning may return. Stable remains 1.3.1 pending resolution and validation of the
remaining reports.

Reference: https://developers.home-assistant.io/blog/2026/08/24/device-registry-follow-up-changes/
