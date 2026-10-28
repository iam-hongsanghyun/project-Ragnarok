"""Cost columns reach PyPSA unchanged (build_network).

PyPSA defaults ``lifetime`` to +inf. Ragnarok no longer substitutes a fallback life or annuitises
anything itself: ``capital_cost`` is PyPSA's periodised cost per horizon, as is, and an
``overnight_cost`` is annuitised BY PyPSA with the row's own ``discount_rate`` and ``lifetime``
(``annuity(r, inf) = r``, i.e. interest only, when the life is blank). See test_cost_basis.py for
the full cost-basis suite.
"""
from __future__ import annotations

from typing import Any

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
            # Extendable, NO explicit lifetime → PyPSA default +inf (annuity = the discount rate).
            {"name": "wind", "bus": "n1", "carrier": "wind", "marginal_cost": 0,
             "p_nom": 0, "p_nom_extendable": True, "p_nom_max": 1000, "overnight_cost": 1_000_000,
             "discount_rate": 0.05},
        ],
        "loads": [{"name": "L", "bus": "n1"}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
    }


def test_extendable_asset_without_lifetime_is_priced_by_pypsa_as_interest_only() -> None:
    from pypsa.costs import annuity

    network, notes = build_network(_base_model(), {"discountRate": 0.05}, {})
    # Nothing is substituted or noted by Ragnarok: PyPSA's annuity(r, inf) is r.
    assert not any("lifetime" in n and "default" in n for n in notes)
    per_mw = float(network.components.generators.capital_cost["wind"])
    assert per_mw == pytest.approx(1_000_000 * float(annuity(0.05, float("inf"))) * (24.0 / 8760.0), rel=1e-12)
    assert float(network.generators.at["wind", "capital_cost"]) == 0.0      # the column itself is untouched


def test_high_capital_cost_curbs_expansion() -> None:
    """With a steep CAPEX the optimiser must NOT build to p_nom_max."""
    model = _base_model()
    model["generators"][1].update({"overnight_cost": 1e12})
    res = run_pypsa(model, {"discountRate": 0.05}, {"snapshotWeight": 1})
    wind = next((r for r in (res.get("expansionResults") or []) if r["name"] == "wind"), None)
    assert wind is not None
    assert wind["p_nom_opt_mw"] < 1000.0


def test_dispatch_only_build_needs_no_discount_rate() -> None:
    model = _base_model()
    model["generators"] = [model["generators"][0]]
    network, _notes = build_network(model, {}, {})
    assert len(network.generators) == 1


def test_free_extendable_capacity_needs_no_discount_rate() -> None:
    model = _base_model()
    model["generators"][1] = {k: v for k, v in model["generators"][1].items() if k not in ("overnight_cost", "discount_rate")}
    network, _notes = build_network(model, {}, {})
    assert float(network.generators.at["wind", "capital_cost"]) == 0.0


def test_an_overnight_row_without_a_rate_is_refused_not_defaulted() -> None:
    """Refuse rather than pick a rate silently: a low rate makes new capacity look cheap.

    The scenario's discountRate does NOT rescue it - the column has to be in the workbook
    (Forge -> Fill discount rate), the same message PyPSA's consistency check gives.
    """
    from fastapi import HTTPException

    model = _base_model()
    del model["generators"][1]["discount_rate"]
    for scenario in ({}, {"discountRate": 0.05}):
        with pytest.raises(HTTPException) as caught:
            build_network(model, scenario, {})
        assert caught.value.status_code == 400
        detail = str(caught.value.detail)
        assert "overnight_cost" in detail and "discount_rate" in detail and "wind" in detail


def test_a_capital_cost_only_row_is_pypsas_own_semantics_and_needs_no_rate() -> None:
    model = _base_model()
    model["generators"][1] = {k: v for k, v in model["generators"][1].items() if k not in ("overnight_cost", "discount_rate")}
    model["generators"][1]["capital_cost"] = 1_000_000
    network, _notes = build_network(model, {}, {})
    assert float(network.generators.at["wind", "capital_cost"]) == 1_000_000
