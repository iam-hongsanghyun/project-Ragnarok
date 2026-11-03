"""Fuel-costs module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

import logging
from typing import Any

from backend.app import module_hooks as mh

from . import (
    SHEET_PRICE_SCENARIOS,
    apply_plan,
    apply_stochastic_plans,
    build_plan,
    build_stochastic_plans,
    is_enabled,
    raise_on_efficiency_problems,
    raise_on_marginal_cost_overrides,
    read_price_scenarios,
    resolve_units,
    results,
    stochastic_price_changes,
    stochastic_results,
)

MODULE = "fuel-costs"
PLAN_ATTR = "_ragnarok_fuel_plan"
PLANS_ATTR = "_ragnarok_fuel_plans"          # stochastic: {scenario: FuelPlan}
CAPTURE_ATTR = "_ragnarok_fuel_scenarios"    # stochastic: per-scenario results read before the collapse
_log = logging.getLogger(__name__)


def _stochastic(ctx: mh.RunContext) -> bool:
    return ctx.stochastic is not None and bool(getattr(ctx.stochastic, "enabled", False))


def _guard(ctx: mh.RunContext) -> None:
    """Refuse before the network is built: a priced unit without a usable efficiency (the row check; a series that is <= 0 on
    a modelled snapshot, in any scenario, is caught at the build) and, in a stochastic run, a scenario override of the
    ``marginal_cost`` of a unit the module prices."""
    if not is_enabled(ctx.model, ctx.options):
        return
    specs = resolve_units(ctx.model or {})
    raise_on_efficiency_problems(specs)
    if _stochastic(ctx):
        raise_on_marginal_cost_overrides(ctx.stochastic, specs)


def _build_step(ctx: mh.RunContext) -> None:
    """Write the fuel-priced marginal-cost series onto the built network and keep the plan for the study.

    A stochastic run is handled by :func:`_build_step_stochastic` (after the scenarios exist); this path stays as it was."""
    if ctx.network is None or not is_enabled(ctx.model, ctx.options) or _stochastic(ctx):
        return
    model = ctx.model or {}
    if read_price_scenarios(model):
        ctx.notes.append(f"Fuel costs: {SHEET_PRICE_SCENARIOS} rows apply to stochastic scenarios only; this run has none, so they are ignored.")
    plan = build_plan(ctx.network, model, ctx.currency)
    if not plan.units:
        return
    apply_plan(ctx.network, plan)
    setattr(ctx.network, PLAN_ATTR, plan)
    ctx.notes.extend(plan.notes)


def _build_step_stochastic(ctx: mh.RunContext) -> None:
    """Stochastic run: after ``stochastic-overrides`` (order 90) has expanded the network to ``(scenario, name)`` and applied
    each scenario's overrides, write every scenario's own series: fuel_S(t) / eta_S(t) + VOM."""
    if ctx.network is None or not is_enabled(ctx.model, ctx.options) or not _stochastic(ctx):
        return
    plans = build_stochastic_plans(ctx.network, ctx.model or {}, ctx.stochastic, ctx.currency)
    if not any(p.units for p in plans.values()):
        if any(c for c in stochastic_price_changes(ctx.stochastic)):
            ctx.notes.append("Fuel costs: carriers.fuel_price overrides found no priced unit; they change nothing.")
        return
    apply_stochastic_plans(ctx.network, plans)
    setattr(ctx.network, PLANS_ATTR, plans)
    for p in plans.values():
        ctx.notes.extend(p.notes)


def _capture(ctx: mh.RunContext) -> dict[str, Any]:
    """``post_solve`` BEFORE ``stochastic-collapse``: read every scenario's breakdown and LCOE while the network still carries
    all of them, and keep it for the study (the collapse leaves only the representative scenario)."""
    plans = getattr(ctx.network, PLANS_ATTR, None) if ctx.network is not None else None
    if not plans or not _stochastic(ctx):
        return {}
    weights = {s.name: s.weight for s in ctx.stochastic.scenarios}
    rep = max(ctx.stochastic.scenarios, key=lambda s: s.weight).name
    try:
        setattr(ctx.network, CAPTURE_ATTR, stochastic_results(ctx.network, plans, weights, rep))
    except Exception as exc:  # noqa: BLE001 - a finished solve is never lost to its read-back
        _log.warning("fuel-costs scenario results failed: %s", exc)
        ctx.notes.append(f"Fuel-costs scenario results could not be computed: {exc}")
    return {}


def _study(ctx: mh.RunContext) -> dict[str, Any]:
    net = ctx.network
    plan = getattr(net, PLAN_ATTR, None) if net is not None else None
    captured = getattr(net, CAPTURE_ATTR, None) if net is not None else None
    if plan is None and captured is None:
        return {"fuelCosts": None}
    try:
        if captured is not None:
            plans = getattr(net, PLANS_ATTR)
            rep = captured["representativeScenario"]
            rows = next(sc["units"] for sc in captured["scenarios"] if sc["name"] == rep)
            block = results(net, plans[rep], ctx.currency, units=rows)
            block.update(captured)
            block["notes"] = [n for p in plans.values() for n in p.notes]
            return {"fuelCosts": block}
        return {"fuelCosts": results(net, plan, ctx.currency)}
    except Exception as exc:  # noqa: BLE001 - a finished solve is never lost to its read-back
        _log.warning("fuel-costs results failed: %s", exc)
        ctx.notes.append(f"Fuel-costs results could not be computed: {exc}")
        return {"fuelCosts": None}


# Refuse before the build; write the series after it (after demand response 10, before the stochastic broadcast 90). A stochastic
# run writes per-scenario series AFTER the broadcast and its overrides (stochastic-overrides, order 90) and reads every scenario
# before stochastic-collapse (post_solve order 10) leaves one.
mh.register("guard", "fuel-costs-guard", _guard, module=MODULE, order=40)
mh.register("build_step", "fuel-costs", _build_step, module=MODULE, order=20)
mh.register("build_step", "fuel-costs-stochastic", _build_step_stochastic, module=MODULE, order=95)
mh.register("post_solve", "fuel-costs-capture", _capture, module=MODULE, order=5)
mh.register("study", "fuel-costs", _study, module=MODULE, order=60, payload_keys=("fuelCosts",))
