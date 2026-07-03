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


def _budget_net(*, window_hours: int = 24, load_mw: float = 100.0, p_nom: float = 200.0,
                e_sum_max_scaled: float | None = None) -> pypsa.Network:
    """A window where capacity is ample (p_nom > load) so only the cumulative
    e_sum_max budget can be the structural cause. ``e_sum_max_scaled`` is the
    value build_network would store, i.e. annual × window_hours/8760."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=window_hours, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "gas")
    n.add("Load", "L", bus="b", p_set=load_mw)
    kwargs = {} if e_sum_max_scaled is None else {"e_sum_max": e_sum_max_scaled}
    n.add("Generator", "gas_well", bus="b", carrier="gas", p_nom=p_nom, marginal_cost=50, **kwargs)
    return n


def test_flags_window_scaled_annual_budget() -> None:
    # 8000 MWh/yr on a 24 h window → build stores 8000 × 24/8760 ≈ 21.92 MWh.
    # Window load = 100 MW × 24 h = 2400 MWh, potential = 200 MW × 24 h = 4800 MWh:
    # the budget is <1% of both, while the power-based check sees no shortfall.
    scaled = 8000.0 * 24.0 / 8760.0
    diag = diagnose_infeasibility(_budget_net(e_sum_max_scaled=scaled))
    assert diag["shortfalls"] == []  # capacity is NOT the cause here
    assert len(diag["starvedBudgets"]) == 1
    st = diag["starvedBudgets"][0]
    assert st["name"] == "gas_well"
    assert st["annualBudgetMWh"] == pytest.approx(8000.0, rel=1e-6)
    assert st["scaledBudgetMWh"] == pytest.approx(scaled, abs=0.01)
    assert st["windowHours"] == pytest.approx(24.0)
    assert st["windowLoadMWh"] == pytest.approx(2400.0)
    line = next(ln for ln in diag["lines"] if "ANNUAL" in ln)
    assert "gas_well" in line and "8000" in line and "24 h window" in line
    assert "starved" in diag["headline"]
    assert any("8760" in s for s in diag["suggestions"])


def test_ample_budget_not_flagged() -> None:
    # 1000 MWh over the window exceeds 20% of both window load (2400 MWh)
    # and capacity-bound energy (4800 MWh) → not starved.
    diag = diagnose_infeasibility(_budget_net(e_sum_max_scaled=1000.0))
    assert diag["starvedBudgets"] == []
    # Default e_sum_max (inf) never flags.
    diag = diagnose_infeasibility(_budget_net())
    assert diag["starvedBudgets"] == []


def test_full_year_window_budget_not_scaled() -> None:
    # When Σ objective weights ≥ 8760 h the build applies NO scaling
    # (period factor 1.0), so the annual-convention explanation would be
    # wrong — the check must stay silent even for a tiny budget.
    n = _budget_net(window_hours=3, e_sum_max_scaled=5.0)
    n.snapshot_weightings["objective"] = 2920.0  # 3 × 2920 h = 8760 h
    diag = diagnose_infeasibility(n)
    assert diag["starvedBudgets"] == []


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


def test_end_to_end_starved_budget_explains_annual_convention() -> None:
    # The motivating gap: e_sum_max=8000 looks generous, capacity (200 MW) covers
    # the 100 MW load, yet the solve is infeasible because build_network scales
    # the ANNUAL budget to the 24 h window (≈21.9 MWh ≪ 2400 MWh load energy).
    # The error detail must now explain the convention with the scaled number.
    from fastapi import HTTPException

    from backend.pypsa.results import run_pypsa

    snaps = [ts.isoformat() for ts in pd.date_range("2030-01-01", periods=24, freq="h")]
    model = {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "generators": [{"name": "gas_well", "bus": "b", "carrier": "gas",
                        "p_nom": 200, "marginal_cost": 50, "e_sum_max": 8000}],
    }
    with pytest.raises(HTTPException) as ei:
        run_pypsa(model, {"discountRate": 0.0, "carbonPrice": 0.0}, {})
    detail = str(ei.value.detail)
    assert "gas_well" in detail
    assert "ANNUAL budget" in detail
    assert "8000" in detail and "21.9" in detail  # annual figure + scaled figure
    assert "8760" in detail  # the suggested fix explains the convention
