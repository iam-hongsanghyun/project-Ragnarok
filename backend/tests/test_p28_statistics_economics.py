"""P28 (remaining) + RB10: economics on ``n.statistics`` and per-owner emissions on the primary-energy basis.

Reference values are the pre-move hand-rolled definitions, restated here so each
moved number is pinned to the old one (``assert_allclose``, rtol 1e-9):

    revenue_i   = sum_t w_t * pi_b(t) * p_i(t)                  (x period objective weight in a pathway)
    capex_i     = capital_cost_i * p_nom_opt_i                  (annual; / window scale when scaled)
    emissions_o = sum_{i in owner o} (primary_energy term of i)  -> sum over owners = system total
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
import pypsa
import pytest

from backend.pypsa.results.asset_swap import _emissions
from backend.pypsa.results.company import build_company_breakdown
from backend.pypsa.results.company_statement import build_company_statement
from backend.pypsa.results.expansion import build_expansion_results
from backend.pypsa.results.market import CAPEX_WINDOW_SCALE_KEY, build_generator_economics
from backend.pypsa.results.summaries import _pathway_period_summaries
from backend.pypsa.utils.emissions import primary_energy_emissions

RTOL = 1e-9
ATOL = 1e-6


def _solve(n: pypsa.Network, **kwargs: object) -> pypsa.Network:
    warnings.simplefilter("ignore")
    logging.disable(logging.CRITICAL)
    try:
        status, cond = n.optimize(solver_name="highs", **kwargs)
    finally:
        logging.disable(logging.NOTSET)
    assert (status, cond) == ("ok", "optimal")
    return n


def _mixed() -> pypsa.Network:
    """Wind + gas (eta 0.5) + extendable peaker + battery + Process; coal Store -> Link; PS StorageUnit."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=4, freq="h"))
    n.snapshot_weightings.loc[:, :] = 2.0
    n.add("Carrier", ["gas", "coal", "ps", "wind", "battery", "chp", "heat"],
          co2_emissions=[0.2, 0.34, 0.1, 0.0, 0.0, 0.0, 0.0])
    n.add("Bus", ["el", "coalbus", "gasbus", "heat"])
    n.add("Load", "l", bus="el", p_set=[40.0, 60.0, 200.0, 50.0])
    n.add("Load", "h", bus="heat", p_set=5.0)
    n.add("Generator", "gas", bus="el", carrier="gas", p_nom=100, marginal_cost=60, efficiency=0.5)
    n.add("Generator", "gas2", bus="el", carrier="gas", p_nom=10, marginal_cost=70, efficiency=0.4)
    n.add("Generator", "wind", bus="el", carrier="wind", p_nom=30, p_max_pu=[0.2, 1.0, 0.5, 0.9])
    n.add("Generator", "peak", bus="el", carrier="gas", p_nom_extendable=True, capital_cost=100,
          marginal_cost=200)
    n.add("Generator", "well", bus="gasbus", carrier="gas", p_nom=500, marginal_cost=5)
    n.add("Generator", "heat_dump", bus="heat", p_nom=100, p_min_pu=-1.0, p_max_pu=0.0, carrier="heat")
    n.add("Store", "coalpile", bus="coalbus", carrier="coal", e_nom=500, e_initial=300, e_cyclic=False)
    n.add("Link", "coalplant", bus0="coalbus", bus1="el", efficiency=0.4, p_nom=30, marginal_cost=1)
    n.add("StorageUnit", "res", bus="el", carrier="ps", p_nom=10, max_hours=5,
          state_of_charge_initial=20, cyclic_state_of_charge=False)
    n.add("StorageUnit", "bat", bus="el", carrier="battery", p_nom=20, max_hours=2, marginal_cost=1)
    n.add("Process", "chp", bus0="gasbus", bus1="el", bus2="heat", rate0=-1.0, rate1=0.4, rate2=0.3,
          p_nom=60, carrier="chp", p_min_pu=0.0, marginal_cost=2)
    n.add("GlobalConstraint", "co2_cap", type="primary_energy", carrier_attribute="co2_emissions",
          sense="<=", constant=1e9)
    return _solve(n)


def _factors(n: pypsa.Network) -> dict[str, float]:
    """The app's ``emissions_factors`` map: carrier -> tCO2/MWh_thermal."""
    return {str(c): float(v) for c, v in n.carriers["co2_emissions"].items()}


# ── generator economics ──────────────────────────────────────────────────────

def test_revenue_margin_capture_identical_to_hand_rolled() -> None:
    n = _mixed()
    econ = build_generator_economics(n)
    w = n.snapshot_weightings["generators"]
    mp = n.buses_t.marginal_price
    rows = {g["name"]: g for g in econ["generators"]}
    checked = 0
    for name, row in rows.items():
        bus = n.generators.at[name, "bus"]
        p = n.generators_t.p[name]
        ref_rev = float((mp[bus] * p * w).sum())
        np.testing.assert_allclose(row["revenue"], ref_rev, rtol=RTOL, atol=1.0)  # payload rounds to 1 currency
        e = float((p.clip(lower=0) * w).sum())
        np.testing.assert_allclose(row["energyMwh"], e, rtol=1e-6, atol=0.1)
        if e > 1e-9:
            np.testing.assert_allclose(row["capturePrice"], ref_rev / e, rtol=1e-3, atol=0.01)
            checked += 1
    assert checked >= 3
    for s in econ["storage"]:
        p = n.storage_units_t.p[s["name"]]
        bus = n.storage_units.at[s["name"], "bus"]
        np.testing.assert_allclose(s["revenue"], float((mp[bus] * p * w).sum()), rtol=RTOL, atol=1.0)
        np.testing.assert_allclose(s["energyDischargedMwh"], float((p.clip(lower=0) * w).sum()), rtol=1e-6, atol=0.1)
        np.testing.assert_allclose(s["energyChargedMwh"], float(((-p).clip(lower=0) * w).sum()), rtol=1e-6, atol=0.1)
    # Process: net port value at nodal prices
    proc = {r["name"]: r for r in econ["processes"]}["chp"]
    t = n.c.processes.dynamic
    ref = sum(float((-t[f"p{i}"]["chp"] * mp[n.processes.at["chp", f"bus{i}"]] * w).sum()) for i in (0, 1, 2))
    np.testing.assert_allclose(proc["revenue"], ref, rtol=RTOL, atol=1.0)


def test_capture_price_and_capacity_factor_equal_statistics() -> None:
    n = _mixed()
    econ = build_generator_economics(n)
    mv = n.statistics.market_value(components=["Generator"], groupby=False, drop_zero=False, round=12)
    cf = n.statistics.capacity_factor(components=["Generator"], groupby=False, drop_zero=False, round=12)
    cf_carrier = n.statistics.capacity_factor(components=["Generator"], groupby="carrier", drop_zero=False, round=12)
    n_checked = 0
    for g in econ["generators"]:
        key = ("Generator", g["name"])
        if g["capturePrice"] is not None and key in mv.index and np.isfinite(mv[key]) and g["name"] != "heat_dump":
            np.testing.assert_allclose(g["capturePrice"], mv[key], rtol=1e-3, atol=0.01)
            n_checked += 1
        if g["capacityFactor"] is not None and key in cf.index:
            np.testing.assert_allclose(g["capacityFactor"], cf[key], rtol=1e-4, atol=1e-4)
    assert n_checked >= 3
    # carrier table: capacity-weighted value == PyPSA's groupby="carrier" (gas mixes 4 units, wind 1)
    by = {c["carrier"]: c["capacityFactor"] for c in econ["byCarrier"]}
    assert {"gas", "wind"} <= set(by)
    for carrier, value in by.items():
        np.testing.assert_allclose(value, cf_carrier[("Generator", carrier)], rtol=1e-4, atol=1e-4)


def test_multi_period_revenue_weighted_and_inactive_masked() -> None:
    n = pypsa.Network()
    ts = pd.date_range("2030-01-01", periods=4, freq="h")
    n.set_snapshots(pd.MultiIndex.from_product([[2030, 2040], ts], names=["period", "timestep"]))
    n.investment_periods = [2030, 2040]
    n.investment_period_weightings["years"] = [10.0, 5.0]
    n.investment_period_weightings["objective"] = [1.0, 0.5]
    n.add("Carrier", ["gas", "wind"], co2_emissions=[0.2, 0.0])
    n.add("Bus", "b")
    n.add("Load", "l", bus="b", p_set=[10, 20, 30, 20] * 2)
    n.add("Generator", "old", bus="b", carrier="gas", p_nom=100, marginal_cost=50, build_year=2020, lifetime=15)
    n.add("Generator", "new", bus="b", carrier="gas", p_nom_extendable=True, capital_cost=1000,
          marginal_cost=40, build_year=2040, lifetime=20)
    n.add("Generator", "wind", bus="b", carrier="wind", p_nom=15, p_max_pu=[0.2, 1, 0.5, 0.9] * 2)
    _solve(n, multi_investment_periods=True)
    econ = build_generator_economics(n)
    rows = {g["name"]: g for g in econ["generators"]}
    obj = {2030: 1.0, 2040: 0.5}
    mp = n.buses_t.marginal_price["b"]
    for name in ("old", "new", "wind"):
        p = n.generators_t.p[name]
        ref = sum(obj[per] * float((mp.loc[per] * p.loc[per]).sum()) for per in (2030, 2040))
        np.testing.assert_allclose(rows[name]["revenue"], ref, rtol=RTOL, atol=1.0)
    # inactive periods contribute nothing: 'old' retired in 2035 (no dispatch 2040), 'new' not built in 2030
    assert float(n.generators_t.p.loc[2040, "old"].abs().sum()) == pytest.approx(0.0, abs=1e-9)
    assert float(n.generators_t.p.loc[2030, "new"].abs().sum()) == pytest.approx(0.0, abs=1e-9)
    # capacity factor averages only over the periods the unit exists in
    cf_stat = n.statistics.capacity_factor(components=["Generator"], groupby=False, drop_zero=False, round=12)
    np.testing.assert_allclose(rows["old"]["capacityFactor"], cf_stat.loc[("Generator", "old"), 2030], rtol=1e-4)
    np.testing.assert_allclose(rows["new"]["capacityFactor"], cf_stat.loc[("Generator", "new"), 2040], rtol=1e-4)


# ── expansion CAPEX ──────────────────────────────────────────────────────────

def test_expansion_capex_is_statistics_and_matches_capital_cost_times_opt() -> None:
    n = _mixed()
    row = {r["name"]: r for r in build_expansion_results(n)}["peak"]
    opt = float(n.generators.at["peak", "p_nom_opt"])
    np.testing.assert_allclose(row["capex_annual"], 100.0 * opt, rtol=RTOL, atol=1.0)
    stat = n.statistics.capex(components=["Generator"], groupby=False, round=12)
    np.testing.assert_allclose(row["capex_annual"], float(stat[("Generator", "peak")]), rtol=RTOL, atol=1.0)
    np.testing.assert_allclose(row["capex_expanded"] + row["capex_installed"], row["capex_annual"], atol=1.0)


def test_expansion_capex_window_scaled_run_reports_annual() -> None:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=24, freq="h"))
    scale = 24 / 8760
    n.meta[CAPEX_WINDOW_SCALE_KEY] = scale
    n.add("Bus", "b")
    n.add("Load", "L", bus="b", p_set=50)
    n.add("Generator", "g", bus="b", p_nom_extendable=True, capital_cost=1000 * scale, marginal_cost=1)
    _solve(n)
    row = build_expansion_results(n)[0]
    np.testing.assert_allclose(row["capex_annual"], 1000.0 * float(n.generators.at["g", "p_nom_opt"]), rtol=RTOL, atol=1.0)


def test_expansion_native_overnight_fom_statistics() -> None:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=24, freq="h"))
    n.add("Bus", "b")
    n.add("Load", "L", bus="b", p_set=50)
    n.add("Generator", "g", bus="b", p_nom_extendable=True, overnight_cost=1000, discount_rate=0.07,
          lifetime=20, fom_cost=10)
    n.add("Generator", "peak", bus="b", p_nom=100, marginal_cost=500)
    _solve(n, include_objective_constant=False)
    row = build_expansion_results(n)[0]
    opt = float(n.generators.at["g", "p_nom_opt"])
    from pypsa.costs import annuity
    np.testing.assert_allclose(row["capex_annual"], 1000 * float(annuity(0.07, 20)) * opt, rtol=1e-6, atol=1.0)
    np.testing.assert_allclose(row["fom_total"], 10 * opt, rtol=RTOL)
    np.testing.assert_allclose(row["overnight_total"], 1000 * opt, rtol=RTOL)


# ── per-owner emissions ──────────────────────────────────────────────────────

def _owner_model(include_unassigned: bool) -> dict[str, list[dict[str, str]]]:
    gens = [{"name": "gas", "owner": "A"}, {"name": "peak", "owner": "B"}, {"name": "well", "owner": "B"},
            {"name": "wind", "owner": "B"}]
    if not include_unassigned:
        gens.append({"name": "gas2", "owner": "A"})
    return {
        "generators": gens,
        "storage_units": [{"name": "res", "owner": "A"}, {"name": "bat", "owner": "B"}],
        "stores": [{"name": "coalpile", "owner": "B"}],
    }


@pytest.mark.parametrize("include_unassigned", [False, True])
def test_company_emissions_sum_to_system_total(include_unassigned: bool) -> None:
    n = _mixed()
    total = primary_energy_emissions(n).total
    assert total > 0
    out = build_company_breakdown(
        n, _owner_model(include_unassigned), owner_column="owner", currency="$", emissions_factors=_factors(n),
    )
    assert out is not None
    owned = sum(c["emissionsTonnes"] for c in out["companies"])
    np.testing.assert_allclose(owned + out["unassignedEmissionsTonnes"], total, rtol=1e-6, atol=0.05)
    if include_unassigned:
        assert out["unassignedEmissionsTonnes"] > 0  # gas2 emits and has no owner
    else:
        np.testing.assert_allclose(owned, total, rtol=1e-6, atol=0.05)
    by = {c["company"]: c["emissionsTonnes"] for c in out["companies"]}
    pe = primary_energy_emissions(n)
    expected_a = pe.generators["gas"] + pe.storage_units["res"] + (0 if include_unassigned else pe.generators["gas2"])
    np.testing.assert_allclose(by["A"], expected_a, rtol=1e-6, atol=0.05)
    # the depleting coal Store is allocated to its owner, not dropped
    assert pe.stores["coalpile"] > 0
    expected_b = pe.generators[["peak", "well"]].sum() + pe.stores["coalpile"]
    np.testing.assert_allclose(by["B"], expected_b, rtol=1e-6, atol=0.05)


def test_company_statement_emissions_sum_to_annualised_system_total() -> None:
    n = _mixed()
    total = primary_energy_emissions(n).total
    out = build_company_statement(
        n, _owner_model(True), owner_column="owner", currency="$", emissions_factors=_factors(n), carbon_price=0.0,
    )
    assert out is not None
    horizon = float(n.snapshot_weightings["objective"].sum())
    owned = sum(c["emissionsTonnes"] for c in out["companies"])
    np.testing.assert_allclose(owned + out["unassignedEmissionsTonnes"], total * 8760.0 / horizon, rtol=1e-6, atol=1.0)


def test_asset_swap_emissions_equal_system_total() -> None:
    n = _mixed()
    np.testing.assert_allclose(_emissions(n, _factors(n)), primary_energy_emissions(n).total, rtol=RTOL, atol=ATOL)


def test_pathway_period_summaries_emissions_sum_to_generator_total() -> None:
    n = pypsa.Network()
    ts = pd.date_range("2030-01-01", periods=3, freq="h")
    n.set_snapshots(pd.MultiIndex.from_product([[2030, 2040], ts], names=["period", "timestep"]))
    n.investment_periods = [2030, 2040]
    n.investment_period_weightings["years"] = [10.0, 5.0]
    n.add("Carrier", ["gas"], co2_emissions=[0.2])
    n.add("Bus", "b")
    n.add("Load", "l", bus="b", p_set=[10, 20, 30, 20, 20, 20.0])
    n.add("Generator", "g", bus="b", carrier="gas", p_nom=100, marginal_cost=10, efficiency=0.5,
          build_year=2030, lifetime=30)
    _solve(n, multi_investment_periods=True)
    pe = primary_energy_emissions(n)
    rows = _pathway_period_summaries(
        n, n.generators_t.p, n.loads_t.p_set.sum(axis=1), pd.Series(0.0, index=n.snapshots), _factors(n),
    )
    # efficiency 0.5 is now in the per-period figure (the old clipped basis agrees here: p >= 0)
    weighted = sum(r["totalEmissions"] * r["yearsWeight"] for r in rows)
    np.testing.assert_allclose(weighted, pe.generators.sum(), rtol=RTOL, atol=ATOL)
    np.testing.assert_allclose(sum(r["totalEmissions"] for r in rows), pe.generators_snapshot.sum(), rtol=RTOL)
