"""RB10: reported emissions follow PyPSA's ``primary_energy`` GlobalConstraint accounting.

The reference is the constraint itself: after a solve with a ``primary_energy``
CO2 cap, ``n.model.constraints["GlobalConstraint-<name>"].lhs.solution`` is the
emission total PyPSA bounded. Ragnarok's reported total must equal it.

    E = sum_g sum_t w_t * y_p * p_g(t)/eta_g(t) * ef_c           (generators, signed)
      + sum_s ef_c * (e_initial - e_final)                       (non-cyclic StorageUnit / Store)

Links and Processes are deliberately not counted: PyPSA does not count them and
the fuel-supply generator already carries the fuel's emissions (counting the
converting link too would double count).
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
import pypsa

from backend.pypsa.results.emissions import build_emissions_breakdown, emission_totals_by_carrier
from backend.pypsa.utils.emissions import primary_energy_emissions

RTOL = 1e-9
ATOL = 1e-6


def _solve(n: pypsa.Network, **kwargs: object) -> pypsa.Network:
    warnings.simplefilter("ignore")
    logging.disable(logging.CRITICAL)
    try:
        n.optimize(solver_name="highs", **kwargs)
    finally:
        logging.disable(logging.NOTSET)
    return n


def _lhs(n: pypsa.Network, name: str = "co2_cap") -> float:
    """Full left-hand side of the ``primary_energy`` constraint at the solution.

    linopy moves the constant part of the expression (the ``e_initial`` terms of
    non-cyclic storage) to the right-hand side, so the stored ``lhs`` carries only
    the variable terms; the constant is ``GlobalConstraint.constant - rhs``.
    """
    con = n.model.constraints[f"GlobalConstraint-{name}"]
    moved_constant = float(n.global_constraints.at[name, "constant"]) - float(con.rhs)
    return float(con.lhs.solution) + moved_constant


def _mixed_network() -> pypsa.Network:
    """Gas generator (eta 0.5, time-varying weights), a coal Store feeding a Link,
    and an emitting non-cyclic StorageUnit, under a non-binding primary_energy cap."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=4, freq="h"))
    n.snapshot_weightings.loc[:, :] = 2.0
    n.add("Carrier", ["gas", "coal", "ps", "elec"], co2_emissions=[0.2, 0.34, 0.1, 0.0])
    n.add("Bus", ["el", "coalbus"])
    n.add("Load", "l", bus="el", p_set=[40.0, 60.0, 80.0, 50.0])
    n.add("Generator", "gas", bus="el", carrier="gas", p_nom=100, marginal_cost=60, efficiency=0.5)
    n.add("Store", "coalpile", bus="coalbus", carrier="coal", e_nom=500, e_initial=300, e_cyclic=False)
    n.add("Link", "coalplant", bus0="coalbus", bus1="el", efficiency=0.4, p_nom=30, marginal_cost=1)
    n.add("StorageUnit", "res", bus="el", carrier="ps", p_nom=10, max_hours=5,
          state_of_charge_initial=20, cyclic_state_of_charge=False)
    n.add("GlobalConstraint", "co2_cap", type="primary_energy", carrier_attribute="co2_emissions",
          sense="<=", constant=1e9)
    return _solve(n)


def test_reported_emissions_equal_constraint_lhs_mixed() -> None:
    n = _mixed_network()
    lhs = _lhs(n)
    pe = primary_energy_emissions(n)
    assert lhs > 0
    np.testing.assert_allclose(pe.total, lhs, rtol=RTOL, atol=ATOL)
    # each emitting carrier is really exercised, so the test is not vacuous
    assert pe.generators["gas"] > 0
    assert pe.stores["coalpile"] > 0
    assert pe.storage_units["res"] > 0
    # the same number reaches the result payload and the summary aggregation
    breakdown = build_emissions_breakdown(n, n.carriers["co2_emissions"].to_dict())
    np.testing.assert_allclose(breakdown["totalTco2"], lhs, rtol=RTOL, atol=ATOL)
    by_carrier = emission_totals_by_carrier(n, n.carriers["co2_emissions"].to_dict())
    np.testing.assert_allclose(sum(by_carrier.values()), lhs, rtol=RTOL, atol=ATOL)
    np.testing.assert_allclose(
        sum(r["emissions_tco2"] for r in breakdown["byGenerator"])
        + sum(r["emissions_tco2"] for r in breakdown["byStorage"]),
        lhs, rtol=1e-6, atol=0.05,  # rows are rounded to 0.01 t
    )


def test_store_depletion_is_counted_and_links_are_not() -> None:
    """Analytic check: the coal Store emits ef * (e_initial - e_final); the link adds nothing."""
    n = _mixed_network()
    expected_store = 0.34 * (300.0 - float(n.stores_t.e["coalpile"].iloc[-1]))
    np.testing.assert_allclose(primary_energy_emissions(n).stores["coalpile"], expected_store, rtol=RTOL, atol=ATOL)
    expected_su = 0.1 * (20.0 - float(n.storage_units_t.state_of_charge["res"].iloc[-1]))
    np.testing.assert_allclose(primary_energy_emissions(n).storage_units["res"], expected_su, rtol=RTOL, atol=ATOL)
    # generator term: weights 2.0, efficiency 0.5, ef 0.2
    gas = float((n.generators_t.p["gas"] * 2.0 / 0.5 * 0.2).sum())
    np.testing.assert_allclose(primary_energy_emissions(n).generators["gas"], gas, rtol=RTOL, atol=ATOL)


def test_binding_cap_total_equals_cap() -> None:
    """With a binding cap the reported total sits exactly on the constraint constant."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=3, freq="h"))
    n.add("Carrier", ["gas", "wind"], co2_emissions=[0.2, 0.0])
    n.add("Bus", "b")
    n.add("Load", "l", bus="b", p_set=100.0)
    n.add("Generator", "gas", bus="b", carrier="gas", p_nom=200, marginal_cost=10, efficiency=0.4)
    n.add("Generator", "wind", bus="b", carrier="wind", p_nom=200, marginal_cost=50)
    n.add("GlobalConstraint", "co2_cap", type="primary_energy", carrier_attribute="co2_emissions",
          sense="<=", constant=60.0)
    _solve(n)
    total = primary_energy_emissions(n).total
    np.testing.assert_allclose(total, 60.0, rtol=RTOL, atol=ATOL)
    np.testing.assert_allclose(total, _lhs(n), rtol=RTOL, atol=ATOL)
    # CO2 shadow price is positive: the cap binds
    assert float(n.global_constraints.at["co2_cap", "mu"]) < 0.0 or n.global_constraints.at["co2_cap", "mu"] != 0.0


def test_multi_period_years_weighting_matches_constraint() -> None:
    """Investment-period ``years`` weights multiply the generator term, as in the constraint."""
    n = pypsa.Network()
    ts = pd.date_range("2030-01-01", periods=3, freq="h")
    sn = pd.MultiIndex.from_product([[2030, 2040], ts], names=["period", "timestep"])
    n.set_snapshots(sn)
    n.investment_periods = [2030, 2040]
    n.investment_period_weightings["years"] = [10.0, 5.0]
    n.add("Carrier", ["gas"], co2_emissions=[0.2])
    n.add("Bus", "b")
    n.add("Load", "l", bus="b", p_set=[10, 20, 30, 20, 20, 20.])
    n.add("Generator", "g", bus="b", carrier="gas", p_nom=100, marginal_cost=10, efficiency=0.5,
          build_year=2030, lifetime=30)
    n.add("GlobalConstraint", "co2_cap", type="primary_energy", carrier_attribute="co2_emissions",
          sense="<=", constant=1e9)
    _solve(n, multi_investment_periods=True)  # the flag Ragnarok's pathway runs set
    pe = primary_energy_emissions(n)
    np.testing.assert_allclose(pe.total, _lhs(n), rtol=RTOL, atol=ATOL)
    # snapshot-basis total is the unweighted one (used for intensities): years 10 and 5 differ
    p = n.generators_t.p["g"]
    snapshot_basis = float((p / 0.5 * 0.2).sum())
    np.testing.assert_allclose(pe.generators_snapshot["g"], snapshot_basis, rtol=RTOL)
    expected = 0.2 / 0.5 * (p.loc[2030].sum() * 10.0 + p.loc[2040].sum() * 5.0)
    np.testing.assert_allclose(pe.total, expected, rtol=RTOL)


def test_multi_period_without_period_flag_is_unweighted() -> None:
    """Without ``multi_investment_periods`` PyPSA applies no ``years`` weights - neither do we."""
    n = pypsa.Network()
    ts = pd.date_range("2030-01-01", periods=2, freq="h")
    n.set_snapshots(pd.MultiIndex.from_product([[2030, 2040], ts], names=["period", "timestep"]))
    n.investment_periods = [2030, 2040]
    n.investment_period_weightings["years"] = [10.0, 5.0]
    n.add("Carrier", ["gas"], co2_emissions=[0.2])
    n.add("Bus", "b")
    n.add("Load", "l", bus="b", p_set=20.0)
    n.add("Generator", "g", bus="b", carrier="gas", p_nom=100, marginal_cost=10)
    n.add("GlobalConstraint", "co2_cap", type="primary_energy", carrier_attribute="co2_emissions",
          sense="<=", constant=1e9)
    _solve(n)
    np.testing.assert_allclose(primary_energy_emissions(n).total, _lhs(n), rtol=RTOL, atol=ATOL)


def test_fuel_generator_not_double_counted_with_conversion_link() -> None:
    """Gas supply generator (eta 1) -> CCGT link: emissions = fuel burned, counted once."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Carrier", ["gas", "ccgt"], co2_emissions=[0.2, 0.2])  # the link carrier also has a factor
    n.add("Bus", ["el", "gasbus"])
    n.add("Load", "l", bus="el", p_set=40.0)
    n.add("Generator", "gas_supply", bus="gasbus", carrier="gas", p_nom=500, marginal_cost=20)
    n.add("Link", "ccgt", bus0="gasbus", bus1="el", carrier="ccgt", efficiency=0.5, p_nom=200)
    n.add("GlobalConstraint", "co2_cap", type="primary_energy", carrier_attribute="co2_emissions",
          sense="<=", constant=1e9)
    _solve(n)
    fuel = float(n.generators_t.p["gas_supply"].sum())  # = 2 * 40 / 0.5 = 160 MWh_th
    np.testing.assert_allclose(primary_energy_emissions(n).total, 0.2 * fuel, rtol=RTOL)
    np.testing.assert_allclose(primary_energy_emissions(n).total, _lhs(n), rtol=RTOL, atol=ATOL)
