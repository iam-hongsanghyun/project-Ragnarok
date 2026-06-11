"""Pin the NATIVE ``global_constraints`` sheet path end-to-end.

The sheet rides the generic component ingestion (``_ordered_component_sheets``
iterates PyPSA's full registry, and ``_drop_broken_bus_refs`` treats its ``bus``
as optional), and PyPSA applies ``GlobalConstraint`` rows natively inside
``optimize()`` — no Ragnarok-side constraint code is involved. Until now that
was verified only by an import round-trip; this pins the solve-level effect:
a ``primary_energy`` CO₂ cap must actually bind dispatch.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.network import build_network

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
OPTIONS = {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0}


def _model(co2_cap_t: float | None) -> dict[str, list[dict[str, Any]]]:
    """1 bus, flat 100 MW load over 4 h; cheap gas (0.5 tCO2/MWh) + clean backup.

    Unconstrained, gas serves all 400 MWh. A cap of C tonnes limits gas energy
    to C / 0.5 MWh; the clean generator must cover the remainder.
    """
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]
    model: dict[str, list[dict[str, Any]]] = {
        "buses": [{"name": "b"}],
        "carriers": [
            {"name": "gas", "co2_emissions": 0.5},
            {"name": "clean", "co2_emissions": 0.0},
        ],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
        "generators": [
            {"name": "G_gas", "bus": "b", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 10.0},
            {"name": "G_clean", "bus": "b", "carrier": "clean", "p_nom": 200.0, "marginal_cost": 100.0},
        ],
    }
    if co2_cap_t is not None:
        model["global_constraints"] = [
            {
                "name": "co2_cap",
                "type": "primary_energy",
                "carrier_attribute": "co2_emissions",
                "sense": "<=",
                "constant": co2_cap_t,
            }
        ]
    return model


def test_primary_energy_co2_cap_binds_dispatch() -> None:
    """gas energy <= cap / intensity; the expensive clean unit covers the rest."""
    n, _ = build_network(_model(co2_cap_t=100.0), SCENARIO, OPTIONS)
    assert "co2_cap" in n.global_constraints.index  # sheet was ingested
    n.optimize(solver_name="highs")

    gas_mwh = float(n.generators_t.p["G_gas"].sum())
    clean_mwh = float(n.generators_t.p["G_clean"].sum())
    assert gas_mwh == pytest.approx(200.0, rel=1e-6)  # 100 t / 0.5 t/MWh
    assert clean_mwh == pytest.approx(200.0, rel=1e-6)  # remainder of 400 MWh


def test_without_cap_cheapest_serves_everything() -> None:
    """Control: no global_constraints sheet -> gas (cheapest) serves all load."""
    n, _ = build_network(_model(co2_cap_t=None), SCENARIO, OPTIONS)
    assert len(n.global_constraints.index) == 0
    n.optimize(solver_name="highs")
    assert float(n.generators_t.p["G_gas"].sum()) == pytest.approx(400.0, rel=1e-6)
