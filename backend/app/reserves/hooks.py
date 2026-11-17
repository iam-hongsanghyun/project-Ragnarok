"""Operating-reserves module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from backend.app import module_hooks as mh

from .reserves import apply_reserve_constraints, extract_reserve_results, validate_reserve_config

MODULE = "reserves"


def _prepare(ctx: mh.RunContext) -> Callable[[Any, Any], None] | None:
    reserve_cfg: dict[str, Any] = ctx.options.get("reserveConfig") or {}
    if not bool(reserve_cfg.get("enabled")):
        return None
    if ctx.stochastic is not None and ctx.stochastic.enabled:
        # Stochastic (set_scenarios) adds a `scenario` dimension to Generator-p, which the reserve builder
        # can't key its variable/constraints against. Refuse explicitly rather than silently dropping reserve.
        raise HTTPException(
            status_code=400,
            detail="Operating-reserve co-optimization cannot be combined with stochastic scenarios.",
        )

    try:  # a reserve rule that cannot be honoured as written stops the run (a bad plan is a 400)
        validate_reserve_config(reserve_cfg)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    def contribute(n: Any, snapshots: Any) -> None:
        apply_reserve_constraints(n, reserve_cfg, snapshots, ctx.notes, model=ctx.model)

    return contribute


def _results(ctx: mh.RunContext) -> dict[str, Any]:
    # Reads the in-solve Generator-r variable and the reserve_requirement dual off n.model; None-safe when
    # reserves were not enabled or n.model is unavailable (the derive-from-outputs path never re-solves).
    return {"reserve": extract_reserve_results(ctx.network, ctx.options.get("reserveConfig") or {})}


# Added after the custom constraints so it sees their final dispatch/capacity variables.
mh.register("constraints", "reserves", _prepare, module=MODULE, order=40)
mh.register("study", "reserves", _results, module=MODULE, order=900, payload_keys=("reserve",))
