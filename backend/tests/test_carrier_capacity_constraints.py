"""Carrier total-capacity (MW) and capacity-share (%) constraints.

These bind on the *capacity* decision variable (``Generator-p_nom``), so the
models here make the relevant generators extendable. A carrier with no
extendable capacity has no decision variable, so its capacity constraint is
skipped (asserted in ``test_fixed_carrier_capacity_constraint_is_skipped``).
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network.custom_constraints import apply_custom_constraints

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
OPTIONS = {"snapshotStart": 0, "snapshotCount": 6, "snapshotWeight": 1.0}


def _snaps(n_snaps: int = 6) -> list[str]:
    return [f"2030-01-01T{h:02d}:00:00" for h in range(n_snaps)]


def _exp_model(n_snaps: int = 6) -> dict[str, list[dict[str, Any]]]:
    """Flat 100 MW load; cheap *extendable* wind + fixed expensive backup.

    Unconstrained, wind builds exactly 100 MW (enough to serve load at the
    lowest cost) and backup stays idle. A capacity cap below 100 forces backup
    on; a capacity floor above 100 forces extra (idle) wind to be built.
    """
    snaps = _snaps(n_snaps)
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "wind"}, {"name": "backup"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
        "generators": [
            {
                "name": "G_wind", "bus": "b", "carrier": "wind", "p_nom": 0.0,
                "p_nom_extendable": True, "p_nom_max": 1000.0,
                "capital_cost": 10.0, "marginal_cost": 0.0,
            },
            {"name": "G_backup", "bus": "b", "carrier": "backup", "p_nom": 200.0,
             "marginal_cost": 100.0},
        ],
    }


def _share_model(n_snaps: int = 6) -> dict[str, list[dict[str, Any]]]:
    """Flat 100 MW load served by two extendable carriers, wind cheaper.

    Unconstrained the optimiser builds all wind and no solar (wind's capacity
    share is 100 %). Capping wind's *capacity share* at 40 % forces solar
    capacity to be built until wind is at most 40 % of the total — the cap binds
    at exactly 0.40.
    """
    snaps = _snaps(n_snaps)
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "wind"}, {"name": "solar"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
        "generators": [
            {"name": "G_wind", "bus": "b", "carrier": "wind", "p_nom": 0.0,
             "p_nom_extendable": True, "p_nom_max": 1000.0,
             "capital_cost": 5.0, "marginal_cost": 0.0},
            {"name": "G_solar", "bus": "b", "carrier": "solar", "p_nom": 0.0,
             "p_nom_extendable": True, "p_nom_max": 1000.0,
             "capital_cost": 10.0, "marginal_cost": 1.0},
        ],
    }


def _ef(constraints):
    notes: list[str] = []

    def extra_functionality(net, snapshots):
        apply_custom_constraints(net, constraints, {}, notes, snapshots)

    return extra_functionality


def _opt(gen: str, network) -> float:
    return float(network.generators.at[gen, "p_nom_opt"])


def test_carrier_max_cap_caps_built_capacity():
    n, _ = build_network(_exp_model(), SCENARIO, OPTIONS)
    cons = [{"enabled": True, "metric": "carrier_max_cap", "carrier": "wind",
             "value": 50.0, "label": "c"}]
    n.optimize(solver_name="highs", extra_functionality=_ef(cons))
    assert _opt("G_wind", n) <= 50.0 + 1e-6


def test_carrier_min_cap_forces_build():
    n, _ = build_network(_exp_model(), SCENARIO, OPTIONS)
    cons = [{"enabled": True, "metric": "carrier_min_cap", "carrier": "wind",
             "value": 150.0, "label": "c"}]
    n.optimize(solver_name="highs", extra_functionality=_ef(cons))
    assert _opt("G_wind", n) >= 150.0 - 1e-6


def test_carrier_max_cap_share_forces_split():
    n, _ = build_network(_share_model(), SCENARIO, OPTIONS)
    cons = [{"enabled": True, "metric": "carrier_max_cap_share", "carrier": "wind",
             "value": 40.0, "label": "c"}]
    n.optimize(solver_name="highs", extra_functionality=_ef(cons))
    wind, solar = _opt("G_wind", n), _opt("G_solar", n)
    # Cap holds and binds at 0.40; solar had to be built (0 without the cap).
    assert wind / (wind + solar) == pytest.approx(0.40, abs=1e-3)
    assert solar > 1e-3


def test_fixed_carrier_capacity_constraint_is_skipped():
    """A capacity constraint on a fully-fixed carrier has no decision variable.

    It must be skipped (not added as an infeasible literal) so the solve still
    succeeds and the carrier dispatches as if unconstrained.
    """
    from backend.tests.test_custom_constraints import _flat_model  # fixed-only model

    n, _ = build_network(_flat_model(), SCENARIO, OPTIONS)
    cons = [{"enabled": True, "metric": "carrier_max_cap", "carrier": "gas",
             "value": 50.0, "label": "c"}]  # gas is fixed at 200 MW → skipped
    n.optimize(solver_name="highs", extra_functionality=_ef(cons))
    # Gas still serves the full flat load (cap ignored, no crash).
    assert float(n.generators_t.p["G_gas"].sum()) == pytest.approx(600.0, abs=1e-3)
