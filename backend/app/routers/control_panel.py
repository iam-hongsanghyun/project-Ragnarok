"""Control-panel module endpoints: switch rules that turn PyPSA attributes off for a filtered set of components.

The rules live in the project's app state under ``ragnarok:control-panel:rules`` (the browser writes that key; these
endpoints read it, preview it against the session model and let an agent set it). Applying them happens at submit
time, in the module's ``submit`` hook (``backend/app/control_panel/hooks.py``); nothing here edits the workbook.

* ``GET  /api/control-panel``          - the project's rules, the attribute groups, the components of the model with
  their input attributes and columns, and a preview of every rule.
* ``POST /api/control-panel/preview``  - the same preview for a rule list that is not saved yet. Read-only.
* ``POST /api/control-panel/values``   - the distinct values of one column of a component sheet, with row counts.
* ``POST /api/control-panel/set``      - validate and store a rule list in the project (open browsers re-apply it).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...pypsa import pypsa_schema
from .. import control_panel as cp
from .. import events_bus, model_store
from ..run_options_reference import RunOption, register_options

router = APIRouter(tags=["control-panel"])

register_options([
    RunOption(f"options.{cp.OPTION_KEY}", "array", "Control-panel switch rules for this run only, replacing the project's "
              "(ragnarok:control-panel:rules). Each {id, component, attributes, column, values, on}; a rule with on=false sets "
              "the attributes of the matched rows to PyPSA's default in the run's copy of the model.", None, None, None,
              "backend/app/control_panel/__init__.py", "api", "control-panel"),
    RunOption(f"options.{cp.APPLIED_KEY}", "array", "Written by the control-panel submit hook: what each switched-off rule "
              "changed (matched names, cells, series columns, time-unit rows). Kept with the run; read into its notes.",
              None, None, None, "backend/app/control_panel/hooks.py", "api", "control-panel"),
])


class SessionBody(BaseModel):
    sessionId: str = "default"


class RulesBody(SessionBody):
    rules: list[dict[str, Any]]


class ValuesBody(SessionBody):
    component: str
    column: str


def _model(session_id: str) -> dict[str, Any]:
    model = model_store.load_full_model(session_id)
    if not model:
        raise HTTPException(status_code=400, detail=f"No model loaded in session {session_id!r}.")
    return model


def _stored_rules(session_id: str) -> list[dict[str, Any]]:
    raw = (model_store.get_app_state(session_id) or {}).get(cp.STATE_KEY)
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    rules = value.get("rules") if isinstance(value, dict) else value
    return [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []


def _parse(rules: list[dict[str, Any]]) -> list[cp.Rule]:
    try:
        return cp.parse_rules(rules)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def preview(model: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Per rule: the rows it selects and what switching it off changes (computed whether it is on or off)."""
    parsed = _parse(rules)
    out: list[dict[str, Any]] = []
    for rule in parsed:
        _, effects = cp.apply_rules(model, [cp.Rule(**{**rule.__dict__, "on": False})])
        out.append({**effects[0].as_dict(), "on": rule.on})
    active = [e for e in out if not e["on"]]
    return {"rules": out, "offCount": len(active), "notes": [cp.describe(e) for e in active]}


def _components(model: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for sheet in pypsa_schema.component_sheets():
        rows = model.get(sheet)
        if not rows or sheet in ("buses", "carriers", "snapshots", "network", "shapes", "sub_networks"):
            continue
        out.append({"component": sheet, "rows": len(rows), "columns": cp.component_columns(model, sheet),
                    "attributes": sorted(cp.input_attributes(sheet))})
    return out


@router.get("/api/control-panel")
def control_panel_get(session_id: str = "default") -> dict[str, Any]:
    model = _model(session_id)
    rules = _stored_rules(session_id)
    try:
        prev = preview(model, rules)
    except HTTPException as exc:
        prev = {"rules": [], "offCount": 0, "notes": [], "error": exc.detail}
    return {"stateKey": cp.STATE_KEY, "rules": rules, "groups": {k: list(v) for k, v in cp.GROUPS.items()},
            "components": _components(model), "preview": prev}


@router.post("/api/control-panel/preview")
def control_panel_preview(body: RulesBody) -> dict[str, Any]:
    return preview(_model(body.sessionId), body.rules)


@router.post("/api/control-panel/values")
def control_panel_values(body: ValuesBody) -> dict[str, Any]:
    model = _model(body.sessionId)
    return {"component": body.component, "column": body.column,
            "values": cp.column_values(model, body.component, body.column)}


@router.post("/api/control-panel/set")
def control_panel_set(body: RulesBody) -> dict[str, Any]:
    model = _model(body.sessionId)
    prev = preview(model, body.rules)  # validates (400 on a bad rule)
    value = json.dumps({"version": 1, "rules": body.rules}, separators=(",", ":"))
    state = model_store.set_app_state(body.sessionId, {cp.STATE_KEY: value}, replace=False)
    if state is None:
        raise HTTPException(status_code=409, detail="No project is loaded in this session; load or build a model first.")
    events_bus.publish(body.sessionId, "session.appState", {"keys": [cp.STATE_KEY]})
    return {"rules": body.rules, "preview": prev}
