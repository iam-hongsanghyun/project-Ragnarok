"""Merchant / price-taker optimisation (B1) — most-profitable for one owner.

A one-bus system: two gas tiers set the price, plus a zero-marginal-cost wind
farm and a battery, both tagged to owner "Acme". Against the stage-1 system
price the wind is a pure price-taker (runs whenever price > 0) and the battery
arbitrages. We assert the owner's economics come back coherent.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T0{h}:00:00" for h in range(6)]
    load = [80, 140, 200, 120, 90, 160]
    pmax = [0.5, 0.3, 0.6, 0.4, 0.7, 0.2]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": "wind"}, {"name": "batt"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 120, "marginal_cost": 40},
            {"name": "gas2", "bus": "b", "carrier": "gas", "p_nom": 120, "marginal_cost": 90},
            {"name": "wind1", "bus": "b", "carrier": "wind", "p_nom": 80, "marginal_cost": 0, "owner": "Acme"},
        ],
        "generators-p_max_pu": [{"snapshot": s, "wind1": w} for s, w in zip(snaps, pmax)],
        "storage_units": [
            {"name": "batt1", "bus": "b", "carrier": "batt", "p_nom": 50, "max_hours": 4,
             "efficiency_store": 0.95, "efficiency_dispatch": 0.95, "owner": "Acme"},
        ],
    }


def test_merchant_owner_economics() -> None:
    res = run_pypsa(_model(), SCENARIO, {"merchantConfig": {"enabled": True, "owner": "Acme", "priceSource": "lmp"}})
    m = res["merchant"]
    assert m is not None
    assert m["owner"] == "Acme"
    assert m["priceSource"] == "lmp"
    names = {a["name"] for a in m["assets"]}
    assert names == {"wind1", "batt1"}
    wind = next(a for a in m["assets"] if a["name"] == "wind1")
    # Zero-marginal-cost price-taker: positive energy, revenue and profit, and a
    # capture price equal to the time-weighted price it sold at.
    assert wind["energyMWh"] > 0
    assert wind["revenue"] > 0
    assert wind["operatingCost"] == 0
    assert wind["profit"] == pytest.approx(wind["revenue"], rel=1e-6)
    assert wind["capturePrice"] is not None and wind["capturePrice"] > 0
    # Totals are internally consistent.
    tot = m["totals"]
    assert tot["profit"] == pytest.approx(tot["revenue"] - tot["operatingCost"] - tot["capex"], rel=1e-6)
    assert m["priceStats"]["max"] >= m["priceStats"]["mean"] >= m["priceStats"]["min"]


def test_merchant_series_price_source() -> None:
    # Flat exogenous price of 75/MWh — owner wind runs full whenever 75 > 0.
    res = run_pypsa(
        _model(), SCENARIO,
        {"merchantConfig": {"enabled": True, "owner": "Acme", "priceSource": "series", "flatPrice": 75}},
    )
    m = res["merchant"]
    assert m is not None
    assert m["priceSource"] == "series"
    assert m["priceStats"]["mean"] == pytest.approx(75.0)
    wind = next(a for a in m["assets"] if a["name"] == "wind1")
    assert wind["capturePrice"] == pytest.approx(75.0, rel=1e-6)


def test_merchant_custom_owner_column() -> None:
    # Tag assets under a "Company" column instead of "owner".
    model = _model()
    for g in model["generators"]:
        if g["name"] == "wind1":
            g.pop("owner", None)
            g["Company"] = "Globex"
    for s in model["storage_units"]:
        s.pop("owner", None)
        s["Company"] = "Globex"
    res = run_pypsa(
        model, SCENARIO,
        {"merchantConfig": {"enabled": True, "owner": "Globex", "ownerColumn": "Company"}},
    )
    m = res["merchant"]
    assert m is not None
    assert m["ownerColumn"] == "Company"
    assert {a["name"] for a in m["assets"]} == {"wind1", "batt1"}


def test_merchant_absent_when_disabled() -> None:
    assert run_pypsa(_model(), SCENARIO, {})["merchant"] is None


def test_merchant_unknown_owner_returns_none() -> None:
    res = run_pypsa(_model(), SCENARIO, {"merchantConfig": {"enabled": True, "owner": "Nobody"}})
    assert res["merchant"] is None


def test_merchant_rejects_incompatible_mode() -> None:
    with pytest.raises(HTTPException) as exc:
        run_pypsa(
            _model(), SCENARIO,
            {"merchantConfig": {"enabled": True, "owner": "Acme"}, "contingencyConfig": {"enabled": True}},
        )
    assert exc.value.status_code == 400
