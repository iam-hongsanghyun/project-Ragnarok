"""M3 — fuel/thermal basis: CO₂ emissions and carbon cost are efficiency-aware.

PyPSA stores ``carrier.co2_emissions`` on the primary-energy (fuel) basis, so a
thermal generator with efficiency η burns ``1/η`` MWh of fuel per MWh delivered
and emits ``co2_emissions / η`` per MWh electrical. These pins check that the
app's custom paths (the emission-factor helper, the carbon-price adder, the
emissions breakdown, and the custom ``co2_cap`` constraint) all use that basis —
and that η = 1 reproduces the historical output-basis numbers.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa
import pytest

from backend.pypsa.carbon_price import apply_carbon_price, parse_carbon_price_config
from backend.pypsa.network import build_network
from backend.pypsa.network.custom_constraints import apply_custom_constraints
from backend.pypsa.results.emissions import build_emissions_breakdown
from backend.pypsa.utils.emissions import per_generator_emission_factor

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
OPTIONS_4H = {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0}


# ── The helper ────────────────────────────────────────────────────────────────
def test_effective_factor_divides_by_efficiency() -> None:
    """ef_electrical = co2_emissions / η, per generator."""
    n = pypsa.Network()
    n.add("Carrier", "gas", co2_emissions=0.4)
    n.add("Bus", "b")
    n.add("Generator", "g_hi", bus="b", carrier="gas", efficiency=1.0)
    n.add("Generator", "g_lo", bus="b", carrier="gas", efficiency=0.5)
    ef = per_generator_emission_factor(n, {"gas": 0.4})
    assert ef["g_hi"] == pytest.approx(0.4)
    assert ef["g_lo"] == pytest.approx(0.8)  # 0.4 / 0.5


def test_effective_factor_defaults_to_one_and_guards_zero() -> None:
    """Missing η → 1.0; a zero/blank η is floored (never inf); clean stays 0."""
    n = pypsa.Network()
    n.add("Carrier", "gas", co2_emissions=0.4)
    n.add("Carrier", "wind", co2_emissions=0.0)
    n.add("Bus", "b")
    n.add("Generator", "g", bus="b", carrier="gas")  # PyPSA default η = 1.0
    n.add("Generator", "w", bus="b", carrier="wind", efficiency=0.9)
    n.add("Generator", "z", bus="b", carrier="gas", efficiency=0.0)
    ef = per_generator_emission_factor(n, {"gas": 0.4, "wind": 0.0})
    assert ef["g"] == pytest.approx(0.4)
    assert ef["w"] == pytest.approx(0.0)          # zero carrier factor stays zero
    assert ef["z"] == pytest.approx(0.4)          # η=0 floored to 1.0, finite
    assert float(ef["z"]) < float("inf")


# ── Carbon-price adder ──────────────────────────────────────────────────────
def test_carbon_adder_is_efficiency_aware() -> None:
    """adder = price × co2 / η. At η=0.5 the adder doubles vs the η=1 baseline."""
    n = pypsa.Network()
    n.set_snapshots(pd.DatetimeIndex(["2025-01-01"]))
    n.add("Carrier", "gas", co2_emissions=0.4)
    n.add("Bus", "b")
    n.add("Generator", "g", bus="b", carrier="gas", marginal_cost=20.0, efficiency=0.5)
    apply_carbon_price(n, parse_carbon_price_config(50.0, None), [], "$")
    # 20 + 50 × 0.4 / 0.5 = 20 + 40 = 60
    assert n.generators.at["g", "marginal_cost"] == pytest.approx(60.0)


def test_carbon_adder_efficiency_one_is_unchanged() -> None:
    """Back-compat: η = 1 gives the historical price × co2 adder."""
    n = pypsa.Network()
    n.set_snapshots(pd.DatetimeIndex(["2025-01-01"]))
    n.add("Carrier", "gas", co2_emissions=0.4)
    n.add("Bus", "b")
    n.add("Generator", "g", bus="b", carrier="gas", marginal_cost=20.0)  # η = 1
    apply_carbon_price(n, parse_carbon_price_config(50.0, None), [], "$")
    assert n.generators.at["g", "marginal_cost"] == pytest.approx(40.0)


# ── Emissions breakdown (post-solve reporting) ──────────────────────────────
def test_emissions_breakdown_is_efficiency_aware() -> None:
    """A gas unit at η=0.5 reports double the emissions of the output basis."""
    n = pypsa.Network()
    n.set_snapshots(pd.DatetimeIndex(["2025-01-01"]))
    n.add("Carrier", "gas", co2_emissions=0.4)
    n.add("Bus", "b")
    n.add("Generator", "g", bus="b", carrier="gas", p_nom=200.0, marginal_cost=10.0, efficiency=0.5)
    n.add("Load", "L", bus="b", p_set=100.0)
    n.optimize(solver_name="highs")

    out = build_emissions_breakdown(n, {"gas": 0.4})
    gen = next(r for r in out["byGenerator"] if r["name"] == "g")
    assert gen["energy_mwh"] == pytest.approx(100.0)
    assert gen["emissions_tco2"] == pytest.approx(80.0)     # 100 × 0.4 / 0.5
    assert gen["intensity_kg_mwh"] == pytest.approx(800.0)  # (0.4 / 0.5) × 1000


# ── Solve-level custom co2_cap intensity constraint ─────────────────────────
def _capped_model(efficiency: float) -> dict[str, list[dict[str, Any]]]:
    """1 bus, flat 100 MW load over 4 h (400 MWh). Cheap gas + expensive clean."""
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]
    return {
        "buses": [{"name": "b"}],
        "carriers": [
            {"name": "gas", "co2_emissions": 0.4},
            {"name": "clean", "co2_emissions": 0.0},
        ],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
        "generators": [
            {"name": "G_gas", "bus": "b", "carrier": "gas", "p_nom": 200.0,
             "marginal_cost": 10.0, "efficiency": efficiency},
            {"name": "G_clean", "bus": "b", "carrier": "clean", "p_nom": 200.0,
             "marginal_cost": 100.0},
        ],
    }


def _co2_cap_ef(value: float, factors: dict[str, float]):
    """extra_functionality applying a co2_cap intensity constraint per window."""
    cons = [{"enabled": True, "metric": "co2_cap", "value": value, "label": "cap"}]

    def extra_functionality(net: pypsa.Network, snapshots: Any) -> None:
        apply_custom_constraints(net, cons, factors, [], snapshots)

    return extra_functionality


def test_custom_co2_cap_is_efficiency_aware() -> None:
    """η=0.5 → effective 0.8 tCO₂/MWh_e; a 0.4 tCO₂/MWh cap limits gas to 200 MWh.

    Constraint: (0.4/0.5)·g ≤ 0.4·(g + c) with g + c = 400 ⇒ 0.8g ≤ 0.4·400 ⇒
    g ≤ 200. Only the thermal (÷η) basis binds gas here; the output basis would
    leave it unconstrained.
    """
    n, _ = build_network(_capped_model(efficiency=0.5), SCENARIO, OPTIONS_4H)
    assert n.generators.at["G_gas", "efficiency"] == pytest.approx(0.5)
    n.optimize(solver_name="highs", extra_functionality=_co2_cap_ef(0.4, {"gas": 0.4, "clean": 0.0}))
    assert float(n.generators_t.p["G_gas"].sum()) == pytest.approx(200.0, abs=1e-3)
    assert float(n.generators_t.p["G_clean"].sum()) == pytest.approx(200.0, abs=1e-3)


def test_custom_co2_cap_efficiency_one_leaves_gas_unconstrained() -> None:
    """Control: at η=1 the effective factor is 0.4, so a 0.4 tCO₂/MWh intensity
    cap is exactly the gas intensity — gas serves the full 400 MWh."""
    n, _ = build_network(_capped_model(efficiency=1.0), SCENARIO, OPTIONS_4H)
    n.optimize(solver_name="highs", extra_functionality=_co2_cap_ef(0.4, {"gas": 0.4, "clean": 0.0}))
    assert float(n.generators_t.p["G_gas"].sum()) == pytest.approx(400.0, abs=1e-3)
