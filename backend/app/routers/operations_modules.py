"""Temporal and operations modules (core cleanup steps 4 and 5): the visible workbook steps and their previews.

Core hands PyPSA what the workbook holds. What PyPSA lacks is a module that WRITES visible inputs; these are the
endpoints of those modules (each one changes the session workbook and says what it changed, except the previews).

* ``GET  /api/time-units`` / ``POST /api/time-units/set`` - the ``RAGNAROK_TimeUnits`` rows: ramps and UC times in hours /
  per hour (``backend/pypsa/network/time_units.py``).
* ``POST /api/time-units/preview`` - what a run with the given options would write for PyPSA, per snapshot. Read-only.
* ``POST /api/model/set-weightings-from-spacing`` - fill the snapshots sheet's objective / stores / generators from the
  timestamps (irregular spacing and investment periods handled).
* ``POST /api/transform/sample`` - test-run sampling written into the workbook (sampled snapshots, weightings, series).
* ``POST /api/model/make-noncyclic`` - the rolling-horizon step: every cyclic storage flag False.
* ``POST /api/model/relax-maintenance`` - the Force-LP companion step: ``maintainable`` False (``apply: false`` previews).
* ``POST /api/demand-response/preview`` - the ``dr_*`` rows the demand-response module would write. Read-only.
* ``POST /api/demand-response/apply`` - write them (buses / links / stores / loads / generators / carriers);
  a disabled config removes the module's rows.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...pypsa import sampling as sampling_module
from ...pypsa.network import time_units
from ...pypsa.network.force_lp import relax_maintenance
from ...pypsa.rolling import make_noncyclic
from ...pypsa.utils.weightings import set_weightings_from_spacing
from .. import demand_response, model_store
from ..run_options_reference import RunOption, register_options

router = APIRouter(tags=["operations-modules"])

register_options([
    RunOption("options.rollingConfig.horizonHours", "number", "Rolling window in hours (converted to snapshots with the run's weights).", None, "hours",
              None, "backend/pypsa/rolling.py (resolve_rolling)", "api", "rolling"),
    RunOption("options.rollingConfig.overlapHours", "number", "Rolling overlap in hours.", None, "hours",
              None, "backend/pypsa/rolling.py (resolve_rolling)", "api", "rolling"),
    RunOption("options.samplingConfig.scaleStartUpCosts", "boolean", "Test-run sampling: multiply start_up_cost / shut_down_cost of committable units by the "
              "representation factor (PyPSA charges them per event, unweighted).", True, None, None, "backend/pypsa/sampling.py (apply_test_run_sampling)", "api", "sampling"),
])


def _model(session_id: str) -> dict[str, Any]:
    model = model_store.load_full_model(session_id)
    if not model:
        raise HTTPException(status_code=400, detail=f"No model loaded in session {session_id!r}.")
    return model


class SessionBody(BaseModel):
    sessionId: str = "default"


# ── time units ────────────────────────────────────────────────────────────────────

@router.get("/api/time-units")
def time_units_get(session_id: str = "default") -> dict[str, Any]:
    model = _model(session_id)
    try:
        rows = time_units.read_rows(model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"sheet": time_units.SHEET, "rows": [{**r.__dict__} for r in rows],
            "components": list(time_units.COMPONENTS),
            "attributes": {"ramps": list(time_units.RAMP_ATTRS), "times": list(time_units.TIME_ATTRS)},
            "units": {"ramps": list(time_units.RATE_UNITS), "times": list(time_units.TIME_UNITS)}}


class TimeUnitsSet(SessionBody):
    rows: list[dict[str, Any]]
    replace: bool = False


@router.post("/api/time-units/set")
def time_units_set(body: TimeUnitsSet) -> dict[str, Any]:
    model = _model(body.sessionId)
    try:
        out = time_units.set_rows(model, body.rows) if body.replace else time_units.merge_rows(model, body.rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = out.get(time_units.SHEET) or []
    model_store.merge_static_model(body.sessionId, {time_units.SHEET: rows})
    return {"rows": rows}


class TimeUnitsPreview(SessionBody):
    scenario: dict[str, Any] | None = None
    options: dict[str, Any] | None = None


@router.post("/api/time-units/preview")
def time_units_preview(body: TimeUnitsPreview) -> dict[str, Any]:
    model = _model(body.sessionId)
    options = body.options or {}
    try:
        table = time_units.preview(model, body.scenario, options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"table": table, "stepHours": table[0]["stepHours"] if table else None}


# ── snapshot weightings from the spacing ──────────────────────────────────────────────

@router.post("/api/model/set-weightings-from-spacing")
def weightings_from_spacing(body: SessionBody) -> dict[str, Any]:
    model = _model(body.sessionId)
    try:
        out, report = set_weightings_from_spacing(model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    model_store.merge_static_model(body.sessionId, {"snapshots": out["snapshots"]})
    return report


# ── test-run sampling (written) ─────────────────────────────────────────────────────────

class SampleBody(SessionBody):
    options: dict[str, Any] | None = None


@router.post("/api/transform/sample")
def sample_workbook(body: SampleBody) -> dict[str, Any]:
    """Test-run sampling as a visible transform: returns the reduced workbook (the client applies it, like temporal)."""
    model = _model(body.sessionId)
    try:
        return sampling_module.sample_model(model, body.options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Force-LP and rolling companion steps ─────────────────────────────────────────────────

@router.post("/api/model/make-noncyclic")
def make_noncyclic_step(body: SessionBody) -> dict[str, Any]:
    model = _model(body.sessionId)
    out, changed = make_noncyclic(model)
    sheets = {sheet: out[sheet] for sheet in {c["sheet"] for c in changed}}
    if sheets:
        model_store.merge_static_model(body.sessionId, sheets)
    return {"changed": changed, "sheetsWritten": sorted(sheets)}


class RelaxMaintenanceBody(SessionBody):
    apply: bool = True  # false = preview: report what would change, write nothing


@router.post("/api/model/relax-maintenance")
def relax_maintenance_step(body: RelaxMaintenanceBody) -> dict[str, Any]:
    model = _model(body.sessionId)
    out, changed = relax_maintenance(model)
    sheets = {sheet: out[sheet] for sheet in {c["sheet"] for c in changed}}
    if sheets and body.apply:
        model_store.merge_static_model(body.sessionId, sheets)
    return {"changed": changed, "sheetsWritten": sorted(sheets) if body.apply else [], "applied": body.apply}


# ── demand response (rows written into the workbook) ─────────────────────────────────────

class DemandResponseBody(SessionBody):
    config: dict[str, Any] | None = None
    pathwayConfig: dict[str, Any] | None = None


def _dr_rows(body: DemandResponseBody) -> tuple[dict[str, Any], dict[str, Any]]:
    model = _model(body.sessionId)
    options = {"pathwayConfig": body.pathwayConfig} if body.pathwayConfig else None
    try:
        return model, demand_response.compute_rows(model, body.config, options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/demand-response/preview")
def demand_response_preview(body: DemandResponseBody) -> dict[str, Any]:
    """The rows the module would write for ``config``, the rows it already wrote, and the sheets that would change."""
    model, out = _dr_rows(body)
    return {"existing": demand_response.workbook_rows(model), "rows": out["rows"], "removed": out["removed"],
            "sheets": out["sheets"], "notes": out["notes"]}


@router.post("/api/demand-response/apply")
def demand_response_apply(body: DemandResponseBody) -> dict[str, Any]:
    """Write the module's rows into the session workbook (previous ``dr_*`` rows replaced)."""
    _model_in, out = _dr_rows(body)
    sheets = {sheet: out["model"].get(sheet) or [] for sheet in out["sheets"]}
    if sheets and model_store.merge_static_model(body.sessionId, sheets) is None:
        raise HTTPException(status_code=400, detail="No session to write into.")
    return {"rows": out["rows"], "removed": out["removed"], "sheetsWritten": sorted(sheets), "notes": out["notes"]}
