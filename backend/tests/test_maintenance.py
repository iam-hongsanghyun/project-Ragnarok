"""P11: maintenance scheduling — force-LP relaxation, adequacy derate, result view."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pypsa
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network.serialize import network_to_model
from backend.pypsa.results.adequacy import maintenance_available_pmax
from backend.pypsa.results.commitment import build_maintenance
from backend.pypsa.results.full_outputs import build_full_outputs


def _net() -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=6, freq="h"))
    n.add("Bus", "b")
    n.add("Load", "L", bus="b", p_set=[50, 50, 50, 50, 50, 50])
    n.add("Generator", "cheap", bus="b", p_nom=100, marginal_cost=1,
          maintainable=True, maintenance_duration=2, maintenance_pu=0.5, maintenance_events=1)
    n.add("Generator", "dear", bus="b", p_nom=100, marginal_cost=50)
    return n


def test_maintenance_results_and_derate():
    n = _net()
    n.optimize(solver_name="highs", include_objective_constant=False)
    m = n.generators_t.maintenance["cheap"]
    assert m.sum() >= 2  # one 2 h event
    avail = maintenance_available_pmax(n)["cheap"].to_numpy()
    np.testing.assert_allclose(avail, 1.0 - 0.5 * m.to_numpy(), atol=1e-9)
    view = build_maintenance(n)
    assert view["totals"]["events"] == 1
    assert view["units"][0]["hoursInMaintenance"] == pytest.approx(float(m.sum()))
    assert "generators-maintenance" in build_full_outputs(n)["series"]


def test_force_lp_clears_maintainable():
    model = network_to_model(_net())
    assert model["generators"][0]["maintainable"] is True
    net, notes = build_network(model, {"carbonPrice": 0.0, "discountRate": 0.0}, {"forceLp": True})
    assert not net.generators["maintainable"].any()
    assert any("maintainable" in x for x in notes)
    net2, _ = build_network(model, {"carbonPrice": 0.0, "discountRate": 0.0}, {})
    assert bool(net2.generators.at["cheap", "maintainable"])
