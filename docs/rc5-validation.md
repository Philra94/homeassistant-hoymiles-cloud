# RC5: settings reads and empty indicator templates

## Findings and fixes

- #74: transport errors caught inside the API became unreadable settings dictionaries,
  replacing previously readable cached values. Known transient failures and pending
  jobs now raise a distinct read error that the optional coordinator read treats as
  unavailable for this poll. Explicit permission denials still clear permissions.
- Simultaneous battery/relay reads produced failures in the read-only account probe;
  serial reads recovered after a pause. Serialize reads for each station through job
  completion and give coordinator reads separate deadlines. This avoids overlapping
  reads within this integration, but cannot prevent jobs from other clients.
- #77/#78: two official demo stations returned zero PV total, placeholder PV channels,
  and an all-zero grid template while station production was positive. Both contain
  multiple microinverters. Other stations in the same account had valid indicators;
  account station count alone does not explain this symptom.
- The module chart endpoint supplies usable DC power. Sum only a complete set of
  explicitly addressed ports; keep caches separate by station, device, and port.
  Do not invent a mapping to station channel numbers or substitute AC production.
- Withhold the contradictory empty indicator template for generating micro-only
  stations. Preserve genuine zero readings in other cases. Accept grid_f for frequency.

## Validation

- HA-free unit suite and Python compilation pass, including transient read errors,
  permissions, serialization, complete/partial module totals, and genuine zero cases.
- Read-only live test after changes: three consecutive battery/relay pairs readable.
- Two demo stations: totals recovered from 4 devices / 7 ports and 4 devices / 16 ports;
  complete module fetches took approximately 1.0 and 1.4 seconds, within the five-second
  fallback budget. The observed grid templates were withheld.
- No device writes were executed. Only synthetic fixtures are committed.
- No full Home Assistant UI validation was performed for this change. Cloud grid
  measurements and station-level multi-device PV channel mapping remain unresolved;
  these changes do not establish that all user variants of #77/#78 are fixed.

## Device-addressed module sensors

Subsequent read-only investigation found a complete, unique device/port layout
for both affected demo stations (7 and 16 modules). No field identifies the legacy
station-wide PV channel number. Individual module charts provide DC measurements;
the official frontend's separate microinverter voltage/frequency charts returned
no series for the tested current and previous days. No replacement grid readings
are claimed.

The coordinator now retains its already device-addressed chart samples for sensor
use. Multi-inverter DC voltage/current/power entities use inverter serial and port,
including with fast polling disabled. Existing burst power entity IDs are reused.
Burst offline/stale verdicts still suppress chart power; AC power is never replaced
with DC module power. Only missing/placeholder station PV totals use aggregation.

Validation: 204 HA-free tests pass. The Home Assistant 2026.9.2 lifecycle smoke was
extended with multi-inverter module telemetry and run with fast polling off and on.
It checks device-specific voltage/current, power source precedence, absent samples,
offline suppression, discovery, authentication handling and unload. These are
synthetic HA checks, not installation testing on the affected users' systems.
