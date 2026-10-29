"""Demand-response module: shiftable and price-elastic load, written as visible PyPSA workbook rows.

PyPSA has no demand shifting. This module expresses it in the standard PyPSA pattern (a demand bus fed by a Link,
with a cyclic Store buffering the timing difference; an elastic load as stepped negative-cost generators) and
WRITES those components into the model sheets through an explicit apply step (:mod:`.rows`;
``POST /api/demand-response/apply``, MCP ``apply_demand_response``). The run then builds what the workbook holds
and reads the outcome back as the ``demandResponse`` / ``priceElastic`` result blocks.

Back-compat: a stored run or an old workbook whose ``options.demandResponseConfig`` asks for demand response but
which carries no ``dr_*`` rows is rewired at build time, as before (the ``build_step`` hook says so in the notes).
"""
from __future__ import annotations

from .rows import compute_rows, remove_rows, workbook_rows
from .shift import (
    apply_demand_response,
    apply_price_elastic,
    build_demand_response,
    build_price_elastic,
)

__all__ = [
    "apply_demand_response", "apply_price_elastic", "build_demand_response", "build_price_elastic",
    "compute_rows", "remove_rows", "workbook_rows",
]
