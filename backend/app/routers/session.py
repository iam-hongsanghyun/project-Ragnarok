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


class SeriesTransform(BaseModel):
    """Body for ``POST /api/session/series/{name}/transform`` (T1 bulk edit).

    ``op`` ∈ scale | offset | shift | interpolate | clip. Params: ``factor``
    (scale), ``delta`` (offset), ``shift`` + ``wrap`` (shift), ``minValue`` /
    ``maxValue`` (clip), and optional ``columns`` to restrict to a subset of
    assets. Operates server-side on the stored series.
    """

    op: str
    columns: list[str] | None = None
    factor: float = 1.0
    delta: float = 0.0
    shift: int = 0
    wrap: bool = True
    minValue: float | None = None
    maxValue: float | None = None
    growthPct: float = 0.0
    sessionId: str = "default"


@router.post("/series/{name}/transform")
def transform_series(name: str, payload: SeriesTransform) -> dict:
    """Apply a bulk transform (scale/shift/interpolate/…) to a series sheet."""
    params = {
        "columns": payload.columns, "factor": payload.factor, "delta": payload.delta,
        "shift": payload.shift, "wrap": payload.wrap,
        "minValue": payload.minValue, "maxValue": payload.maxValue,
        "growthPct": payload.growthPct,
    }
    try:
        result = model_store.transform_series(payload.sessionId, name, payload.op, params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Time-series sheet {name!r} not found in session.")
    return result


class SnapshotRetarget(BaseModel):
    """Body for ``POST /api/session/snapshots/retarget`` (T1).

    Regenerate the snapshot index over ``[start, end]`` at ``stepHours`` and
    reindex every temporal sheet onto it (``fill``: ``tile`` = cycle the source to
    fill a longer window, ``pad`` = repeat the last value).
    """

    start: str
    end: str
    stepHours: float = 1.0
    fill: str = "tile"
    sessionId: str = "default"


@router.post("/snapshots/retarget")
def retarget_snapshots(payload: SnapshotRetarget) -> dict:
    """Retarget the session's snapshot window and reindex all temporal sheets."""
    from .. import timeseries  # local import: keeps the module's import graph light

    model = model_store.load_full_model(payload.sessionId)
    if not model:
        raise HTTPException(status_code=400, detail="No working model in this session.")
    try:
        new_snaps = timeseries.generate_snapshots(payload.start, payload.end, payload.stepHours)
    except Exception as exc:  # noqa: BLE001 — bad dates → 400, not 500
        raise HTTPException(status_code=400, detail=f"Invalid window: {exc}") from exc
    if not new_snaps:
        raise HTTPException(status_code=400, detail="The window produced no snapshots (check start/end/step).")

    retargeted: list[str] = []
    for sheet, rows in list(model.items()):
        if not model_store.is_series_sheet(sheet, rows):
            continue
        index_col = timeseries.series_index_col(list(rows[0].keys()) if rows else ["snapshot"])
        model[sheet] = timeseries.retarget_rows(rows, index_col, new_snaps, payload.fill)
        retargeted.append(sheet)
    model["snapshots"] = [{"snapshot": s} for s in new_snaps]

    model_store.save_model(payload.sessionId, model)
    return {"snapshots": len(new_snaps), "retargeted": retargeted}


class SnapshotForecast(BaseModel):
    """Body for ``POST /api/session/snapshots/forecast`` (T1 multi-year).

    Project the current series to a future year: shift every snapshot's year by
    ``toYear − fromYear`` and grow the demand sheets by a CAGR / linear factor.
    Availability sheets (p_max_pu) are re-dated but not grown.
    """

    fromYear: int
    toYear: int
    growthPct: float = 0.0
    method: str = "cagr"  # cagr | linear
    growSheets: list[str] | None = None  # default: demand (loads-p_set)
    sessionId: str = "default"


@router.post("/snapshots/forecast")
def forecast_snapshots(payload: SnapshotForecast) -> dict:
    """Project the session's series to ``toYear`` with demand growth (T1(b))."""
    from .. import timeseries

    model = model_store.load_full_model(payload.sessionId)
    if not model:
        raise HTTPException(status_code=400, detail="No working model in this session.")
    delta = int(payload.toYear) - int(payload.fromYear)
    method = payload.method if payload.method in ("cagr", "linear") else "cagr"
    factor = timeseries.growth_factor(payload.growthPct, delta, method)
    grow = set(payload.growSheets or ["loads-p_set"])

    grown: list[str] = []
    for sheet, rows in list(model.items()):
        if not model_store.is_series_sheet(sheet, rows) or not rows:
            continue
        index_col = timeseries.series_index_col(list(rows[0].keys()))
        scale = factor if sheet in grow else 1.0
        new_rows: list[dict[str, Any]] = []
        for r in rows:
            nr: dict[str, Any] = {}
            for k, v in r.items():
                if k == index_col:
                    nr[k] = timeseries.shift_snapshot_year(str(v), delta)
                elif scale != 1.0 and isinstance(v, (int, float)) and not isinstance(v, bool):
                    nr[k] = v * scale
                else:
                    nr[k] = v
            new_rows.append(nr)
        model[sheet] = new_rows
        if scale != 1.0:
            grown.append(sheet)

    snaps = model.get("snapshots") or []
    model["snapshots"] = [{**s, "snapshot": timeseries.shift_snapshot_year(str(s.get("snapshot")), delta)} for s in snaps]

    model_store.save_model(payload.sessionId, model)
    return {"toYear": payload.toYear, "growthFactor": round(factor, 4), "grown": grown}


@router.post("/clear")
def clear_session(session_id: str = Query("default", alias="session_id")) -> dict:
    """Clear the session's working model (settings are a separate frontend concern)."""
    return {"cleared": model_store.clear(session_id)}
