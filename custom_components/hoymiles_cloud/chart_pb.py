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
