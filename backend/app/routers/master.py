"""``/api/session/master`` — the stored master model + the derive-by-filter step.

The *master* is a full (typically multi-year) model imported once from an Excel
project and kept in its own store slot beside the working model. The working
model on the Model page stays exactly what it is today; the master is a source
you **derive** working models from:

    POST   /api/session/master/import    -> {meta, years}   (upload .xlsx/.zip)
    GET    /api/session/master/meta      -> meta + years | {}
    GET    /api/session/master/distinct  -> unique values of one column
    POST   /api/session/master/derive    -> filter master -> replace working model
    POST   /api/session/master/clear     -> {cleared}

Storage costs nothing new: both store backends are fully ``session_id``-keyed,
so the master simply lives under ``<session>__master`` (one extra ``project.db``
next to the session's own). Filtering itself is pure —
:mod:`backend.app.model_derive`.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel

from .. import model_derive, model_store

router = APIRouter(prefix="/api/session/master", tags=["master"])

MASTER_SUFFIX = "__master"


def master_id(session_id: str) -> str:
    """Store slot of the master model belonging to ``session_id``."""
    return f"{session_id}{MASTER_SUFFIX}"


def _master_summary(session_id: str) -> dict[str, Any]:
    """Master meta + the year list the derive dialog needs (cheap: snapshots only)."""
    meta = model_store.get_meta(master_id(session_id))
    if not meta:
        return {}
    page = model_store.get_sheet_page(master_id(session_id), "snapshots", offset=0, limit=10_000_000)
    years = model_derive.snapshot_years({"snapshots": page.get("rows", [])}) if page else []
    return {**meta, "years": years}


@router.post("/import")
async def import_master(file: UploadFile, session_id: str = Query("default", alias="session_id")) -> dict:
    """Parse an uploaded project (.zip / .xlsx) and store it as the master.

    The working model is NOT touched — importing a master only fills the slot
    the derive step reads from. Replaces any previous master.
    """
    from .. import project_workbook

    raw = await file.read()
    filename = file.filename or "master.xlsx"

    def _parse_and_store() -> dict[str, Any]:
        bundle = project_workbook.import_bundle_from_upload(raw, filename)
        model = bundle.get("model") or {}
        if not model_derive.component_sheets(model):
            raise ValueError(
                f"{filename}: no component sheets found. Expected sheets like "
                '"buses", "generators", "loads".'
            )
        return model_store.save_model(master_id(session_id), model, filename=filename)

    # Parsing + storing a multi-year workbook is heavy synchronous CPU work —
    # keep it off the event loop (same rationale as /api/import/project/load).
    try:
        await asyncio.to_thread(_parse_and_store)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Master import failed: {exc}") from exc
    return _master_summary(session_id)


@router.get("/meta")
def get_master_meta(session_id: str = Query("default", alias="session_id")) -> dict:
    """Master meta (+ ``years``), or ``{}`` when no master is stored."""
    return _master_summary(session_id)


@router.get("/distinct")
def get_master_distinct(
    sheet: str = Query(...),
    column: str = Query(...),
    session_id: str = Query("default", alias="session_id"),
) -> dict:
    """Sorted distinct non-empty values of one master-sheet column (filter picker)."""
    values = model_store.distinct_values(master_id(session_id), sheet, column)
    if values is None:
        raise HTTPException(status_code=404, detail=f"Sheet {sheet!r} not found in the master model.")
    return {"sheet": sheet, "column": column, "values": values}


class DeriveRequest(BaseModel):
    """Body for ``POST /api/session/master/derive``.

    ``years`` — calendar years to keep (empty/omitted = all years).
    ``filters`` — ``[{sheet, column, values}]`` attribute filters.
    ``mode`` — ``deactivate`` (default) marks excluded components
    ``active = False`` (PyPSA skips them in the solve, rows stay);
    ``remove`` hard-deletes them. Components outside their
    ``build_year``/``lifetime`` window for every selected year are always
    excluded (see :func:`model_derive.derive_model`).
    """

    years: list[int] | None = None
    filters: list[dict[str, Any]] | None = None
    mode: str = "deactivate"
    sessionId: str = "default"


@router.post("/derive")
async def derive_working_model(payload: DeriveRequest) -> dict:
    """Filter the master and REPLACE the session's working model with the result."""

    def _derive() -> dict[str, Any]:
        master = model_store.load_full_model(master_id(payload.sessionId))
        if not master:
            raise ValueError("No master model stored — import one first.")
        mode = "remove" if payload.mode == "remove" else "deactivate"
        derived, report = model_derive.derive_model(
            master, years=payload.years, filters=payload.filters, mode=mode
        )
        master_meta = model_store.get_meta(master_id(payload.sessionId)) or {}
        meta = model_store.save_model(
            payload.sessionId, derived, filename=master_meta.get("filename", "")
        )
        return {"meta": meta, "report": report}

    try:
        return await asyncio.to_thread(_derive)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/clear")
def clear_master(session_id: str = Query("default", alias="session_id")) -> dict:
    """Remove the stored master model (the working model is untouched)."""
    return {"cleared": model_store.clear(master_id(session_id))}
