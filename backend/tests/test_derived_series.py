"""X1 server-side derived chart-series — aggregation correctness."""
from __future__ import annotations

import pytest

from backend.pypsa.results.derived_series import carrier_map, derive_series

MODEL = {"generators": [
    {"name": "g_wind", "carrier": "wind"},
    {"name": "g_gas1", "carrier": "gas"},
    {"name": "g_gas2", "carrier": "gas"},
]}
COLUMNS = ["snapshot", "g_wind", "g_gas1", "g_gas2"]
ROWS = [
    {"snapshot": "t0", "g_wind": 10, "g_gas1": 20, "g_gas2": 5},
    {"snapshot": "t1", "g_wind": 30, "g_gas1": 0, "g_gas2": -3},  # negative dropped
]


def test_dispatch_aggregates_by_carrier() -> None:
    d = derive_series(COLUMNS, ROWS, "snapshot", metric="dispatch_by_carrier",
                      carriers=carrier_map(MODEL))
    by = {s["key"]: s["values"] for s in d["series"]}
    assert d["labels"] == ["t0", "t1"]
    assert by["wind"] == [10.0, 30.0]
    assert by["gas"] == [25.0, 0.0]   # t0: 20+5; t1: 0 (negative -3 clipped out)


def test_load_sums_all_columns() -> None:
    cols = ["snapshot", "L1", "L2"]
    rows = [{"snapshot": "t0", "L1": 40, "L2": 60}, {"snapshot": "t1", "L1": 30, "L2": 30}]
    d = derive_series(cols, rows, "snapshot", metric="load", carriers={})
    assert d["series"][0]["values"] == [100.0, 60.0]


def test_system_price_means_buses() -> None:
    cols = ["snapshot", "b1", "b2"]
    rows = [{"snapshot": "t0", "b1": 50, "b2": 70}, {"snapshot": "t1", "b1": 10, "b2": 30}]
    d = derive_series(cols, rows, "snapshot", metric="system_price", carriers={})
    assert d["series"][0]["values"] == [60.0, 20.0]


def test_unknown_metric_raises() -> None:
    with pytest.raises(ValueError, match="Unknown derived metric"):
        derive_series(COLUMNS, ROWS, "snapshot", metric="nope", carriers={})


def test_carrier_map_falls_back_to_name() -> None:
    m = carrier_map({"generators": [{"name": "x"}, {"name": "y", "carrier": "solar"}]})
    assert m == {"x": "x", "y": "solar"}
