"""Plants module hooks (see :mod:`backend.app.module_hooks`): gas + H2 co-firing blend-share limits."""
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
