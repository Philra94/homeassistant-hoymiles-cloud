# 1.4.1rc1 — report unconfirmed battery changes

Related to #63, including the November 2 report on 1.4.0 / HA 2026.10.4.

- A failed battery-mode API call now raises a Home Assistant action error instead
  of only logging and returning normally. Automations can detect the failure.
- Missing requested fields in battery readback no longer count as confirmation.
  This inconclusive result does not trigger another write through the fallback
  transport. Permission checks and successful-write refresh behavior remain.

Reproduced the silent action-success path with a synthetic failed API write in
Home Assistant. The regression fails before the selector fix. Added coverage for
incomplete readback, no duplicate fallback write, and complete readback success.
Validation: 221 HA-free tests; HA 2026.9.2 lifecycle with 15 synthetic stations,
fast polling off/on. No live battery writes performed.

This fixes misleading success reporting, not the unverified underlying device
failure in #63. Device model/firmware, exact control and sanitized error details
are still needed to diagnose that installation. Other known 1.4.0 limitations
remain. Stable is unchanged; this candidate is not ready for stable promotion.

Enable prereleases in HACS, select 1.4.1rc1 and restart HA. On an unconfirmed
change, check the current mode in the vendor app before retrying. Rollback:
reinstall 1.4.0 and restart; the misleading success behavior may return.
