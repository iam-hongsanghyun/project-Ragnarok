"""``/api/session`` — the server-side working model (backend = source of truth).

The frontend imports a model once (``POST /api/session/model``) and thereafter
fetches only what it shows: a page of static rows (``GET .../sheet/{name}``) or a
windowed, downsampled time-series slice (``GET .../series/{name}``). This keeps
the browser a thin terminal — see :mod:`backend.app.session_store` for the store
itself.

Endpoints::

    POST   /api/session/model            -> meta (ingest a full model)
    GET    /api/session/meta             -> meta | {} (cheap "is anything loaded?")
    GET    /api/session/sheet/{name}     -> one page of rows
    GET    /api/session/series/{name}    -> windowed + downsampled series slice
    POST   /api/session/clear            -> {cleared: bool}

``session_id`` defaults to ``"default"`` (single-user, one machine). It is a
first-class parameter everywhere so a remote, multi-session deployment is a
config change, not a rewrite.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import model_store
from ..models import SessionModelPayload

router = APIRouter(prefix="/api/session", tags=["session"])


class SheetPatch(BaseModel):
    """Body for ``PATCH /api/session/sheet/{name}`` — a batch of edit ops.

    Ops (applied in order): ``{op:"set",row,column,value}``,
    ``{op:"addRow",values,index?}``, ``{op:"deleteRows",rows:[...]}``.
    """

    ops: list[dict[str, Any]] = []
    sessionId: str = "default"


@router.post("/model")
def put_model(payload: SessionModelPayload) -> dict:
    """Ingest a full model into the session, replacing any current one.

    Returns the lightweight meta only — the frontend never re-receives the whole
    model it just sent.
    """
    try:
        return model_store.save_model(
            payload.sessionId,
            payload.model,
            filename=payload.filename,
            scenario_name=payload.scenarioName,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/model/static")
def merge_static(payload: SessionModelPayload) -> dict:
    """Merge the static sheets of ``model`` into the session, keeping series.

    The thin client calls this to sync its in-memory static edits before a run
    without clobbering the heavy time-series it doesn't hold.
    """
    meta = model_store.merge_static_model(payload.sessionId, payload.model)
    if meta is None:
        raise HTTPException(status_code=400, detail="No session to merge into.")
    return meta


@router.get("/meta")
def get_meta(session_id: str = Query("default", alias="session_id")) -> dict:
    """Return the session meta, or ``{}`` when no model is loaded."""
    return model_store.get_meta(session_id) or {}


@router.get("/model/full")
def get_full_model(
    session_id: str = Query("default", alias="session_id"),
    static_only: bool = Query(False, alias="staticOnly"),
) -> dict:
    """Return the working model ``{sheet: rows}`` from the session.

    With ``staticOnly=true`` the heavy time-series sheets are omitted — that's
    what the thin client uses to rehydrate the editor on boot (it pages series
    on demand). Returns ``{model: null}`` when nothing is loaded.
    """
    return {"model": model_store.load_full_model(session_id, static_only=static_only)}


@router.get("/sheet/{name}")
def get_sheet(
    name: str,
    session_id: str = Query("default", alias="session_id"),
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=0),
) -> dict:
    """Return one page of a sheet's rows (static or series)."""
    page = model_store.get_sheet_page(session_id, name, offset=offset, limit=limit)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Sheet {name!r} not found in session.")
    return page


@router.get("/sheet/{name}/distinct")
def get_sheet_distinct(
    name: str,
    column: str = Query(..., description="Column whose distinct non-empty values to return."),
    session_id: str = Query("default", alias="session_id"),
) -> dict:
    """Return the sorted distinct non-empty values of one column in a sheet.

    Backs Ragnarok's own unique-value features (Forge target pickers, grid column
    filters). Served by the store's native ``SELECT DISTINCT`` on the SQLite
    backend and a row-scan fallback on the legacy store, so the capability works
    regardless of ``RAGNAROK_STORE``. The model never travels to the browser.
    """
    values = model_store.distinct_values(session_id, name, column)
    if values is None:
        raise HTTPException(status_code=404, detail=f"Sheet {name!r} not found in session.")
    return {"sheet": name, "column": column, "values": values}


@router.get("/series/{name}")
def get_series(
    name: str,
    session_id: str = Query("default", alias="session_id"),
    start: int = Query(0, ge=0),
    end: int | None = Query(None, ge=0),
    columns: str | None = Query(None, description="Comma-separated asset columns; omit for all."),
    max_points: int | None = Query(None, alias="maxPoints", ge=1),
    agg: str = Query("mean"),
) -> dict:
    """Return a windowed, downsampled slice of a time-series sheet."""
    cols = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
    window = model_store.get_series_window(
        session_id,
        name,
        start=start,
        end=end,
        columns=cols,
        max_points=max_points,
        agg=agg,  # type: ignore[arg-type]  (validated inside the store)
    )
    if window is None:
        raise HTTPException(
            status_code=404, detail=f"Time-series sheet {name!r} not found in session."
        )
    return window


@router.patch("/sheet/{name}")
def patch_sheet(name: str, payload: SheetPatch) -> dict:
    """Apply a batch of edits to a sheet (backend is the source of truth)."""
    result = model_store.patch_sheet(payload.sessionId, name, payload.ops)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Sheet {name!r} not found in session.")
    return result


@router.post("/clear")
def clear_session(session_id: str = Query("default", alias="session_id")) -> dict:
    """Clear the session's working model (settings are a separate frontend concern)."""
    return {"cleared": model_store.clear(session_id)}
