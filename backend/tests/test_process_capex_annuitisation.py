"""An extendable PyPSA ``Process`` carries an annuitised, window-scaled ``capital_cost``, exactly like a ``Link``.

Regression: ``annuitisable`` in ``build_network`` listed generators, storage units, stores, lines and links
only, so an extendable Process was charged its OVERNIGHT cost against one modelled window.

Algorithm (annualisation, window scaling):
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
                           "capital_cost": CAPEX, "lifetime": LIFE, "marginal_cost": 1.0}
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
    net_l, _ = build_network(_model("links"), {"discountRate": RATE}, {})
    net_p, notes = build_network(_model("processes"), {"discountRate": RATE}, {})
    a = RATE / (1.0 - (1.0 + RATE) ** -LIFE)
    scale = HOURS / 8760.0
    expected = CAPEX * a * scale
    np.testing.assert_allclose(float(net_l.links.at["conv", "capital_cost"]), expected, rtol=RTOL)
    np.testing.assert_allclose(float(net_p.processes.at["conv", "capital_cost"]), expected, rtol=RTOL)
    np.testing.assert_allclose(float(net_p.processes.at["conv", "capital_cost"]),
                               float(net_l.links.at["conv", "capital_cost"]), rtol=RTOL)
    assert any("Process" in n or "process" in n for n in notes if "Annualised CAPEX" in n)


def test_process_and_link_solve_to_the_same_expansion() -> None:
    out = {}
    for comp in ("links", "processes"):
        res = run_pypsa(_model(comp), {"discountRate": RATE}, {"snapshotWeight": 1})
        row = next(r for r in res["expansionResults"] if r["name"] == "conv")
        out[comp] = (row["p_nom_opt_mw"], res["summary"])
    np.testing.assert_allclose(out["processes"][0], out["links"][0], rtol=1e-6, atol=1e-6)
    assert out["processes"][0] > 0.0
