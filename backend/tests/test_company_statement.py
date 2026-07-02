"""Consolidated per-company P&L statement — line-item consistency.

The statement must add up: variable cost = carbon + fuel/VOM; gross margin =
revenue − variable cost; EBIT = gross margin − capex; net = EBIT − interest.
Carbon must appear only when a carbon price is set and the owner emits, and it
must be backed out of the dispatch cost (never double-counted with fuel).
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.results import run_pypsa


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T0{h}:00:00" for h in range(6)]
    load = [80, 140, 200, 120, 90, 160]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": "wind"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            # Emitting incumbent owned by GasCo (price-setter at mc 80).
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 300,
             "marginal_cost": 80, "owner": "GasCo"},
            # WindCo's zero-marginal-cost wind (a pure inframarginal earner).
            {"name": "wind1", "bus": "b", "carrier": "wind", "p_nom": 120,
             "marginal_cost": 0, "owner": "WindCo"},
        ],
        "generators-p_max_pu": [
            {"snapshot": s, "wind1": 0.5} for s in snaps
        ],
    }


def test_statement_line_items_add_up() -> None:
    res = run_pypsa(_model(), {"discountRate": 0.0, "carbonPrice": 50.0}, {})
    st = res["companyStatement"]
    assert st is not None
    assert st["carbonPrice"] == pytest.approx(50.0)
    for c in st["companies"]:
        assert c["variableCost"] == pytest.approx(c["carbonCost"] + c["fuelVomCost"], abs=1e-3)
        assert c["grossMargin"] == pytest.approx(c["revenue"] - c["variableCost"], abs=1e-3)
        assert c["ebit"] == pytest.approx(c["grossMargin"] - c["capexAnnual"], abs=1e-3)
        assert c["netMargin"] == pytest.approx(c["ebit"] - c["interest"], abs=1e-3)


def test_carbon_only_hits_the_emitter() -> None:
    res = run_pypsa(_model(), {"discountRate": 0.0, "carbonPrice": 50.0}, {})
    st = res["companyStatement"]
    by = {c["company"]: c for c in st["companies"]}
    # WindCo (carrier wind, no co2) carries no carbon cost; GasCo does.
    assert by["WindCo"]["carbonCost"] == pytest.approx(0.0, abs=1e-6)
    assert by["GasCo"]["carbonCost"] > 0
    # WindCo earns at the gas-set price with zero variable cost → healthy margin.
    assert by["WindCo"]["grossMargin"] > 0


def test_zero_carbon_price_zeroes_the_carbon_line() -> None:
    res = run_pypsa(_model(), {"discountRate": 0.0, "carbonPrice": 0.0}, {})
    st = res["companyStatement"]
    for c in st["companies"]:
        assert c["carbonCost"] == pytest.approx(0.0, abs=1e-6)
        # With no carbon, variable cost is entirely fuel/VOM.
        assert c["variableCost"] == pytest.approx(c["fuelVomCost"], abs=1e-6)


def test_totals_sum_the_companies() -> None:
    res = run_pypsa(_model(), {"discountRate": 0.0, "carbonPrice": 50.0}, {})
    st = res["companyStatement"]
    for key in ("revenue", "netMargin", "carbonCost", "grossMargin"):
        assert st["totals"][key] == pytest.approx(sum(c[key] for c in st["companies"]), abs=1e-2)


def test_none_without_owner_tags() -> None:
    m = _model()
    for g in m["generators"]:
        g.pop("owner", None)
    assert run_pypsa(m, {"discountRate": 0.0, "carbonPrice": 0.0}, {})["companyStatement"] is None
