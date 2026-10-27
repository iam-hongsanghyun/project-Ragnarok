"""P28: curtailment and system price follow PyPSA's ``n.statistics`` definitions.

Re-baselined definitions (field names unchanged):

* ``curtailmentSeries`` / ``generatorEnergy[].curtailmentMwh`` come from
  ``n.statistics.curtailment`` (``max(p_max_pu * p_nom_opt - p, 0)``), restricted to
  variable-availability generators, with inactive multi-period units masked.
* ``systemPriceSeries`` weights bus prices by the power *withdrawn* from each bus
  (``n.statistics.withdrawal``: loads + storage charging + link inputs), not by the
  load set-point alone; ``runMeta.averageSystemPrice`` is
  ``n.statistics.prices(weighting="load")``.
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
import pypsa

from backend.pypsa.results.dispatch import (
    build_curtailment_series,
    curtailment_mwh_by_generator,
    metric_definitions,
    system_average_price,
    system_price_series,
)

RTOL = 1e-9
ATOL = 1e-9


def _solve(n: pypsa.Network, **kwargs: object) -> pypsa.Network:
    warnings.simplefilter("ignore")
    logging.disable(logging.CRITICAL)
    try:
        n.optimize(solver_name="highs", **kwargs)
    finally:
        logging.disable(logging.NOTSET)
    return n


def _multi_period_wind() -> pypsa.Network:
    """Wind built in 2040 (inactive in 2030), 2 h snapshot weights, gas backup."""
    n = pypsa.Network()
    ts = pd.date_range("2030-01-01", periods=3, freq="h")
    n.set_snapshots(pd.MultiIndex.from_product([[2030, 2040], ts], names=["period", "timestep"]))
    n.investment_periods = [2030, 2040]
    n.snapshot_weightings[["objective", "stores", "generators"]] = 2.0
    n.add("Carrier", ["wind", "gas"], co2_emissions=[0.0, 0.2])
    n.add("Bus", "b")
    n.add("Load", "l", bus="b", p_set=[10, 20, 30, 10, 20, 30.0])
    n.add("Generator", "wind", bus="b", carrier="wind", p_nom=15, p_max_pu=[1, 0.5, 0.2, 1, 0.5, 0.2],
          marginal_cost=1, build_year=2040, lifetime=30)
    n.add("Generator", "gas", bus="b", carrier="gas", p_nom=40, marginal_cost=50, build_year=2030, lifetime=30)
    return _solve(n, multi_investment_periods=True)


def test_curtailment_matches_statistics_and_masks_inactive_period() -> None:
    n = _multi_period_wind()
    series = build_curtailment_series(n, n.generators_t.p)
    # Raw PyPSA reports the unbuilt 2030 wind unit's whole availability as curtailed ...
    raw = n.statistics.curtailment(components=["Generator"], groupby=False, round=9, drop_zero=False)
    assert float(raw.loc[("Generator", "wind"), 2030]) > 0.0
    # ... Ragnarok masks it: zero in 2030, analytic max(avail - p, 0) in 2040.
    by_period: dict[int, float] = {2030: 0.0, 2040: 0.0}
    for row in series:
        by_period[row["period"]] += row["values"].get("wind", 0.0)
    assert by_period[2030] == 0.0
    avail = np.array([15.0, 7.5, 3.0])
    expected_mw = np.clip(avail - n.generators_t.p["wind"].loc[2040].to_numpy(), 0.0, None).sum()
    np.testing.assert_allclose(by_period[2040], expected_mw, rtol=RTOL, atol=ATOL)
    # thermal gas (static p_max_pu) is never reported as curtailed
    assert all("gas" not in row["values"] for row in series)


def test_curtailment_energy_uses_snapshot_weights() -> None:
    n = _multi_period_wind()
    mwh = curtailment_mwh_by_generator(n)
    assert set(mwh) == {"wind"}
    mw = sum(row["values"].get("wind", 0.0) for row in build_curtailment_series(n, n.generators_t.p))
    np.testing.assert_allclose(mwh["wind"], 2.0 * mw, rtol=RTOL, atol=ATOL)  # weight 2 h, not period years


def _congested_with_link_draw() -> pypsa.Network:
    """a (cheap, 10) --line 20 MW-- b (dear, 50); b also feeds a 20 MW h2 load through a link."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Carrier", ["AC", "h2"])
    n.add("Bus", ["a", "b"], carrier="AC")
    n.add("Bus", "c", carrier="h2")
    n.add("Generator", "ga", bus="a", marginal_cost=10, p_nom=200)
    n.add("Generator", "gb", bus="b", marginal_cost=50, p_nom=200)
    n.add("Line", "ab", bus0="a", bus1="b", x=0.1, r=0.01, s_nom=20)
    n.add("Load", "la", bus="a", p_set=30.0)
    n.add("Load", "lb", bus="b", p_set=10.0)
    n.add("Link", "elz", bus0="b", bus1="c", efficiency=1.0, p_nom=100)
    n.add("Load", "lc", bus="c", p_set=20.0)
    return _solve(n)


def test_system_price_uses_withdrawal_weights() -> None:
    """Weights are what each bus withdraws (load + link draw + line sending end), not the load alone.

    a withdraws 30 (load) + 20 (line to b); b withdraws 10 (load) + 20 (link to the h2 bus).
    Before (P28 re-baseline): (30*10 + 10*50) / 40 = 20.0 per snapshot.
    After:                    (50*10 + 30*50) / 80 = 25.0 per snapshot.
    """
    n = _congested_with_link_draw()
    mp = n.buses_t.marginal_price
    np.testing.assert_allclose(mp["a"].to_numpy(), 10.0, rtol=1e-6)
    np.testing.assert_allclose(mp["b"].to_numpy(), 50.0, rtol=1e-6)
    price = system_price_series(n, {"a", "b"}, n.get_switchable_as_dense("Load", "p_set"))
    np.testing.assert_allclose(price.to_numpy(), 25.0, rtol=1e-6)
    old_load_only = (30 * 10 + 10 * 50) / 40
    assert old_load_only == 20.0  # the superseded definition, kept as documentation


def test_average_price_is_statistics_prices_load_weighted() -> None:
    n = _congested_with_link_draw()
    native = n.statistics.prices(weighting="load", groupby="bus_carrier", bus_carrier=["AC"], round=9, drop_zero=False)
    avg = system_average_price(n, {"a", "b"})
    assert avg is not None
    np.testing.assert_allclose(avg, float(native.loc["AC"]), rtol=1e-9)
    np.testing.assert_allclose(avg, 25.0, rtol=1e-6)


def test_series_falls_back_to_load_weights_without_flows() -> None:
    """An imported run with prices but no stored flows keeps the load-set-point weighting."""
    n = _congested_with_link_draw()
    n.model.solver_model = None  # a solved network cannot be copied with its solver model attached
    stripped = n.copy()
    for comp in ("generators", "loads", "links", "lines", "storage_units", "stores"):
        for attr in ("p", "p0", "p1"):
            frame = getattr(stripped, f"{comp}_t").get(attr)
            if frame is not None and len(frame.columns):
                frame.loc[:, :] = 0.0
    price = system_price_series(stripped, {"a", "b"}, stripped.get_switchable_as_dense("Load", "p_set"))
    np.testing.assert_allclose(price.to_numpy(), 20.0, rtol=1e-6)  # load-only weights


def test_metric_definitions_document_changed_fields() -> None:
    defs = metric_definitions("EUR")
    for key in ("curtailmentSeries", "systemPriceSeries", "runMeta.averageSystemPrice", "emissionsBreakdown"):
        assert defs[key]["unit"] and defs[key]["definition"]
    assert defs["systemPriceSeries"]["unit"] == "EUR/MWh"
