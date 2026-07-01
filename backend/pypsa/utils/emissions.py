"""Efficiency-aware CO₂ emission factors (M3 — fuel/thermal basis).

PyPSA stores ``carrier.co2_emissions`` on the **primary-energy (fuel)** basis —
tCO₂ per MWh of fuel *burned*. A thermal generator with ``efficiency`` η turns
one MWh of fuel into η MWh of electricity, so the fuel burned to produce one
MWh of electrical output is ``1 / η`` MWh, and the emissions per MWh *electrical*
are ``co2_emissions / η``.

This matches PyPSA's own native ``GlobalConstraint`` (``primary_energy``)
accounting, which divides dispatch by ``efficiency`` before applying the carrier
factor. The app's custom paths — the carbon-price adder, the constraint DSL
``emissions[...]`` term, the ``co2_cap`` intensity constraint, and the emissions
reports — historically used the *electrical-output* basis (efficiency ignored),
which is only correct while every efficiency is 1.0. Routing them all through
:func:`per_generator_emission_factor` puts them on the same thermal basis.

Algorithm:
    $$ \\text{ef}^{\\text{elec}}_g = \\frac{\\text{co2\\_emissions}(\\text{carrier}_g)}{\\eta_g} $$
    ASCII: ef_elec[g] = co2_emissions[carrier(g)] / efficiency[g]

Symbols:
    ef_elec[g]            tCO₂ per MWh_electrical for generator g
    co2_emissions[carrier] tCO₂ per MWh_thermal (fuel) for the carrier
    efficiency[g] (η_g)   MWh_electrical out / MWh_thermal in (dimensionless)
"""
from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
import pypsa

# Guard so a zero/negative efficiency can't produce inf/negative emissions; a
# real thermal unit is well above this and clean carriers have ef = 0 anyway.
_MIN_EFFICIENCY = 1e-6


def generator_efficiencies(network: pypsa.Network) -> pd.Series:
    """Per-generator efficiency η (MWh_e out / MWh_thermal in).

    Defaults to 1.0 when the column is absent or a value is missing, and floors
    at ``_MIN_EFFICIENCY`` so downstream division is always finite. Indexed by
    generator name.
    """
    gens = network.generators
    if "efficiency" not in gens.columns:
        return pd.Series(1.0, index=gens.index, dtype=float)
    eta = pd.to_numeric(gens["efficiency"], errors="coerce").fillna(1.0)
    return eta.where(eta > _MIN_EFFICIENCY, 1.0).astype(float)


def per_generator_emission_factor(
    network: pypsa.Network,
    ef_by_carrier: Mapping[str, float],
) -> pd.Series:
    """tCO₂ per MWh **electrical** for each generator = carrier factor ÷ efficiency.

    Args:
        network: the (built) PyPSA network.
        ef_by_carrier: carrier name → tCO₂/MWh_thermal (the primary-energy factor,
            e.g. ``network.carriers["co2_emissions"]`` or the app's
            ``emissions_factors`` map).

    Returns:
        Series indexed by generator name; 0.0 for non-emitting carriers.
    """
    gens = network.generators
    carrier_ef = gens["carrier"].map(
        lambda c: float(ef_by_carrier.get(str(c), 0.0))
    ).astype(float)
    eta = generator_efficiencies(network)
    return (carrier_ef / eta).astype(float)
