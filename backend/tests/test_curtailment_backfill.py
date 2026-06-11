"""Tests for the curtailment backfill on stored runs (run_store).

Runs saved before ``curtailmentSeries`` / ``generatorEnergy[].curtailmentMwh``
existed must get them derived on read from data already in the run db:
``generatorDispatchSeries`` (per-snapshot dispatch), the input
``generators-p_max_pu`` sheet (index-aligned with solved snapshots), and
``p_nom_opt`` from static outputs.

    curtailment_g(t) = max(p_max_pu_g(t) * p_nom_g - p_g(t), 0)   [MW]
    MWh = sum_t curtailment * snapshot_weight
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app import run_store


@pytest.fixture()
def _runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "runs"
    monkeypatch.setattr(run_store, "RUNS_DIR", target)
    return target


def _legacy_bundle() -> dict:
    """A bundle shaped like a run stored before the curtailment fields existed.

    Wind: 100 MW, p_max_pu 0.5 / 1.0, dispatched 30 / 100 → curtailed 20 / 0 MW.
    Gas: static p_max_pu (not in the series sheet) → never curtailed.
    """
    model = {
        "generators": [
            {"name": "wind", "carrier": "Wind", "p_nom": 100.0},
            {"name": "gas", "carrier": "Gas", "p_nom": 100.0},
        ],
        "generators-p_max_pu": [
            {"snapshot": "2025-01-01T00:00:00", "wind": 0.5},
            {"snapshot": "2025-01-01T01:00:00", "wind": 1.0},
        ],
    }
    result = {
        "summary": [{"label": "Total cost", "value": "1"}],
        "runMeta": {"componentCounts": {"generators": 2}},
        "generatorEnergy": [
            {"name": "wind", "value": 130.0, "carrier": "Wind"},
            {"name": "gas", "value": 100.0, "carrier": "Gas"},
        ],
        "generatorDispatchSeries": [
            {"label": "00:00", "timestamp": "2025-01-01T00:00:00", "period": None,
             "values": {"wind": 30.0, "gas": 70.0}},
            {"label": "01:00", "timestamp": "2025-01-01T01:00:00", "period": None,
             "values": {"wind": 100.0, "gas": 30.0}},
        ],
        "outputs": {
            "static": {"generators": {"wind": {"p_nom_opt": 100.0}, "gas": {"p_nom_opt": 100.0}}},
            "series": {},
        },
    }
    return {"model": model, "result": result, "snapshotWeight": 1.0}


def test_curtailment_fallback_math() -> None:
    series, mwh = run_store._curtailment_fallback(_legacy_bundle())
    assert [row["values"] for row in series] == [{"Wind": 20.0}, {}]
    assert mwh == {"wind": 20.0}


def test_curtailment_fallback_respects_snapshot_weight() -> None:
    bundle = _legacy_bundle()
    bundle["snapshotWeight"] = 3.0
    _series, mwh = run_store._curtailment_fallback(bundle)
    assert mwh == {"wind": 60.0}


def test_attach_curtailment_enriches_generator_energy() -> None:
    bundle = _legacy_bundle()
    light_result = dict(bundle["result"])
    assert run_store._attach_curtailment(light_result, bundle) is True
    assert [row["values"] for row in light_result["curtailmentSeries"]] == [{"Wind": 20.0}, {}]
    by_name = {e["name"]: e for e in light_result["generatorEnergy"]}
    assert by_name["wind"]["curtailmentMwh"] == 20.0
    assert by_name["gas"]["curtailmentMwh"] is None  # static availability → not curtailable


def test_attach_curtailment_is_idempotent() -> None:
    bundle = _legacy_bundle()
    light_result = dict(bundle["result"])
    assert run_store._attach_curtailment(light_result, bundle) is True
    assert run_store._attach_curtailment(light_result, bundle) is False  # already present


def test_get_run_analytics_backfills_and_persists(_runs_dir: Path) -> None:
    """A stored legacy run gains curtailment on first read; the enriched
    analytics is persisted so the second read needs no re-derivation."""
    bundle = _legacy_bundle()
    meta = run_store.store_run(
        bundle["model"], {"label": "s"}, {"snapshotWeight": 1.0, "runLabel": "legacy"},
        bundle["result"],
    )
    assert meta is not None
    name = meta["name"]

    # Simulate a legacy run: strip the curtailment fields the new solver adds.
    with run_store._connect(name) as conn:
        analytics = run_store._kv_get(conn, "analytics")
        analytics["result"].pop("curtailmentSeries", None)
        for entry in analytics["result"].get("generatorEnergy") or []:
            entry.pop("curtailmentMwh", None)
        run_store._kv_set(conn, "analytics", analytics)

    out = run_store.get_run_analytics(name)
    assert out is not None
    assert [row["values"] for row in out["result"]["curtailmentSeries"]] == [{"Wind": 20.0}, {}]

    # Persisted: the stored kv now carries the field directly.
    with run_store._connect(name) as conn:
        stored = run_store._kv_get(conn, "analytics")
    assert stored["result"].get("curtailmentSeries")


def test_storage_soc_fallback_groups_by_carrier() -> None:
    bundle = _legacy_bundle()
    bundle["model"]["storage_units"] = [
        {"name": "bat1", "carrier": "battery", "p_nom": 10.0},
        {"name": "pump1", "carrier": "phs", "p_nom": 50.0},
    ]
    bundle["result"]["outputs"]["series"]["storage_units-state_of_charge"] = [
        {"snapshot": "2025-01-01T00:00:00", "bat1": 5.0, "pump1": 100.0},
        {"snapshot": "2025-01-01T01:00:00", "bat1": 8.0, "pump1": 90.0},
    ]
    series = run_store._storage_soc_fallback(bundle)
    assert [row["values"] for row in series] == [
        {"battery": 5.0, "phs": 100.0},
        {"battery": 8.0, "phs": 90.0},
    ]


def test_attach_storage_soc_marks_no_storage_runs() -> None:
    """A no-storage run gets an empty list persisted as a 'checked' marker, so
    later reads never re-load the full bundle."""
    bundle = _legacy_bundle()
    light_result = dict(bundle["result"])
    assert run_store._attach_storage_soc(light_result, bundle) is True
    assert light_result["storageSocSeries"] == []
    assert run_store._attach_storage_soc(light_result, bundle) is False
