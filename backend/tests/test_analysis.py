"""X2 server-side import analysis — per-column statistics."""
from __future__ import annotations

import pytest

from backend.app.analysis import (
    column_statistics,
    daily_profile,
    duration_curve,
    grouped_aggregate,
)


def test_numeric_column_stats() -> None:
    rows = [{"p_nom": v} for v in [10, 20, 30, 40, 50]]
    stats = column_statistics(rows)
    col = next(c for c in stats["columns"] if c["name"] == "p_nom")
    assert col["kind"] == "numeric"
    assert col["count"] == 5 and col["nulls"] == 0
    assert col["min"] == 10 and col["max"] == 50
    assert col["mean"] == pytest.approx(30.0)
    assert col["median"] == pytest.approx(30.0)
    assert col["sum"] == pytest.approx(150.0)
    assert col["p25"] == pytest.approx(20.0) and col["p75"] == pytest.approx(40.0)
    assert sum(col["histogram"]["counts"]) == 5


def test_categorical_column_stats() -> None:
    rows = [{"carrier": c} for c in ["gas", "gas", "wind", "solar", "gas", ""]]
    stats = column_statistics(rows)
    col = next(c for c in stats["columns"] if c["name"] == "carrier")
    assert col["kind"] == "categorical"
    assert col["count"] == 5 and col["nulls"] == 1  # blank excluded
    assert col["distinct"] == 3
    assert col["top"][0] == {"value": "gas", "count": 3}


def test_mixed_and_blank_handling() -> None:
    rows = [{"x": "1"}, {"x": "2"}, {"x": ""}, {"x": "3"}]
    result = column_statistics(rows)
    col = next(c for c in result["columns"] if c["name"] == "x")
    # Mostly-numeric string column is treated as numeric; the blank is a null.
    assert col["kind"] == "numeric"
    assert col["count"] == 3 and col["nulls"] == 1
    assert result["total"] == 4


def test_empty_rows() -> None:
    assert column_statistics([]) == {"total": 0, "columns": []}


def test_column_subset_and_order() -> None:
    rows = [{"a": 1, "b": "x", "c": 2}]
    cols = column_statistics(rows, ["c", "a"])["columns"]
    assert [c["name"] for c in cols] == ["c", "a"]


def test_duration_curve_sorts_descending() -> None:
    rows = [{"v": x} for x in [10, 50, 20, 40, 30]]
    d = duration_curve(rows, "v")
    assert d["values"] == [50, 40, 30, 20, 10]


def test_duration_curve_downsamples() -> None:
    rows = [{"v": x} for x in range(1000)]
    d = duration_curve(rows, "v", max_points=100)
    assert len(d["values"]) == 100
    assert d["values"][0] == 999  # still starts at the max


def test_daily_profile_means_by_hour() -> None:
    rows = [
        {"snapshot": "2020-01-01 00:00", "L": 10},
        {"snapshot": "2020-01-02 00:00", "L": 30},   # same hour → mean 20
        {"snapshot": "2020-01-01 12:00", "L": 50},
    ]
    d = daily_profile(rows, "snapshot", ["L"])
    vals = d["series"][0]["values"]
    assert len(vals) == 24
    assert vals[0] == 20.0     # (10+30)/2
    assert vals[12] == 50.0
    assert vals[6] == 0.0      # no data that hour


def test_grouped_aggregate_sum_and_sort() -> None:
    rows = [
        {"carrier": "gas", "p": 10}, {"carrier": "gas", "p": 20},
        {"carrier": "wind", "p": 5},
    ]
    g = grouped_aggregate(rows, "carrier", "p", "sum")
    assert g["bars"] == [{"label": "gas", "value": 30.0}, {"label": "wind", "value": 5.0}]
    gm = grouped_aggregate(rows, "carrier", "p", "mean")
    assert next(b for b in gm["bars"] if b["label"] == "gas")["value"] == 15.0


def test_derive_endpoint_via_session() -> None:
    from fastapi.testclient import TestClient

    from backend.app.main import app

    c = TestClient(app)
    model = {"loads-p_set": [
        {"snapshot": "2020-01-01 00:00", "L": 10},
        {"snapshot": "2020-01-02 00:00", "L": 30},
        {"snapshot": "2020-01-01 12:00", "L": 50},
    ]}
    sid = "test_x2_derive"
    assert c.post("/api/session/model", json={"model": model, "sessionId": sid}).status_code == 200
    r = c.get(f"/api/session/sheet/loads-p_set/derive?mode=daily_profile&column=L&session_id={sid}")
    assert r.status_code == 200
    assert r.json()["series"][0]["values"][0] == 20.0
    r2 = c.get(f"/api/session/sheet/loads-p_set/derive?mode=duration&column=L&session_id={sid}")
    assert r2.json()["values"] == [50, 30, 10]
    c.post(f"/api/session/clear?session_id={sid}")


def test_endpoint_via_session(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from backend.app.main import app

    c = TestClient(app)
    model = {
        "generators": [
            {"name": "g1", "carrier": "gas", "p_nom": 100},
            {"name": "g2", "carrier": "gas", "p_nom": 200},
            {"name": "g3", "carrier": "wind", "p_nom": 50},
        ]
    }
    sid = "test_x2_stats"
    assert c.post("/api/session/model", json={"model": model, "sessionId": sid}).status_code == 200
    r = c.get(f"/api/session/sheet/generators/stats?session_id={sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    by = {col["name"]: col for col in body["columns"]}
    assert by["p_nom"]["kind"] == "numeric" and by["p_nom"]["mean"] == pytest.approx(116.667, abs=1e-2)
    assert by["carrier"]["kind"] == "categorical" and by["carrier"]["distinct"] == 2
    c.post(f"/api/session/clear?session_id={sid}")
