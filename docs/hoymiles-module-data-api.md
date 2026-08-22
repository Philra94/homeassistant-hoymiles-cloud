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

## Notes

- `date` is computed from the Home Assistant host's local time (same
  convention as `get_energy_flow`). Hosts in a different timezone from the
  station may briefly request the "wrong" day near midnight; the endpoint
  then returns an empty series and the integration keeps the previous
  behavior (placeholder values).
- Related reverse-engineered references: `Eistee82/ioBroker.hoymiles`
  (chart parser), `wil-lem/ha-hoymiles-s-cloud` (per-panel sensors).
