# PV Channel Data Fallback — Design

Date: 2026-08-20
Status: Approved (approach A)

## Background

The integration creates per-channel PV sensors (`PV{n} Voltage/Current/Power`)
from indicator keys (`{n}_pv_v`, `{n}_pv_i`, `{n}_pv_p`) returned by
`POST /pvm-data/api/0/indicators/data/select_real_indicators_data` (type 4).

For some hardware families (observed: Hoymiles HF-800-1WB microinverter) that
endpoint returns the keys but with placeholder values (`"-"`), so the sensors
exist but stay `unknown` forever. `pv_p_total` is also returned as `"0"`,
leaving the PV String Power sensor stale.

The data itself IS available in the cloud: the S-Miles web "O&M" per-port view
(backing the user-facing CSV export) is served by a protobuf endpoint that was
verified live against an affected account:

```
POST https://neapi.hoymiles.com/pvm-data/api/0/module/data/count_by_day
Content-Type: application/json (authenticated, bearer token)
{
  "sid": 15068730,
  "date": "2026-08-20",
  "mi_list": [{"id": 34762140, "port": 1}],
  "quota": ["MODULE_POWER", "MODULE_V", "MODULE_I"]
}
→ 200, Content-Type: application/octet-stream (protobuf LineChart)
```

The `pvmc/api/0/module_data/count_by_day_c` variant returned identical bytes in
testing; we use the `pvm-data` path only.

## Observed protobuf schema (wire format, no codegen)

```protobuf
message LineSeries {
  string type = 1;                          // "MODULE_POWER" | "MODULE_V" | "MODULE_I"
  repeated float data = 2 [packed = true];  // float32, 5-min series for the day
  int32 did = 3;
  int32 port = 4;
}
message LineChart {
  repeated string x_axis = 1;   // "06:05", ... up to current 5-min slot
  repeated LineSeries series = 2;
  string type = 3;
}
```

The series fills from dawn to the current 5-minute slot; the **last element**
is the freshest value the cloud has.

## Goal

PV channel sensors (and PV String Power) show real values on hardware where
the indicators endpoint only returns placeholders, without changing behavior
for accounts where indicators already work.

Non-goals (out of scope): stations with multiple microinverters, separate
per-panel entities/devices, the `ChartV2` wire format (only `LineChart`
observed), and the `micro/data/count_by_day` micro-level endpoint.

## Design

### Approach: indicators-first with module-data fallback

The existing `pv_indicators` fetch stays the primary source. Only when a
discovered channel's values are placeholders AND the station has exactly one
microinverter do we call the module-data endpoint per affected channel and
merge the values into `pv_indicators` before it reaches the sensor layer.

Rationale: zero extra API calls and zero behavior change for working accounts
(e.g. HYT systems); sensor layer untouched; multi-micro stations keep current
behavior because channel↔port mapping would be ambiguous there.

### Components

1. **`chart_pb.py`** (new, HA-free, no new dependency)
   Manual protobuf wire-format decoder:
   `decode_line_chart(raw: bytes) -> {"x_axis": list[str], "series": [{"type": str, "data": list[float], "did": int|None, "port": int|None}]}`
   Raises `ValueError` on malformed input. ~70 lines, no `protobuf` package
   requirement added to `manifest.json`.

2. **`hoymiles_api.py`**
   - `_post_bytes(url, payload)` — like `_post_json` but returns raw `bytes`.
   - `get_module_channel_data(station_id, mi_id, port, date=None) -> dict`
     Returns `{"MODULE_V": float|None, "MODULE_I": float|None, "MODULE_POWER": float|None}`
     using the **last element** of each series (real zeros at night are valid
     data). `date` defaults to local `datetime.now().strftime("%Y-%m-%d")`
     (same convention as `get_energy_flow`). Decode errors and non-protobuf
     error bodies → log warning, return `{}`.

3. **`data.py`**
   `merge_missing_pv_channel_values(pv_indicators, module_values_by_channel) -> dict`
   Pure function. For each channel `n` in `module_values_by_channel`:
   - If indicator `f"{n}_pv_v"` / `_i` / `_p` is a non-numeric placeholder
     (`None`, `"-"`, `""`, whitespace, unparseable) and the corresponding
     module value is not `None`, replace it (as float).
   - Numeric indicator values are never overwritten.
   - If `pv_p_total` is a placeholder and module powers exist, set it to the
     sum of `MODULE_POWER` across channels.
   Returns the (possibly) modified dict; input not mutated.

4. **`__init__.py` (coordinator `async_update_data`)**
   After the `pv_indicators` fetch:
   - Determine placeholder channels (discovered via `discover_pv_channels`
     whose v/i/p values are all non-numeric).
   - Micro inventory comes from the already-fetched static payload
     (`devices.microinverters`, includes `layout_list`). Fallback runs only
     when `len(microinverters) == 1`.
   - One `get_module_channel_data(sid, mi_id, port=channel)` call per
     affected channel (channel number == port number).
   - Merge into `pv_indicators` via the `data.py` function.
   - All module-fetch exceptions are caught, logged as warnings, and
     swallowed (same pattern as every other fetch in the coordinator);
     indicators pass through unmerged on failure.

### Data flow

```
async_update_data
  → static payload (already cached; has devices.microinverters)
  → get_pv_indicators (unchanged)
  → [new] if placeholder channels and exactly 1 micro:
        for each channel: get_module_channel_data(sid, mi_id, port=channel)
        pv_indicators = merge_missing_pv_channel_values(pv_indicators, {...})
  → StationData(... pv_indicators ...)   (unchanged)
  → sensors read merged values; availability/value logic untouched
```

### Error handling

- Module endpoint failure → warning log, sensors behave exactly as today
  (unknown), telemetry for everything else unaffected.
- Malformed protobuf → `ValueError` from decoder, caught in the API method,
  warning logged, `{}` returned.
- Zero-length or empty series → metric stays `None` → placeholder not
  replaced → sensor state unchanged.
- Extra API cost: one call per placeholder channel per coordinator cycle
  (affected single-micro stations: 1–2 calls/min at the default 60s scan).

### Timezone note

`date` uses the HA host's local date (existing convention in
`get_energy_flow`). Near midnight, hosts in a different timezone from the
station may briefly request the "wrong" day; the endpoint returns an empty
series, values stay placeholder, no crash. Acceptable for now; noted in the
API doc.

## Testing (standalone, no HA)

- `tests/test_chart_pb.py`: hand-crafted wire bytes — single/multiple series,
  packed floats, x_axis strings, empty buffer, truncated/garbage input
  raising `ValueError`.
- `tests/test_hoymiles_api.py` additions: `get_module_channel_data` with a
  `FakeSession` extended with `read()` (binary responses); happy path (last
  values extracted), JSON error body → `{}`.
- `tests/test_data.py` additions: merge semantics — placeholder replaced,
  numeric preserved, `None` module values leave placeholders, `pv_p_total`
  summed from module powers, missing/unrelated keys untouched, empty inputs.

## Documentation & version

- `docs/hoymiles-module-data-api.md`: observed endpoint, request/response,
  protobuf schema, timezone caveat (follows `docs/hoymiles-battery-mode-api.md`
  convention).
- README: feature/notes mention.
- `manifest.json` version bump 1.0.0 → 1.1.0.
- AGENTS.md: add `chart_pb.py` to the HA-free module list.
