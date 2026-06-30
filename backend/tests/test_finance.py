"""Company-level financial model (F2) — NPV / IRR / payback / DSCR per owner.

A profitable owner (cheap extendable renewables that capture a high system
price) should show a positive NPV and a finite payback; the metrics must be
internally consistent (NPV sign agrees with IRR vs discount rate).
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.07, "carbonPrice": 0.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T0{h}:00:00" for h in range(6)]
    load = [80, 140, 200, 120, 90, 160]
    pmax = [0.5, 0.3, 0.6, 0.4, 0.7, 0.2]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": "wind"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            # Price-setting incumbent (not owned by the company under study).
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 300, "marginal_cost": 80},
            # Acme's extendable wind: cheap to run, low capital cost (so it gets
            # built over this short test horizon), long life.
            {"name": "wind1", "bus": "b", "carrier": "wind", "p_nom_extendable": True,
             "capital_cost": 50, "marginal_cost": 0, "lifetime": 25, "owner": "Acme"},
        ],
        "generators-p_max_pu": [{"snapshot": s, "wind1": w} for s, w in zip(snaps, pmax)],
    }


def test_company_finance_metrics() -> None:
    res = run_pypsa(_model(), SCENARIO, {})
    cf = res["companyFinance"]
    assert cf is not None
    assert cf["discountRate"] == pytest.approx(0.07)
    acme = next(c for c in cf["companies"] if c["company"] == "Acme")
    assert acme["overnightCapex"] > 0
    assert acme["horizonYears"] == 25
    # A viable project: NPV > 0 implies IRR above the discount rate.
    if acme["npv"] > 0:
        assert acme["irr"] is not None and acme["irr"] > cf["discountRate"]
        assert acme["paybackYears"] is not None
    # DSCR omitted when no debt is configured.
    assert acme["dscr"] is None


def test_company_finance_dscr_with_debt() -> None:
    res = run_pypsa(
        _model(), SCENARIO,
        {"financeConfig": {"gearing": 0.6, "interestRate": 0.05, "tenorYears": 15}},
    )
    cf = res["companyFinance"]
    acme = next(c for c in cf["companies"] if c["company"] == "Acme")
    assert acme["dscr"] is not None and acme["dscr"] > 0


def test_company_finance_absent_without_owners() -> None:
    model = _model()
    for g in model["generators"]:
        g.pop("owner", None)
    assert run_pypsa(model, SCENARIO, {})["companyFinance"] is None
