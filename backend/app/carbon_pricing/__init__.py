"""Carbon-pricing module: the carbon price as a visible, declared objective term sent to PyPSA.

PyPSA has no native carbon price. This module owns it: the scenario's ``carbonPrice`` (and
``options.carbonPriceSchedule``) configure it, :func:`extra_functionality` adds ``price x emissions`` to
the objective, and the results read the carbon cost back from that same term. See :mod:`.term` for the
formulation and :mod:`.config` for the price series.
"""
from __future__ import annotations

from .config import (
    PLAN_KEY,
    CarbonPriceConfig,
    CarbonPriceScheduleEntry,
    config_from_run,
    early_snapshots,
    parse_carbon_price_config,
    price_series,
    snapshot_years,
)
from .term import (
    add_adder,
    adder_frame,
    build_notes,
    carbon_adder_series,
    carbon_cost,
    carbon_cost_by_generator,
    effective_marginal_cost,
    emission_factors,
    extra_functionality,
    objective_weights,
    plan_of,
    set_plan,
    write_marginal_cost_adder,
)

__all__ = [
    "PLAN_KEY", "CarbonPriceConfig", "CarbonPriceScheduleEntry", "add_adder", "adder_frame", "build_notes",
    "carbon_adder_series", "carbon_cost", "carbon_cost_by_generator", "config_from_run",
    "early_snapshots", "effective_marginal_cost", "emission_factors", "extra_functionality",
    "objective_weights", "parse_carbon_price_config", "plan_of", "price_series", "set_plan",
    "snapshot_years", "write_marginal_cost_adder",
]
