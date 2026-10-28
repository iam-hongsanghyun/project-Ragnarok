"""Emissions module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from typing import Any

from backend.app import module_hooks as mh

from .breakdown import build_emissions_breakdown


def _breakdown(ctx: mh.RunContext) -> dict[str, Any]:
    return {"emissionsBreakdown": build_emissions_breakdown(ctx.network, ctx.emissions_factors)}


mh.register("study", "emissions-breakdown", _breakdown, module="emissions", order=30,
            payload_keys=("emissionsBreakdown",))
