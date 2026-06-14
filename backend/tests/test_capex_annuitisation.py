"""CAPEX annuitisation for extendable assets (build_network).

Regression: PyPSA defaults ``lifetime`` to +inf, and ``annuity_factor(rate, inf)``
is NaN — so an extendable asset with no explicit lifetime used to annuitise its
``capital_cost`` to NaN → 0 in the objective, building for FREE up to its max
(and reporting zero CAPEX). build_network must fall back to a finite lifetime so
the cost is actually priced.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.results import run_pypsa


def _base_model() -> dict[str, Any]:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(24)]
    load = [300 if 8 <= h <= 20 else 120 for h in range(24)]
    return {
        "snapshots": [{"snapshot": s} for s in snaps],
        "buses": [{"name": "n1"}],
        "carriers": [{"name": "gas"}, {"name": "wind"}],
        "generators": [
            {"name": "gas", "bus": "n1", "carrier": "gas", "p_nom": 1000, "marginal_cost": 80},
            # Extendable, NO explicit lifetime → PyPSA default +inf.
            {"name": "wind", "bus": "n1", "carrier": "wind", "marginal_cost": 0,
             "p_nom": 0, "p_nom_extendable": True, "p_nom_max": 1000, "capital_cost": 1_000_000},
        ],
        "loads": [{"name": "L", "bus": "n1"}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
    }


def test_extendable_asset_without_lifetime_gets_finite_annuitised_capex() -> None:
    network, _notes = build_network(_base_model(), {"discountRate": 0.05}, {})
    cc = float(network.generators.at["wind", "capital_cost"])
    # Not NaN, and the overnight cost × the 20-year-fallback annuity factor
    # (≈ 0.08024) — finite, positive, and not the raw 1e6 (which would mean no
    # annuitisation).
    assert np.isfinite(cc)
    expected = 1_000_000 * (0.05 / (1 - (1.05) ** -20))
    assert cc == pytest.approx(expected)


def test_high_capital_cost_curbs_expansion() -> None:
    """With a steep CAPEX the optimiser must NOT build to p_nom_max."""
    model = _base_model()
    model["generators"][1]["capital_cost"] = 1e12  # absurdly expensive → build ~0
    res = run_pypsa(model, {"discountRate": 0.05}, {"snapshotWeight": 1})
    wind = next((r for r in (res.get("expansionResults") or []) if r["name"] == "wind"), None)
    assert wind is not None
    assert wind["p_nom_opt_mw"] < 1000.0  # not maxed out (was 1000 with the NaN bug)
