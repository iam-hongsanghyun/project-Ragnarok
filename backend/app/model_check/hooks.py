"""Model-check module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from backend.app import module_hooks as mh

from .diagnostics import diagnose_infeasibility, diagnosis_text


def _diagnose(ctx: mh.RunContext) -> dict[str, str]:
    diag = diagnose_infeasibility(ctx.network)
    return {"headline": diag["headline"], "text": diagnosis_text(diag)}


mh.register("diagnose", "infeasibility", _diagnose, module="model-check", order=10)
