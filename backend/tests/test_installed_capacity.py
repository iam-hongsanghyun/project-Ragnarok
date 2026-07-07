"""Installed-capacity KPI uses the SOLVED p_nom_opt, not the raw input p_nom.

Regression: the "Generator capacity" / "Storage capacity" summary KPIs (and the
reserve position derived from them) used ``network.generators.p_nom.sum()``, so a
capacity-expansion run reported its pre-solve nameplate instead of what the
optimiser actually built. They must use ``p_nom_opt`` (== p_nom for fixed units,
the built capacity for extendable ones) and exclude the injected
``load_shedding_`` backstop.
"""
from __future__ import annotations

import re
from typing import Any

import pytest

from backend.pypsa.results import run_pypsa


def _model_with_extendable_wind() -> dict[str, Any]:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(6)]
    return {
        "snapshots": [{"snapshot": s} for s in snaps],
        "buses": [{"name": "n1"}],
        "carriers": [{"name": "gas"}, {"name": "wind"}],
        "generators": [
            # Fixed, expensive backup so the solver prefers building wind.
            {"name": "gas", "bus": "n1", "carrier": "gas", "p_nom": 100, "marginal_cost": 500},
            # Extendable from ZERO input capacity, cheap → the solver builds it.
            {"name": "wind", "bus": "n1", "carrier": "wind", "marginal_cost": 0,
             "p_nom": 0, "p_nom_extendable": True, "p_nom_max": 1000, "capital_cost": 1000},
        ],
        "loads": [{"name": "L", "bus": "n1"}],
        "loads-p_set": [{"snapshot": s, "L": 300.0} for s in snaps],
    }


def _kpi_mw(summary: list[dict[str, Any]], label: str) -> float:
    for item in summary:
        if item["label"] == label:
            return float(re.sub(r"[^0-9.]", "", str(item["value"]).split("MW")[0]))
    pytest.fail(f"summary KPI {label!r} not found")


def test_generator_capacity_kpi_uses_p_nom_opt_not_input_p_nom() -> None:
    result = run_pypsa(_model_with_extendable_wind(), {"discountRate": 0.05}, {})
    gen_cap = _kpi_mw(result["summary"], "Generator capacity")

    # Input p_nom sum is gas(100) + wind(0) = 100. With the bug the KPI reads 100;
    # with the fix it reflects the built wind (p_nom_opt), so it must exceed 100
    # (the solver builds wind to cover the 300 MW load rather than run expensive gas).
    assert gen_cap > 100.0, f"expected built wind in capacity, got {gen_cap} MW"
    # It should roughly equal 100 (gas) + the built wind (~300 to serve load).
    assert gen_cap == pytest.approx(400.0, abs=1.0)


def test_installed_capacity_excludes_load_shedding_backstop() -> None:
    # Force load shedding: demand exceeds all real capacity so the injected
    # load_shedding_ generator (large p_nom) is needed. Its capacity must NOT
    # inflate the installed-capacity KPI.
    model = _model_with_extendable_wind()
    model["generators"][1]["p_nom_max"] = 50  # cap wind so load can't be fully met
    model["loads-p_set"] = [{"snapshot": s["snapshot"], "L": 5000.0} for s in model["snapshots"]]

    result = run_pypsa(model, {"discountRate": 0.05}, {"enableLoadShedding": True})
    gen_cap = _kpi_mw(result["summary"], "Generator capacity")

    # Only gas(100) + wind(<=50); the load-shedding backstop (huge) is excluded.
    assert gen_cap <= 200.0, f"load-shedding backstop leaked into capacity: {gen_cap} MW"
