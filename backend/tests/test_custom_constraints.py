"""Pin custom-constraint application, including rolling-horizon window scoping.

Regression: ``carrier_max_cf`` (and absolute MWh caps) used full-horizon hours
inside every rolling-horizon window, so each window's RHS was N× too large and
the cap never bound. The fix scopes weights/hours to the window passed into
``extra_functionality`` and apportions absolute budgets by the window's share.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network.custom_constraints import apply_custom_constraints

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
OPTIONS = {"snapshotStart": 0, "snapshotCount": 6, "snapshotWeight": 1.0}


def _flat_model(n_snaps: int = 6) -> dict[str, list[dict[str, Any]]]:
    """1 bus, flat 100 MW load; cheap gas (200 MW) + expensive backup (200 MW).

    Unconstrained, gas covers all load at 50% CF. A 30% CF cap forces backup on.
    """
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(n_snaps)]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}, {"name": "backup"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
        "generators": [
            {"name": "G_gas", "bus": "b", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 10.0},
            {"name": "G_backup", "bus": "b", "carrier": "backup", "p_nom": 200.0, "marginal_cost": 100.0},
        ],
    }


def _gas_cf(network) -> float:
    energy = float(network.generators_t.p["G_gas"].sum())
    cap = float(network.generators.at["G_gas", "p_nom"])
    hours = float(network.snapshot_weightings["generators"].sum())
    return energy / (cap * hours)


def _ef(constraints):
    """Mirror results.extra_functionality: apply the constraints to each window."""
    notes: list[str] = []

    def extra_functionality(net, snapshots):
        apply_custom_constraints(net, constraints, {}, notes, snapshots)

    return extra_functionality


def test_carrier_max_cf_single_shot_binds():
    n, _ = build_network(_flat_model(), SCENARIO, OPTIONS)
    cons = [{"enabled": True, "metric": "carrier_max_cf", "carrier": "gas", "value": 30.0, "label": "g"}]
    n.optimize(solver_name="highs", extra_functionality=_ef(cons))
    assert _gas_cf(n) == pytest.approx(0.30, abs=1e-3)


def test_carrier_max_cf_rolling_horizon_uses_window_hours():
    """Regression: cap must bind per window using window hours, not the full run."""
    n, _ = build_network(_flat_model(), SCENARIO, OPTIONS)
    cons = [{"enabled": True, "metric": "carrier_max_cf", "carrier": "gas", "value": 30.0, "label": "g"}]
    n.optimize.optimize_with_rolling_horizon(
        horizon=3, overlap=0, solver_name="highs", extra_functionality=_ef(cons)
    )
    # Before the fix this came back at 50% (RHS used 6 h instead of 3 h/window).
    assert _gas_cf(n) <= 0.301


def test_carrier_max_gen_budget_apportioned_across_windows():
    """A whole-run MWh cap is apportioned per window so the horizon total holds."""
    n, _ = build_network(_flat_model(), SCENARIO, OPTIONS)
    # Unconstrained gas would generate 600 MWh over the 6 h; cap the run at 300.
    cons = [{"enabled": True, "metric": "carrier_max_gen", "carrier": "gas", "value": 300.0, "label": "g"}]
    n.optimize.optimize_with_rolling_horizon(
        horizon=3, overlap=0, solver_name="highs", extra_functionality=_ef(cons)
    )
    assert float(n.generators_t.p["G_gas"].sum()) <= 300.0 + 1e-6
