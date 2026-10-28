"""Emissions module: the CO2 accounting PyPSA has no statistic for, on PyPSA's own ``primary_energy`` basis.

One factor definition (:func:`thermal_basis_factor`: carrier ``co2_emissions`` / efficiency), one carrier map
(:func:`carrier_emission_factors`), the per-run totals that equal the ``primary_energy`` GlobalConstraint
left-hand side (:func:`primary_energy_emissions`, :func:`emission_totals_by_carrier`) and the by-carrier /
by-generator breakdown (:func:`build_emissions_breakdown`, the ``emissionsBreakdown`` result block, a ``study``
hook in :mod:`.hooks`).
"""
from __future__ import annotations

from .accounting import (
    PrimaryEnergyEmissions,
    carrier_emission_factors,
    generator_efficiencies,
    per_generator_emission_factor,
    primary_energy_emissions,
    thermal_basis_factor,
)
from .breakdown import build_emissions_breakdown, emission_totals_by_carrier

__all__ = [
    "PrimaryEnergyEmissions", "build_emissions_breakdown", "carrier_emission_factors", "emission_totals_by_carrier",
    "generator_efficiencies", "per_generator_emission_factor", "primary_energy_emissions", "thermal_basis_factor",
]
