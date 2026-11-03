"""Fuel-costs module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from backend.app import module_hooks as mh

from . import (
    apply_plan,
    build_plan,
    is_enabled,
    raise_on_efficiency_problems,
    resolve_units,
    results,
)

MODULE = "fuel-costs"
PLAN_ATTR = "_ragnarok_fuel_plan"
_log = logging.getLogger(__name__)


def _guard(ctx: mh.RunContext) -> None:
    """Refuse what the module cannot honour before the network is built: stochastic runs, and a priced unit without
    a usable efficiency (the row check; a series that is <= 0 on a modelled snapshot is caught at the build)."""
    if not is_enabled(ctx.model, ctx.options):
        return
    if ctx.stochastic is not None and bool(getattr(ctx.stochastic, "enabled", False)):
        from .inputs import has_inputs

        if has_inputs(ctx.model):
            raise HTTPException(
                status_code=400,
                detail="Fuel costs (RAGNAROK_FuelPrices / RAGNAROK_VariableOM / carriers.fuel_cost_thermal) cannot be combined with "
                       "stochastic scenarios (the scenario dimension is not supported). Run without stochastic, or turn the module "
                       "off with options.fuelCosts.enabled = false.",
            )
        return
    raise_on_efficiency_problems(resolve_units(ctx.model or {}))


def _build_step(ctx: mh.RunContext) -> None:
    """Write the fuel-priced marginal-cost series onto the built network and keep the plan for the study."""
    if ctx.network is None or not is_enabled(ctx.model, ctx.options):
        return
    plan = build_plan(ctx.network, ctx.model or {}, ctx.currency)
    if not plan.units:
        return
    apply_plan(ctx.network, plan)
    setattr(ctx.network, PLAN_ATTR, plan)
    ctx.notes.extend(plan.notes)


def _study(ctx: mh.RunContext) -> dict[str, Any]:
    plan = getattr(ctx.network, PLAN_ATTR, None) if ctx.network is not None else None
    if plan is None:
        return {"fuelCosts": None}
    try:
        return {"fuelCosts": results(ctx.network, plan, ctx.currency)}
    except Exception as exc:  # noqa: BLE001 - a finished solve is never lost to its read-back
        _log.warning("fuel-costs results failed: %s", exc)
        ctx.notes.append(f"Fuel-costs results could not be computed: {exc}")
        return {"fuelCosts": None}


# Refuse before the build; write the series after it (after demand response 10, before the stochastic broadcast 90).
mh.register("guard", "fuel-costs-guard", _guard, module=MODULE, order=40)
mh.register("build_step", "fuel-costs", _build_step, module=MODULE, order=20)
mh.register("study", "fuel-costs", _study, module=MODULE, order=60, payload_keys=("fuelCosts",))
