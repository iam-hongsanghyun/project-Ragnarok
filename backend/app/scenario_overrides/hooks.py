"""Scenario-overrides module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from typing import Any

from backend.app import module_hooks as mh

from . import apply_model_overrides


def _apply(data: dict[str, Any]) -> dict[str, Any]:
    """Per-scenario model overrides (capacity, etc.), applied to the snapshot now so the solved and stored run
    reflects them (batch scenario runs differ here)."""
    overrides = (data.get("options") or {}).get("modelOverrides") or []
    if overrides:
        data["model"] = apply_model_overrides(data["model"], overrides)
    return data


mh.register("submit", "scenario-overrides", _apply, module="scenario-overrides", order=10)
