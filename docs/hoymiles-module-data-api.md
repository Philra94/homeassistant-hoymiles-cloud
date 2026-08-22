# Hoymiles Module (Per-Port PV) Data API

## Scope

Documents the endpoint backing the S-Miles Cloud web "O&M" per-port view and
its CSV export. This integration uses it as a fallback when the PV
indicators endpoint returns placeholder values for per-channel PV data.

Observed live on 2026-08-20 against `https://neapi.hoymiles.com` for a
single-microinverter station (Hoymiles HF-800-1WB, one PV string).

## Endpoint

```
POST /pvm-data/api/0/module/data/count_by_day
Authorization: Bearer <token>
Content-Type: application/json

{
  "sid": 15068730,
  "date": "2026-08-20",
  "mi_list": [{"id": 34762140, "port": 1}],
  "quota": ["MODULE_POWER", "MODULE_V", "MODULE_I"]
}
```

Response: `200`, `Content-Type: application/octet-stream` — protobuf
`LineChart` (wire format, no official schema). The S-Miles Home profile
variant `/pvmc/api/0/module_data/count_by_day_c` returned identical bytes in
testing; this integration uses the `pvm-data` path only.

## Protobuf schema (observed)

```protobuf
message LineSeries {
  string type = 1;                          // "MODULE_POWER" | "MODULE_V" | "MODULE_I"
  repeated float data = 2 [packed = true];  // float32 series for the day
  int32 did = 3;
  int32 port = 4;
}

message LineChart {
  repeated string x_axis = 1;      // "06:05", ... 5-minute slot labels
  repeated LineSeries series = 2;
  string type = 3;
}
```

The series fills from dawn to the current 5-minute slot; the last element of
each series is the freshest value the cloud has. Decoding is implemented in
`custom_components/hoymiles_cloud/chart_pb.py` (manual wire-format parsing,
no protobuf dependency).

## Freshness

The series simply **stops growing** once the inverter goes to sleep — it is not
padded with zeros. Taking the last element unconditionally would therefore
repeat the final daylight reading all night and feed phantom energy into any
Riemann sum built on the PV sensors.

`data.latest_module_values()` resolves the slot label belonging to the newest
sample against the current time and reports `0.0` for a sample older than
`MODULE_DATA_MAX_AGE_MINUTES` (15) — zero volts, amps and watts is what a
sleeping panel actually reports. A slot in the future (clock skew between Home
Assistant and the cloud) counts as current, and a response without a usable
`x_axis` keeps its raw sample so hardware variants that omit the labels still
work.

## Polling cost

The cloud refreshes plant telemetry only every ~5 minutes, so the coordinator
caches each per-channel response for `MODULE_DATA_CACHE_INTERVAL` (240 s)
instead of re-fetching it on every poll. This matters because all stations
share one 30 second update budget (`async_timeout.timeout(30)` in
`__init__.py`), and each placeholder channel costs one extra request.

## Notes

- `date` and the freshness comparison are anchored to `dt_util.now()`, i.e. the
  timezone configured in Home Assistant rather than the host clock. Callers
  outside Home Assistant fall back to `datetime.now()`.
- Stations whose timezone differs from the Home Assistant one may briefly
  request the "wrong" day near midnight; the endpoint then returns an empty
  series and the integration keeps the previous behavior (placeholder values).
- Related reverse-engineered references: `Eistee82/ioBroker.hoymiles`
  (chart parser), `wil-lem/ha-hoymiles-s-cloud` (per-panel sensors).
