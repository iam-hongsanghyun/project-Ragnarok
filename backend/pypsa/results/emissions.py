"""
emissions.py — per-generator and per-carrier emission breakdowns.

Returned after optimisation; does not require a second solve.
All values are in tCO₂e for totals and kg CO₂e/MWh for intensity.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import pypsa

from ..utils.emissions import primary_energy_emissions
from ..utils.series import weighted_sum

_DEFINITION = (
    "PyPSA primary_energy accounting: generators sum(w*p/efficiency)*co2_emissions; non-cyclic "
    "StorageUnits/Stores co2_emissions*(initial - final stock); Link/Process flows are not counted "
    "(emissions stay at the fuel generator). Equals the primary_energy GlobalConstraint left-hand side."
)


def build_emissions_breakdown(
    network: pypsa.Network,
    emissions_factors: dict[str, float],
) -> dict[str, Any]:
    """Emission breakdown on PyPSA's ``primary_energy`` basis (RB10).

    Algorithm:
        $$E = \\sum_g \\sum_t w_t\\,y_{p(t)}\\,\\frac{p_g(t)}{\\eta_g(t)}\\,ef_{c(g)}
            + \\sum_{s\\,\\text{non-cyclic}} ef_{c(s)}\\,(e^0_s - e^T_s)$$
        ASCII: E = sum_g sum_t w*y*p/eta*ef + sum_s ef*(e_initial - e_final).
        Same accounting as :func:`backend.pypsa.utils.emissions.primary_energy_emissions`,
        so ``total_tco2`` equals the left-hand side of a ``primary_energy``
        GlobalConstraint solved on the same network (tCO₂).

    Returns:
        {
          "byGenerator": [{ name, carrier, bus, energy_mwh, emissions_tco2, intensity_kg_mwh }],
          "byCarrier":   [{ carrier, energy_mwh, emissions_tco2, intensity_kg_mwh }],
          "byStorage":   [{ name, component, carrier, emissions_tco2 }],   # net depletion of emitting stocks
          "totalTco2": float,
          "definition": str,
        }

    energy_mwh       - weighted dispatch (MWh) over the modelled snapshots
    emissions_tco2   - tCO₂ on the constraint basis (multi-period runs apply the
                       investment-period ``years`` weighting; single-period: none)
    intensity_kg_mwh - kg CO₂e per MWh dispatched, on the snapshot-weighted basis

    Link and Process flows are not counted (PyPSA does not count them and the fuel
    generator already carries the fuel's emissions) — documented in ``definition``.
    A storage unit that charges with emitting-carrier stock contributes negative
    emissions while it refills; a depleted one positive, as in the constraint.
    """
    empty: dict[str, Any] = {"byGenerator": [], "byCarrier": [], "byStorage": [], "totalTco2": 0.0,
                             "definition": _DEFINITION}
    if network.generators_t.p.empty and network.storage_units_t.state_of_charge.empty and network.stores_t.e.empty:
        return empty

    weights = network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)
    pe = primary_energy_emissions(network, emissions_factors)
    gens = network.generators

    by_generator: list[dict[str, Any]] = []
    carrier_energy: dict[str, float] = defaultdict(float)
    carrier_emissions: dict[str, float] = defaultdict(float)
    carrier_snapshot_emissions: dict[str, float] = defaultdict(float)

    for name in gens.index:
        if name.startswith("load_shedding_") or name not in network.generators_t.p.columns:
            continue
        carrier = str(gens.at[name, "carrier"])
        energy_mwh = float(weighted_sum(network.generators_t.p[name].clip(lower=0.0), weights))
        emissions = float(pe.generators.get(name, 0.0))
        snapshot_emissions = float(pe.generators_snapshot.get(name, 0.0))
        by_generator.append({
            "name": name,
            "carrier": carrier,
            "bus": str(gens.at[name, "bus"]),
            "energy_mwh": round(energy_mwh, 1),
            "emissions_tco2": round(emissions, 2),
            "intensity_kg_mwh": round(snapshot_emissions / energy_mwh * 1000.0, 1) if energy_mwh > 0 else 0.0,
        })
        carrier_energy[carrier] += energy_mwh
        carrier_emissions[carrier] += emissions
        carrier_snapshot_emissions[carrier] += snapshot_emissions

    by_generator.sort(key=lambda x: x["emissions_tco2"], reverse=True)

    by_carrier: list[dict[str, Any]] = []
    for carrier, energy_mwh in sorted(carrier_energy.items(), key=lambda kv: kv[1], reverse=True):
        if energy_mwh <= 0:
            continue
        by_carrier.append({
            "carrier": carrier,
            "energy_mwh": round(energy_mwh, 1),
            "emissions_tco2": round(carrier_emissions[carrier], 2),
            "intensity_kg_mwh": round(carrier_snapshot_emissions[carrier] / energy_mwh * 1000.0, 1),
        })

    by_storage: list[dict[str, Any]] = []
    for component, series, static in (
        ("StorageUnit", pe.storage_units, network.storage_units),
        ("Store", pe.stores, network.stores),
    ):
        for name, tco2 in series.items():
            by_storage.append({
                "name": str(name), "component": component,
                "carrier": str(static.at[name, "carrier"]), "emissions_tco2": round(float(tco2), 2),
            })

    return {"byGenerator": by_generator, "byCarrier": by_carrier, "byStorage": by_storage,
            "totalTco2": pe.total, "definition": _DEFINITION}


def emission_totals_by_carrier(
    network: pypsa.Network,
    emissions_factors: dict[str, float],
) -> dict[str, float]:
    """tCO₂ per carrier on the ``primary_energy`` basis (generators + non-cyclic stocks).

    Sums to the left-hand side of a ``primary_energy`` GlobalConstraint; the
    result-summary "System emissions" is ``sum(values) / 1000`` ktCO₂e.
    """
    pe = primary_energy_emissions(network, emissions_factors)
    out: dict[str, float] = defaultdict(float)
    for name, tco2 in pe.generators.items():
        out[str(network.generators.at[name, "carrier"])] += float(tco2)
    for static, series in ((network.storage_units, pe.storage_units), (network.stores, pe.stores)):
        for name, tco2 in series.items():
            out[str(static.at[name, "carrier"])] += float(tco2)
    return dict(out)
