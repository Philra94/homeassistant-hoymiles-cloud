# Weekly review — 2026-11-07

Reviewed 13 open issues and two open PRs, changes since October 31, release/main
checks, HACS submission and public integration-specific feedback.

New evidence: https://github.com/Philra94/homeassistant-hoymiles-cloud/issues/63#issuecomment-6584308055
The November 2 reporter uses 1.4.0 with HA 2026.10.4 and reports apparently
successful settings changes without effect. Model, firmware, exact control and
sanitized error details are absent. No hardware-specific cause can be claimed.

Reproduced a concrete related defect: battery-mode Select returned normally after
API False. Synthetic HA regression fails before the fix and passes after it.
Also fixed incomplete readback accepting missing requested fields as confirmation;
inconclusive readback does not retry the write on the fallback transport.
See release-1.4.1rc1.md. 221 HA-free tests pass; HA 2026.9.2 15-station lifecycle
passes with fast polling off/on. No live device writes or hardware validation.

All other issue activity is unchanged. #74/#79 positive evidence retained; #80
still needs hardware confirmation. #56/#77/#78 cloud grid and channel mapping,
#32 battery-only telemetry, #76 installation reproduction and #69 wider HMS
validation remain open. #44/#66 features deferred; #64 no new feedback.
PRs #67/#81 already incorporated/adapted, no duplicate merge warranted. No new
closed or merged items returned. Main Validate passed on the 1.4.0 commit.

HACS https://github.com/hacs/default/pull/10673 remains open/ready, unchanged
since October 27; aiohttp removal is in stable 1.4.0. Discussions are disabled.
Public search found no new actionable integration-specific feedback; latest visible
community-thread post remains October 12:
https://community.home-assistant.io/t/integration-hoymiles-cloud-control-hyt-inverters-and-battery-systems/880739

Publish the narrow fixes only as 1.4.1rc1. Stable 1.4.0 remains unchanged; no claim
that #63's underlying hardware failure is solved. No issue comments sent.
