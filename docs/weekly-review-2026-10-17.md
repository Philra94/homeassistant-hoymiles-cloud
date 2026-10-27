# Weekly review — 2026-10-17

Reviewed 13 open issues and 4 open PRs, new issue comments, PR conversations and
checks, current releases and items closed since 2026-10-10. No newly closed items
were returned. GitHub Discussions remain disabled.

- PR #81: reviewed its patch and two tests. Adapted into #73 rather than merging
  the stable-version bump or declaring stable 1.3.2. Extended coverage to JSON
  decode failure, privacy, success after failure, mixed profiles, real rejection
  and HA coordinator recovery. Contributor proposal is credited in RC6 notes.
- #74: reporter confirms 15 hours of control stability with RC5. Keep open pending
  broader confirmation; this is meaningful positive evidence, not proof for all
  battery models.
- #79: deprecated device-parent warning confirmed fixed under HA 2026.9.4 and
  2026.10.0, RC4/RC5. New HMS port-update slowdown also occurs after rollback and
  reportedly in the official app. Backend change is a hypothesis, not established
  cause. Need simultaneous station/inverter stream timing on matching hardware.
- #80: no reporter confirmation yet for RC5's grid-counter correction.
- #77/#78/#56: retain RC5 explicit device-port samples and totals; missing vendor
  grid measurements and legacy station channel mapping remain unresolved.
- #63/#76: installation reproduction still missing; do not close as covered by #74.
- #32: battery-only matching live telemetry unavailable; do not infer power from energy.
- #69: fast polling implemented in the RC, real HMS lifecycle evidence incomplete.
- #44/#66: naming/temperature feature work deferred; no new validated data source.
- #64: previous charger-state confirmation retained, no new report.
- PR #67/#75: changes already incorporated; no duplicate merge. No new reviews.

Public feedback: the Home Assistant community thread has a new October 12 question
about automating charging schedules, not a reproducible regression. Older comments
cover account compatibility, unnecessary battery entities, HYS write failures,
battery flow direction and concerns about read/write frequency. Existing guarded
controls, schedule services and readback verification cover parts of these topics;
no untested cross-model compatibility is claimed. No public replies were posted.
Source: https://community.home-assistant.io/t/integration-hoymiles-cloud-control-hyt-inverters-and-battery-systems/880739

Validation: 220 unit tests and HA 2026.9.2 synthetic 15-station lifecycle off/on.
No live hardware outage test. Remain prerelease due to unresolved reports and
hardware-validation gaps. Review-bot execution failures are not successful reviews.
