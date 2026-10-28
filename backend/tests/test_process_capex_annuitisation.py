"""An extendable PyPSA ``Process`` is priced by PyPSA's ``overnight_cost`` path exactly like a ``Link``.

Ragnarok converts nothing: PyPSA annuitises the row's ``overnight_cost`` with its own ``discount_rate`` and
``lifetime`` and scales it by ``n.nyears``, for a Process as for a Link (``c.capital_cost`` of each component).

Algorithm (PyPSA's periodised cost):
    $$k_{LP} = k\\, a(r, L)\\, \\frac{H}{8760},\\qquad a(r,L)=\\frac{r(1+r)^L}{(1+r)^L-1}$$
    ASCII: k_LP = k * a(r, L) * H / 8760
    k = overnight cost (currency/MW), r = discount rate (1/a), L = lifetime (a), H = modelled hours (h).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from backend.pypsa.network import build_network
from backend.pypsa.results import run_pypsa

RTOL = 1e-12
CAPEX = 800_000.0
LIFE = 20.0
RATE = 0.05
HOURS = 24


def _model(component: str) -> dict[str, Any]:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(HOURS)]
    row: dict[str, Any] = {"name": "conv", "bus0": "el", "bus1": "h2", "p_nom_extendable": True, "p_nom_max": 500,
                           "overnight_cost": CAPEX, "discount_rate": RATE, "lifetime": LIFE, "marginal_cost": 1.0}
    row.update({"efficiency": 0.7} if component == "links" else {"rate0": -1.0, "rate1": 0.7})
    return {
        "snapshots": [{"snapshot": s} for s in snaps],
        "buses": [{"name": "el"}, {"name": "h2"}],
        "carriers": [{"name": "gas"}],
        "generators": [{"name": "g", "bus": "el", "carrier": "gas", "p_nom": 1000, "marginal_cost": 10}],
        "loads": [{"name": "L", "bus": "h2", "p_set": 30.0}],
        component: [row],
    }


def test_process_capital_cost_matches_link_with_identical_parameters() -> None:
    net_l, _ = build_network(_model("links"), {}, {})
    net_p, _notes = build_network(_model("processes"), {}, {})
    a = RATE / (1.0 - (1.0 + RATE) ** -LIFE)
    scale = HOURS / 8760.0
    expected = CAPEX * a * scale
    cost_l = float(net_l.components.links.capital_cost["conv"])
    cost_p = float(net_p.components.processes.capital_cost["conv"])
    np.testing.assert_allclose(cost_l, expected, rtol=RTOL)
    np.testing.assert_allclose(cost_p, expected, rtol=RTOL)
    np.testing.assert_allclose(cost_p, cost_l, rtol=RTOL)
    assert float(net_p.processes.at["conv", "capital_cost"]) == 0.0      # the column itself is untouched


def test_process_and_link_solve_to_the_same_expansion() -> None:
    out = {}
    for comp in ("links", "processes"):
        res = run_pypsa(_model(comp), {"discountRate": RATE}, {"snapshotWeight": 1})
        row = next(r for r in res["expansionResults"] if r["name"] == "conv")
        out[comp] = (row["p_nom_opt_mw"], res["summary"])
    np.testing.assert_allclose(out["processes"][0], out["links"][0], rtol=1e-6, atol=1e-6)
    assert out["processes"][0] > 0.0
