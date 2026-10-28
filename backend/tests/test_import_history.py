"""Tests for the History import split (H1 / H2).

H1 — "Import Project" is *opening a file*: ``POST /api/import/project/load``
returns the model side to the editor. P28: a file that carries SOLVED RESULTS is also
stored as a run (``runName``), so the browser reads every result from the run routes
and never derives a metric; an inputs-only file still creates no History entry.
H2 — "Import result" is *persisting an external result*:
``POST /api/import/result`` writes a History entry tagged
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


# ── H1: project load returns the model; its results become a stored run (P28) ──


def test_import_project_load_stores_results_as_a_run(_runs_dir: Path) -> None:
    # Re-baselined for P28: this used to assert that History stays empty (the results rode
    # back to the browser, which re-derived them). The results are now stored as a run and the
    # response names it; `result` is empty because the browser reads the run, not the upload.
    client = TestClient(app)
    data = pw.bundle_to_workbook(_sample_bundle(), include_bundle=True)
    files = {"file": ("demo.xlsx", io.BytesIO(data), _XLSX_MIME)}

    resp = client.post("/api/import/project/load", files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The model side still round-trips back to the editor ...
    assert {row["name"] for row in body["model"]["generators"]} == {"wind", "gas"}
    assert body["scenario"]["carbonPrice"] == 50.0
    assert body["filename"] == "demo.xlsx"

    # ... and the solved results are a stored run, with the outputs intact.
    assert body["result"] == {}
    runs = run_store.list_runs()
    assert [m["name"] for m in runs] == [body["runName"]]
    assert runs[0]["origin"] == "xlsx_import"
    bundle = run_store.get_run(body["runName"])
    assert bundle is not None
    assert bundle["result"]["outputs"]["static"]["generators"]["wind"]["p_nom_opt"] == 120.0


def test_import_project_load_without_results_stores_nothing(_runs_dir: Path) -> None:
    client = TestClient(app)
    bundle = _sample_bundle()
    bundle["result"] = {}
    data = pw.bundle_to_workbook(bundle, include_bundle=True)
    files = {"file": ("inputs.xlsx", io.BytesIO(data), _XLSX_MIME)}

    resp = client.post("/api/import/project/load", files=files)
    assert resp.status_code == 200, resp.text
    assert resp.json()["runName"] is None
    assert run_store.list_runs() == []


# ── H2: external result import persists with the imported origin ────────────


def test_import_result_xlsx_persists_history_entry(_runs_dir: Path) -> None:
    client = TestClient(app)
    # A *reconstructed* workbook (no embedded bundle) is the real external case:
    # readable sheets only, mapped to the canonical result schema on import.
    data = pw.bundle_to_workbook(_sample_bundle(), include_bundle=False)
    files = {"file": ("third_party_result.xlsx", io.BytesIO(data), _XLSX_MIME)}

    resp = client.post("/api/import/result", files=files)
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


def test_import_result_zip_preserves_model_and_results(_runs_dir: Path) -> None:
    """A project .zip imports into History with BOTH model and results — the
    embedded bundle's derived analytics round-trip verbatim (not re-derived)."""
    client = TestClient(app)
    pkg = pw.bundle_to_package(
        _sample_bundle(), "north-sea", meta={"name": "north-sea", "label": "North Sea", "kpis": []}
    )
    files = {"file": ("north-sea.zip", io.BytesIO(pkg), "application/zip")}

    resp = client.post("/api/import/result", files=files)
    assert resp.status_code == 200, resp.text
    name = resp.json()["name"]

    stored = {m["name"]: m for m in run_store.list_runs()}[name]
    assert stored["origin"] == "xlsx_import"
    # Results preserved verbatim from the embedded bundle (summary kept as-is).
    assert any(s.get("label") == "Total cost" for s in (stored.get("summary") or []))
    # Model round-tripped too.
    bundle = run_store.get_run(name)
    assert bundle is not None
    assert {row["name"] for row in bundle["model"]["generators"]} == {"wind", "gas"}
    assert bundle["result"]["outputs"]["static"]["generators"]["wind"]["p_nom_opt"] == 120.0


def test_import_result_rejects_unsupported_file(_runs_dir: Path) -> None:
    client = TestClient(app)
    files = {"file": ("notes.txt", io.BytesIO(b"not a workbook"), "text/plain")}
    resp = client.post("/api/import/result", files=files)
    assert resp.status_code == 400
    assert run_store.list_runs() == []


# ── Server-side analytics derivation from stored outputs ────────────────────


def _result_only_bundle() -> dict[str, Any]:
    """A complete two-snapshot result with the frames the derivation needs:
    snapshots, a carrier mapping, generator dispatch, and nodal prices."""
    return {
        "model": {
            "snapshots": [
                {"snapshot": "2025-01-01T00:00:00"},
                {"snapshot": "2025-01-01T01:00:00"},
            ],
            "carriers": [
                {"name": "wind", "co2_emissions": 0.0},
                {"name": "gas", "co2_emissions": 0.4},
            ],
            "buses": [{"name": "n1", "v_nom": 380.0}],
            "generators": [
                {"name": "wind", "bus": "n1", "carrier": "wind", "p_nom": 100.0, "marginal_cost": 0.0},
                {"name": "gas", "bus": "n1", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 50.0},
            ],
            "loads": [{"name": "L", "bus": "n1", "p_set": 120.0}],
        },
        "scenario": {},
        "options": {"snapshotStart": 0, "snapshotEnd": 2, "snapshotWeight": 1, "filename": "ext.xlsx"},
        "result": {
            "outputs": {
                "static": {"generators": {"wind": {"p_nom_opt": 100.0}, "gas": {"p_nom_opt": 100.0}}},
                "series": {
                    "generators-p": [
                        {"snapshot": "2025-01-01T00:00:00", "wind": 80.0, "gas": 40.0},
                        {"snapshot": "2025-01-01T01:00:00", "wind": 60.0, "gas": 60.0},
                    ],
                    "buses-marginal_price": [
                        {"snapshot": "2025-01-01T00:00:00", "n1": 50.0},
                        {"snapshot": "2025-01-01T01:00:00", "n1": 50.0},
                    ],
                },
            },
        },
    }


def test_derive_imported_result_populates_analytics() -> None:
    """The derivation rebuilds the network, injects the stored outputs, and
    produces the analytics the Result view renders — with the right numbers."""
    from backend.pypsa.results.from_outputs import derive_imported_result

    b = _result_only_bundle()
    derived = derive_imported_result(b["model"], b["scenario"], b["options"], b["result"]["outputs"])

    mix = {m["label"]: m["value"] for m in derived["carrierMix"]}
    # Wind energy = 80 + 60 = 140 MWh; gas = 40 + 60 = 100 MWh (weight 1).
    assert mix["wind"] == 140.0
    assert mix["gas"] == 100.0
    # Series span both snapshots; price series carries the injected 50/MWh.
    assert len(derived["dispatchSeries"]) == 2
    assert len(derived["systemPriceSeries"]) == 2
    assert derived["systemPriceSeries"][0]["value"] == 50.0
    # A non-empty summary makes the run render like a solved one in History.
    # Capacity is reported split into generator + storage installed nameplate.
    assert any(s["label"] == "Generator capacity" for s in derived["summary"])
    assert derived["runMeta"]["componentCounts"]["generators"] == 2


def test_import_result_xlsx_stores_derived_analytics(_runs_dir: Path) -> None:
    """End to end: importing a results workbook persists the derived summary +
    carrier mix into the History meta (not just the raw outputs)."""
    client = TestClient(app)
    data = pw.bundle_to_workbook(_result_only_bundle(), include_bundle=False)
    files = {"file": ("ext.xlsx", io.BytesIO(data), _XLSX_MIME)}

    resp = client.post("/api/import/result", files=files)
    assert resp.status_code == 200, resp.text

    meta = run_store.list_runs()[0]
    assert meta["origin"] == "xlsx_import"
    assert len(meta["summary"]) > 0
    assert len(meta["carrierMix"]) == 2
    assert meta["componentCounts"]["generators"] == 2


def test_importing_the_same_file_twice_returns_the_existing_run(_runs_dir: Path) -> None:
    """The same bytes (content hash) never create a second run, on either import route."""
    client = TestClient(app)
    data = pw.bundle_to_workbook(_sample_bundle(), include_bundle=True)

    def upload(route: str, filename: str = "demo.xlsx") -> dict[str, Any]:
        resp = client.post(route, files={"file": (filename, io.BytesIO(data), _XLSX_MIME)})
        assert resp.status_code == 200, resp.text
        return resp.json()

    first = upload("/api/import/result")["name"]
    assert upload("/api/import/result")["name"] == first
    assert upload("/api/import/result", "renamed.xlsx")["name"] == first  # content, not file name
    assert upload("/api/import/project/load")["runName"] == first
    assert [m["name"] for m in run_store.list_runs()] == [first]
    assert run_store.list_runs()[0]["contentHash"]

    # A different file is a different run; deleting the run lets the same file import again.
    other = pw.bundle_to_workbook({**_sample_bundle(), "scenario": {"carbonPrice": 99.0}}, include_bundle=True)
    resp = client.post("/api/import/result", files={"file": ("other.xlsx", io.BytesIO(other), _XLSX_MIME)})
    assert resp.json()["name"] != first
    assert run_store.delete_run(first)
    upload("/api/import/result")
    assert len(run_store.list_runs()) == 2  # re-imported as a new run (the name may repeat within a second)
