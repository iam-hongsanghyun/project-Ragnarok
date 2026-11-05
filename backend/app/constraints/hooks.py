"""Constraints module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.app import module_hooks as mh

from . import carrier_output_cap, period_budgets
from .constraint_dsl import apply_constraint_specs, apply_dsl_constraints
from .custom_constraints import apply_custom_constraints
from .native_routing import (
    dsl_candidates,
    route_native,
    routed_keys,
    spec_candidates,
    structured_candidates,
)

MODULE = "constraints"


def _prepare(ctx: mh.RunContext) -> Callable[[Any, Any], None]:
    custom_constraints: list[dict] = ctx.scenario.get("constraints") or []
    # Advanced constraints arrive as a structured JSON spec from the frontend (constraintSpecs). Older payloads
    # may still send the raw DSL text; accept both, preferring the JSON spec.
    constraint_specs: list[dict] = ctx.scenario.get("constraintSpecs") or []
    custom_dsl_text: str = str(ctx.scenario.get("customDsl") or "")
    emissions_factors = ctx.emissions_factors
    notes = ctx.notes
    _route_native(ctx)

    def contribute(n: Any, snapshots: Any) -> None:
        # `snapshots` is the window being optimised (a rolling-horizon window, or the whole run): budgets and
        # weights are scoped to it. Constraints the build step wrote as native GlobalConstraint rows are skipped.
        apply_custom_constraints(
            n, custom_constraints, emissions_factors, notes, snapshots, skip=routed_keys(n, "cc")
        )
        if constraint_specs:
            apply_constraint_specs(
                n, constraint_specs, emissions_factors, notes, snapshots, skip=routed_keys(n, "spec")
            )
        elif custom_dsl_text:
            apply_dsl_constraints(
                n, custom_dsl_text, emissions_factors, notes, snapshots, skip=routed_keys(n, "dsl")
            )

    return contribute


def _route_native(ctx: mh.RunContext) -> None:
    """Write the constraints PyPSA's GlobalConstraint expresses exactly as native rows (run from ``_prepare``,
    on the built network and before the solve, so the rows are part of the model PyPSA builds).

    Same precedence as :func:`_prepare`: ``constraintSpecs`` over the DSL text. Rolling, stochastic and pathway
    runs keep the linopy path (see :mod:`.native_routing`).
    """
    scenario = ctx.scenario or {}
    candidates = structured_candidates(scenario.get("constraints") or [])
    if scenario.get("constraintSpecs"):
        candidates += spec_candidates(scenario["constraintSpecs"])
    elif scenario.get("customDsl"):
        candidates += dsl_candidates(str(scenario["customDsl"]))
    if not candidates or ctx.network is None:
        return
    route_native(
        ctx.network,
        candidates,
        ctx.notes,
        rolling_enabled=bool(getattr(ctx.rolling, "enabled", False)),
        stochastic_enabled=bool(getattr(ctx.stochastic, "enabled", False)),
    )


def _dsl_fallback(data: dict[str, Any]) -> dict[str, Any]:
    """DSL precedence: scenario.constraintSpecs > scenario.customDsl > the model's RAGNAROK_CustomDSL sheet.

    Resolved at submit time so the queued snapshot carries the text it will solve with.
    """
    from backend.app import run_guards

    data["scenario"] = run_guards.apply_model_dsl_fallback(data.get("model"), data.get("scenario"))
    return data


mh.register("constraints", "constraints", _prepare, module=MODULE, order=30)
mh.register("submit", "constraints-dsl-fallback", _dsl_fallback, module=MODULE, order=20)
# The per-snapshot carrier output cap (sheet RAGNAROK_CarrierOutputCap): refused in modes it cannot honour, then a
# linopy constraint per carrier. Ordered after the custom constraints.
mh.register("guard", "carrier-output-cap-guard", carrier_output_cap.guard, module=MODULE, order=30)
mh.register("constraints", "carrier-output-cap", carrier_output_cap.prepare, module=MODULE, order=35)
mh.register("guard", "period-budgets-guard", period_budgets.guard, module=MODULE, order=31)


def _carry_whole_run_limits(ctx: mh.RunContext) -> None:
    """Rolling horizon: the model's whole-run limits (CO2 cap, carrier energy limit, e_sum) become budgets tracked window
    by window instead of being applied in full to every window. A build step, so the rolling check that follows sees
    them gone and the period-budgets constraint hook finds them in ``network.meta``."""
    if ctx.network is not None and bool(getattr(ctx.rolling, "enabled", False)):
        period_budgets.carry_whole_run_limits(ctx.network, ctx.notes)


mh.register("build_step", "period-budgets-rolling", _carry_whole_run_limits, module=MODULE, order=90)
mh.register("constraints", "period-budgets", period_budgets.prepare, module=MODULE, order=36)
