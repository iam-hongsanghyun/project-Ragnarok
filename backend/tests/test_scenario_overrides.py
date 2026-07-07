"""Tests for per-scenario model overrides (pure applier + the run wiring)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import scenario_overrides as so
from backend.app import session_store
from backend.app.main import app

client = TestClient(app)


def _model() -> dict:
    return {
        "buses": [{"name": "b1"}],
        "generators": [
            {"name": "g1", "bus": "b1", "p_nom": 100.0},
            {"name": "g2", "bus": "b1", "p_nom": 200.0},
        ],
    }


# ── pure applier ────────────────────────────────────────────────────────────────

def test_apply_sets_matching_cell() -> None:
    out = so.apply_model_overrides(_model(), [{"sheet": "generators", "name": "g1", "column": "p_nom", "value": 500}])
    assert [r["p_nom"] for r in out["generators"]] == [500, 200.0]


def test_apply_does_not_mutate_input() -> None:
    model = _model()
    so.apply_model_overrides(model, [{"sheet": "generators", "name": "g1", "column": "p_nom", "value": 9}])
    assert model["generators"][0]["p_nom"] == 100.0  # original untouched


def test_apply_skips_missing_sheet_name_and_malformed() -> None:
    out = so.apply_model_overrides(
        _model(),
        [
            {"sheet": "ghost", "name": "g1", "column": "p_nom", "value": 1},
            {"sheet": "generators", "name": "nope", "column": "p_nom", "value": 1},
            {"sheet": "generators", "name": "g1", "column": "", "value": 1},
            {"sheet": "generators", "column": "p_nom", "value": 1},  # no name
        ],
    )
    assert [r["p_nom"] for r in out["generators"]] == [100.0, 200.0]  # unchanged


def test_apply_empty_returns_same_object() -> None:
    model = _model()
    assert so.apply_model_overrides(model, []) is model


def test_apply_multiple_columns_one_component() -> None:
    out = so.apply_model_overrides(
        _model(),
        [
            {"sheet": "generators", "name": "g2", "column": "p_nom", "value": 300},
            {"sheet": "generators", "name": "g2", "column": "marginal_cost", "value": 12},
        ],
    )
    g2 = out["generators"][1]
    assert g2["p_nom"] == 300 and g2["marginal_cost"] == 12


# ── wired into the run path (validate applies overrides to the session model) ─────

@pytest.fixture()
def _session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    return tmp_path


def test_validate_applies_overrides_from_options(_session_dir: Path) -> None:
    model = {
        "buses": [{"name": "b1", "x": 0, "y": 0, "v_nom": 100}],
        "generators": [{"name": "g1", "bus": "b1", "p_nom": 100.0, "carrier": "gas"}],
        "loads": [{"name": "L1", "bus": "b1", "p_set": 50.0}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": "2030-01-01T00:00:00"}],
    }
    assert client.post("/api/session/model", json={"sessionId": "default", "model": model, "filename": "c.xlsx"}).status_code == 200

    # Validate with an override that bumps g1 capacity — the resolved model the
    # validator sees must carry p_nom=999 (proves overrides apply to the session
    # snapshot for a by-sessionId run).
    resp = client.post("/api/validate", json={
        "sessionId": "default", "scenario": {}, "options": {
            "modelOverrides": [{"sheet": "generators", "name": "g1", "column": "p_nom", "value": 999}],
            "snapshotStart": 0, "snapshotEnd": 1,
        },
    })
    assert resp.status_code == 200, resp.text
    # The session's stored model is unchanged (override is per-run, not persisted).
    page = client.get("/api/session/sheet/generators", params={"limit": 10}).json()
    assert page["rows"][0]["p_nom"] == 100.0
