"""Core cleanup step 4 (temporal): visible resolution, weightings from the spacing, no hidden stride.

The weighting audit (hourly model vs its exact 4-hourly aggregate) says PyPSA weights costs, energy, storage, budgets and
statistics correctly and counts SNAPSHOTS in ramps / UC times / rolling. These tests pin what Ragnarok does about it:
resolution is a transform that writes the weights (this file), the unweighted attributes are time-units (test_time_units).
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from backend.app.routers import operations_modules as ops
from backend.pypsa.model_check import check_model
from backend.pypsa.network import build_network
from backend.pypsa.network_ops import temporal_cluster
from backend.pypsa.utils.weightings import set_weightings_from_spacing, spacing_weights

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _hourly(n: int = 48, step_h: float = 1.0, weights: float | None = None) -> dict[str, Any]:
    stamps = pd.date_range("2030-01-01", periods=n, freq=pd.Timedelta(hours=step_h))
    snaps = []
    for s in stamps:
        row: dict[str, Any] = {"snapshot": s.strftime("%Y-%m-%d %H:%M:%S")}
        if weights is not None:
            row.update(objective=weights, stores=weights, generators=weights)
        snaps.append(row)
    load = [80.0 + (i % 24) * 3.0 for i in range(n)]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.2}],
        "snapshots": snaps,
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s["snapshot"], "L": v} for s, v in zip(snaps, load)],
        "generators": [{"name": "G", "bus": "b", "carrier": "gas", "p_nom": 400.0, "marginal_cost": 20.0}],
    }


# ── weightings from the spacing ──────────────────────────────────────────────────────────

def test_spacing_weights_regular_irregular_and_last_snapshot() -> None:
    assert spacing_weights(["2030-01-01 00:00", "2030-01-01 04:00", "2030-01-01 08:00"])[0] == [4.0, 4.0, 4.0]
    w, notes = spacing_weights(["2030-01-01 00:00", "2030-01-01 01:00", "2030-01-01 04:00", "2030-01-01 08:00"])
    assert w == [1.0, 3.0, 4.0, 4.0] and any("irregular" in n for n in notes)  # forward gap; the last repeats its predecessor
    w, notes = spacing_weights(["2030-01-01 00:00", "2030-01-01 00:00", "2030-01-01 02:00"])
    assert w[0] == 2.0 and any("duplicate" in n for n in notes)


def test_spacing_weights_pathway_periods_never_weight_the_jump_between_periods() -> None:
    stamps = ["2030-01-01 00:00", "2030-01-01 02:00", "2030-01-01 04:00", "2040-01-01 00:00", "2040-01-01 03:00"]
    w, _ = spacing_weights(stamps, [2030, 2030, 2030, 2040, 2040])
    assert w == [2.0, 2.0, 2.0, 3.0, 3.0]


def test_set_weightings_writes_the_three_columns_and_the_totals_follow() -> None:
    m = _hourly(12, step_h=4.0)  # 4-hourly stamps, no weights: PyPSA would book a quarter of the energy
    findings = {f["code"]: f for f in check_model(m)["findings"]}
    action = findings["weighting_spacing"]["action"]
    assert action["id"] == "set_weightings_from_spacing" and action["endpoint"].endswith("/api/model/set-weightings-from-spacing")
    out, report = set_weightings_from_spacing(m)
    assert report["changed"] == 12 and report["medianSpacingHours"] == 4.0 and report["totalHours"] == 48.0
    assert all(r[c] == 4.0 for r in out["snapshots"] for c in ("objective", "stores", "generators"))
    assert "objective" not in m["snapshots"][0]  # the input is untouched
    assert "weighting_spacing" not in {f["code"] for f in check_model(out)["findings"]}
    n, _ = build_network(out, SCENARIO, {})
    assert float(n.snapshot_weightings["objective"].sum()) == pytest.approx(48.0)


def test_set_weightings_handles_pathway_rows_and_irregular_spacing() -> None:
    m = {"snapshots": [
        {"snapshot": "2030-01-01 00:00", "period": 2030}, {"snapshot": "2030-01-01 01:00", "period": 2030},
        {"snapshot": "2030-01-01 04:00", "period": 2030}, {"snapshot": "2040-01-01 00:00", "period": 2040},
        {"snapshot": "2040-01-01 06:00", "period": 2040},
    ]}
    out, report = set_weightings_from_spacing(m)
    assert [r["objective"] for r in out["snapshots"]] == [1.0, 3.0, 3.0, 6.0, 6.0]
    assert report["notes"]
    with pytest.raises(ValueError):
        set_weightings_from_spacing({"snapshots": [{"snapshot": "now"}, {"snapshot": "later"}]})


def test_the_action_endpoint_writes_the_snapshots_sheet(monkeypatch: pytest.MonkeyPatch) -> None:
    written: dict[str, Any] = {}
    monkeypatch.setattr(ops, "_model", lambda _sid: _hourly(6, step_h=2.0))
    monkeypatch.setattr(ops.model_store, "merge_static_model", lambda sid, sheets: written.update(sheets))
    report = ops.weightings_from_spacing(ops.SessionBody())
    assert report["changed"] == 6 and all(r["generators"] == 2.0 for r in written["snapshots"])


# ── resolution is a visible transform ─────────────────────────────────────────────────

def test_resample_writes_snapshots_weightings_and_the_aggregated_series_and_the_run_totals_agree() -> None:
    """The hourly workbook at 4 h through the transform: block means, weights 4, same energy; the run uses what is written."""
    hourly = _hourly(48)
    reduced = temporal_cluster(hourly, method="resample", offset="4h")
    m = reduced["model"]
    assert len(m["snapshots"]) == 12 and all(r["objective"] == 4.0 and r["stores"] == 4.0 for r in m["snapshots"])
    first_load = m["loads-p_set"][0]["L"]
    assert first_load == pytest.approx(sum(80.0 + h * 3.0 for h in range(4)) / 4)  # the block MEAN, not the first hour
    full, _ = build_network(hourly, SCENARIO, {})
    coarse, _ = build_network(m, SCENARIO, {})
    for n in (full, coarse):
        n.optimize(solver_name="highs", include_objective_constant=False)
    # linear costs and a load that is a block mean: energy and cost are identical
    assert coarse.objective == pytest.approx(full.objective, rel=1e-9)


def test_downsample_is_pypsas_point_sampling_with_weight_equal_to_the_stride() -> None:
    reduced = temporal_cluster(_hourly(48), method="downsample", stride=4)["model"]
    assert len(reduced["snapshots"]) == 12 and reduced["snapshots"][0]["objective"] == 4.0
    assert reduced["loads-p_set"][1]["L"] == pytest.approx(80.0 + 4 * 3.0)  # the 5th hour: a point sample


def test_the_core_has_no_stride_left() -> None:
    import inspect

    import backend.pypsa.network as core

    src = inspect.getsource(core.build_network)
    assert "[::step]" not in src and "[::stride]" not in src
    from backend.pypsa import sampling

    assert not hasattr(core, "rescale_weightings") and hasattr(sampling, "apply_test_run_sampling")


# ── sampling transform (visible) ─────────────────────────────────────────────────────

def test_sample_endpoint_returns_the_workbook_with_the_written_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops, "_model", lambda _sid: _hourly(48))
    out = ops.sample_workbook(ops.SampleBody(options={"samplingConfig": {"enabled": True, "mode": "count", "blockSize": 6, "blockCount": 2}}))
    assert len(out["model"]["snapshots"]) == 12 and out["factor"] == pytest.approx(4.0)
    with pytest.raises(Exception, match="enabled"):
        ops.sample_workbook(ops.SampleBody(options={"samplingConfig": {"enabled": False}}))


def test_time_units_endpoints_round_trip_and_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, Any] = {}
    base = _hourly(6, step_h=0.25, weights=0.25)
    base["generators"][0].update(committable=True, p_min_pu=0.3)
    monkeypatch.setattr(ops, "_model", lambda _sid: {**base, **store})
    monkeypatch.setattr(ops.model_store, "merge_static_model", lambda sid, sheets: store.update(sheets))
    rows = [{"component": "generators", "name": "G", "attribute": "min_up_time", "value": 4, "unit": "hours"},
            {"component": "generators", "name": "G", "attribute": "ramp_limit_up", "value": 0.02, "unit": "per_minute"}]
    assert len(ops.time_units_set(ops.TimeUnitsSet(rows=rows))["rows"]) == 2
    assert [r["attribute"] for r in ops.time_units_get()["rows"]] == ["min_up_time", "ramp_limit_up"]
    prev = ops.time_units_preview(ops.TimeUnitsPreview())
    assert prev["stepHours"] == 0.25
    by_attr = {t["attribute"]: t for t in prev["table"]}
    assert by_attr["min_up_time"]["pypsaValue"] == 16 and by_attr["ramp_limit_up"]["pypsaValue"] == pytest.approx(0.3)
    with pytest.raises(Exception):
        ops.time_units_set(ops.TimeUnitsSet(rows=[{"component": "generators", "name": "G", "attribute": "p_nom", "value": 1, "unit": "hours"}]))
