"""Tests for the History import split (H1 / H2).

H1 — "Import Project" is *opening a file*: ``POST /api/import/project/load``
returns the parsed bundle and creates NO History entry.
H2 — "Import result" is *persisting an external result*:
``POST /api/import/result/xlsx`` writes a History entry tagged
``origin="xlsx_import"``.

Everything runs against a throwaway RUNS_DIR so nothing touches the real
backend/data/runs.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import project_workbook as pw
from backend.app import run_store
from backend.app.main import app


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture()
def _runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point RUNS_DIR at a throwaway directory for the duration of a test."""
    target = tmp_path / "runs"
    monkeypatch.setattr(run_store, "RUNS_DIR", target)
    return target


def _sample_bundle() -> dict[str, Any]:
    return {
        "model": {
            "buses": [{"name": "n1", "v_nom": 380.0}, {"name": "n2", "v_nom": 380.0}],
            "generators": [
                {"name": "wind", "bus": "n1", "p_nom": 100.0, "carrier": "wind"},
                {"name": "gas", "bus": "n2", "p_nom": 50.0, "carrier": "gas", "marginal_cost": 40.0},
            ],
            "loads": [{"name": "load1", "bus": "n1", "p_set": 80.0}],
        },
        "scenario": {
            "carbonPrice": 50.0,
            "constraints": [{"id": "c1", "enabled": True, "metric": "co2_cap", "value": 1000.0}],
        },
        "options": {"snapshotStart": 0, "snapshotEnd": 2, "snapshotWeight": 1, "filename": "demo.xlsx"},
        "result": {
            "outputs": {
                "static": {"generators": {"wind": {"p_nom_opt": 120.0}, "gas": {"p_nom_opt": 50.0}}},
                "series": {
                    "generators-p": [
                        {"snapshot": "2025-01-01T00:00:00", "wind": 80.0, "gas": 10.0},
                        {"snapshot": "2025-01-01T01:00:00", "wind": 60.0, "gas": 30.0},
                    ],
                },
            },
            "runMeta": {"componentCounts": {"generators": 2, "buses": 2}},
            "summary": [{"label": "Total cost", "value": "$1,234"}],
            "carrierMix": [{"carrier": "wind", "value": 140.0}],
        },
    }


# ── store_run origin tagging ────────────────────────────────────────────────


def test_store_run_default_origin_is_solve(_runs_dir: Path) -> None:
    meta = run_store.store_run({"buses": [{"name": "n1"}]}, {}, {}, {})
    assert meta is not None
    assert meta["origin"] == "solve"


def test_store_run_records_explicit_origin(_runs_dir: Path) -> None:
    meta = run_store.store_run(
        {"buses": [{"name": "n1"}]}, {}, {"filename": "external.xlsx"}, {}, origin="xlsx_import"
    )
    assert meta is not None
    assert meta["origin"] == "xlsx_import"
    # The tag also survives a fresh listing (it's persisted in the meta sidecar).
    listed = {m["name"]: m for m in run_store.list_runs()}
    assert listed[meta["name"]]["origin"] == "xlsx_import"


# ── H1: project load does NOT touch History ─────────────────────────────────


def test_import_project_load_returns_bundle_without_storing(_runs_dir: Path) -> None:
    client = TestClient(app)
    data = pw.bundle_to_workbook(_sample_bundle(), include_bundle=True)
    files = {"file": ("demo.xlsx", io.BytesIO(data), _XLSX_MIME)}

    resp = client.post("/api/import/project/load", files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The bundle round-trips back to the editor …
    assert {row["name"] for row in body["model"]["generators"]} == {"wind", "gas"}
    assert body["result"]["outputs"]["static"]["generators"]["wind"]["p_nom_opt"] == 120.0
    assert body["scenario"]["carbonPrice"] == 50.0
    assert body["filename"] == "demo.xlsx"

    # … but NOTHING is persisted: History is still empty.
    assert run_store.list_runs() == []


# ── H2: external result import persists with the imported origin ────────────


def test_import_result_xlsx_persists_history_entry(_runs_dir: Path) -> None:
    client = TestClient(app)
    # A *reconstructed* workbook (no embedded bundle) is the real external case:
    # readable sheets only, mapped to the canonical result schema on import.
    data = pw.bundle_to_workbook(_sample_bundle(), include_bundle=False)
    files = {"file": ("third_party_result.xlsx", io.BytesIO(data), _XLSX_MIME)}

    resp = client.post("/api/import/result/xlsx", files=files)
    assert resp.status_code == 200, resp.text
    name = resp.json()["name"]
    assert name

    runs = run_store.list_runs()
    assert len(runs) == 1
    stored = runs[0]
    assert stored["name"] == name
    assert stored["origin"] == "xlsx_import"
    assert stored["filename"] == "third_party_result.xlsx"

    # The solved outputs survived the mapping (component output columns split
    # back out into outputs.static).
    bundle = run_store.get_run(name)
    assert bundle is not None
    assert bundle["result"]["outputs"]["static"]["generators"]["wind"]["p_nom_opt"] == 120.0


def test_import_result_xlsx_rejects_non_excel(_runs_dir: Path) -> None:
    client = TestClient(app)
    files = {"file": ("notes.txt", io.BytesIO(b"not a workbook"), "text/plain")}
    resp = client.post("/api/import/result/xlsx", files=files)
    assert resp.status_code == 400
    assert run_store.list_runs() == []
