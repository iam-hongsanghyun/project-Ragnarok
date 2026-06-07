"""Tests for the server-side run store (backend/app/run_store.py).

Exercises the full lifecycle — store → list → get → xlsx → delete — against a
temporary RUNS_DIR so nothing is written into the real backend/data/runs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app import run_store


@pytest.fixture()
def _runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point RUNS_DIR at a throwaway directory for the duration of a test."""
    target = tmp_path / "runs"
    monkeypatch.setattr(run_store, "RUNS_DIR", target)
    return target


def _sample_result() -> dict:
    return {
        "summary": [
            {"label": "Total cost", "value": "1000"},
            {"label": "Generation", "value": "500"},
            {"label": "Capacity", "value": "200"},
            {"label": "Avg price", "value": "42"},
            {"label": "Emissions", "value": "7"},
        ],
        "runMeta": {"componentCounts": {"generators": 3, "buses": 2}},
        "outputs": {
            "static": {
                "generators": {
                    "wind": {"p_nom_opt": 100.0},
                    "gas": {"p_nom_opt": 50.0},
                },
            },
            "series": {
                "generators-p": [
                    {"snapshot": "2025-01-01T00:00:00", "wind": 10.0, "gas": 5.0},
                    {"snapshot": "2025-01-01T01:00:00", "wind": 12.0, "gas": 3.0},
                ],
            },
        },
    }


def test_run_store_lifecycle(_runs_dir: Path) -> None:
    model = {"buses": [{"name": "n1"}, {"name": "n2"}], "generators": [{"name": "wind"}]}
    scenario = {"label": "Test scenario"}
    options = {
        "snapshotStart": 0,
        "snapshotEnd": 24,
        "snapshotWeight": 1,
        "runLabel": "My Run",
        "filename": "case.xlsx",
    }
    result = _sample_result()

    meta = run_store.store_run(model, scenario, options, result)
    assert meta is not None
    assert meta["name"]
    assert meta["label"] == "My Run"
    assert meta["componentCounts"] == {"generators": 3, "buses": 2}
    assert len(meta["kpis"]) == 4
    assert meta["sizeBytes"] > 0

    name = meta["name"]

    listed = run_store.list_runs()
    assert len(listed) == 1
    assert listed[0]["name"] == name

    bundle = run_store.get_run(name)
    assert bundle is not None
    assert bundle["model"] == model
    assert bundle["scenario"] == scenario
    assert bundle["result"]["summary"] == result["summary"]
    assert bundle["snapshotStart"] == 0
    assert bundle["snapshotEnd"] == 24

    xlsx_bytes = run_store.run_to_xlsx(name)
    assert xlsx_bytes is not None
    assert len(xlsx_bytes) > 0
    # xlsx files are zip archives — they start with the PK signature.
    assert xlsx_bytes[:2] == b"PK"

    assert run_store.delete_run(name) is True
    assert run_store.get_run(name) is None
    assert run_store.list_runs() == []


def test_get_run_rejects_unsafe_names(_runs_dir: Path) -> None:
    assert run_store.get_run("../secret") is None
    assert run_store.get_run("foo/bar") is None
    assert run_store.get_run("") is None
    assert run_store.run_to_xlsx("../etc/passwd") is None
    assert run_store.delete_run("../x") is False


def test_list_runs_tolerates_corrupt_meta(_runs_dir: Path) -> None:
    _runs_dir.mkdir(parents=True, exist_ok=True)
    (_runs_dir / "broken.meta.json").write_text("{ not json", encoding="utf-8")
    # A corrupt sidecar is skipped, not fatal.
    assert run_store.list_runs() == []


def test_get_run_missing_returns_none(_runs_dir: Path) -> None:
    assert run_store.get_run("2025-01-01T00-00-00") is None
