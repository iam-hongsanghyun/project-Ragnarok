"""Plants module hooks (see :mod:`backend.app.module_hooks`): gas + H2 co-firing blend-share limits and hot / warm / cold start costs."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from backend.app import module_hooks as mh

MODULE = "plants"


def _prepare(ctx: mh.RunContext) -> Callable[[Any, Any], None] | None:
    """Co-firing blend-share limits for fuel-network plants: same pre-solve 400 rule as RFNBO."""
    from . import cofiring

    try:
        plan = cofiring.resolve_plan(ctx.model, ctx.options.get("cofiringConfig"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not plan:
        return None
    if ctx.stochastic is not None and ctx.stochastic.enabled:
        raise HTTPException(status_code=400, detail="Co-firing blend-share limits cannot be combined with stochastic scenarios.")

    def contribute(n: Any, snapshots: Any) -> None:
        # H2 energy share of each fuel-network plant within [min, max], hourly or over the period.
        cofiring.apply_cofiring_constraints(n, plan, snapshots, ctx.notes)

    return contribute


mh.register("constraints", "plants-cofiring", _prepare, module=MODULE, order=60)


def _prepare_start_costs(ctx: mh.RunContext) -> Callable[[Any, Any], None] | None:
    """Hot / warm / cold start-cost tiers (``RAGNAROK_StartCosts``): refuse what the rows cannot honour, else add them to the objective."""
    from . import startcosts

    try:
        plans = startcosts.read_plans(ctx.model or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not plans:
        return None
    modes = [m for m in ctx.incompatible_modes if m in ("rolling horizon", "stochastic", "sampled-block")]
    if ctx.pathway is not None and bool(getattr(ctx.pathway, "enabled", False)):
        modes.append("multi-period pathway")
    if modes:
        raise HTTPException(
            status_code=400,
            detail=("Hot / warm / cold start costs (RAGNAROK_StartCosts) look back over the snapshots before each start, so they need one contiguous "
                    f"single-period run; this run uses {', '.join(modes)}. Remove the RAGNAROK_StartCosts rows (the plant's single start_up_cost, the hot "
                    "cost, then applies) or turn that mode off."),
        )

    def contribute(n: Any, snapshots: Any) -> None:
        try:
            startcosts.apply_start_cost_tiers(n, plans, snapshots, ctx.notes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return contribute


mh.register("constraints", "plants-start-costs", _prepare_start_costs, module=MODULE, order=61)
