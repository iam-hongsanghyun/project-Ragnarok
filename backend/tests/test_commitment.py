"""Unit-commitment view (Tier 1) — starts, start-up cost, on/off patterns.

A committable coal unit (cheap to run, expensive to start, min up/down) plus a
committable gas peaker meet a spiky load. The coal unit should cycle at least
once, and its start-up cost should be attributed.
"""
from __future__ import annotations

from typing import Any

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T0{h}:00:00" for h in range(8)]
    load = [40, 220, 60, 240, 50, 230, 45, 210]  # spiky → forces cycling
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "coal"}, {"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "coal1", "bus": "b", "carrier": "coal", "p_nom": 150, "marginal_cost": 25,
             "committable": True, "start_up_cost": 800, "p_min_pu": 0.3},
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 200, "marginal_cost": 90,
             "committable": True, "start_up_cost": 150},
        ],
    }


def test_commitment_summary() -> None:
    res = run_pypsa(_model(), SCENARIO, {})
    cm = res["commitment"]
    assert cm is not None
    assert cm["totals"]["committableCount"] == 2
    names = {g["name"] for g in cm["generators"]}
    assert names == {"coal1", "gas1"}
    for g in cm["generators"]:
        assert g["starts"] >= 0
        assert 0.0 <= g["onlineFraction"] <= 1.0
        # start-up cost total is starts × per-start cost
        assert g["startUpCostTotal"] == g["starts"] * g["startUpCost"]
        # run-length segments cover the whole horizon
        assert sum(s["length"] for s in g["segments"]) == 8
    # At least one unit actually cycled (a start happened).
    assert cm["totals"]["starts"] >= 1
    assert cm["totals"]["startUpCostTotal"] >= 0


def test_commitment_absent_without_committable() -> None:
    model = _model()
    # Without commitment, p_min_pu becomes an always-on floor — drop it (and the
    # start cost) so the plain LP stays feasible when load dips below that floor.
    for g in model["generators"]:
        g.pop("committable", None)
        g.pop("p_min_pu", None)
        g.pop("start_up_cost", None)
    assert run_pypsa(model, SCENARIO, {})["commitment"] is None


def test_commitment_absent_when_force_lp() -> None:
    # Force-LP overrides committable=True → no MILP status → no commitment view.
    # Drop p_min_pu so the relaxed LP stays feasible at low load.
    model = _model()
    for g in model["generators"]:
        g.pop("p_min_pu", None)
    assert run_pypsa(model, SCENARIO, {"forceLp": True})["commitment"] is None
