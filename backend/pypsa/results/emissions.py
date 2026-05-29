"""
emissions.py — per-generator and per-carrier emission breakdowns.

Returned after optimisation; does not require a second solve.
All values are in tCO₂e for totals and kg CO₂e/MWh for intensity.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import pypsa

from ..utils.series import weighted_sum


def build_emissions_breakdown(
    network: pypsa.Network,
    emissions_factors: dict[str, float],
) -> dict[str, list[dict[str, Any]]]:
    """
    Returns:
        {
          "byGenerator": [
            { name, carrier, bus, energy_mwh, emissions_tco2, intensity_kg_mwh }, ...
          ],
          "byCarrier": [
            { carrier, energy_mwh, emissions_tco2, intensity_kg_mwh }, ...
          ]
        }

    energy_mwh      — weighted dispatch (MWh) over the modelled period
    emissions_tco2  — tCO₂e over the modelled period
    intensity_kg_mwh — kg CO₂e / MWh dispatched
    """
    if network.generators_t.p.empty:
        return {"byGenerator": [], "byCarrier": []}

    weights = network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)

    # ── Per-generator ─────────────────────────────────────────────────────────
    by_generator: list[dict[str, Any]] = []
    carrier_energy: dict[str, float] = defaultdict(float)
    carrier_emissions: dict[str, float] = defaultdict(float)

    for name in network.generators.index:
        # Skip system helpers
        if name.startswith("load_shedding_"):
            continue
        if name not in network.generators_t.p.columns:
            continue

        carrier = str(network.generators.at[name, "carrier"])
        ef = emissions_factors.get(carrier, 0.0)       # tCO₂/MWh_e
        bus = str(network.generators.at[name, "bus"])

        dispatch = network.generators_t.p[name].clip(lower=0.0)
        energy_mwh = float(weighted_sum(dispatch, weights))
        emissions_tco2 = energy_mwh * ef
        intensity_kg = ef * 1000.0  # tCO₂/MWh → kg CO₂e/MWh (constant, independent of dispatch)

        by_generator.append({
            "name": name,
            "carrier": carrier,
            "bus": bus,
            "energy_mwh": round(energy_mwh, 1),
            "emissions_tco2": round(emissions_tco2, 2),
            "intensity_kg_mwh": round(intensity_kg, 1),
        })

        carrier_energy[carrier] += energy_mwh
        carrier_emissions[carrier] += emissions_tco2

    # Sort by emissions descending
    by_generator.sort(key=lambda x: x["emissions_tco2"], reverse=True)

    # ── Per-carrier ───────────────────────────────────────────────────────────
    by_carrier: list[dict[str, Any]] = []
    for carrier, energy_mwh in sorted(carrier_energy.items(), key=lambda kv: kv[1], reverse=True):
        if energy_mwh <= 0:
            continue
        ems = carrier_emissions[carrier]
        by_carrier.append({
            "carrier": carrier,
            "energy_mwh": round(energy_mwh, 1),
            "emissions_tco2": round(ems, 2),
            "intensity_kg_mwh": round(ems / energy_mwh * 1000.0, 1) if energy_mwh > 0 else 0.0,
        })

    return {"byGenerator": by_generator, "byCarrier": by_carrier}
