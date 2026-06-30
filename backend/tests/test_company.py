"""Company / owner dimension (F1) — per-company KPIs from a solved network.

Two owners share a one-bus system: Acme owns the gas fleet, Globex the wind.
The breakdown should group capacity / energy / revenue / emissions by owner and
flag any untagged assets.
"""
from __future__ import annotations

from typing import Any

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T0{h}:00:00" for h in range(4)]
    load = [90, 140, 110, 130]
    pmax = [0.5, 0.4, 0.7, 0.3]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": "wind"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 200, "marginal_cost": 50, "owner": "Acme"},
            {"name": "wind1", "bus": "b", "carrier": "wind", "p_nom": 120, "marginal_cost": 0, "owner": "Globex"},
            {"name": "wind2", "bus": "b", "carrier": "wind", "p_nom": 60, "marginal_cost": 0},  # untagged
        ],
        "generators-p_max_pu": [
            {"snapshot": s, "wind1": w, "wind2": w} for s, w in zip(snaps, pmax)
        ],
    }


def test_company_breakdown_groups_by_owner() -> None:
    res = run_pypsa(_model(), SCENARIO, {})
    cb = res["companies"]
    assert cb is not None
    assert cb["ownerColumn"] == "owner"
    names = {c["company"] for c in cb["companies"]}
    assert names == {"Acme", "Globex"}
    assert cb["untaggedCount"] == 1  # wind2

    acme = next(c for c in cb["companies"] if c["company"] == "Acme")
    globex = next(c for c in cb["companies"] if c["company"] == "Globex")
    # Acme is the only emitter (gas); Globex (wind) emits nothing.
    assert acme["emissionsTonnes"] > 0
    assert globex["emissionsTonnes"] == 0
    assert acme["generatorCount"] == 1 and globex["generatorCount"] == 1
    assert acme["capacityMW"] > 0 and globex["capacityMW"] > 0


def test_company_breakdown_custom_column() -> None:
    model = _model()
    for g in model["generators"]:
        owner = g.pop("owner", None)
        if owner:
            g["Operator"] = owner
    res = run_pypsa(model, SCENARIO, {"ownerColumn": "Operator"})
    cb = res["companies"]
    assert cb is not None
    assert cb["ownerColumn"] == "Operator"
    assert {c["company"] for c in cb["companies"]} == {"Acme", "Globex"}


def test_company_breakdown_absent_without_tags() -> None:
    model = _model()
    for g in model["generators"]:
        g.pop("owner", None)
    assert run_pypsa(model, SCENARIO, {})["companies"] is None
