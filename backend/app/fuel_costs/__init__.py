"""Fuel-costs module: fuel price series become each unit's time-varying marginal cost at run time.

PyPSA's ``marginal_cost`` is one number per unit; a fuel price is a time series per carrier and a thermal unit pays
``fuel / efficiency`` per MWh of electricity. This module owns that translation. Its inputs are two visible sheets
(``RAGNAROK_FuelPrices``, ``RAGNAROK_VariableOM``) plus the carriers column ``fuel_cost_thermal``; at run time (a
``build_step`` hook) it writes ``generators_t.marginal_cost`` / ``links_t.marginal_cost`` and says so in the run notes;
its results (a ``study`` hook) show each unit's fuel / VOM / carbon split and an ex-post LCOE.

Carbon stays with :mod:`backend.app.carbon_pricing` (an objective term, never in ``marginal_cost``) and the system
marginal price is an OUTPUT (``buses_t.marginal_price``): nothing here writes either. See :mod:`.plan` for the
formulation and the Link convention, :mod:`.inputs` for the sheets, :mod:`.report` for the breakdown and LCOE.
"""
from __future__ import annotations

from .inputs import (
    FLAT_COLUMN,
    SHEET_PRICES,
    SHEET_VOM,
    PriceSet,
    VomTable,
    flat_prices,
    has_inputs,
    is_enabled,
    price_set,
    priced_carriers,
    read_price_sheet,
    read_vom,
)
from .plan import (
    AppliedUnit,
    FuelPlan,
    UnitSpec,
    apply_plan,
    build_plan,
    efficiency_problems,
    raise_on_efficiency_problems,
    resolve_units,
)
from .report import SMP_REFERENCE, components, preview, results, unit_rows

__all__ = [
    "FLAT_COLUMN", "SHEET_PRICES", "SHEET_VOM", "SMP_REFERENCE", "AppliedUnit", "FuelPlan", "PriceSet", "UnitSpec",
    "VomTable", "apply_plan", "build_plan", "components", "efficiency_problems", "flat_prices", "has_inputs",
    "is_enabled", "preview", "price_set", "priced_carriers", "raise_on_efficiency_problems", "read_price_sheet",
    "read_vom", "resolve_units", "results", "unit_rows",
]
