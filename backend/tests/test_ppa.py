"""PPA contract modeler (PP1) — value a fixed-price PPA against the run LMP.

A wind owner sells under a fixed-price CfD. When the strike is above the average
spot, the seller gains (a price floor) and the buyer loses by the same amount;
settlement is zero-sum and consistent with the energy × (strike − avg spot).
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T0{h}:00:00" for h in range(4)]
    load = [90, 140, 110, 130]
    pmax = [0.5, 0.4, 0.7, 0.3]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}, {"name": "wind"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 200, "marginal_cost": 50},
            {"name": "wind1", "bus": "b", "carrier": "wind", "p_nom": 120, "marginal_cost": 0, "owner": "Acme"},
        ],
        "generators-p_max_pu": [{"snapshot": s, "wind1": w} for s, w in zip(snaps, pmax)],
    }


def test_ppa_generation_settlement_zero_sum() -> None:
    res = run_pypsa(
        _model(), SCENARIO,
        {"ppaConfig": {"enabled": True, "owner": "Acme", "volumeType": "generation", "strikePrice": 70}},
    )
    ppa = res["ppa"]
    assert ppa is not None
    assert ppa["energyMWh"] > 0
    # Zero-sum: buyer net = − seller net.
    assert ppa["buyerNet"] == pytest.approx(-ppa["sellerNet"], rel=1e-6)
    # Settlement = contract value − spot value, and = energy × (strike − avg spot).
    assert ppa["sellerNet"] == pytest.approx(ppa["contractValue"] - ppa["spotValue"], rel=1e-6)
    assert ppa["sellerNet"] == pytest.approx(ppa["energyMWh"] * (ppa["strikePrice"] - ppa["avgSpotPrice"]), rel=1e-3)


def test_ppa_flat_block() -> None:
    res = run_pypsa(
        _model(), SCENARIO,
        {"ppaConfig": {"enabled": True, "volumeType": "flat", "flatMW": 50, "strikePrice": 40}},
    )
    ppa = res["ppa"]
    assert ppa is not None and ppa["volumeType"] == "flat"
    assert ppa["energyMWh"] > 0


def test_ppa_absent_when_disabled() -> None:
    assert run_pypsa(_model(), SCENARIO, {})["ppa"] is None
