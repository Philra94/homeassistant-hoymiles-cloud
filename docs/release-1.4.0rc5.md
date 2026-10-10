# 1.4.0rc5 — control availability and device-addressed telemetry

- Fix #74's remaining internal-timeout path: transient settings read failures and
  pending jobs retain cached controls. Serialize battery/relay reads by station;
  explicit permission denial still revokes controls. Write confirmation still
  requires fresh readback and never treats a cached value as verification.
- Recover missing multi-microinverter PV totals from complete device/port module
  measurements. Expose device-addressed DC power, voltage and current with fast
  polling off or on, preserving existing burst power entity IDs (#56, #77, #78).
- Withhold the observed contradictory empty grid template rather than publishing
  false zero measurements. Accept grid_f as the grid-frequency field.
- Fix #80: use explicit grid_in_eq/grid_out_eq counters for daily, monthly, yearly
  and lifetime grid energy. Legacy-only replies retain meter_b/mb sources. Zero
  is valid; missing or invalid fields in an explicit grid family stay unknown
  instead of borrowing a different meter's counter. Units remain Wh.

The grid counter correction changes the source behind existing energy entity IDs.
Previously recorded statistics are not rewritten. A source change can cause a
one-time jump in total_increasing statistics; users of the Energy dashboard should
compare the transition and repair affected statistics if necessary. No automatic
history deletion or offset is applied.

Validation: 213 HA-free tests; Home Assistant 2026.9.2 synthetic lifecycle with 15
stations, fast polling off/on, and all eight grid-energy sensor mappings. Prior
read-only account/demo probes validated serialized settings reads and complete PV
module totals. #80 is reproduced with synthetic unequal counter families, not
validated on the reporter's physical HIT installation.

Known limitations: missing vendor grid measurements are not reconstructed; old
station-wide PV channel numbers cannot be mapped to device ports. #63/#76 need
user-installation reproduction, #32 needs battery-only live telemetry, and #69
still needs real HMS lifecycle testing. The automated Claude reviewer fails
technically and has not provided a substantive review. Do not treat this RC as a
stable-release approval.

Enable prereleases in HACS, select v1.4.0rc5 and restart Home Assistant. Fast polling
remains off by default. Rollback: reinstall RC4 and restart; new module entities
may become unavailable and the old grid counter selection returns. Historical
statistics are not restored by rollback. Stable remains v1.3.1.
