# 1.4.0rc2 — diagnostic privacy fixes

This candidate retains the experimental fast polling from RC1 and incorporates
stable 1.3.1. It remains a prerelease; published RC1 artifacts are unchanged.

- Redact additional cloud access-key, token, cookie, account-contact and creator
  fields from diagnostics, including nested and mixed-case fields.
- Redact private local hostnames and configuration paths in diagnostic strings.
- Remove debug output containing token prefixes and complete cloud payloads.
- Remove tracked Finder metadata and ignore local configuration files.
- Resolve the merge conflict with stable 1.3.1 and correct the README release status.

Validation: 173 standalone tests pass. The Home Assistant 2026.9.2 lifecycle
smoke passes with 15 simulated stations and fast polling enabled. No live cloud
credentials or real device commands were used for this review.

The fixes reduce known disclosure paths; they are not a guarantee that arbitrary
vendor text contains no private data. Inspect and redact diagnostics before sharing.
Previously shared exports are not repaired retroactively. If they contain a real
access key or token, remove the public exposure and revoke or rotate it as applicable.

Installer setup (#71) and missing PV2 (#72) have since been reported fixed after
updating. Fast polling (#69) still requires real HMS and multi-inverter validation.
No new temperature, naming, battery-power or channel-mapping feature is claimed.

Install through HACS with beta versions enabled and restart Home Assistant.
Fast polling stays off by default. Disable it in options to return to normal
polling, or reinstall stable 1.3.1 and restart to roll back integration code.
Existing entity IDs and battery control behavior are unchanged.
