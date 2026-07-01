"""T1 (a) — snapshot-window retarget: regenerate the index + reindex series."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import session_store
from backend.app.main import app
from backend.app.timeseries import (
    generate_snapshots,
    growth_factor,
    retarget_rows,
    shift_snapshot_year,
)

client = TestClient(app)


# ── pure helpers ────────────────────────────────────────────────────────────────
def test_generate_snapshots_hourly() -> None:
    snaps = generate_snapshots("2030-01-01", "2030-01-01 02:00", 1.0)
    assert snaps == ["2030-01-01 00:00", "2030-01-01 01:00", "2030-01-01 02:00"]


def test_generate_snapshots_step() -> None:
    snaps = generate_snapshots("2030-01-01", "2030-01-01 06:00", 3.0)
    assert snaps == ["2030-01-01 00:00", "2030-01-01 03:00", "2030-01-01 06:00"]


def test_retarget_rows_tile_pad_truncate() -> None:
    src = [{"snapshot": "s0", "L": 1.0}, {"snapshot": "s1", "L": 2.0}]
    new = ["a", "b", "c", "d"]
    tiled = retarget_rows(src, "snapshot", new, fill="tile")
    assert [r["snapshot"] for r in tiled] == new
    assert [r["L"] for r in tiled] == [1.0, 2.0, 1.0, 2.0]        # cycles the source
    padded = retarget_rows(src, "snapshot", new, fill="pad")
    assert [r["L"] for r in padded] == [1.0, 2.0, 2.0, 2.0]       # repeats the last
    assert [r["L"] for r in retarget_rows(src, "snapshot", ["x"], "tile")] == [1.0]  # truncates


# ── HTTP end-to-end ─────────────────────────────────────────────────────────────
@pytest.fixture()
def _session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    return tmp_path


def _load() -> None:
    snaps = ["2019-06-01T00:00:00", "2019-06-01T01:00:00"]
    model = {
        "buses": [{"name": "b"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b"}],
        "loads-p_set": [{"snapshot": snaps[0], "L": 10.0}, {"snapshot": snaps[1], "L": 20.0}],
    }
    r = client.post("/api/session/model", json={"sessionId": "default", "model": model, "filename": "c.xlsx", "scenarioName": "ref"})
    assert r.status_code == 200, r.text


def test_retarget_endpoint_reindexes_series_and_snapshots(_session_dir: Path) -> None:
    _load()
    # retarget the 2-hour 2019 window to a 4-hour 2025 window (tile the source).
    resp = client.post("/api/session/snapshots/retarget", json={
        "sessionId": "default", "start": "2025-01-01", "end": "2025-01-01 03:00", "stepHours": 1.0, "fill": "tile",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["snapshots"] == 4
    assert "loads-p_set" in body["retargeted"]

    snaps = client.get("/api/session/sheet/snapshots", params={"limit": 100}).json()["rows"]
    assert [s["snapshot"] for s in snaps] == [
        "2025-01-01 00:00", "2025-01-01 01:00", "2025-01-01 02:00", "2025-01-01 03:00",
    ]
    pset = client.get("/api/session/sheet/loads-p_set", params={"limit": 100}).json()["rows"]
    assert [r["snapshot"] for r in pset] == [s["snapshot"] for s in snaps]
    assert [r["L"] for r in pset] == [10.0, 20.0, 10.0, 20.0]  # tiled onto the longer window


def test_retarget_bad_window_is_400(_session_dir: Path) -> None:
    _load()
    assert client.post("/api/session/snapshots/retarget", json={
        "sessionId": "default", "start": "not-a-date", "end": "also-bad",
    }).status_code == 400


# ── T1(b) multi-year forecast ─────────────────────────────────────────────────
def test_shift_snapshot_year_and_growth_factor() -> None:
    assert shift_snapshot_year("2022-06-01 00:00", 8) == "2030-06-01 00:00"
    assert shift_snapshot_year("2020-02-29 00:00", 1) == "2021-02-28 00:00"  # leap fallback
    assert growth_factor(2.0, 8, "cagr") == pytest.approx(1.02 ** 8)
    assert growth_factor(2.0, 8, "linear") == pytest.approx(1.0 + 0.02 * 8)


def _load_with_availability() -> None:
    snaps = ["2019-06-01T00:00:00", "2019-06-01T01:00:00"]
    model = {
        "buses": [{"name": "b"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b"}],
        "loads-p_set": [{"snapshot": snaps[0], "L": 100.0}, {"snapshot": snaps[1], "L": 200.0}],
        "generators": [{"name": "pv", "bus": "b", "carrier": "solar"}],
        "generators-p_max_pu": [{"snapshot": snaps[0], "pv": 0.5}, {"snapshot": snaps[1], "pv": 0.8}],
    }
    r = client.post("/api/session/model", json={"sessionId": "default", "model": model, "filename": "c.xlsx", "scenarioName": "ref"})
    assert r.status_code == 200, r.text


def test_forecast_grows_demand_redates_all_leaves_availability(_session_dir: Path) -> None:
    _load_with_availability()
    resp = client.post("/api/session/snapshots/forecast", json={
        "sessionId": "default", "fromYear": 2019, "toYear": 2029, "growthPct": 2.0, "method": "cagr",
    })
    assert resp.status_code == 200, resp.text
    f = 1.02 ** 10
    # demand grown + re-dated to 2029
    pset = client.get("/api/session/sheet/loads-p_set", params={"limit": 100}).json()["rows"]
    assert pset[0]["snapshot"].startswith("2029-06-01")
    assert pset[0]["L"] == pytest.approx(100.0 * f) and pset[1]["L"] == pytest.approx(200.0 * f)
    # availability re-dated but NOT grown
    pmax = client.get("/api/session/sheet/generators-p_max_pu", params={"limit": 100}).json()["rows"]
    assert pmax[0]["snapshot"].startswith("2029-06-01")
    assert pmax[0]["pv"] == pytest.approx(0.5) and pmax[1]["pv"] == pytest.approx(0.8)
