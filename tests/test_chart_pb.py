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
