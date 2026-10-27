# 1.4.0rc3 — preserve controls after settings timeouts

This bugfix candidate continues the existing 1.4.0 RC line and includes RC2's
privacy corrections. It does not add new features or promote the release to stable.

Based on PR #75 for issue #74, a failed optional settings read preserves the
previous battery/relay cache rather than blanking controls until the next static
refresh. A fresh empty or permission-denied result still replaces the cache.
Refresh cadence remains unchanged; cached readings can remain stale during outages.
API errors returned as explicit unreadable settings still clear controls.

The adaptation additionally requires a fresh battery-settings read after applying
a schedule draft. Cached readable settings cannot count as fresh readback or cause
the draft to be replaced. Existing API write verification remains in place.
Optional-endpoint logs record exception type, avoiding blank timeout messages
without including exception representations that could carry credentials.

177 standalone tests pass. The expanded Home Assistant lifecycle regression checks
cached controls after a timeout, explicit permission denial, and preservation of
a schedule draft when post-write refresh times out. All transport is synthetic;
no real device write or live credential was used.

#63 may overlap with the refresh problem but its reopened report lacks sufficient
version/trace evidence to claim a complete fix. #76's daily reload symptom remains
unclassified. Real HMS and multi-inverter burst validation for #69 is still missing.
The candidate remains experimental and the review PR remains draft.

Enable beta versions in HACS, install v1.4.0rc3 and restart Home Assistant. Fast
polling stays off by default. To roll back, reinstall RC2 and restart; this restores
the previous timeout behavior. Existing entity IDs and schedule storage are unchanged.
