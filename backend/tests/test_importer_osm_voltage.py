"""OSM ``voltage`` tag parser edge cases."""
from __future__ import annotations

import pytest

from backend.app.importers.databases.osm.voltage import (
    max_voltage_kv,
    parse_voltage_kv,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("110000", [110.0]),
        ("110000;220000", [110.0, 220.0]),
        ("110000,220000", [110.0, 220.0]),
        ("110 kV", [110.0]),
        ("110kv", [110.0]),
        ("110000 V", [110.0]),
        ("110", [110.0]),
        ("0.4", [0.4]),
        ("", []),
        ("unknown", []),
        ("None", []),
        (None, []),
        ("110000;110000;220000", [110.0, 220.0]),
    ],
)
def test_parse_voltage_kv(raw, expected):
    assert parse_voltage_kv(raw) == expected


def test_max_voltage_kv_picks_max():
    assert max_voltage_kv("110000;220000;380000") == 380.0


def test_max_voltage_kv_empty():
    assert max_voltage_kv("") is None
    assert max_voltage_kv(None) is None
