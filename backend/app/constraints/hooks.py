"""Constraints module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.app import module_hooks as mh

from .constraint_dsl import apply_constraint_specs, apply_dsl_constraints
from .custom_constraints import apply_custom_constraints

MODULE = "constraints"


def _prepare(ctx: mh.RunContext) -> Callable[[Any, Any], None]:
    custom_constraints: list[dict] = ctx.scenario.get("constraints") or []
    # Advanced constraints arrive as a structured JSON spec from the frontend (constraintSpecs). Older payloads
    # may still send the raw DSL text; accept both, preferring the JSON spec.
    constraint_specs: list[dict] = ctx.scenario.get("constraintSpecs") or []
    custom_dsl_text: str = str(ctx.scenario.get("customDsl") or "")
    emissions_factors = ctx.emissions_factors
    notes = ctx.notes

    def contribute(n: Any, snapshots: Any) -> None:
        # `snapshots` is the window being optimised (a rolling-horizon window, or the whole run): budgets and
        # weights are scoped to it.
        apply_custom_constraints(n, custom_constraints, emissions_factors, notes, snapshots)
        if constraint_specs:
            apply_constraint_specs(n, constraint_specs, emissions_factors, notes, snapshots)
        elif custom_dsl_text:
            apply_dsl_constraints(n, custom_dsl_text, emissions_factors, notes, snapshots)

    return contribute


def _dsl_fallback(data: dict[str, Any]) -> dict[str, Any]:
    """DSL precedence: scenario.constraintSpecs > scenario.customDsl > the model's RAGNAROK_CustomDSL sheet.

    Resolved at submit time so the queued snapshot carries the text it will solve with.
    """
    from backend.app import run_guards

    data["scenario"] = run_guards.apply_model_dsl_fallback(data.get("model"), data.get("scenario"))
    return data


mh.register("constraints", "constraints", _prepare, module=MODULE, order=30)
mh.register("submit", "constraints-dsl-fallback", _dsl_fallback, module=MODULE, order=20)
