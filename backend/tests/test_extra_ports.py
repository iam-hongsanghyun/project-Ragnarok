"""P8/P9/P16: multi-port Link/Process attributes survive build, round-trip and outputs."""
from __future__ import annotations

import warnings

import pandas as pd
import pypsa
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network.serialize import network_to_model
from backend.pypsa.results.full_outputs import build_full_outputs

SC = {"carbonPrice": 0.0, "discountRate": 0.0}
OP = {"enableLoadShedding": False}


def _base() -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=6, freq="h"))
    n.add("Bus", ["a", "b", "c"])
    n.add("Load", "L", bus="b", p_set=[50, 60, 80, 90, 70, 60])
    n.add("Generator", "g", bus="a", p_nom=500, marginal_cost=10)
    # Sink at c that is paid to absorb the co-product (makes the 3rd port matter).
    n.add("Generator", "cd", bus="c", p_nom=500, marginal_cost=-1, p_min_pu=-1, p_max_pu=0)
    return n


def _solve(n):
    n.optimize(solver_name="highs", include_objective_constant=False)
    return n


def _native_link():
    n = _base()
    n.add("Link", "l", bus0="a", bus1="b", bus2="c", efficiency=0.9, efficiency2=0.3, p_nom=200)
    return n


def _native_process():
    n = _base()
    n.add("Process", "l", bus0="a", bus1="b", bus2="c", rate0=-1, rate1=0.9, rate2=0.3, p_nom=200)
    return n


@pytest.mark.parametrize("factory,sheet", [(_native_link, "links"), (_native_process, "processes")])
def test_extra_port_roundtrip_matches_native(factory, sheet):
    warnings.simplefilter("ignore")
    native = _solve(factory())
    model = network_to_model(factory())
    assert model[sheet][0]["bus2"] == "c"  # P9: no longer dropped
    built, _ = build_network(model, SC, OP)
    assert built.c[sheet].static.at["l", "bus2"] == "c"  # P8
    _solve(built)
    assert built.objective == pytest.approx(native.objective, rel=1e-9, abs=1e-6)
    # P16: dynamic p2 in full_outputs and equal to native
    out = build_full_outputs(built)["series"][f"{sheet}-p2"]
    nat_p2 = native.c[sheet].dynamic["p2"]["l"].to_numpy()
    assert [r["l"] for r in out] == pytest.approx(list(nat_p2), abs=1e-6)


def test_process_native_objective_value():
    """The P8 reference value (native 3-port Process) is 4692.2."""
    assert _solve(_native_process()).objective == pytest.approx(4692.2, abs=0.1)
