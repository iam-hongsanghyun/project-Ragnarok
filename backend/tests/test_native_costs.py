"""P15: PyPSA-native overnight_cost / fom_cost flow through build and reports."""
from __future__ import annotations

import pandas as pd
import pypsa
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network.serialize import network_to_model
from backend.pypsa.results.expansion import build_expansion_results


def _net() -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=24, freq="h"))
    n.add("Bus", "b")
    n.add("Load", "L", bus="b", p_set=50)
    n.add("Generator", "g", bus="b", p_nom_extendable=True, overnight_cost=1000,
          discount_rate=0.07, lifetime=20, fom_cost=10)
    n.add("Generator", "peak", bus="b", p_nom=100, marginal_cost=500)
    return n


def test_native_overnight_and_fom_match_pypsa_objective():
    n = _net()
    n.optimize(solver_name="highs", include_objective_constant=False)
    model = network_to_model(n)
    built, _ = build_network(model, {"discountRate": 0.07}, {"skipCapexAnnuitisation": False})
    built.optimize(solver_name="highs", include_objective_constant=False)
    assert built.objective == pytest.approx(n.objective, rel=1e-9)
    rows = build_expansion_results(built)
    row = rows[0]
    opt = float(built.generators.at["g", "p_nom_opt"])
    assert opt == pytest.approx(50.0)
    window_capex = row["capex_annual"] * 24 / 8760
    native = float(n.statistics.capex().sum())
    assert window_capex == pytest.approx(native, rel=1e-3)
    assert row["fom_total"] == pytest.approx(float(n.statistics.fom().sum()), rel=1e-6)


def test_missing_discount_rate_filled_from_scenario():
    n = _net()
    n.generators.loc["g", "discount_rate"] = float("nan")
    model = network_to_model(n)
    built, _ = build_network(model, {"discountRate": 0.07}, {})
    assert built.generators.at["g", "discount_rate"] == pytest.approx(0.07)
