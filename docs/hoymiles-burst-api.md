# Burst power implementation and validation

## Source comparison (2026-09-17)

The implementation is original Python code. These independent clients were
inspected to cross-check protocol behavior, not treated as a universal contract:

- [ioBroker.hoymiles, e39c7e8](https://github.com/Eistee82/ioBroker.hoymiles/tree/e39c7e8323d319ede2c04395164a8938dac6af51):
  `src/lib/cloudConnection.ts` defines station `power` and inverter `mis` schemas;
  `burstPoller.ts` requests `m:3, mis:[serials], t:1` and `m:0,t:1`, follows `dly`,
  marks `con != 1` stale, and prevents slow polling from overwriting fast power.
  Its executable HTTP call includes the raw account token despite a misleading
  nearby comment about URL-only authentication. The Python implementation keeps
  RC2's independently validated raw Authorization header and isolated cookies.
- [hoymiles-ms-a2-to-mqtt, 5ba55af](https://github.com/krikk/hoymiles-ms-a2-to-mqtt/tree/5ba55af91ddf86e1baaeb6623a50588b1c468702):
  independently uses raw Authorization on the burst URL, but obtains it from
  `/pvmc/api/0/station/get_sd_uri_c` and requests `m:0,sid:...`. That consumer
  profile is distinct and is not silently substituted into our installer/web
  path. Its special treatment of `dly:10000` is not adopted: our live hybrid
  samples demonstrate that 10000 can be a valid connected cadence.
- [homebridge-hoymiles, f32bc9b](https://github.com/rafalr100/homebridge-hoymiles/tree/f32bc9b773c977840292a231d2b3575b595bd891):
  uses `count_station_real_data` for its power metrics rather than this burst
  loop. It does not independently validate HMS burst fields. Its different power
  conventions reinforce the decision not to replace battery/grid/load sources.

## Request and interpretation

1. Authenticated `POST /pvm/api/0/station/get_sd_uri`, body `{"sid": <id>}`.
2. Validate HTTPS, exact EU host, port and path before sending credentials.
3. POST the returned URL with raw `Authorization`, no cookies or redirects.
   Station request: `{"m":0,"t":1,"reflux":0}`.
   Inverter request: `{"m":3,"t":1,"mis":[<known serials>]}`.
4. Refresh signed URLs after four minutes or once after a failure. Expired
   account tokens refresh under a lock shared by API requests. HTTP 401 also
   expires the account token before retry. Persistent authentication failure
   stops burst polling and asks HA to reauthenticate.

| Response | Values exposed |
| --- | --- |
| Hybrid `es` | `pp` → station PV Power; `sp` → charger only with `icon.pile` |
| HMS `power` | `pv` → station PV Power |
| Inverter `mis[]` | `sn` routes `pac` → AC Power and `pN` → declared port N |

`power.sp` is not interpreted as charger power. Missing, negative, nonfinite or
boolean power fields are not coerced to zero. Unknown serials/ports never borrow
another inverter's value. A single microinverter can reuse the proven station
channel/port mapping. Multiple microinverters use serial-specific entities.
The single-inverter string-power total is summed only when every declared port
has a valid sample. Only `rule.port` establishes the number of ports; model names are not guessed.

## Scheduling and freshness

The opt-in poller has independent cancellable station/inverter loops and a two-request limit
per account. Station and inverter scopes have separate due times, failure counts
and exponential backoff (10 to 300 seconds). Inverter failures do not delay the
station's next due time. The effective cadence includes request duration and
contention. Server `dly` is honored, with a 1.5-second minimum and a 10-second
fallback for invalid delays; longer valid delays are not clamped down.

All power samples require `con:1`. Receipt time is monotonic. A sample expires
after max(30 seconds, three server intervals), including when its vendor timestamp
stops advancing. If the station supplies an IANA timezone, vendor timestamps are
also checked against wall time, allowing up to 30 seconds of future skew. No HA
host timezone is assumed. A separate expiry task publishes unavailable state even
while a network request is still pending.

Fast callbacks notify coordinator listeners without resetting the slow refresh
timer. At the end of a slow refresh, the latest burst snapshot is attached, so
an in-flight slow request cannot overwrite it. Raw slow measurements are retained
separately for fallback. Explicit offline/stale stream verdicts suppress cached
slow power. Transport errors allow ordinary PV fallback where available; charger
and new inverter sensors have no fabricated fallback. Tasks stop on unload and HA
shutdown; authentication failures request one reauth per poller.

## Validation and remaining hardware checks

Deterministic tests cover both formats, request bodies, zero/missing values,
serial routing, cadence, proactive URL renewal, token refresh, stale timestamps,
disconnect/recovery, scope-specific backoff, expiry and cancellation. The HA
2026.9.2 smoke exercises 15 stations with the option off and on, sensor values,
late discovery, a slow request racing a newer burst, unchanged slow scheduling,
disconnect/recovery, authentication failure and unload. Options defaults and
changes, multi-inverter entities, and two-account storage isolation across reloads
are also exercised. All 172 standalone tests pass.

Three read-only samples on the configured real hybrid account returned `es`,
`con:1`, `dly:10000`, advancing vendor timestamps and usable PV values through the
new poller/selector. No commands or configuration changes were sent. The account
had no microinverter scope to validate; no real HMS result is claimed.

Before stable 1.4.0: compare HMS station/AC/per-port power with the app in daylight,
verify overnight disconnect and morning recovery, run through actual token/URL
expiry and HA restart, and compare multiple real inverters. Consumer-profile and
non-EU endpoint support remains separate work. Keep issue #69 open until these
hardware results are recorded.
