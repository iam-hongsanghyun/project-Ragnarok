"""P29: Process in generator economics and company finance (capex / opex / revenue).

A Process ``elz`` converts electricity (bus0, rate0=-1) to hydrogen (bus1, rate1=0.7).
With internal power p (MW):

    revenue        R = sum_t w * (-p0 * pi_el  - p1 * pi_h2)    # inputs cost, outputs earn
    variable cost  C = sum_t w * marginal_cost * p
    capex (horizon) K = capital_cost * p_nom_opt                 # n.statistics.capex; per year = K / n.nyears

Emissions are NOT attributed to the Process: they stay at the fuel generator.
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
import pypsa

from backend.pypsa.results.finance import build_company_finance
from backend.pypsa.results.market import build_generator_economics

RTOL = 1e-9
ATOL = 1e-6
MARGINAL = 2.0
CAPITAL = 10.0
HOURS = 4


def _solved() -> pypsa.Network:
    warnings.simplefilter("ignore")
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=HOURS, freq="h"))
    n.add("Carrier", ["gas", "el", "h2"], co2_emissions=[0.2, 0.0, 0.0])
    n.add("Bus", ["el", "h2"], carrier=["AC", "h2"])
    n.add("Generator", "g", bus="el", carrier="gas", p_nom=200, marginal_cost=30, efficiency=0.5)
    n.add("Load", "le", bus="el", p_set=50.0)
    n.add("Load", "lh", bus="h2", p_set=20.0, carrier="h2")
    n.add("Process", "elz", bus0="el", bus1="h2", rate0=-1, rate1=0.7, p_nom_extendable=True,
          capital_cost=CAPITAL, marginal_cost=MARGINAL, carrier="el")
    logging.disable(logging.CRITICAL)
    try:
        n.optimize(solver_name="highs")
    finally:
        logging.disable(logging.NOTSET)
    return n


def test_generator_economics_lists_process_with_analytic_values() -> None:
    n = _solved()
    rows = build_generator_economics(n)["processes"]
    assert [r["name"] for r in rows] == ["elz"]
    row = rows[0]
    d = n.c.processes.dynamic
    pi = n.buses_t.marginal_price
    expected_revenue = float((-d["p0"]["elz"] * pi["el"] - d["p1"]["elz"] * pi["h2"]).sum())
    expected_cost = float((MARGINAL * d["p"]["elz"]).sum())
    p_nom_opt = float(n.processes.at["elz", "p_nom_opt"])
    np.testing.assert_allclose(row["revenue"], expected_revenue, rtol=1e-6, atol=1.0)  # payload rounds to 1 currency unit
    np.testing.assert_allclose(row["variableCost"], expected_cost, rtol=1e-6, atol=1.0)
    np.testing.assert_allclose(row["grossMargin"], expected_revenue - expected_cost, rtol=1e-6, atol=1.0)
    # capital_cost is PyPSA's cost per modelled HORIZON: the fixed charge over it is capital_cost x p_nom_opt
    # (n.statistics.capex) and the per-year display figure is that over n.nyears
    np.testing.assert_allclose(row["fixedCostHorizon"], CAPITAL * p_nom_opt, rtol=1e-6, atol=1.0)
    np.testing.assert_allclose(row["fixedCostAnnual"], CAPITAL * p_nom_opt / float(n.nyears), rtol=1e-4, atol=1.0)
    np.testing.assert_allclose(row["capacityMw"], p_nom_opt, rtol=1e-6, atol=0.05)
    assert p_nom_opt > 0 and expected_revenue > expected_cost > 0  # the case is non-trivial


def test_company_finance_includes_process_owner() -> None:
    n = _solved()
    model = {"processes": [{"name": "elz", "owner": "H2Co"}], "generators": [{"name": "g", "owner": "GasCo"}]}
    out = build_company_finance(n, model, owner_column="owner", discount_rate=0.05, currency="$")
    assert out is not None
    by_company = {c["company"]: c for c in out["companies"]}
    assert "H2Co" in by_company
    d = n.c.processes.dynamic
    pi = n.buses_t.marginal_price
    margin_window = float((-d["p0"]["elz"] * pi["el"] - d["p1"]["elz"] * pi["h2"]).sum()
                          - (MARGINAL * d["p"]["elz"]).sum())
    expected_annual = margin_window * 8760.0 / HOURS
    np.testing.assert_allclose(by_company["H2Co"]["annualMargin"], expected_annual, rtol=1e-6, atol=0.01)
    assert by_company["H2Co"]["overnightCapex"] > 0  # extendable process: capex recovered via the annuity


def test_emissions_stay_at_fuel_generator() -> None:
    """The Process neither adds nor removes emissions; the gas generator carries them all."""
    from backend.pypsa.utils.emissions import primary_energy_emissions

    n = _solved()
    pe = primary_energy_emissions(n)
    assert list(pe.generators.index) == ["g"]
    np.testing.assert_allclose(pe.total, 0.2 * float((n.generators_t.p["g"] / 0.5).sum()), rtol=RTOL, atol=ATOL)
