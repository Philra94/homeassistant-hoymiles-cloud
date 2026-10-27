# 1.4.0rc6 — retry transient login failures

Adapted the network-failure classification proposed in PR #81 into the existing
1.4 RC line. DNS/connect errors, timeouts and non-JSON login responses no longer
become invalid-credential verdicts. Home Assistant can retry setup or coordinator
updates instead of asking users to re-enter unchanged credentials.

If one login profile rejects the request while another is unreachable, the result
is inconclusive and retried. A successful profile still wins. Real server-side
credential rejections still follow the existing authentication flow. Transport
exception details are omitted from authentication messages and logs to avoid
exposing request URLs or private values. No battery-write behavior changes.

Validation: 220 HA-free tests pass. Home Assistant 2026.9.2 lifecycle checks with
15 synthetic stations pass with fast polling off/on, including a temporary auth
connection failure, no reauth prompt and successful subsequent refresh. No live
credentials or device writes were used for this release's tests. This is not a
claim of router-outage validation on every supported installation.

Feedback: #74 reports 15 hours without control dropouts on RC5; #79 confirms the
via_device warning is gone through HA 2026.10 and RC5. The same report describes
slower HMS per-port updates, including after rollback and in S-Miles. That remains
unresolved; no unverified fast-polling fix is claimed. Missing cloud grid data,
legacy multi-device channel mapping, #32 and #63/#76 reproduction, and broader
real HMS lifecycle validation remain open. Stable remains v1.3.1.

RC5 grid counter selection and device-addressed module sensors are included.
The RC5 note about possible one-time Energy-dashboard statistics changes when
upgrading from older versions still applies; history is not rewritten.

Install v1.4.0rc6 with HACS prereleases enabled and restart Home Assistant.
Rollback: reinstall RC5 and restart; unnecessary reauth after a network outage
may recur. Published RC5 artifacts and tags are unchanged.
