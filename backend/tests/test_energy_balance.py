"""M1 — per-carrier energy balance over a gas→electricity conversion.

A gas well feeds a CCGT Link (η=0.5) that serves an electricity load. To deliver
100 MW of power the CCGT burns 200 MW of gas, so over 4 snapshots the balances
are exact: electricity 400 MWh in/out, gas 800 MWh in/out. Single-carrier runs
return None (the carrier-mix donut already covers them).
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.network import build_network
from backend.pypsa.results.emissions import build_emissions_breakdown
from backend.pypsa.results.energy_balance import build_energy_balance

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
OPTIONS = {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0}


def _sector_model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]
    return {
        "buses": [
            {"name": "elec", "carrier": "electricity"},
            {"name": "gas", "carrier": "gas"},
        ],
        "carriers": [
            {"name": "electricity", "co2_emissions": 0.0},
            {"name": "gas", "co2_emissions": 0.2},
            {"name": "CCGT", "co2_emissions": 0.0},
        ],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "elec", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
        "generators": [
            {"name": "gas_well", "bus": "gas", "carrier": "gas", "p_nom": 500.0, "marginal_cost": 5.0},
        ],
        "links": [
            {"name": "CCGT", "bus0": "gas", "bus1": "elec", "carrier": "CCGT",
             "efficiency": 0.5, "p_nom": 500.0, "marginal_cost": 0.0},
        ],
    }


def _single_carrier_model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
        "generators": [
            {"name": "g", "bus": "b", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 10.0},
        ],
    }


def test_single_carrier_returns_none() -> None:
    n, _ = build_network(_single_carrier_model(), SCENARIO, OPTIONS)
    n.optimize(solver_name="highs")
    assert build_energy_balance(n) is None


def test_sector_coupled_balance_is_exact() -> None:
    n, _ = build_network(_sector_model(), SCENARIO, OPTIONS)
    n.optimize(solver_name="highs")
    out = build_energy_balance(n)
    assert out is not None
    by_carrier = {c["carrier"]: c for c in out["carriers"]}
    assert set(by_carrier) == {"electricity", "gas"}

    # Electricity: 100 MW × 4 h delivered by the CCGT, consumed by the load.
    elec = by_carrier["electricity"]
    assert elec["supplyMWh"] == pytest.approx(400.0, abs=1e-3)
    assert elec["demandMWh"] == pytest.approx(400.0, abs=1e-3)
    elec_src = {s["label"]: s for s in elec["sources"]}
    assert elec_src["CCGT"]["energyMWh"] == pytest.approx(400.0, abs=1e-3)
    assert elec_src["CCGT"]["kind"] == "conversion"
    elec_snk = {s["label"]: s for s in elec["sinks"]}
    assert elec_snk["Demand"]["energyMWh"] == pytest.approx(400.0, abs=1e-3)
    assert elec_snk["Demand"]["kind"] == "load"

    # Gas: 200 MW × 4 h from the well, all consumed by the CCGT (η=0.5).
    gas = by_carrier["gas"]
    assert gas["supplyMWh"] == pytest.approx(800.0, abs=1e-3)
    assert gas["demandMWh"] == pytest.approx(800.0, abs=1e-3)
    gas_src = {s["label"]: s for s in gas["sources"]}
    assert gas_src["gas"]["energyMWh"] == pytest.approx(800.0, abs=1e-3)
    assert gas_src["gas"]["kind"] == "generation"
    gas_snk = {s["label"]: s for s in gas["sinks"]}
    assert gas_snk["CCGT"]["energyMWh"] == pytest.approx(800.0, abs=1e-3)
    assert gas_snk["CCGT"]["kind"] == "conversion"


def test_conversion_emissions_counted_once_at_fuel_generator() -> None:
    """M1+M3: fuel burned in a Link is counted at the fuel generator (primary
    energy), efficiency-aware, and never double-counted on the Link itself.

    Gas well makes 800 MWh of gas to drive the η=0.5 CCGT to 400 MWh of power, so
    emissions = 800 × 0.2 = 160 tCO₂ — attributed to the well, not the CCGT.
    """
    n, _ = build_network(_sector_model(), SCENARIO, OPTIONS)
    n.optimize(solver_name="highs")
    out = build_emissions_breakdown(n, {"gas": 0.2, "electricity": 0.0, "CCGT": 0.0})
    gas = next(r for r in out["byGenerator"] if r["name"] == "gas_well")
    assert gas["emissions_tco2"] == pytest.approx(160.0, abs=1e-1)
    # The CCGT Link is not a generator → not a second emissions source.
    assert all(r["name"] != "CCGT" for r in out["byGenerator"])
    # System total equals the single fuel-generator figure (no double count).
    assert sum(r["emissions_tco2"] for r in out["byGenerator"]) == pytest.approx(160.0, abs=1e-1)
