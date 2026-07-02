"""Q1 — PyPSA reference-parity suite.

The strongest "faithful frontend" guarantee: prove Ragnarok *reproduces* PyPSA,
not just round-trips its files. For each curated network we

  1. build it natively with PyPSA and solve with ``n.optimize()`` (the reference),
  2. serialize it to Ragnarok's workbook model (``network_to_model``),
  3. rebuild it through Ragnarok (``build_network``) and solve identically,

then assert the **objective**, **optimal capacities**, **dispatch**, and
**nodal prices** match within tolerance. A divergence means Ragnarok's
serialize/build path changed the problem — exactly what this pins down. One case
is also driven through the full ``run_pypsa`` results path to confirm the
reported optimal capacities equal the native ones.

Cases cover single-period dispatch, capacity expansion, and storage arbitrage.
"""
from __future__ import annotations

import pandas as pd
import pypsa
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network.serialize import network_to_model
from backend.pypsa.results import run_pypsa

RTOL = 1e-4
SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.0}
OPTIONS = {"enableLoadShedding": False, "currencySymbol": "$"}


# ── Curated reference networks (native PyPSA) ────────────────────────────────

def _dispatch_network() -> pypsa.Network:
    """Two generators, a 6-hour varying load — pure economic dispatch."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=6, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "wind")
    n.add("Carrier", "gas")
    n.add("Load", "L", bus="b", p_set=[80, 140, 200, 120, 90, 160])
    n.add("Generator", "wind", bus="b", carrier="wind", p_nom=100,
          marginal_cost=0, p_max_pu=[0.5, 0.3, 0.6, 0.4, 0.7, 0.2])
    n.add("Generator", "gas", bus="b", carrier="gas", p_nom=300, marginal_cost=60)
    return n


def _capacity_expansion_network() -> pypsa.Network:
    """Greenfield: the optimiser sizes extendable wind + gas to meet load.

    Ragnarok's convention is that model ``capital_cost`` is an **overnight** cost
    which ``build_network`` annualises (÷ lifetime, via the capital-recovery
    factor) — native PyPSA takes ``capital_cost`` as already annualised. To test
    pure *solve* parity (not the annualisation layer), ``lifetime=1`` with a zero
    discount rate makes the CRF = 1, so both use the same effective capital cost.
    """
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=8, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "wind")
    n.add("Carrier", "gas")
    n.add("Load", "L", bus="b", p_set=[100, 120, 150, 200, 180, 140, 110, 90])
    n.add("Generator", "wind", bus="b", carrier="wind", p_nom_extendable=True,
          capital_cost=90, marginal_cost=0, lifetime=1,
          p_max_pu=[0.6, 0.5, 0.4, 0.3, 0.5, 0.7, 0.8, 0.6])
    n.add("Generator", "gas", bus="b", carrier="gas", p_nom_extendable=True,
          capital_cost=40, marginal_cost=70, lifetime=1)
    return n


def _storage_network() -> pypsa.Network:
    """A battery arbitrages a cheap/expensive price split against a peaker."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=6, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "gas")
    n.add("Load", "L", bus="b", p_set=[40, 40, 120, 120, 60, 60])
    n.add("Generator", "cheap", bus="b", carrier="gas", p_nom=80, marginal_cost=20)
    n.add("Generator", "peak", bus="b", carrier="gas", p_nom=100, marginal_cost=200)
    n.add("StorageUnit", "batt", bus="b", p_nom=30, max_hours=4,
          efficiency_store=0.95, efficiency_dispatch=0.95, cyclic_state_of_charge=True)
    return n


CASES = [
    ("dispatch", _dispatch_network),
    ("capacity_expansion", _capacity_expansion_network),
    ("storage", _storage_network),
]


def _solve(n: pypsa.Network) -> None:
    n.optimize(solver_name="highs")


@pytest.mark.parametrize("name,factory", CASES, ids=[c[0] for c in CASES])
def test_build_solve_parity_with_native_pypsa(name: str, factory) -> None:
    native = factory()
    model = network_to_model(native)
    rag, _notes = build_network(model, SCENARIO, OPTIONS)

    _solve(native)
    _solve(rag)

    # Objective — the single most important parity signal.
    assert rag.objective == pytest.approx(native.objective, rel=RTOL), (
        f"{name}: objective {rag.objective} vs native {native.objective}")

    # Optimal capacities (extendable assets).
    for g in native.generators.index:
        assert float(rag.generators.at[g, "p_nom_opt"]) == pytest.approx(
            float(native.generators.at[g, "p_nom_opt"]), rel=RTOL, abs=1e-4), f"{name}: p_nom_opt[{g}]"

    # Total generation by generator (dispatch), robust to snapshot ordering.
    for g in native.generators.index:
        assert float(rag.generators_t.p[g].sum()) == pytest.approx(
            float(native.generators_t.p[g].sum()), rel=RTOL, abs=1e-3), f"{name}: energy[{g}]"

    # Nodal prices (mean over the horizon) — equal at a non-degenerate optimum.
    rag_price = float(rag.buses_t.marginal_price["b"].mean())
    nat_price = float(native.buses_t.marginal_price["b"].mean())
    assert rag_price == pytest.approx(nat_price, rel=1e-3, abs=1e-2), f"{name}: mean price"


def test_run_pypsa_reports_native_optimal_capacities() -> None:
    """The full build → solve → results path reports the native optimum."""
    native = _capacity_expansion_network()
    model = network_to_model(native)
    _solve(native)

    res = run_pypsa(model, SCENARIO, OPTIONS)
    by_name = {r["name"]: r for r in res["expansionResults"]}
    for g in native.generators.index:
        assert g in by_name, f"missing expansion result for {g}"
        assert float(by_name[g]["p_nom_opt_mw"]) == pytest.approx(
            float(native.generators.at[g, "p_nom_opt"]), rel=1e-3, abs=1e-3)
