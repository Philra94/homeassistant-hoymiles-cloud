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
