"""Demand-response module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from typing import Any

from backend.app import module_hooks as mh

from .rows import elastic_kwargs, network_has_elastic, network_has_shift, shift_kwargs
from .shift import (
    apply_demand_response,
    apply_price_elastic,
    build_demand_response,
    build_price_elastic,
)

MODULE = "demand-response"

_APPLY_HINT = "Write them into the workbook with the demand-response apply step (POST /api/demand-response/apply)."


def _rewire(ctx: mh.RunContext) -> None:
    """Build what the workbook holds; create the ``dr_*`` components only for a workbook without them.

    The module's components are workbook rows written by the explicit apply step (:mod:`.rows`), and the core
    build already added them. The in-build rewiring below is the BACK-COMPAT path for stored runs and old
    workbooks whose ``options.demandResponseConfig`` asks for demand response but which carry no ``dr_*`` rows:
    it creates the same components, as builds did before the apply step existed, and says so in the notes.
    """
    dr_cfg = ctx.options.get("demandResponseConfig") or {}
    shift, elastic = shift_kwargs(dr_cfg), elastic_kwargs(dr_cfg)

    n_shift = network_has_shift(ctx.network)
    if n_shift:
        ctx.notes.append(f"Demand response: {n_shift} shiftable load(s) from the workbook rows (dr_* bus, drlink_* link, drstore_* store).")
    elif shift["enabled"]:
        ctx.notes.append(f"Demand response (legacy): the workbook has no dr_* rows, so the shiftable loads are created at build time. {_APPLY_HINT}")
        apply_demand_response(ctx.network, ctx.notes, **shift)

    n_elastic = network_has_elastic(ctx.network)
    if n_elastic:
        ctx.notes.append(f"Price-elastic demand: {n_elastic} block(s) from the workbook rows (load_shedding_elastic_* generators).")
    elif elastic["enabled"]:
        ctx.notes.append(f"Price-elastic demand (legacy): the workbook has no elastic rows, so the blocks are created at build time. {_APPLY_HINT}")
        apply_price_elastic(ctx.network, ctx.notes, **elastic)


def _outcome(ctx: mh.RunContext) -> dict[str, Any]:
    return {
        "demandResponse": build_demand_response(ctx.network),  # shiftable-load outcome; None if no DR
        "priceElastic": build_price_elastic(ctx.network),  # elastic-demand outcome; None if none
    }


mh.register("build_step", "demand-response", _rewire, module=MODULE, order=10)
mh.register("study", "demand-response", _outcome, module=MODULE, order=10,
            payload_keys=("demandResponse", "priceElastic"))
