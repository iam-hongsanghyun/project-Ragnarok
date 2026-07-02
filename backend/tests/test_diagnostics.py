"""Q2 infeasibility diagnostics — structural cause detection."""
from __future__ import annotations

import pandas as pd
import pypsa
import pytest

from backend.pypsa.results.diagnostics import diagnose_infeasibility, diagnosis_text


def _net(peak: float, gas_cap: float, *, extendable_unbounded: bool = False,
         load_shedding: bool = False) -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=3, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "gas")
    n.add("Load", "L", bus="b", p_set=[peak * 0.6, peak, peak * 0.8])
    if extendable_unbounded:
        n.add("Generator", "gas1", bus="b", carrier="gas", p_nom_extendable=True,
              capital_cost=100, marginal_cost=50)  # p_nom_max defaults to inf
    else:
        n.add("Generator", "gas1", bus="b", carrier="gas", p_nom=gas_cap, marginal_cost=50)
    if load_shedding:
        n.add("Generator", "load_shedding_b", bus="b", carrier="gas", p_nom=1e6, marginal_cost=1e4)
    return n


def test_detects_capacity_shortfall() -> None:
    diag = diagnose_infeasibility(_net(peak=200, gas_cap=120))
    assert diag["shortfalls"], "a shortfall should be reported"
    worst = diag["shortfalls"][0]
    assert worst["deficitMW"] == pytest.approx(80.0, abs=1e-6)  # 200 − 120
    assert any("Capacity shortfall" in ln for ln in diag["lines"])
    assert any("load shedding" in s.lower() for s in diag["suggestions"])


def test_unbounded_extendable_is_not_a_shortfall() -> None:
    # An extendable generator with unbounded p_nom_max can always build enough,
    # so capacity is never the cause.
    diag = diagnose_infeasibility(_net(peak=200, gas_cap=0, extendable_unbounded=True))
    assert diag["shortfalls"] == []


def test_load_shedding_suppresses_capacity_shortfall() -> None:
    diag = diagnose_infeasibility(_net(peak=200, gas_cap=120, load_shedding=True))
    assert diag["shortfalls"] == []
    assert diag["loadSheddingEnabled"] is True


def test_flags_extreme_marginal_cost() -> None:
    n = _net(peak=100, gas_cap=200)
    n.generators.loc["gas1", "marginal_cost"] = 1e12
    diag = diagnose_infeasibility(n)
    assert any(s["attr"] == "marginal_cost" for s in diag["suspects"])
    assert any("placeholder" in ln.lower() or "extreme" in ln.lower() for ln in diag["lines"])


def test_diagnosis_text_renders_lines_and_fixes() -> None:
    txt = diagnosis_text(diagnose_infeasibility(_net(peak=200, gas_cap=120)))
    assert "•" in txt and "→" in txt  # bullet lines + suggested fixes


def test_end_to_end_infeasible_run_surfaces_diagnosis() -> None:
    from fastapi import HTTPException

    from backend.pypsa.results import run_pypsa

    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    model = {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": 200.0} for s in snaps],  # 200 > 120 cap
        "generators": [{"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 120, "marginal_cost": 50}],
    }
    with pytest.raises(HTTPException) as ei:
        run_pypsa(model, {"discountRate": 0.0, "carbonPrice": 0.0}, {})
    detail = str(ei.value.detail)
    assert "Capacity shortfall" in detail
    assert "load shedding" in detail.lower()
