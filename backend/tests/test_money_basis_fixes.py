"""Regression tests for the window-vs-annual money-basis fixes (2026-07 review).

Covers, with hand-checkable analytical cases:
  1. ``build_company_finance`` annualises the modelled-window operating margin
     by × 8760/H before it enters annualMargin / cashflow / NPV, prices opex
     off the DENSE (time-varying) marginal cost, and ``_irr`` expands its
     bracket for very profitable projects.
  2. ``build_company_statement`` annualises the flow lines (revenue, energy,
     carbon, fuel/VOM, emissions) × 8760/H onto capexAnnual's basis, and
     charges interest = rate × reconstructed principal
     (gearing × capexAnnual / CRF(i, tenor)) — 0 without a tenor.
  3. ``build_merchant`` pro-rates the annual capital charge onto the window
     (× H/8760) so profit subtracts like from like.
  4. ``build_asset_swap`` computes paybackYears against the ANNUALISED opex
     saving (window saving × 8760/H).
  5. ``build_ess_business_case`` feeds NPV/IRR/payback an annualised margin
     (window arbitrage revenue × 8760/H) while the per-size energyMWh /
     arbitrageRevenue stay window totals.

All networks use snapshot weightings summing to H = 4380 h (half a year, so
the annualisation factor is exactly 2) except the asset-swap case, which uses
the unweighted build path (H = number of snapshots).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pypsa
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.results.asset_swap import build_asset_swap
from backend.pypsa.results.company_statement import build_company_statement
from backend.pypsa.results.ess import build_ess_business_case
from backend.pypsa.results.finance import _irr, build_company_finance
from backend.pypsa.results.merchant import build_merchant

H_HALF_YEAR = 4380.0  # 2 snapshots × 2190 h → annualise = 8760/4380 = 2


# ── Shared half-year fixture (finance + company statement) ────────────────────


def _half_year_market(*, time_varying_cost: bool = False) -> tuple[pypsa.Network, dict[str, list[dict[str, Any]]]]:
    """Load 100 MW: Acme's g_own (80 MW @ 10) runs flat; g_price (200 MW @ 50)
    covers the residual 20 MW and sets the LMP at 50 in both snapshots.

    Two snapshots, each weighted 2190 h → H = 4380 (half a year)."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.snapshot_weightings.loc[:, :] = 2190.0
    n.add("Bus", "b")
    n.add("Carrier", "gas")
    n.add("Carrier", "peak")
    n.add("Load", "L", bus="b", p_set=100.0)
    n.add("Generator", "g_own", bus="b", carrier="gas", p_nom=80.0,
          marginal_cost=10.0, capital_cost=100_000.0)
    n.add("Generator", "g_price", bus="b", carrier="peak", p_nom=200.0,
          marginal_cost=50.0)
    if time_varying_cost:
        # True cost varies [10, 30] via the time-varying frame; the static
        # column stays 10 — the regression priced opex off the stale 10.
        n.generators_t.marginal_cost["g_own"] = pd.Series([10.0, 30.0], index=n.snapshots)
    n.optimize(solver_name="highs")
    model = {"generators": [{"name": "g_own", "owner": "Acme"}]}
    return n, model


# ── 1. Company finance (F2) ───────────────────────────────────────────────────


def test_finance_annual_margin_is_window_margin_times_two() -> None:
    n, model = _half_year_market()
    res = build_company_finance(
        n, model, owner_column="owner", discount_rate=0.0, currency="€",
    )
    assert res is not None
    acme = next(c for c in res["companies"] if c["company"] == "Acme")
    # Window margin = (π − mc)·p·H = (50 − 10)·80·4380 = 14,016,000.
    # Annual margin = window × 8760/4380 = ×2.
    window_margin = (50.0 - 10.0) * 80.0 * H_HALF_YEAR
    np.testing.assert_allclose(acme["annualMargin"], 2.0 * window_margin,
                               rtol=1e-9, atol=1e-2)
    # r = 0, default 25-yr life, no capex (g_own is not extendable):
    # NPV = 25 × annual margin — the annualised margin flows into the cashflow.
    assert acme["horizonYears"] == 25
    np.testing.assert_allclose(acme["overnightCapex"], 0.0, rtol=0, atol=1e-9)
    np.testing.assert_allclose(acme["npv"], 25 * 2.0 * window_margin,
                               rtol=1e-9, atol=1e-2)


def test_finance_opex_prices_time_varying_marginal_cost() -> None:
    n, model = _half_year_market(time_varying_cost=True)
    res = build_company_finance(
        n, model, owner_column="owner", discount_rate=0.0, currency="€",
    )
    assert res is not None
    acme = next(c for c in res["companies"] if c["company"] == "Acme")
    # Window opex on the DENSE cost = (10 + 30)·80·2190 = 7,008,000; revenue
    # = 50·80·4380 = 17,520,000 → window margin 10,512,000 → annual ×2.
    window_margin = (50.0 * 80.0 * H_HALF_YEAR) - (10.0 + 30.0) * 80.0 * 2190.0
    np.testing.assert_allclose(acme["annualMargin"], 2.0 * window_margin,
                               rtol=1e-9, atol=1e-2)
    # Guard: the stale-static-column figure would be 2·(50−10)·80·4380.
    stale = 2.0 * (50.0 - 10.0) * 80.0 * H_HALF_YEAR
    assert abs(acme["annualMargin"] - stale) > 1e6


def test_irr_bracket_expands_beyond_initial_hi() -> None:
    # −1 today, +100 in a year → IRR = 99 (9900%), far beyond the initial
    # [−0.9, 10] bracket; the regression returned None for such projects.
    irr = _irr([-1.0, 100.0])
    assert irr is not None
    np.testing.assert_allclose(irr, 99.0, rtol=1e-4, atol=1e-4)


# ── 2. Company statement (F1+F2 P&L) ─────────────────────────────────────────


def test_statement_flow_lines_annualized_capex_untouched() -> None:
    n, model = _half_year_market()
    res = build_company_statement(
        n, model, owner_column="owner", currency="€",
        emissions_factors={"gas": 0.4}, carbon_price=5.0,
    )
    assert res is not None
    acme = next(c for c in res["companies"] if c["company"] == "Acme")
    # Window flows: energy = 80·4380 = 350,400 MWh; revenue = 50·energy;
    # emissions = 0.4·energy; carbon = emissions·5; fuelVom = 10·energy − carbon.
    energy_w = 80.0 * H_HALF_YEAR
    carbon_w = 0.4 * energy_w * 5.0
    np.testing.assert_allclose(acme["energyMWh"], 2.0 * energy_w, rtol=1e-9, atol=1e-2)
    np.testing.assert_allclose(acme["revenue"], 2.0 * 50.0 * energy_w, rtol=1e-9, atol=1e-2)
    np.testing.assert_allclose(acme["emissionsTonnes"], 2.0 * 0.4 * energy_w, rtol=1e-9, atol=1e-2)
    np.testing.assert_allclose(acme["carbonCost"], 2.0 * carbon_w, rtol=1e-9, atol=1e-2)
    np.testing.assert_allclose(acme["fuelVomCost"], 2.0 * (10.0 * energy_w - carbon_w),
                               rtol=1e-9, atol=1e-2)
    # capexAnnual is ALREADY annual — it must NOT be rescaled:
    # capital_cost × p_nom_opt = 100,000 × 80 = 8,000,000.
    np.testing.assert_allclose(acme["capexAnnual"], 8_000_000.0, rtol=1e-9, atol=1e-2)
    # And the statement stays internally consistent on the annual basis.
    np.testing.assert_allclose(
        acme["grossMargin"], acme["revenue"] - acme["carbonCost"] - acme["fuelVomCost"],
        rtol=1e-9, atol=1e-2,
    )
    np.testing.assert_allclose(acme["ebit"], acme["grossMargin"] - acme["capexAnnual"],
                               rtol=1e-9, atol=1e-2)


def test_statement_interest_is_rate_times_reconstructed_principal() -> None:
    n, model = _half_year_market()
    gearing, i, tenor = 0.4, 0.05, 10.0
    res = build_company_statement(
        n, model, owner_column="owner", currency="€",
        emissions_factors={}, carbon_price=0.0,
        debt={"gearing": gearing, "interestRate": i, "tenorYears": tenor},
    )
    assert res is not None
    acme = next(c for c in res["companies"] if c["company"] == "Acme")
    # principal = gearing × capexAnnual / CRF(i, tenor); interest = principal × i.
    crf = i / (1.0 - (1.0 + i) ** (-tenor))
    expected_interest = gearing * 8_000_000.0 / crf * i
    np.testing.assert_allclose(acme["interest"], expected_interest, rtol=1e-9, atol=1e-2)
    np.testing.assert_allclose(acme["netMargin"], acme["ebit"] - expected_interest,
                               rtol=1e-9, atol=1e-2)


def test_statement_interest_zero_without_tenor() -> None:
    n, model = _half_year_market()
    res = build_company_statement(
        n, model, owner_column="owner", currency="€",
        emissions_factors={}, carbon_price=0.0,
        debt={"gearing": 0.4, "interestRate": 0.05},  # no tenorYears
    )
    assert res is not None
    acme = next(c for c in res["companies"] if c["company"] == "Acme")
    # Without a tenor the principal is unknowable → interest omitted (0).
    np.testing.assert_allclose(acme["interest"], 0.0, rtol=0, atol=1e-9)
    np.testing.assert_allclose(acme["netMargin"], acme["ebit"], rtol=1e-9, atol=1e-2)


# ── 3. Merchant (B1) window P&L ───────────────────────────────────────────────


def test_merchant_profit_prorates_annual_capex_onto_window() -> None:
    """Own1's extendable unit (mc 10, annual capex 100k/MW·yr, max 60 MW)
    against a flat 50 price on a half-year window: the merchant LP builds the
    full 60 MW (window-weighted margin 40·4380 = 175,200 > 100,000/MW), and
    the reported profit must charge only the window share of the capex."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.snapshot_weightings.loc[:, :] = 2190.0
    n.add("Bus", "b")
    n.add("Carrier", "gas")
    n.add("Carrier", "own")
    n.add("Load", "L", bus="b", p_set=100.0)
    n.add("Generator", "sys", bus="b", carrier="gas", p_nom=200.0, marginal_cost=30.0)
    n.add("Generator", "m_own", bus="b", carrier="own", p_nom=0.0,
          p_nom_extendable=True, p_nom_max=60.0,
          capital_cost=100_000.0, marginal_cost=10.0)
    n.optimize(solver_name="highs")

    res = build_merchant(
        n, {"generators": [{"name": "m_own", "owner": "Own1"}]},
        owner="Own1", owner_column="owner",
        price_source="series", flat_price=50.0, price_series=None, currency="€",
    )
    assert res is not None
    row = next(a for a in res["assets"] if a["name"] == "m_own")
    np.testing.assert_allclose(row["capacityMW"], 60.0, rtol=0, atol=1e-6)
    # Window totals: energy = 60·4380; revenue = 50·energy; opex = 10·energy.
    energy = 60.0 * H_HALF_YEAR
    np.testing.assert_allclose(res["totals"]["energyMWh"], energy, rtol=1e-9, atol=1e-2)
    np.testing.assert_allclose(res["totals"]["revenue"], 50.0 * energy, rtol=1e-9, atol=1e-2)
    np.testing.assert_allclose(res["totals"]["operatingCost"], 10.0 * energy, rtol=1e-9, atol=1e-2)
    # Annual capex 100,000·60 = 6,000,000 pro-rated × H/8760 = ×0.5 → 3,000,000.
    np.testing.assert_allclose(res["totals"]["capex"], 3_000_000.0, rtol=1e-9, atol=1e-2)
    # Profit subtracts like from like: revenue − opex − window capex share.
    np.testing.assert_allclose(
        res["totals"]["profit"], 50.0 * energy - 10.0 * energy - 3_000_000.0,
        rtol=1e-9, atol=1e-2,
    )


# ── 4. Asset swap (DW2) payback ───────────────────────────────────────────────


def test_asset_swap_payback_uses_annualized_savings() -> None:
    """Retire 120 MW coal (mc 50, serving 100 MW flat) for firm wind (mc 0,
    36,500/MW·yr) on a 2-snapshot unweighted window (H = 2 h):

        window saving  = 50·100·2            =        10,000
        annual saving  = 10,000 × 8760/2     =    43,800,000
        overnight      = 36,500·120 × 25     =   109,500,000  (r = 0 → 1/CRF = 25)
        payback        = 109.5e6 / 43.8e6    =           2.5 yr
    """
    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    model: dict[str, list[dict[str, Any]]] = {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "coal", "co2_emissions": 0.3}, {"name": "wind"},
                     {"name": "backup"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
        "generators": [
            {"name": "C1", "bus": "b", "carrier": "coal", "p_nom": 120.0,
             "marginal_cost": 50.0},
            # Idle costed backstop: keeps the after-model's LP objective
            # non-empty (the free wind replacement alone carries no cost term)
            # without dispatching in either solve.
            {"name": "B1", "bus": "b", "carrier": "backup", "p_nom": 50.0,
             "marginal_cost": 200.0},
        ],
    }
    scenario = {"discountRate": 0.0, "carbonPrice": 0.0}
    base, _ = build_network(model, scenario, {})
    base.optimize(solver_name="highs")
    assert float(base.snapshot_weightings["objective"].sum()) == pytest.approx(2.0)

    res = build_asset_swap(
        base, model, scenario, {}, build_network,
        remove_filters=[{"field": "carrier", "values": ["coal"]}],
        remove_carrier="", add_carrier="wind",
        add_capital_cost=36_500.0, add_marginal_cost=0.0,
        currency="€", emissions_factors={"coal": 0.3},
    )
    assert res is not None
    # Window operating costs bracket the saving: 10,000 → 0.
    np.testing.assert_allclose(res["before"]["operatingCost"], 10_000.0, rtol=1e-9, atol=1e-2)
    np.testing.assert_allclose(res["after"]["operatingCost"], 0.0, rtol=0, atol=1e-2)
    np.testing.assert_allclose(res["replacementCapex"], 36_500.0 * 120.0, rtol=1e-9, atol=1e-2)
    # The payback divides overnight capex by the ANNUAL saving — 2.5 years,
    # not the 10,950 "years" the un-annualised window saving would give.
    np.testing.assert_allclose(res["paybackYears"], 2.5, rtol=0, atol=0.01)
    # Emissions delta sanity: 0.3 t/MWh × 200 MWh window → −60 t.
    np.testing.assert_allclose(res["before"]["emissionsTonnes"], 60.0, rtol=1e-9, atol=1e-2)
    np.testing.assert_allclose(res["delta"]["emissionsTonnes"], -60.0, rtol=1e-9, atol=1e-2)


# ── 5. ESS business case (DW3) ────────────────────────────────────────────────


def test_ess_npv_annualizes_window_revenue_but_reports_window_totals() -> None:
    """LMP [10, 90] on a half-year window (weights 2190). A 10 MW / 2190 h
    lossless battery cycles once: window arbitrage revenue
    = 10·(90 − 10)·2190 = 1,752,000; the NPV cashflow margin is ×2 that.

        overnight = 100,000·10 × 15 = 15,000,000   (r = 0, 15-yr life)
        NPV       = −15e6 + 15 × 3,504,000 = 37,560,000
        payback   = 4 + (15 − 4·3.504)/3.504 ≈ 4.28 yr
    """
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.snapshot_weightings.loc[:, :] = 2190.0
    n.add("Bus", "b")
    n.add("Carrier", "cheap")
    n.add("Carrier", "exp")
    n.add("Load", "L", bus="b", p_set=[50.0, 150.0])
    n.add("Generator", "g_cheap", bus="b", carrier="cheap", p_nom=100.0, marginal_cost=10.0)
    n.add("Generator", "g_exp", bus="b", carrier="exp", p_nom=100.0, marginal_cost=90.0)
    n.optimize(solver_name="highs")
    np.testing.assert_allclose(
        n.buses_t.marginal_price["b"].to_numpy(), [10.0, 90.0], rtol=1e-6, atol=1e-6,
    )

    res = build_ess_business_case(
        n, bus="b", max_hours=2190.0, capital_cost_per_mw=100_000.0,
        min_size_mw=10.0, max_size_mw=10.0, steps=1,
        round_trip_efficiency=1.0, discount_rate=0.0, currency="€",
    )
    assert res is not None
    assert len(res["sizes"]) == 1
    row = res["sizes"][0]
    # Per-size figures stay WINDOW totals (what the sweep simulated).
    window_revenue = 10.0 * (90.0 - 10.0) * 2190.0
    np.testing.assert_allclose(row["arbitrageRevenue"], window_revenue, rtol=1e-9, atol=1e-2)
    np.testing.assert_allclose(row["energyMWh"], 10.0 * 2190.0, rtol=1e-9, atol=0.1)
    np.testing.assert_allclose(row["annualisedCapex"], 1_000_000.0, rtol=1e-9, atol=1e-2)
    # NPV uses the ANNUALISED margin: −15e6 + 15·(1.752e6 × 2) = 37.56e6.
    annual_margin = 2.0 * window_revenue
    overnight = 1_000_000.0 * 15.0
    np.testing.assert_allclose(row["npv"], -overnight + 15.0 * annual_margin,
                               rtol=1e-9, atol=1e-2)
    # Payback on the annualised margin ≈ 4.28 yr (the window margin would
    # never pay back a 15e6 overnight within the 15-yr horizon).
    np.testing.assert_allclose(row["paybackYears"], 4.28, rtol=0, atol=0.01)
    assert row["irr"] is not None and row["irr"] > 0.2
