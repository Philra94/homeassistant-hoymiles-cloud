# PV Channel Data Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate PV channel sensors (and PV String Power) with real values on hardware where the PV indicators endpoint only returns placeholders, by falling back to the per-port module-data chart endpoint.

**Architecture:** Indicators-first with module-data fallback. A new HA-free protobuf wire decoder (`chart_pb.py`) feeds a new API method (`get_module_channel_data`); a pure merge helper in `data.py` substitutes placeholder indicator values; the coordinator (`__init__.py`) orchestrates the fallback only when placeholder channels exist and the station has exactly one microinverter.

**Tech Stack:** Python 3.11+ (integration code must stay 3.11-compatible), aiohttp, stdlib `struct` for protobuf wire parsing, pytest with the repo's standalone module loader.

**Spec:** `docs/superpowers/specs/2026-08-20-pv-channel-data-fallback-design.md`

## Global Constraints

- No new runtime dependencies — protobuf decoding is manual wire-format parsing; do NOT add `protobuf` to `manifest.json` requirements or `pyproject.toml`.
- No Home Assistant imports in `chart_pb.py` or `data.py` (HA-free modules, loadable by `tests/module_loader.py`).
- All tests run via `uv run pytest -q` from the repo root without Home Assistant test fixtures (no `pytest-homeassistant-custom-component`).
- Integration code is Python 3.11+ syntax only (no 3.12+ features).
- Never log or print credentials/tokens.
- Existing tests must keep passing (30 currently; suite grows to ~44).
- Commit after every green test cycle; never commit `resources/1787222993356.csv` or other runtime/user files.

---

### Task 1: Protobuf chart decoder (`chart_pb.py`)

**Files:**
- Create: `custom_components/hoymiles_cloud/chart_pb.py`
- Create: `tests/pb_wire.py` (test-only wire encoder)
- Create: `tests/test_chart_pb.py`

**Interfaces:**
- Consumes: nothing (stdlib only)
- Produces: `decode_line_chart(raw: bytes) -> dict` where the dict is `{"x_axis": list[str], "series": list[dict], "type": str}` and each series dict is `{"type": str, "data": list[float], "did": int | None, "port": int | None}`. Raises `ValueError` on malformed input. Empty input returns `{"x_axis": [], "series": [], "type": ""}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pb_wire.py` (wire-format encoder used by tests only):

```python
"""Helpers to encode protobuf wire-format bytes for tests."""
from __future__ import annotations

import struct


def _varint(value: int) -> bytes:
    out = b""
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out += bytes([byte | 0x80])
        else:
            out += bytes([byte])
            return out


def _tag(field: int, wire_type: int) -> bytes:
    return _varint((field << 3) | wire_type)


def _length_delimited(field: int, payload: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(payload)) + payload


def encode_line_series(series_type: str, data: list[float]) -> bytes:
    """Encode one LineSeries message body."""
    out = _length_delimited(1, series_type.encode())
    out += _length_delimited(2, struct.pack(f"<{len(data)}f", *data))
    return out


def encode_line_chart(x_axis: list[str], series: list[tuple[str, list[float]]]) -> bytes:
    """Encode one LineChart message from (series_type, data) tuples."""
    out = b""
    for label in x_axis:
        out += _length_delimited(1, label.encode())
    for series_type, data in series:
        out += _length_delimited(2, encode_line_series(series_type, data))
    return out
```

Create `tests/test_chart_pb.py`:

```python
"""Tests for the Hoymiles chart protobuf wire decoder."""
import pytest

from tests.module_loader import load_integration_module
from tests.pb_wire import encode_line_chart

chart_pb = load_integration_module("chart_pb")
decode_line_chart = chart_pb.decode_line_chart


def test_decode_single_series_with_values() -> None:
    raw = encode_line_chart(["11:40", "11:45"], [("MODULE_V", [30.0, 35.3])])

    chart = decode_line_chart(raw)

    assert chart["x_axis"] == ["11:40", "11:45"]
    assert len(chart["series"]) == 1
    series = chart["series"][0]
    assert series["type"] == "MODULE_V"
    assert series["data"] == pytest.approx([30.0, 35.3], abs=1e-4)
    assert series["did"] is None
    assert series["port"] is None


def test_decode_multiple_series() -> None:
    raw = encode_line_chart(["06:00"], [("MODULE_POWER", [140.8]), ("MODULE_I", [3.98])])

    chart = decode_line_chart(raw)

    assert [s["type"] for s in chart["series"]] == ["MODULE_POWER", "MODULE_I"]
    assert chart["series"][0]["data"][0] == pytest.approx(140.8, abs=1e-3)
    assert chart["series"][1]["data"][0] == pytest.approx(3.98, abs=1e-4)


def test_decode_empty_buffer_returns_empty_chart() -> None:
    assert decode_line_chart(b"") == {"x_axis": [], "series": [], "type": ""}


def test_decode_json_error_body_raises_value_error() -> None:
    with pytest.raises(ValueError):
        decode_line_chart(b'{"status": "3", "message": "Query error."}')


def test_decode_truncated_buffer_raises_value_error() -> None:
    raw = encode_line_chart(["11:40"], [("MODULE_V", [30.0])])

    with pytest.raises(ValueError):
        decode_line_chart(raw[:-2])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chart_pb.py -q`
Expected: FAIL — `ImportError`/module-not-found for `chart_pb` from the module loader.

- [ ] **Step 3: Write minimal implementation**

Create `custom_components/hoymiles_cloud/chart_pb.py`:

```python
"""Minimal protobuf wire-format decoder for Hoymiles chart payloads.

Schema (observed from the S-Miles Cloud `module/data/count_by_day` endpoint):

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
"""
from __future__ import annotations

import struct
from typing import Any


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _read_field(buf: bytes, pos: int) -> tuple[int, int, bytes | int, int]:
    """Return (field_number, wire_type, value, new_pos) for one field."""
    tag, pos = _read_varint(buf, pos)
    field_number = tag >> 3
    wire_type = tag & 0x7
    if wire_type == 0:
        value, pos = _read_varint(buf, pos)
        return field_number, wire_type, value, pos
    if wire_type == 2:
        length, pos = _read_varint(buf, pos)
        if pos + length > len(buf):
            raise ValueError("truncated length-delimited field")
        return field_number, wire_type, buf[pos : pos + length], pos + length
    if wire_type == 5:
        if pos + 4 > len(buf):
            raise ValueError("truncated fixed32 field")
        return field_number, wire_type, buf[pos : pos + 4], pos + 4
    if wire_type == 1:
        if pos + 8 > len(buf):
            raise ValueError("truncated fixed64 field")
        return field_number, wire_type, buf[pos : pos + 8], pos + 8
    raise ValueError(f"unsupported wire type {wire_type}")


def _decode_line_series(buf: bytes) -> dict[str, Any]:
    series: dict[str, Any] = {"type": "", "data": [], "did": None, "port": None}
    pos = 0
    while pos < len(buf):
        field, _, value, pos = _read_field(buf, pos)
        if field == 1:
            series["type"] = value.decode("utf-8")
        elif field == 2:
            if len(value) % 4:
                raise ValueError("packed float data not a multiple of 4 bytes")
            series["data"] = list(struct.unpack(f"<{len(value) // 4}f", value))
        elif field == 3:
            series["did"] = value
        elif field == 4:
            series["port"] = value
    return series


def decode_line_chart(raw: bytes) -> dict[str, Any]:
    """Decode a LineChart protobuf message from raw bytes."""
    chart: dict[str, Any] = {"x_axis": [], "series": [], "type": ""}
    pos = 0
    while pos < len(raw):
        field, _, value, pos = _read_field(raw, pos)
        if field == 1:
            chart["x_axis"].append(value.decode("utf-8"))
        elif field == 2:
            chart["series"].append(_decode_line_series(value))
        elif field == 3:
            chart["type"] = value.decode("utf-8")
    return chart
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chart_pb.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/hoymiles_cloud/chart_pb.py tests/pb_wire.py tests/test_chart_pb.py
git commit -m "feat: add protobuf chart decoder for Hoymiles module data"
```

---

### Task 2: Placeholder detection and merge helpers (`data.py`)

**Files:**
- Modify: `custom_components/hoymiles_cloud/data.py` (after `discover_pv_channels`, which ends at line 687)
- Modify: `tests/test_data.py` (imports at top, tests appended at end)

**Interfaces:**
- Consumes: `discover_pv_channels(pv_indicators)` and `get_pv_indicator_value(pv_indicators, key)` from `data.py` (already exist)
- Produces:
  - `find_placeholder_pv_channels(pv_indicators: dict | None) -> list[int]` — channels whose `v`/`i`/`p` indicator values are ALL placeholders
  - `merge_missing_pv_channel_values(pv_indicators: dict | None, module_values_by_channel: dict[int, dict[str, float | None]]) -> dict` — returns merged copy, input not mutated; replaces only placeholder `{n}_pv_{v|i|p}` values; sets `pv_p_total` to the sum of known `MODULE_POWER` values when it is a placeholder or zero; keys `MODULE_V`/`MODULE_I`/`MODULE_POWER` map to metrics `v`/`i`/`p`

- [ ] **Step 1: Write the failing tests**

In `tests/test_data.py`, extend the module-level bindings (after line 14, `validate_schedule_draft = data_module.validate_schedule_draft`):

```python
find_placeholder_pv_channels = data_module.find_placeholder_pv_channels
merge_missing_pv_channel_values = data_module.merge_missing_pv_channel_values
```

Add `import pytest` as a new import line after the existing `from tests.module_loader import load_integration_module` import, and append these tests:

```python
def test_find_placeholder_pv_channels_flags_all_placeholder_channels() -> None:
    """Channels whose v/i/p values are all placeholders should be flagged."""
    pv_indicators = {
        "list": [
            {"key": "pv_p_total", "val": "0"},
            {"key": "1_pv_v", "val": "-"},
            {"key": "1_pv_i", "val": "-"},
            {"key": "1_pv_p", "val": "-"},
        ]
    }

    assert find_placeholder_pv_channels(pv_indicators) == [1]


def test_find_placeholder_pv_channels_ignores_channels_with_real_values() -> None:
    """A channel with any numeric value must not be flagged."""
    pv_indicators = {
        "list": [
            {"key": "1_pv_v", "val": "42.1"},
            {"key": "1_pv_i", "val": "-"},
            {"key": "1_pv_p", "val": "350"},
        ]
    }

    assert find_placeholder_pv_channels(pv_indicators) == []


def test_merge_replaces_placeholder_channel_values() -> None:
    """Placeholder v/i/p values should be replaced with module data."""
    pv_indicators = {
        "list": [
            {"key": "pv_p_total", "val": "0"},
            {"key": "1_pv_v", "val": "-"},
            {"key": "1_pv_i", "val": "-"},
            {"key": "1_pv_p", "val": "-"},
        ]
    }

    merged = merge_missing_pv_channel_values(
        pv_indicators,
        {1: {"MODULE_V": 35.3, "MODULE_I": 3.98, "MODULE_POWER": 140.8}},
    )

    values = {item["key"]: item["val"] for item in merged["list"]}
    assert values["1_pv_v"] == 35.3
    assert values["1_pv_i"] == 3.98
    assert values["1_pv_p"] == 140.8
    assert values["pv_p_total"] == 140.8


def test_merge_preserves_numeric_indicator_values() -> None:
    """Numeric indicator values must never be overwritten."""
    pv_indicators = {
        "list": [
            {"key": "1_pv_v", "val": "42.1"},
            {"key": "1_pv_i", "val": "8.2"},
            {"key": "1_pv_p", "val": "350"},
            {"key": "pv_p_total", "val": "1500"},
        ]
    }

    merged = merge_missing_pv_channel_values(
        pv_indicators,
        {1: {"MODULE_V": 35.3, "MODULE_I": 3.98, "MODULE_POWER": 140.8}},
    )

    values = {item["key"]: item["val"] for item in merged["list"]}
    assert values["1_pv_v"] == "42.1"
    assert values["1_pv_i"] == "8.2"
    assert values["1_pv_p"] == "350"
    assert values["pv_p_total"] == "1500"


def test_merge_skips_none_module_values() -> None:
    """A None module value must leave the placeholder untouched."""
    pv_indicators = {"list": [{"key": "1_pv_v", "val": "-"}]}

    merged = merge_missing_pv_channel_values(pv_indicators, {1: {"MODULE_V": None}})

    assert merged["list"][0]["val"] == "-"


def test_merge_does_not_mutate_input() -> None:
    pv_indicators = {"list": [{"key": "1_pv_v", "val": "-"}]}

    merge_missing_pv_channel_values(pv_indicators, {1: {"MODULE_V": 35.3}})

    assert pv_indicators["list"][0]["val"] == "-"


def test_merge_sums_module_power_across_channels() -> None:
    pv_indicators = {
        "list": [
            {"key": "1_pv_p", "val": "-"},
            {"key": "2_pv_p", "val": "-"},
            {"key": "pv_p_total", "val": "-"},
        ]
    }

    merged = merge_missing_pv_channel_values(
        pv_indicators,
        {
            1: {"MODULE_V": None, "MODULE_I": None, "MODULE_POWER": 140.8},
            2: {"MODULE_V": None, "MODULE_I": None, "MODULE_POWER": 59.2},
        },
    )

    values = {item["key"]: item["val"] for item in merged["list"]}
    assert values["pv_p_total"] == pytest.approx(200.0)


def test_merge_handles_empty_inputs() -> None:
    assert merge_missing_pv_channel_values(None, {1: {"MODULE_V": 1.0}}) == {}
    assert merge_missing_pv_channel_values({"list": []}, {}) == {"list": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_data.py -q`
Expected: FAIL — `AttributeError: module has no attribute 'find_placeholder_pv_channels'` (raised at the module-level binding lines).

- [ ] **Step 3: Write minimal implementation**

In `custom_components/hoymiles_cloud/data.py`, insert after `discover_pv_channels` (i.e. after the line `return sorted(channels)` which currently ends that function at line 687):

```python
def _is_placeholder(value: Any) -> bool:
    """Return whether an indicator value carries no usable number."""
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        if text in {"", "-"}:
            return True
        try:
            float(text)
        except ValueError:
            return True
        return False
    if isinstance(value, (int, float)):
        return False
    return True


def _is_zero(value: Any) -> bool:
    """Return whether an indicator value is the number zero."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        try:
            return float(value) == 0
        except ValueError:
            return False
    return False


def find_placeholder_pv_channels(pv_indicators: dict[str, Any] | None) -> list[int]:
    """Return discovered PV channels whose v/i/p values are all placeholders."""
    channels: list[int] = []
    for channel in discover_pv_channels(pv_indicators):
        metrics = [
            get_pv_indicator_value(pv_indicators, f"{channel}_pv_{metric}")
            for metric in ("v", "i", "p")
        ]
        if all(_is_placeholder(value) for value in metrics):
            channels.append(channel)
    return channels


def _replace_indicator_value(
    items: list[dict[str, Any]],
    key: str,
    value: float,
    *,
    replace_zero: bool = False,
) -> None:
    """Set one indicator value in place, replacing placeholders only."""
    for item in items:
        if isinstance(item, dict) and item.get("key") == key:
            if _is_placeholder(item.get("val")) or (
                replace_zero and _is_zero(item.get("val"))
            ):
                item["val"] = value
            return
    items.append({"key": key, "val": value})


def merge_missing_pv_channel_values(
    pv_indicators: dict[str, Any] | None,
    module_values_by_channel: dict[int, dict[str, float | None]],
) -> dict[str, Any]:
    """Replace placeholder PV indicator values with per-port module data."""
    if not pv_indicators or not module_values_by_channel:
        return pv_indicators or {}

    merged = deepcopy(pv_indicators)
    items = merged.setdefault("list", [])

    metric_map = {
        "MODULE_V": "v",
        "MODULE_I": "i",
        "MODULE_POWER": "p",
    }

    module_power_sum = 0.0
    module_power_known = False

    for channel, module_values in sorted(module_values_by_channel.items()):
        for module_key, metric in metric_map.items():
            value = module_values.get(module_key)
            if value is None:
                continue
            _replace_indicator_value(items, f"{channel}_pv_{metric}", value)
        power = module_values.get("MODULE_POWER")
        if power is not None:
            module_power_sum += power
            module_power_known = True

    if module_power_known:
        _replace_indicator_value(items, "pv_p_total", module_power_sum, replace_zero=True)

    return merged
```

Note: `deepcopy` is already imported in `data.py` (`from copy import deepcopy` at line 4).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_data.py -q`
Expected: all pass (existing + 9 new).

- [ ] **Step 5: Commit**

```bash
git add custom_components/hoymiles_cloud/data.py tests/test_data.py
git commit -m "feat: add PV channel placeholder detection and merge helpers"
```

---

### Task 3: API method `get_module_channel_data` (`hoymiles_api.py`)

**Files:**
- Modify: `custom_components/hoymiles_cloud/const.py` (after `API_INDICATORS_URL`, line 43)
- Modify: `custom_components/hoymiles_cloud/hoymiles_api.py` (const import block lines 20-44; `from .chart_pb import ...` after the `.const` import block ends; `_post_bytes` after `_post_json` which ends at line 299; `get_module_channel_data` after `get_pv_indicators` which ends at line 1151)
- Modify: `tests/test_hoymiles_api.py` (imports; `FakeSession.post` gains bytes support; tests appended)

**Interfaces:**
- Consumes: `decode_line_chart(raw: bytes) -> dict` from Task 1; existing `_ensure_authenticated()`, `_auth_headers()`, `_LOGGER`
- Produces: `HoymilesAPI.get_module_channel_data(station_id: str, mi_id: int, port: int, date: str | None = None) -> dict[str, float | None]` — keys `"MODULE_POWER"`, `"MODULE_V"`, `"MODULE_I"`; each is the LAST element of the matching series, or `None` when the series is missing/empty; decode failures or JSON error bodies → warning log + `{}` return; `date` defaults to local `datetime.now().strftime("%Y-%m-%d")`

- [ ] **Step 1: Write the failing tests**

In `tests/test_hoymiles_api.py`:

(a) Extend imports at the top (after `import asyncio`, keep `from tests.module_loader import load_integration_module`):

```python
from datetime import datetime

import pytest

from tests.pb_wire import encode_line_chart
```

(b) Extend `FakeSession.post` so queued responses may be `bytes` (binary responses). Replace the existing method body:

```python
    def post(self, *args, **kwargs):  # noqa: ANN002, ANN003 - test double
        if not self._responses:
            raise AssertionError("No fake responses left")
        self.requests.append({"args": args, "kwargs": kwargs})
        response = self._responses.pop(0)
        if isinstance(response, bytes):
            return FakeBytesRequest(response)
        return FakeRequest(response)
```

(c) Add the binary request/response doubles next to the existing `FakeResponse`/`FakeRequest` classes:

```python
class FakeBytesResponse:
    """Minimal aiohttp-like binary response wrapper for tests."""

    def __init__(self, body: bytes):
        self._body = body

    async def read(self) -> bytes:
        return self._body


class FakeBytesRequest:
    """Binary counterpart of FakeRequest."""

    def __init__(self, body: bytes):
        self._response = FakeBytesResponse(body)

    def __await__(self):
        async def _result():
            return self._response

        return _result().__await__()

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False
```

(d) Append these tests:

```python
def test_get_module_channel_data_returns_last_series_values() -> None:
    """Module chart data should expose the freshest value per quota."""
    api = HoymilesAPI(
        FakeSession(
            [
                encode_line_chart(
                    ["11:40", "11:45"],
                    [
                        ("MODULE_POWER", [100.0, 140.8]),
                        ("MODULE_V", [30.0, 35.3]),
                        ("MODULE_I", [3.0, 3.98]),
                    ],
                )
            ]
        ),
        "user@example.com",
        "secret",
    )
    api._token = "token"
    api._token_expires_at = 9999999999

    values = asyncio.run(api.get_module_channel_data("15068730", 34762140, 1))

    assert values["MODULE_POWER"] == pytest.approx(140.8, abs=1e-3)
    assert values["MODULE_V"] == pytest.approx(35.3, abs=1e-3)
    assert values["MODULE_I"] == pytest.approx(3.98, abs=1e-3)
    request = api._session.requests[0]["kwargs"]
    assert request["json"] == {
        "sid": 15068730,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "mi_list": [{"id": 34762140, "port": 1}],
        "quota": ["MODULE_POWER", "MODULE_V", "MODULE_I"],
    }


def test_get_module_channel_data_json_error_returns_empty() -> None:
    """Non-protobuf error bodies should degrade to an empty mapping."""
    api = HoymilesAPI(
        FakeSession([b'{"status": "3", "message": "Query error."}']),
        "user@example.com",
        "secret",
    )
    api._token = "token"
    api._token_expires_at = 9999999999

    assert asyncio.run(api.get_module_channel_data("15068730", 34762140, 1)) == {}


def test_get_module_channel_data_empty_series_keeps_none() -> None:
    """Empty series should leave metrics unset."""
    api = HoymilesAPI(
        FakeSession([encode_line_chart(["06:00"], [("MODULE_V", [])])]),
        "user@example.com",
        "secret",
    )
    api._token = "token"
    api._token_expires_at = 9999999999

    values = asyncio.run(api.get_module_channel_data("15068730", 34762140, 1))

    assert values == {"MODULE_POWER": None, "MODULE_V": None, "MODULE_I": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hoymiles_api.py -q`
Expected: 3 FAIL — `AttributeError: 'HoymilesAPI' object has no attribute 'get_module_channel_data'`.

- [ ] **Step 3: Write minimal implementation**

(a) In `custom_components/hoymiles_cloud/const.py`, add after the `API_INDICATORS_URL` line:

```python
API_MODULE_DAY_DATA_URL = f"{API_BASE_URL}/pvm-data/api/0/module/data/count_by_day"
```

(b) In `custom_components/hoymiles_cloud/hoymiles_api.py`:

Add `API_MODULE_DAY_DATA_URL,` to the `.const` import block (e.g. directly after `API_INDICATORS_URL,`).

Add after the `.const` import block (after the closing parenthesis of that import):

```python
from .chart_pb import decode_line_chart
```

Add after `_post_json` (after its `return json.loads(resp_text)` line):

```python
    async def _post_bytes(
        self,
        url: str,
        payload: dict[str, Any],
    ) -> bytes:
        """Send a POST request and return the raw response body."""
        await self._ensure_authenticated()
        async with self._session.post(
            url, headers=self._auth_headers(), json=payload
        ) as response:
            return await response.read()
```

Add after `get_pv_indicators` (after its `return await self.get_indicator_data(station_id, INDICATOR_TYPE_PV)` line):

```python
    async def get_module_channel_data(
        self,
        station_id: str,
        mi_id: int,
        port: int,
        date: str | None = None,
    ) -> dict[str, Any]:
        """Return the latest per-port PV module values from the chart endpoint."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        payload = {
            "sid": int(station_id),
            "date": date,
            "mi_list": [{"id": mi_id, "port": port}],
            "quota": ["MODULE_POWER", "MODULE_V", "MODULE_I"],
        }
        try:
            raw = await self._post_bytes(API_MODULE_DAY_DATA_URL, payload)
            chart = decode_line_chart(raw)
        except (ValueError, UnicodeDecodeError) as err:
            _LOGGER.warning(
                "Failed to decode module chart data for station %s port %s: %s",
                station_id,
                port,
                err,
            )
            return {}

        values: dict[str, Any] = {
            "MODULE_POWER": None,
            "MODULE_V": None,
            "MODULE_I": None,
        }
        for series in chart.get("series", []):
            series_type = series.get("type")
            if series_type not in values:
                continue
            data = series.get("data") or []
            if data:
                values[series_type] = data[-1]
        return values
```

Note: `datetime` is already imported in `hoymiles_api.py` (`from datetime import datetime` at line 6).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hoymiles_api.py -q`
Expected: all pass (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add custom_components/hoymiles_cloud/const.py custom_components/hoymiles_cloud/hoymiles_api.py tests/test_hoymiles_api.py
git commit -m "feat: fetch per-port module chart data from Hoymiles API"
```

---

### Task 4: Coordinator fallback wiring (`__init__.py`)

**Files:**
- Modify: `custom_components/hoymiles_cloud/__init__.py` (`from .data import (...)` block at lines 36-46; coordinator `async_update_data` — insert after the `pv_indicators` fetch block which ends at line 539, before `if fetch_grid_indicators:` at line 541)

**Interfaces:**
- Consumes: `find_placeholder_pv_channels(pv_indicators) -> list[int]` and `merge_missing_pv_channel_values(pv_indicators, module_values_by_channel) -> dict` from Task 2; `HoymilesAPI.get_module_channel_data(station_id, mi_id, port) -> dict` from Task 3; `static_payload["devices"]["microinverters"]` is `dict[str, dict]` keyed by microinverter id string, each value containing `"id": int`
- Produces: none (internal wiring; `pv_indicators` passed to `StationData` may now contain merged values)

No new unit tests — this module imports Home Assistant and is not loadable by the standalone test suite. Verification is the full suite (regression), a syntax check, and the live check in Task 5.

- [ ] **Step 1: Extend the data import block**

In `custom_components/hoymiles_cloud/__init__.py`, add two names to the `from .data import (...)` block, keeping alphabetical order (after `build_station_capabilities,` and after `get_schedule_draft,`):

```python
    find_placeholder_pv_channels,
```

and

```python
    merge_missing_pv_channel_values,
```

- [ ] **Step 2: Insert the fallback block in `async_update_data`**

Immediately after this existing block (which currently ends at line 539):

```python
                    try:
                        pv_indicators = await api.get_pv_indicators(station_id)
                    except Exception as err:
                        _LOGGER.warning(
                            "Failed to get PV indicators for station %s: %s",
                            station_id,
                            err,
                        )
                        pv_indicators = {}
```

insert:

```python
                    microinverters = static_payload.get("devices", {}).get(
                        "microinverters", {}
                    )
                    placeholder_channels = find_placeholder_pv_channels(pv_indicators)
                    if placeholder_channels and len(microinverters) == 1:
                        micro = next(iter(microinverters.values()))
                        mi_id = micro.get("id") if isinstance(micro, dict) else None
                        if mi_id is not None:
                            module_values_by_channel: dict[int, dict[str, Any]] = {}
                            for channel in placeholder_channels:
                                try:
                                    module_values_by_channel[channel] = (
                                        await api.get_module_channel_data(
                                            station_id, mi_id, channel
                                        )
                                    )
                                except Exception as err:
                                    _LOGGER.warning(
                                        "Failed to get module channel data for "
                                        "station %s port %s: %s",
                                        station_id,
                                        channel,
                                        err,
                                    )
                            if module_values_by_channel:
                                pv_indicators = merge_missing_pv_channel_values(
                                    pv_indicators, module_values_by_channel
                                )
                    elif placeholder_channels:
                        _LOGGER.debug(
                            "Skipping module data fallback for station %s: "
                            "%s microinverters",
                            station_id,
                            len(microinverters),
                        )
```

- [ ] **Step 3: Run the full suite and syntax check**

Run: `uv run pytest -q`
Expected: all pass (no regressions; Task 4 adds no tests).

Run: `uv run python -m py_compile custom_components/hoymiles_cloud/__init__.py`
Expected: no output (exit 0).

- [ ] **Step 4: Commit**

```bash
git add custom_components/hoymiles_cloud/__init__.py
git commit -m "feat: merge module PV data into indicators in coordinator"
```

---

### Task 5: Docs, version bump, and live verification

**Files:**
- Create: `docs/hoymiles-module-data-api.md`
- Modify: `README.md` (Features bullet + Notes line)
- Modify: `custom_components/hoymiles_cloud/manifest.json` (`"version": "1.0.0"` → `"1.1.0"`)
- Modify: `AGENTS.md` (HA-free module list)

**Interfaces:**
- Consumes: finished Tasks 1-4
- Produces: documentation and release version; no code changes

- [ ] **Step 1: Write `docs/hoymiles-module-data-api.md`**

```markdown
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
```

- [ ] **Step 2: README and version updates**

In `README.md`, under **Features → Data Monitoring**, add after the "Dynamic PV channel discovery..." bullet:

```markdown
  - Per-channel PV voltage/current/power values via the module-data endpoint when the indicators feed only returns placeholders
```

In `README.md`, under **Notes**, add:

```markdown
- On some hardware (observed: HF-800-1WB) the indicators endpoint returns placeholder values for per-channel PV data; the integration then falls back to the module-data chart endpoint (see `docs/hoymiles-module-data-api.md`) for single-microinverter stations.
```

In `custom_components/hoymiles_cloud/manifest.json`, change `"version": "1.0.0"` to `"version": "1.1.0"`.

In `AGENTS.md`, add `chart_pb.py` to the HA-free modules list sentence (after `hoymiles_api.py (all Hoymiles HTTP + auth hashing)`):

```markdown
`chart_pb.py` (protobuf chart decoding),
```

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass (~44 tests).

- [ ] **Step 4: Live verification (restart the local HA instance)**

The dev instance may be running; restarting it is expected for this feature. Do NOT use `pkill -f "hass -c ..."` (it self-matches the shell command); kill by exact PID:

```bash
pgrep -af "\.venv/bin/hass"  # note the PID
kill <PID>
sleep 5
(nohup uv run hass -c resources/home-assistant-test/config > /tmp/opencode/hass.log 2>&1 &)
```

Poll until up (up to ~120s):

```bash
for i in $(seq 1 40); do sleep 3; curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8123/ | grep -q 200 && echo up && break; done
```

Wait for at least two coordinator cycles (~2 minutes), then check states (expect numeric values, not `unknown`; `pv_string_power` should match the sum of port powers):

```bash
uv run python - <<'EOF'
import sqlite3
con = sqlite3.connect("file:resources/home-assistant-test/config/home-assistant_v2.db?mode=ro", uri=True)
rows = con.execute("""
SELECT m.entity_id, s.state FROM states s
JOIN states_meta m ON s.metadata_id = m.metadata_id
WHERE m.entity_id LIKE '%pv1%' OR m.entity_id LIKE '%pv_string%'
ORDER BY s.last_updated_ts DESC
""").fetchall()
seen = set()
for entity_id, state in rows:
    if entity_id not in seen:
        seen.add(entity_id)
        print(f"{entity_id:45s} {state}")
EOF
```

Expected: `sensor.my_home_pv1_current`, `..._pv1_voltage`, `..._pv1_power` show numeric states; `sensor.my_home_pv_string_power` matches the port power sum. If it is nighttime, values may be 0.0 — still numeric, not `unknown`.

Also check the log for warnings:

```bash
grep -i "module channel\|chart data" /tmp/opencode/hass.log | tail -5
```

Expected: no repeated warnings (a single early failure before the first successful cycle is acceptable if values still appear).

- [ ] **Step 5: Commit**

```bash
git add docs/hoymiles-module-data-api.md README.md custom_components/hoymiles_cloud/manifest.json AGENTS.md
git commit -m "docs: document module data endpoint and bump version to 1.1.0"
```

---

## Self-Review Checklist (for the executing agent)

- Spec coverage: decoder (Task 1), merge + placeholder detection (Task 2), API method + `_post_bytes` + const URL (Task 3), coordinator orchestration incl. single-micro guard and debug log (Task 4), docs + version bump + README + AGENTS.md (Task 5). `pv_p_total` placeholder-or-zero semantics implemented via `replace_zero=True`.
- Float comparisons in tests use `pytest.approx` (values pass through float32).
- `find_placeholder_pv_channels` uses `all()` — a channel with ANY numeric value is not flagged (mixed partial payloads keep indicator data authoritative).
