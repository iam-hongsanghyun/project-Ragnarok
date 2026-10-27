"""``/api/scenarios`` — saved scenario presets, the carbon library and the DSL sheet.

Read-only resolution over the session model's ``RAGNAROK_Scenarios`` /
``RAGNAROK_CarbonSchedules`` / ``RAGNAROK_CustomDSL`` sheets (logic in
:mod:`backend.app.scenario_presets`). Nothing here queues a solve: ``POST
/api/scenarios/resolve`` returns the exact ``{scenario, options}`` body the browser's
batch runner would send to ``POST /api/queue``, so a client submits it itself.

    GET  /api/scenarios                  -> saved presets (short rows) + unreadable rows
    GET  /api/scenarios/carbon-schedules -> the carbon library
    GET  /api/scenarios/dsl              -> the DSL sheet text, parsed per line
    GET  /api/scenarios/{id}             -> one full preset
    POST /api/scenarios/resolve          -> run body for one scenario
    PUT  /api/scenarios/dsl              -> replace the DSL sheet text (validated)
    PUT  /api/scenarios/{id}             -> create / update one preset
    POST /api/scenarios/{id}/activate    -> mark a preset active
    DELETE /api/scenarios/{id}           -> remove a preset

The writes change only the ``RAGNAROK_Scenarios`` / ``RAGNAROK_CustomDSL`` static
sheets (journalled like any session edit), so the browser shows them on its next
static refresh.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import model_store
from .. import scenario_presets as sp

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])
#: ``GET /api/run-options`` - the run-options reference (WA5), served from
#: :mod:`backend.app.run_options_reference`. Registered beside the scenarios router.
options_router = APIRouter(prefix="/api/run-options", tags=["scenarios"])


def _model(session_id: str) -> dict[str, list[dict[str, Any]]]:
    model = model_store.load_full_model(session_id)
    if not model:
        raise HTTPException(status_code=400, detail=f"No model loaded in session {session_id!r}.")
    return model


class ResolveBody(BaseModel):
    sessionId: str = "default"
    scenarioId: str
    uiOptions: dict[str, Any] | None = None
    carbonScheduleId: str | None = None
    optionsPatch: dict[str, Any] | None = None
    runLabel: str | None = None


@router.get("")
def list_scenarios(session_id: str = Query("default")) -> dict[str, Any]:
    catalog = sp.read_scenario_catalog(_model(session_id))
    return {
        "activeScenarioId": catalog["activeScenarioId"],
        "scenarios": [sp.summarize_preset(s) for s in catalog["scenarios"]],
        "unreadable": catalog["unreadable"],
    }


@router.get("/carbon-schedules")
def list_carbon_schedules(session_id: str = Query("default")) -> dict[str, Any]:
    return {"schedules": sp.read_carbon_library(_model(session_id))}


@router.get("/dsl")
def get_dsl(session_id: str = Query("default")) -> dict[str, Any]:
    model = _model(session_id)
    text = sp.read_custom_dsl(model)
    lines = sp.parse_constraint_dsl(text)
    return {
        "sheet": sp.CUSTOM_DSL_SHEET,
        "text": text,
        "lines": lines,
        "errors": [line for line in lines if "error" in line],
        "generatorCarriers": sp.generator_carriers(model),
    }


class DslBody(BaseModel):
    sessionId: str = "default"
    text: str = ""
    allowErrors: bool = False


@router.put("/dsl")
def put_dsl(body: DslBody) -> dict[str, Any]:
    """Replace the model's DSL sheet. Lines that do not parse are refused unless ``allowErrors``."""
    model = _model(body.sessionId)
    lines = sp.parse_constraint_dsl(body.text)
    errors = [line for line in lines if "error" in line]
    if errors and not body.allowErrors:
        raise HTTPException(
            status_code=400,
            detail="DSL not saved — fix these lines: " + "; ".join(
                f"line {e.get('lineNo')}: {e.get('error')}" for e in errors
            ),
        )
    rows = [{"text": body.text}] if body.text.strip() else []
    meta = model_store.merge_static_model(body.sessionId, {sp.CUSTOM_DSL_SHEET: rows})
    return {"saved": True, "lines": lines, "errors": errors, "meta": meta, "generatorCarriers": sp.generator_carriers(model)}


class ScenarioBody(BaseModel):
    sessionId: str = "default"
    fields: dict[str, Any] = {}
    activate: bool = False


@router.put("/{scenario_id}")
def put_scenario(scenario_id: str, body: ScenarioBody) -> dict[str, Any]:
    """Create or update a preset; ``fields`` merge over the stored one (a config block replaces whole)."""
    model = _model(body.sessionId)
    try:
        rows, preset = sp.upsert_scenario(model, scenario_id, body.fields, activate=body.activate)
    except sp.ScenarioResolveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    model_store.merge_static_model(body.sessionId, {sp.SCENARIO_SHEET: rows})
    return {"scenario": preset, "active": any(r["id"] == preset["id"] and r["active"] for r in rows)}


@router.post("/{scenario_id}/activate")
def post_activate(scenario_id: str, session_id: str = Query("default")) -> dict[str, Any]:
    try:
        rows = sp.activate_scenario(_model(session_id), scenario_id)
    except sp.ScenarioResolveError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    model_store.merge_static_model(session_id, {sp.SCENARIO_SHEET: rows})
    return {"activeScenarioId": scenario_id}


@router.delete("/{scenario_id}")
def delete_scenario(scenario_id: str, session_id: str = Query("default")) -> dict[str, Any]:
    try:
        rows = sp.remove_scenario(_model(session_id), scenario_id)
    except sp.ScenarioResolveError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    model_store.merge_static_model(session_id, {sp.SCENARIO_SHEET: rows})
    active = next((r["id"] for r in rows if r["active"]), None)
    return {"removed": scenario_id, "activeScenarioId": active}


@router.get("/{scenario_id}")
def get_scenario(scenario_id: str, session_id: str = Query("default")) -> dict[str, Any]:
    catalog = sp.read_scenario_catalog(_model(session_id))
    for preset in catalog["scenarios"]:
        if preset["id"] == scenario_id:
            return {"scenario": preset, "active": preset["id"] == catalog["activeScenarioId"]}
    known = ", ".join(f'"{s["id"]}"' for s in catalog["scenarios"]) or "none saved"
    raise HTTPException(status_code=404, detail=f'unknown scenario "{scenario_id}"; saved scenarios: {known}')


@router.post("/resolve")
def resolve(body: ResolveBody) -> dict[str, Any]:
    from ..run_options_reference import validate_options_patch

    problems = validate_options_patch(body.optionsPatch or {})
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))
    try:
        return sp.resolve_scenario_run(
            _model(body.sessionId),
            body.scenarioId,
            ui_options=body.uiOptions,
            carbon_schedule_id=body.carbonScheduleId,
            options_patch=body.optionsPatch,
            run_label=body.runLabel,
        )
    except sp.ScenarioResolveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@options_router.get("")
def run_options_reference(key: str | None = Query(None)) -> dict[str, Any]:
    """Index of every run key (no ``key``) or every field of one key, e.g. ``options.essConfig``."""
    from .. import run_options_reference as ref

    try:
        return ref.build_reference(key)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc.args[0])) from exc
