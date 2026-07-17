"""Regression tests for the imported-result derivation paths.

Pins three review findings:

1. ``derive_imported_result`` line loading must include transformers and rate
   branches against the SOLVED capacity (``s_nom_opt`` / ``p_nom_opt`` when the
   stored outputs carry one > 0), not the input nameplate.
2. ``derive_imported_result`` CO₂ shadow must be null-safe on a stored
   ``carbonPrice: null`` and schedule-aware when the run was solved with a
   ``carbonPriceSchedule`` (the schedule supersedes the scalar).
3. ``derive_results_from_outputs`` must NOT strip ``enableLoadShedding`` — it is
   a build-time model option; stripping it rebuilt a network without the
   ``load_shedding_*`` generators, so their stored dispatch columns were dropped
   and a run that shed load derived as zero shed energy.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from backend.pypsa.results import run_pypsa
from backend.pypsa.results.derive_outputs import derive_results_from_outputs
from backend.pypsa.results.from_outputs import derive_imported_result

SNAPS = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]


def _transformer_model() -> dict[str, list[dict[str, Any]]]:
    """Two buses joined by a transformer (via a type-catalogue reference, the
    schema-driven import path), plus a generator and a load."""
    return {
        "buses": [{"name": "bus_a", "v_nom": 380.0}, {"name": "bus_b", "v_nom": 110.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "snapshots": [{"snapshot": s} for s in SNAPS],
        "loads": [{"name": "L", "bus": "bus_b", "p_set": 300.0}],
        "generators": [
            {"name": "gas1", "bus": "bus_a", "carrier": "gas", "p_nom": 400.0,
             "marginal_cost": 50.0},
        ],
        "transformer_types": [
            {"name": "T-380-110", "s_nom": 600.0, "v_nom_0": 380.0, "v_nom_1": 110.0,
             "vsc": 12.0, "vscr": 0.5},
        ],
        "transformers": [
            {"name": "TX1", "bus0": "bus_a", "bus1": "bus_b", "type": "T-380-110",
             "s_nom": 600.0},
        ],
    }


def _stored_outputs(transformer_s_nom_opt: float | None = None) -> dict[str, Any]:
    """Hand-crafted stored outputs, as an imported (never re-solved) file
    carries them: dispatch, nodal prices, transformer flow."""
    outputs: dict[str, Any] = {
        "series": {
            "generators-p": [{"snapshot": s, "gas1": 300.0} for s in SNAPS],
            "buses-marginal_price": [
                {"snapshot": s, "bus_a": 50.0, "bus_b": 50.0} for s in SNAPS
            ],
            "transformers-p0": [{"snapshot": s, "TX1": 300.0} for s in SNAPS],
        },
        "static": {},
    }
    if transformer_s_nom_opt is not None:
        outputs["static"]["transformers"] = {"TX1": {"s_nom_opt": transformer_s_nom_opt}}
    return outputs


# ── 1. Line loading: transformers included, solved rating preferred ─────────

def test_imported_line_loading_includes_transformers() -> None:
    derived = derive_imported_result(
        _transformer_model(), {"carbonPrice": 0.0, "discountRate": 0.05}, {},
        _stored_outputs(),
    )
    loading = {row["label"]: row["value"] for row in derived["lineLoading"]}
    assert "TX1" in loading, "transformer flows must appear in line loading"
    # 300 MW over the input s_nom of 600 MVA (no solved rating stored).
    np.testing.assert_allclose(loading["TX1"], 50.0, rtol=1e-9, atol=1e-9)


def test_imported_line_loading_uses_solved_rating_when_stored() -> None:
    derived = derive_imported_result(
        _transformer_model(), {"carbonPrice": 0.0, "discountRate": 0.05}, {},
        _stored_outputs(transformer_s_nom_opt=1200.0),
    )
    loading = {row["label"]: row["value"] for row in derived["lineLoading"]}
    # 300 MW over the SOLVED 1200 MVA — not the 600 MVA input nameplate.
    np.testing.assert_allclose(loading["TX1"], 25.0, rtol=1e-9, atol=1e-9)


# ── 2. CO₂ shadow: null-safe scalar, schedule-aware ─────────────────────────

def test_imported_co2_shadow_null_carbon_price_is_safe() -> None:
    # A stored ``carbonPrice: null`` used to raise TypeError and kill the
    # whole derivation.
    derived = derive_imported_result(
        _transformer_model(), {"carbonPrice": None, "discountRate": 0.05}, {},
        _stored_outputs(),
    )
    assert derived["co2Shadow"]["explicit_price"] == pytest.approx(0.0)


def test_imported_co2_shadow_uses_carbon_price_schedule() -> None:
    # The run was solved with a schedule — the shadow card must show the
    # schedule-derived price, not the stale scalar.
    derived = derive_imported_result(
        _transformer_model(),
        {"carbonPrice": 25.0, "discountRate": 0.05},
        {"carbonPriceSchedule": [{"year": 2030, "price": 90.0}]},
        _stored_outputs(),
    )
    assert derived["co2Shadow"]["explicit_price"] == pytest.approx(90.0)


# ── 3. Derivation keeps load shedding ────────────────────────────────────────

def _shortfall_model() -> dict[str, list[dict[str, Any]]]:
    """Load exceeds installed capacity at two snapshots — only feasible with
    the load-shedding backstop enabled."""
    load = [80.0, 150.0, 120.0, 60.0]  # 100 MW installed → 50 + 20 MWh shed
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in SNAPS],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(SNAPS, load)],
        "generators": [
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 100.0,
             "marginal_cost": 50.0},
        ],
    }


def test_derive_retains_load_shedding() -> None:
    scenario = {"carbonPrice": 0.0, "discountRate": 0.05}
    options = {"currencySymbol": "$", "ownerColumn": "owner",
               "enableLoadShedding": True, "loadSheddingCost": 5000.0}
    fresh = run_pypsa(_shortfall_model(), scenario, dict(options))
    fresh_shed = next(
        r["value"] for r in fresh["costBreakdown"] if r["label"] == "Load shedding"
    )
    assert fresh_shed > 0.0, "the fixture must actually shed load"

    derived = derive_results_from_outputs(
        _shortfall_model(), fresh["outputs"], scenario, dict(options)
    )
    derived_shed = next(
        r["value"] for r in derived["costBreakdown"] if r["label"] == "Load shedding"
    )
    # Deriving used to strip enableLoadShedding, drop the load_shedding_* dispatch
    # columns as "not present in the model", and report zero shed energy.
    np.testing.assert_allclose(derived_shed, fresh_shed, rtol=1e-6, atol=1e-6)
    # The stored shed dispatch column survives the round trip too.
    gen_p = derived["outputs"]["series"]["generators-p"]
    assert any(k.startswith("load_shedding_") for k in gen_p[0].keys())
