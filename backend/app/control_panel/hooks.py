"""Control-panel module hooks (see :mod:`backend.app.module_hooks`).

* ``submit`` - apply the switched-off rules to the run's model snapshot. The rules come from ``options.controlSwitches``
  when the submitter states them, else from the project's app state (which rides in the snapshot as its
  ``RAGNAROK_AppState`` sheet). What was switched off is kept in ``options.controlSwitchesApplied``.
* ``build_step`` - turn that record into lines of the run's notes, so a result says which constraints it ran without.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.app import app_state
from backend.app import module_hooks as mh

from . import APPLIED_KEY, OPTION_KEY, STATE_KEY, apply_rules, describe, parse_rules

MODULE = "control-panel"


def rules_source(data: dict[str, Any]) -> Any:
    """The rule list a run uses: the stated option, else the project's app-state value, else none."""
    options = data.get("options") or {}
    if OPTION_KEY in options and options[OPTION_KEY] is not None:
        return options[OPTION_KEY]
    model = data.get("model") or {}
    rows = model.get(app_state.SHEET)
    if isinstance(rows, list):
        return app_state.from_rows(rows).get(STATE_KEY)
    return None


def _apply(data: dict[str, Any]) -> dict[str, Any]:
    raw = rules_source(data)
    if not raw or not data.get("model"):
        return data
    try:
        rules = parse_rules(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Control panel: {exc}") from exc
    if all(r.on for r in rules):
        return data
    model, effects = apply_rules(data["model"], rules)
    data["model"] = model
    data["options"] = {**(data.get("options") or {}), APPLIED_KEY: [e.as_dict() for e in effects]}
    return data


def _notes(ctx: mh.RunContext) -> None:
    for effect in (ctx.options or {}).get(APPLIED_KEY) or []:
        if isinstance(effect, dict):
            ctx.notes.append(describe(effect))


# After the scenario overrides (10), so a switch also covers rows an override wrote.
mh.register("submit", "control-panel-switches", _apply, module=MODULE, order=50)
mh.register("build_step", "control-panel-notes", _notes, module=MODULE, order=90)
