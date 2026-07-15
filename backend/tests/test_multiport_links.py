"""Multi-port Links (bus2+/efficiency2+) flow through the builder to the solve.

A gas-fed CHP Link co-produces electricity (bus1, η=0.40) and heat (bus2,
η₂=0.45). Serving 100 MW of electricity burns 250 MW of gas and co-produces
112.5 MW of heat — exact figures the tests assert against:

    p0 = 100 / 0.40 = 250 MW,   p2 = -250 × 0.45 = -112.5 MW

Over 4 snapshots: electricity 400 MWh, heat 450 MWh, gas 1000 MWh. The sheet
mixes the CHP with a plain two-port link to prove blank ``bus2`` cells stay
inert, and a broken ``bus2`` reference drops the row instead of failing
PyPSA's consistency check at solve time.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.network import build_network
from backend.pypsa.results.energy_balance import build_energy_balance

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
OPTIONS = {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0}
SNAPS = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]


def _chp_model() -> dict[str, list[dict[str, Any]]]:
    return {
        "buses": [
            {"name": "elec", "carrier": "electricity"},
            {"name": "elec2", "carrier": "electricity"},
            {"name": "gas", "carrier": "gas"},
            {"name": "heat", "carrier": "heat"},
        ],
        "carriers": [
            {"name": "electricity"},
            {"name": "gas", "co2_emissions": 0.2},
            {"name": "heat"},
            {"name": "CHP"},
        ],
        "snapshots": [{"snapshot": s} for s in SNAPS],
        "loads": [
            {"name": "L_elec", "bus": "elec", "p_set": 100.0},
            {"name": "L_heat", "bus": "heat", "p_set": 112.5},
        ],
        # build_energy_balance reads demand from loads_t.p_set, so mirror the
        # static set-points as a time-series sheet (same as the M1 tests).
        "loads-p_set": [
            {"snapshot": s, "L_elec": 100.0, "L_heat": 112.5} for s in SNAPS
        ],
        "generators": [
            {"name": "gas_well", "bus": "gas", "carrier": "gas", "p_nom": 500.0, "marginal_cost": 5.0},
        ],
        "links": [
            # efficiency2 as a string exercises the numeric coercion of
            # dynamically-registered port attributes (not in PyPSA's static
            # schema, so the generic coercion pass skips them).
            {"name": "CHP", "bus0": "gas", "bus1": "elec", "bus2": "heat",
             "carrier": "CHP", "efficiency": 0.4, "efficiency2": "0.45", "p_nom": 500.0},
            # Plain two-port link in the same sheet → blank bus2 cell.
            {"name": "tie", "bus0": "elec", "bus1": "elec2", "efficiency": 1.0, "p_nom": 50.0},
        ],
    }


def test_builder_keeps_multiport_columns() -> None:
    n, _ = build_network(_chp_model(), SCENARIO, OPTIONS)
    assert "bus2" in n.links.columns and "efficiency2" in n.links.columns
    assert n.links.at["CHP", "bus2"] == "heat"
    assert float(n.links.at["CHP", "efficiency2"]) == pytest.approx(0.45)
    # The plain link's unused port must be the empty string (NOT NaN/"nan"),
    # or PyPSA's consistency check treats it as a missing-bus reference.
    assert n.links.at["tie", "bus2"] == ""


def test_multiport_solve_produces_p2() -> None:
    n, _ = build_network(_chp_model(), SCENARIO, OPTIONS)
    status, condition = n.optimize(solver_name="highs")
    assert (status, condition) == ("ok", "optimal")
    # 100 MW of electricity → 250 MW of gas in, 112.5 MW of heat out.
    assert n.links_t.p0["CHP"].tolist() == pytest.approx([250.0] * 4)
    assert n.links_t.p2["CHP"].tolist() == pytest.approx([-112.5] * 4)


def test_energy_balance_counts_heat_coproduct() -> None:
    n, _ = build_network(_chp_model(), SCENARIO, OPTIONS)
    n.optimize(solver_name="highs")
    out = build_energy_balance(n)
    assert out is not None
    by_carrier = {c["carrier"]: c for c in out["carriers"]}

    heat = by_carrier["heat"]
    heat_src = {s["label"]: s for s in heat["sources"]}
    assert heat_src["CHP"]["energyMWh"] == pytest.approx(450.0, abs=1e-3)
    assert heat_src["CHP"]["kind"] == "conversion"
    assert heat["demandMWh"] == pytest.approx(450.0, abs=1e-3)

    # The fuel side is unchanged: all 1000 MWh of gas sink into the CHP.
    gas_snk = {s["label"]: s for s in by_carrier["gas"]["sinks"]}
    assert gas_snk["CHP"]["energyMWh"] == pytest.approx(1000.0, abs=1e-3)

    # Electricity output (bus1) still counted once, not double-counted.
    elec_src = {s["label"]: s for s in by_carrier["electricity"]["sources"]}
    assert elec_src["CHP"]["energyMWh"] == pytest.approx(400.0, abs=1e-3)


def test_broken_bus2_ref_drops_row_with_note() -> None:
    model = _chp_model()
    model["links"][0]["bus2"] = "no_such_bus"
    n, notes = build_network(model, SCENARIO, OPTIONS)
    assert "CHP" not in n.links.index
    assert "tie" in n.links.index
    assert any("bus2='no_such_bus'" in note for note in notes)


def test_time_varying_efficiency2_sheet_applies() -> None:
    """A ``links-efficiency2`` time-series sheet reaches the solve.

    η₂ drops from 0.45 to 0.30 halfway; the heat load tracks the co-product
    exactly (250 MW of gas × η₂), so the model stays feasible and ``p2``
    mirrors the varying efficiency.
    """
    model = _chp_model()
    eff2 = [0.45, 0.45, 0.30, 0.30]
    heat = [250.0 * e for e in eff2]
    model["links-efficiency2"] = [
        {"snapshot": s, "CHP": eff2[i]} for i, s in enumerate(SNAPS)
    ]
    model["loads-p_set"] = [
        {"snapshot": s, "L_elec": 100.0, "L_heat": heat[i]} for i, s in enumerate(SNAPS)
    ]
    n, _ = build_network(model, SCENARIO, OPTIONS)
    status, condition = n.optimize(solver_name="highs")
    assert (status, condition) == ("ok", "optimal")
    assert n.links_t.p2["CHP"].tolist() == pytest.approx([-h for h in heat])
