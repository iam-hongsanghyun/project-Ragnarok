"""End-to-end tests for ``GET /api/session/sheet/{name}/distinct``.

The endpoint backs Ragnarok's on-demand unique-value pickers (Forge targets,
grid column filters, plugin option dispatch). It runs against the default
(legacy) store here, exercising :func:`model_store.distinct_values`' row-scan
fallback; SQLite-native ``SELECT DISTINCT`` parity is covered separately in
``test_sqlite_store.py``.
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
    """Point the (legacy) store at a temp dir so nothing touches real session data."""
    target = tmp_path / "session"
    monkeypatch.setattr(session_store, "SESSION_DIR", target)
    return target


def _load_model() -> None:
    model = {
        "buses": [{"name": "B1"}, {"name": "B2"}],
        "generators": [
            {"name": "g1", "carrier": "wind", "province": "Seoul"},
            {"name": "g2", "carrier": "gas", "province": "Busan"},
            {"name": "g3", "carrier": "wind", "province": "Seoul"},
            {"name": "g4", "carrier": "", "province": None},  # blank/None dropped
        ],
        "snapshots": [{"snapshot": "2030-01-01T00:00:00"}],
    }
    resp = client.post(
        "/api/session/model",
        json={"sessionId": "default", "model": model, "filename": "case.xlsx", "scenarioName": "ref"},
    )
    assert resp.status_code == 200, resp.text


def test_distinct_returns_sorted_unique_values(_session_dir: Path) -> None:
    _load_model()
    resp = client.get("/api/session/sheet/generators/distinct", params={"column": "carrier"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sheet"] == "generators"
    assert body["column"] == "carrier"
    # de-duplicated, blank/None dropped, sorted
    assert body["values"] == ["gas", "wind"]


def test_distinct_drops_blank_and_none(_session_dir: Path) -> None:
    _load_model()
    resp = client.get("/api/session/sheet/generators/distinct", params={"column": "province"})
    assert resp.status_code == 200
    assert resp.json()["values"] == ["Busan", "Seoul"]


def test_distinct_unknown_column_is_empty(_session_dir: Path) -> None:
    _load_model()
    resp = client.get("/api/session/sheet/generators/distinct", params={"column": "nope"})
    assert resp.status_code == 200
    assert resp.json()["values"] == []


def test_distinct_unknown_sheet_is_404(_session_dir: Path) -> None:
    _load_model()
    resp = client.get("/api/session/sheet/no_such_sheet/distinct", params={"column": "carrier"})
    assert resp.status_code == 404


def test_distinct_requires_column_param(_session_dir: Path) -> None:
    _load_model()
    resp = client.get("/api/session/sheet/generators/distinct")
    assert resp.status_code == 422  # missing required query param
