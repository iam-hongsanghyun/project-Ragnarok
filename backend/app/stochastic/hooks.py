"""Stochastic module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from typing import Any

from backend.app import module_hooks as mh

from .scenarios import (
    apply_scenarios,
    collapse_to_representative_scenario,
    per_scenario_summaries,
)

MODULE = "stochastic"


def _apply_overrides(ctx: mh.RunContext) -> None:
    """Broadcast the scenarios over the final deterministic network and apply each scenario's overrides.

    Runs after every deterministic setup so the scenario dimension broadcasts the final values.
    """
    stochastic = ctx.stochastic
    if stochastic is None or not stochastic.enabled:
        return
    apply_scenarios(ctx.network, stochastic)
    ctx.notes.append(
        "Enabled stochastic mode with "
        + ", ".join(
            f"{s.name} (w={s.weight:.2f}, {len(s.overrides)} override{'s' if len(s.overrides) != 1 else ''})"
            for s in stochastic.scenarios
        )
        + "."
    )


def _collapse(ctx: mh.RunContext) -> dict[str, Any]:
    """Per-scenario summaries, then collapse to the highest-weighted scenario for the single-scenario pipeline."""
    stochastic = ctx.stochastic
    if stochastic is None or not stochastic.enabled:
        return {"stochastic": None}
    scenario_summaries = per_scenario_summaries(ctx.network, stochastic, ctx.emissions_factors, ctx.currency)
    representative_scenario = collapse_to_representative_scenario(ctx.network, stochastic)
    ctx.notes.append(
        f"Showing scenario \"{representative_scenario}\" for detailed analytics; "
        "expected values across all scenarios are available in the Stochastic scenarios card."
    )
    return {
        "stochastic": {
            "enabled": True,
            "representativeScenario": representative_scenario,
            "scenarios": scenario_summaries,
        }
    }


mh.register("build_step", "stochastic-overrides", _apply_overrides, module=MODULE, order=90)
mh.register("post_solve", "stochastic-collapse", _collapse, module=MODULE, order=10, payload_keys=("stochastic",))
