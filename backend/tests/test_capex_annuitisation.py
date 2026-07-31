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


# ── when a discount rate is actually required ────────────────────────────────
#
# `discountRate` is consumed by exactly one thing: the annuitisation above. It was
# once demanded of EVERY build, which meant a dispatch-only run had to supply a
# number that provably could not change its answer — so callers invented one, and
# an invented rate is indistinguishable from a stated one downstream. Ragnarok's
# own transform and imported-result paths both carried a hardcoded 0.05 purely to
# satisfy that guard.


def _dispatch_only_model() -> dict[str, Any]:
    """Same network with nothing extendable — no CAPEX, so no rate can matter."""
    model = _base_model()
    model["generators"] = [model["generators"][0]]
    return model


def test_dispatch_only_build_needs_no_discount_rate() -> None:
    network, _notes = build_network(_dispatch_only_model(), {}, {})
    assert len(network.generators) == 1


def test_free_extendable_capacity_needs_no_discount_rate() -> None:
    """0 × any annuity factor is 0, so a costless expansion needs no rate."""
    model = _base_model()
    model["generators"][1]["capital_cost"] = 0
    network, _notes = build_network(model, {}, {})
    assert float(network.generators.at["wind", "capital_cost"]) == 0.0


def test_priced_expansion_without_a_rate_is_refused_not_defaulted() -> None:
    """The one case where it matters: refuse rather than pick a rate silently.

    A default here would be the worst outcome — a low rate makes new capacity look
    cheap, so the build volume would depend on a number nobody chose.
    """
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        build_network(_base_model(), {}, {})
    assert caught.value.status_code == 400
    detail = str(caught.value.detail)
    # The message must name the envelope and say why THIS run needs it: the old
    # one said "set it in Settings", which is unactionable for an API caller.
    assert "scenario" in detail and "extendable" in detail


def test_annuitisation_opt_out_needs_no_rate() -> None:
    """`skipCapexAnnuitisation` means nothing reads a rate — the transform path."""
    network, _notes = build_network(_base_model(), {}, {"skipCapexAnnuitisation": True})
    assert float(network.generators.at["wind", "capital_cost"]) == 1_000_000
