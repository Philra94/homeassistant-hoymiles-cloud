# Weekly review — 2026-10-10

Reviewed all 13 open issues and 3 open PR conversations/reviews/checks. Since the
last interactive review (2026-10-07), #80 is the only newly reported problem; no
newly closed/merged issues or PRs were returned. Discussions are disabled.
Targeted public web searches found no new actionable report specifically about
this integration on the Home Assistant community. Search coverage is not proof
that no external feedback exists.

| Items | Outcome / next evidence needed |
| --- | --- |
| #80 | Reproduced wrong energy source; grid family preferred for all four periods and both directions. Synthetic tests plus actual HA sensor checks. Reporter-side confirmation outstanding. |
| #74, PR #75 | Existing RC5 retains internal transient failures and serializes reads; contributor's original None-cache fix is already incorporated. No duplicate merge. |
| #56, #77, #78 | RC5 adds complete module totals and explicit device/port sensors. Grid measurements absent from vendor responses and legacy station-channel mapping remain unresolved. |
| #79 | RC4 account-scoped parent linking retained; no new feedback. |
| #63, #76 | Unavailable controls/daily reload symptom still needs installation reproduction; do not claim all cases fixed by #74. |
| #69 | Fast polling remains opt-in RC functionality; real HMS lifecycle/overnight/token expiry evidence outstanding. |
| #32 | Battery-only power source not verified on matching hardware. |
| #44, #66 | Friendly naming and temperatures deferred; no new verified temperature source from prior demo chart probes. |
| #64 | Earlier reporter confirmed all three charger states; existing fix retained. |
| PR #67 | Single-device port-count discovery already incorporated; contributor confirmation present, no duplicate merge. |
| PR #73 | Existing RC branch updated with #80 regression fix and validation/release notes. |

Before this run's changes, HACS, Hassfest, unit tests and HA lifecycle checks on
PR #73 were green. Claude review failed technically with no posted review.
Current validation and publication results are reported with the release/PR.
No stable promotion: unresolved reports, missing hardware validation and no
successful substantive automated review. No live account data is in fixtures.

Sources: https://github.com/Philra94/homeassistant-hoymiles-cloud/issues/80 and
https://github.com/Philra94/homeassistant-hoymiles-cloud/pull/73; remaining issue/PR
numbers refer to the same repository.
