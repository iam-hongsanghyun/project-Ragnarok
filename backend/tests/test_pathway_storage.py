"""Pathway (multi-investment-period) + StorageUnit / Store solves through run_pypsa.

Regression for RE1 / P7: under PyPSA 1.2.4 with pandas 3.1 + xarray 2025.12 any
storage component in a multi-period model raised
``AlignmentError: cannot align objects on coordinate 'period'``. PyPSA 1.4 fixed
it; these tests pin that the full Ragnarok path (workbook JSON -> build ->
optimise -> results) works for StorageUnit, Store, and both.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pypsa
import pytest

from backend.pypsa.network.serialize import network_to_model
from backend.pypsa.results import run_pypsa

PERIODS = [2030, 2040]
LOAD_MW = 100.0
GAS_MC = 50.0


def _model(kind: str) -> dict[str, Any]:
    ts = pd.date_range("2030-01-01", periods=6, freq="h")
    n = pypsa.Network()
    n.set_snapshots(pd.MultiIndex.from_product([PERIODS, ts], names=["period", "timestep"]))
    n.investment_periods = PERIODS
    n.add("Carrier", ["gas", "solar", "battery"])
    n.add("Bus", "b")
    n.add("Load", "L", bus="b", p_set=LOAD_MW)
    n.add("Generator", "gas", bus="b", carrier="gas", p_nom=200, marginal_cost=GAS_MC,
          build_year=2030, lifetime=30)
    n.add("Generator", "pv", bus="b", carrier="solar", p_nom_extendable=True, capital_cost=10,
          p_max_pu=[0, 0.5, 1, 1, 0.5, 0] * 2, build_year=2030, lifetime=30)
    if kind in ("storage_unit", "both"):
        n.add("StorageUnit", "bat", bus="b", carrier="battery", p_nom_extendable=True,
              capital_cost=5, max_hours=4, build_year=2030, lifetime=20)
    if kind in ("store", "both"):
        n.add("Bus", "h")
        n.add("Store", "st", bus="h", e_nom_extendable=True, capital_cost=1,
              build_year=2030, lifetime=20)
        n.add("Link", "ch", bus0="b", bus1="h", p_nom=50, efficiency=0.9)
        n.add("Link", "dis", bus0="h", bus1="b", p_nom=50, efficiency=0.9)
    return network_to_model(n)


_OPTIONS = {
    "enableLoadShedding": False,
    "pathwayConfig": {
        "enabled": True,
        "snapshotMappingMode": "explicit_period_column",
        "periods": [{"period": p, "objectiveWeight": 1.0, "yearsWeight": 1.0} for p in PERIODS],
    },
}


@pytest.mark.parametrize("kind", ["none", "storage_unit", "store", "both"])
def test_pathway_with_storage_solves_and_balances(kind: str) -> None:
    result = run_pypsa(_model(kind), {"carbonPrice": 0.0, "discountRate": 0.0}, _OPTIONS)
    assert result["runMeta"]["planningMode"] == "pathway"
    assert result["runMeta"]["investmentPeriods"] == PERIODS
    # Analytical bound: load is a flat 100 MW over 6 h x 2 periods = 1200 MWh, so
    # total generation (storage losses only add to it) is never below that, and
    # without storage it equals it exactly.
    assert [s["period"] for s in result["pathway"]["summaries"]] == PERIODS
    generation = sum(r["value"] for r in result["generatorEnergy"] if "period" not in r)
    demand = LOAD_MW * 6 * len(PERIODS)
    if kind == "none":
        np.testing.assert_allclose(generation, demand, rtol=1e-6)
    else:
        assert generation >= demand * (1 - 1e-6)
    expansion = {e["name"]: e for e in result["expansionResults"]}
    if kind in ("storage_unit", "both"):
        assert np.isfinite(expansion["bat"]["p_nom_opt_mw"])
    if kind in ("store", "both"):
        assert expansion["st"]["component"] == "Store"
        assert np.isfinite(expansion["st"]["p_nom_opt_mw"])  # Store size (MWh) is reported in this column
