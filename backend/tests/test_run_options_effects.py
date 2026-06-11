"""Effect-level pins for run options that were previously only wired, not tested.

Every test here asserts an OBSERVABLE consequence (window length, dispatch,
generator table, constraint binding) — not just that a key parses. Closes the
gaps found in the 2026-06 input audit: snapshot windowing (incl. the
``snapshotEnd``-only fallback), downsampling weights, ``forceLp``, load
shedding (+ VOLL default), and the raw ``customDsl`` text path.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.app.config import load_system_defaults
from backend.pypsa.network import build_network
from backend.pypsa.network.constraint_dsl import apply_dsl_constraints

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _model(n_snaps: int = 6, load_mw: float = 100.0, committable: bool = False) -> dict[str, list[dict[str, Any]]]:
    """1 bus, flat load; cheap gas + expensive backup (both 200 MW)."""
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(n_snaps)]
    gas: dict[str, Any] = {"name": "G_gas", "bus": "b", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 10.0}
    if committable:
        gas["committable"] = True
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}, {"name": "backup"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": load_mw}],
        "loads-p_set": [{"snapshot": s, "L": load_mw} for s in snaps],
        "generators": [
            gas,
            {"name": "G_backup", "bus": "b", "carrier": "backup", "p_nom": 200.0, "marginal_cost": 100.0},
        ],
    }


# ── Snapshot windowing ─────────────────────────────────────────────────────────


def test_window_start_count_limits_modeled_snapshots_and_energy() -> None:
    n, _ = build_network(_model(6), SCENARIO, {"snapshotStart": 1, "snapshotCount": 3})
    assert len(n.snapshots) == 3
    assert str(n.snapshots[0]).startswith("2030-01-01 01:00")
    n.optimize(solver_name="highs")
    assert float(n.generators_t.p.sum().sum()) == pytest.approx(300.0)  # 3 h × 100 MW


def test_snapshot_end_alone_falls_back_to_window() -> None:
    """A payload with snapshotEnd but no snapshotCount must NOT solve everything."""
    n, _ = build_network(_model(6), SCENARIO, {"snapshotStart": 2, "snapshotEnd": 5})
    assert len(n.snapshots) == 3  # rows 2,3,4 — not all 6
    assert str(n.snapshots[0]).startswith("2030-01-01 02:00")


def test_snapshot_count_wins_over_snapshot_end() -> None:
    n, _ = build_network(_model(6), SCENARIO, {"snapshotStart": 0, "snapshotCount": 2, "snapshotEnd": 6})
    assert len(n.snapshots) == 2


def test_snapshot_weight_downsamples_and_sets_weightings() -> None:
    n, _ = build_network(_model(6), SCENARIO, {"snapshotStart": 0, "snapshotCount": 6, "snapshotWeight": 2})
    assert len(n.snapshots) == 3  # every 2nd row
    assert (n.snapshot_weightings["objective"] == 2.0).all()
    n.optimize(solver_name="highs")
    # Weighted energy: 3 modeled rows × 2 h each × 100 MW = 600 MWh.
    energy = float((n.generators_t.p.sum(axis=1) * n.snapshot_weightings["objective"]).sum())
    assert energy == pytest.approx(600.0)


# ── forceLp ────────────────────────────────────────────────────────────────────


def test_force_lp_clears_committable_flags() -> None:
    options = {"snapshotStart": 0, "snapshotCount": 2}
    n_mip, _ = build_network(_model(2, committable=True), SCENARIO, options)
    assert bool(n_mip.generators.at["G_gas", "committable"]) is True  # control

    n_lp, _ = build_network(_model(2, committable=True), SCENARIO, {**options, "forceLp": True})
    assert not n_lp.generators["committable"].astype(bool).any()
    n_lp.optimize(solver_name="highs")  # solves as a plain LP
    assert float(n_lp.generators_t.p["G_gas"].sum()) == pytest.approx(200.0)


# ── Load shedding ──────────────────────────────────────────────────────────────


def test_load_shedding_serves_excess_load_at_custom_voll() -> None:
    """Load 300 > capacity 200+200? backup covers it — so use 500 to force shed."""
    options = {
        "snapshotStart": 0,
        "snapshotCount": 2,
        "enableLoadShedding": True,
        "loadSheddingCost": 1234.0,
    }
    n, _ = build_network(_model(2, load_mw=500.0), SCENARIO, options)
    assert "load_shedding_b" in n.generators.index
    assert float(n.generators.at["load_shedding_b", "marginal_cost"]) == pytest.approx(1234.0)
    n.optimize(solver_name="highs")
    shed = float(n.generators_t.p["load_shedding_b"].sum())
    assert shed == pytest.approx(200.0)  # (500 − 400) MW × 2 h


def test_load_shedding_cost_defaults_from_system_defaults() -> None:
    default_voll = float(load_system_defaults()["load_shedding"]["marginal_cost"])
    options = {"snapshotStart": 0, "snapshotCount": 2, "enableLoadShedding": True}
    n, _ = build_network(_model(2), SCENARIO, options)
    assert float(n.generators.at["load_shedding_b", "marginal_cost"]) == pytest.approx(default_voll)


def test_load_shedding_disabled_adds_no_generators() -> None:
    n, _ = build_network(_model(2), SCENARIO, {"snapshotStart": 0, "snapshotCount": 2})
    assert not [g for g in n.generators.index if str(g).startswith("load_shedding_")]


# ── Raw customDsl text path ────────────────────────────────────────────────────


def test_custom_dsl_text_binds_dispatch_end_to_end() -> None:
    """The free-text DSL path (scenario.customDsl fallback) must actually bind."""
    n, _ = build_network(_model(4), SCENARIO, {"snapshotStart": 0, "snapshotCount": 4})
    notes: list[str] = []

    def ef(net, snapshots):
        apply_dsl_constraints(net, 'gen("gas") <= 150\n# comment line\n', {}, notes, snapshots)

    n.optimize(solver_name="highs", extra_functionality=ef)
    gas = float(n.generators_t.p["G_gas"].sum())
    backup = float(n.generators_t.p["G_backup"].sum())
    assert gas == pytest.approx(150.0, rel=1e-6)  # cap binds (unconstrained: 400)
    assert backup == pytest.approx(250.0, rel=1e-6)


def test_custom_dsl_bad_line_is_skipped_with_note_and_good_line_applies() -> None:
    n, _ = build_network(_model(2), SCENARIO, {"snapshotStart": 0, "snapshotCount": 2})
    notes: list[str] = []

    def ef(net, snapshots):
        apply_dsl_constraints(net, 'gen("gas") < 150\ngen("gas") <= 120\n', {}, notes, snapshots)

    n.optimize(solver_name="highs", extra_functionality=ef)
    assert any("skip" in note.lower() or "line" in note.lower() for note in notes)  # bad line surfaced
    assert float(n.generators_t.p["G_gas"].sum()) == pytest.approx(120.0, rel=1e-6)
