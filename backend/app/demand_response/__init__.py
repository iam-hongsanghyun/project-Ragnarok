"""Demand-response module: shiftable and price-elastic load, declared as extra PyPSA components.

PyPSA has no demand shifting. This module rewires the selected loads into the standard PyPSA pattern (a
demand bus fed by a Link, with a cyclic Store buffering the timing difference; an elastic load as a
negative-cost generator) as a ``build_step`` hook driven by ``options.demandResponseConfig``, reports what it
did in the run notes, and reads the outcome back as the ``demandResponse`` / ``priceElastic`` result blocks.
The added components are ordinary PyPSA buses, links and stores (named ``dr_*``); writing them into the
workbook as visible rows is a follow-up (the step is currently a declared, reported rewiring).
"""
from __future__ import annotations

from .shift import (
    apply_demand_response,
    apply_price_elastic,
    build_demand_response,
    build_price_elastic,
)

__all__ = ["apply_demand_response", "apply_price_elastic", "build_demand_response", "build_price_elastic"]
