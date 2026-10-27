"""P14: start-up / shut-down costs priced per snapshot for Generator, Link, Process."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pypsa
import pytest

from backend.pypsa.results.commitment import build_commitment
from backend.pypsa.results.market import build_commitment_cost


def _network() -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=8, freq="h"))
    n.snapshot_weightings.loc[:, :] = 2.0
    n.add("Bus", ["a", "b"])
    # Demand alternates so committable units must cycle.
    n.add("Load", "L", bus="b", p_set=[0, 90, 0, 90, 0, 90, 0, 90])
    n.add("Generator", "src", bus="a", p_nom=1000, marginal_cost=1)
    n.add("Generator", "g", bus="b", p_nom=100, marginal_cost=50, committable=True,
          p_min_pu=0.5, start_up_cost=10.0, shut_down_cost=3.0)
    n.generators_t.start_up_cost["g"] = [10, 20, 30, 40, 50, 60, 70, 80.0]
    n.add("Link", "k", bus0="a", bus1="b", p_nom=100, marginal_cost=40, committable=True,
          p_min_pu=0.5, start_up_cost=5.0)
    n.add("Process", "p", bus0="a", bus1="b", rate0=-1, rate1=1, p_nom=100,
          marginal_cost=45, committable=True, p_min_pu=0.5, start_up_cost=7.0)
    return n


def test_commitment_cost_matches_native_opex():
    n = _network()
    n.optimize(solver_name="highs", include_objective_constant=False)
    events = sum(float(n.c[c].dynamic["start_up"].to_numpy().sum()) for c in ("generators", "links", "processes"))
    assert events > 0  # the scenario really cycles
    native = float(
        n.statistics.opex(cost_types=["start_up_cost", "shut_down_cost"], aggregate_across_components=True)
        .sum()
    )
    assert build_commitment_cost(n) == pytest.approx(native, rel=1e-9, abs=1e-6)
    com = build_commitment(n, currency="USD")
    assert {r["component"] for r in com["generators"]} >= {"generators"}
    start_only = float(
        n.statistics.opex(cost_types=["start_up_cost"], aggregate_across_components=True).sum()
    )
    assert com["totals"]["startUpCostTotal"] == pytest.approx(start_only, rel=1e-9, abs=0.01)
