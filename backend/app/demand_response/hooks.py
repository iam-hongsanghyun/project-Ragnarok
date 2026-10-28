"""Demand-response module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from typing import Any

from backend.app import module_hooks as mh

from .shift import (
    apply_demand_response,
    apply_price_elastic,
    build_demand_response,
    build_price_elastic,
)

MODULE = "demand-response"


def _rewire(ctx: mh.RunContext) -> None:
    """Rewire tagged loads into the shiftable (DR bus + Link + Store) and price-elastic patterns."""
    dr_cfg = ctx.options.get("demandResponseConfig") or {}
    if dr_cfg.get("enabled"):
        apply_demand_response(
            ctx.network,
            ctx.notes,
            enabled=True,
            loads=dr_cfg.get("loads") or None,
            shift_fraction=float(dr_cfg.get("shiftFraction", 0.2) or 0.0),
            max_shift_hours=float(dr_cfg.get("maxShiftHours", 4.0) or 0.0),
        )
    if dr_cfg.get("elasticEnabled"):
        apply_price_elastic(
            ctx.network,
            ctx.notes,
            enabled=True,
            loads=dr_cfg.get("loads") or None,
            fraction=float(dr_cfg.get("elasticFraction", 0.2) or 0.0),
            wtp_max=float(dr_cfg.get("wtpMax", 200.0) or 0.0),
        )


def _outcome(ctx: mh.RunContext) -> dict[str, Any]:
    return {
        "demandResponse": build_demand_response(ctx.network),  # shiftable-load outcome; None if no DR
        "priceElastic": build_price_elastic(ctx.network),  # elastic-demand outcome; None if none
    }


mh.register("build_step", "demand-response", _rewire, module=MODULE, order=10)
mh.register("study", "demand-response", _outcome, module=MODULE, order=10,
            payload_keys=("demandResponse", "priceElastic"))
