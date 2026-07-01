"""End-to-end tests for ``POST /api/session/series/{name}/transform`` (T1).

Exercises the full HTTP path: router → model_store facade → the default (SQLite)
store → :func:`timeseries.transform_rows`, then reads the sheet back to confirm
the stored series was rewritten.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import session_store
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def _session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the session store dir (both backends key off this) to a temp dir."""
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    return tmp_path


def _load(series_rows: list[dict]) -> None:
    model = {
        "buses": [{"name": "b"}],
        "snapshots": [{"snapshot": r["snapshot"]} for r in series_rows],
        "loads": [{"name": "L", "bus": "b"}],
        "loads-p_set": series_rows,
    }
    resp = client.post(
        "/api/session/model",
        json={"sessionId": "default", "model": model, "filename": "c.xlsx", "scenarioName": "ref"},
    )
    assert resp.status_code == 200, resp.text


def _values() -> list[float]:
    page = client.get("/api/session/sheet/loads-p_set", params={"limit": 100}).json()
    return [r["L"] for r in page["rows"]]


def test_scale_endpoint_rewrites_series(_session_dir: Path) -> None:
    _load([
        {"snapshot": "2030-01-01T00:00:00", "L": 10.0},
        {"snapshot": "2030-01-01T01:00:00", "L": 20.0},
    ])
    resp = client.post(
        "/api/session/series/loads-p_set/transform",
        json={"sessionId": "default", "op": "scale", "factor": 2.0},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "series"
    assert _values() == [20.0, 40.0]


def test_shift_wrap_endpoint(_session_dir: Path) -> None:
    _load([
        {"snapshot": "2030-01-01T00:00:00", "L": 1.0},
        {"snapshot": "2030-01-01T01:00:00", "L": 2.0},
        {"snapshot": "2030-01-01T02:00:00", "L": 3.0},
    ])
    resp = client.post(
        "/api/session/series/loads-p_set/transform",
        json={"sessionId": "default", "op": "shift", "shift": 1, "wrap": True},
    )
    assert resp.status_code == 200, resp.text
    assert _values() == [3.0, 1.0, 2.0]


def test_bad_op_is_400(_session_dir: Path) -> None:
    _load([{"snapshot": "2030-01-01T00:00:00", "L": 5.0}])
    resp = client.post(
        "/api/session/series/loads-p_set/transform",
        json={"sessionId": "default", "op": "nonsense"},
    )
    assert resp.status_code == 400


def test_static_or_missing_sheet_is_404(_session_dir: Path) -> None:
    _load([{"snapshot": "2030-01-01T00:00:00", "L": 5.0}])
    # 'buses' is a static sheet → not transformable.
    assert client.post(
        "/api/session/series/buses/transform",
        json={"sessionId": "default", "op": "scale", "factor": 2.0},
    ).status_code == 404
    assert client.post(
        "/api/session/series/no_such_sheet/transform",
        json={"sessionId": "default", "op": "scale", "factor": 2.0},
    ).status_code == 404
