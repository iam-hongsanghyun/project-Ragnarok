"""Forge / Build helpers + the single fragment merge, as endpoints (WA8).

``/api/forge/snap``, ``/api/forge/adjust``, ``/api/forge/adjust/revert``,
``/api/build/conversions``, ``/api/build/conversion`` and
``/api/session/merge-fragment`` wrap the pure modules
:mod:`backend.app.forge_helpers` and :mod:`backend.app.fragment_merge`, so the
GUI and the MCP server run the same code. Each endpoint takes its data from the
body when given (``rows`` / ``model``) and otherwise from the session, and
mutates the session only when ``apply`` is true.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import forge_helpers as fh
from .. import fragment_merge, model_store

router = APIRouter(tags=["forge-build"])


def _session_model(session_id: str, *, static_only: bool = True) -> dict[str, list[dict[str, Any]]]:
    model = model_store.load_full_model(session_id, static_only=static_only)
    if not model:
        raise HTTPException(status_code=400, detail="No working model in this session.")
    return model


# ── Forge: snap ──────────────────────────────────────────────────────────────


class SnapRequest(BaseModel):
    sessionId: str = "default"
    sheet: str | None = Field(None, description="Session sheet to snap (when `rows` is omitted).")
    rows: list[dict[str, Any]] | None = None
    targets: list[dict[str, Any]] | None = Field(
        None, description="[{name, lat, lon}]; default = `targetRows`, else the session's buses carrying x/y."
    )
    targetRows: list[dict[str, Any]] | None = Field(
        None, description="Inline bus rows (name, x = lon, y = lat) to derive the snap targets from (UI)."
    )
    bufferKm: float = Field(50.0, ge=0)
    apply: bool = Field(False, description="Write the changed bus fields into the session sheet.")


@router.post("/api/forge/snap")
def snap(req: SnapRequest) -> dict[str, Any]:
    """Connect components carrying x/y to their nearest bus within ``bufferKm``."""
    model: dict[str, list[dict[str, Any]]] | None = None
    rows = req.rows
    if rows is None:
        if not req.sheet:
            raise HTTPException(status_code=400, detail="Give `rows` or a session `sheet`.")
        model = _session_model(req.sessionId)
        rows = model.get(req.sheet)
        if rows is None:
            raise HTTPException(status_code=404, detail=f"Sheet {req.sheet!r} not found in session.")
    targets = req.targets
    if targets is None and req.targetRows is not None:
        targets = fh.build_targets(req.targetRows)
    if targets is None:
        model = model or _session_model(req.sessionId)
        targets = fh.build_targets(model.get("buses") or [])
    result = fh.snap_sheet(rows, targets, req.bufferKm)
    result["targets"] = len(targets)
    result["applied"] = False
    if req.apply:
        if not req.sheet or req.rows is not None:
            raise HTTPException(status_code=400, detail="`apply` needs a session `sheet` and no inline `rows`.")
        ops = [
            {"op": "set", "row": i, "column": col, "value": new[col]}
            for i, (old, new) in enumerate(zip(rows, result["rows"]))
            if new is not old
            for _x, _y, col in fh.SNAP_ANCHORS
            if new.get(col) != old.get(col)
        ]
        if ops and model_store.patch_sheet(req.sessionId, req.sheet, ops) is None:
            raise HTTPException(status_code=404, detail=f"Sheet {req.sheet!r} not found in session.")
        result["applied"] = True
        result["changedCells"] = len(ops)
    return result


# ── Forge: fill discount_rate ────────────────────────────────────────────────


class FillDiscountRateRequest(BaseModel):
    sessionId: str = "default"
    discountRate: float = Field(..., description="Fraction per year (0.05 = 5 %), from Settings -> Discount rate.")
    overwrite: bool = Field(False, description="Also replace a discount_rate a row already carries.")
    apply: bool = Field(False, description="Write the changed sheets into the session (preview when false).")


@router.post("/api/forge/fill-discount-rate")
def fill_discount_rate(req: FillDiscountRateRequest) -> dict[str, Any]:
    """Write ``discount_rate`` into every row with an ``overnight_cost`` (PyPSA's own annuity column).

    The Settings -> Discount rate action. A preview (counts only) unless ``apply``.
    """
    model = _session_model(req.sessionId)
    try:
        result = fh.fill_discount_rate(model, req.discountRate, overwrite=req.overwrite)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["applied"] = False
    if req.apply and result["sheets"]:
        _write_sheets(req.sessionId, model, result["sheets"])
        result["applied"] = True
    result["sheets"] = {s: len(rows) for s, rows in result["sheets"].items()}
    return result


# ── Forge: clean placeholder bounds ──────────────────────────────────────────


class CleanPlaceholderBoundsRequest(BaseModel):
    sessionId: str = "default"
    apply: bool = Field(False, description="Write the changed sheets into the session (preview when false).")


@router.post("/api/forge/clean-placeholder-bounds")
def clean_placeholder_bounds(req: CleanPlaceholderBoundsRequest) -> dict[str, Any]:
    """Blank every finite 1e9+ bound (1e12 standing for "no limit") so the row takes PyPSA's ``inf`` default.

    The run no longer snaps these itself; the model check flags them and this is the visible fix.
    A preview (the cells it would clear) unless ``apply``.
    """
    model = _session_model(req.sessionId)
    result = fh.clean_placeholder_bounds(model)
    result["applied"] = False
    if req.apply and result["sheets"]:
        _write_sheets(req.sessionId, model, result["sheets"])
        result["applied"] = True
    result["sheets"] = {s: len(rows) for s, rows in result["sheets"].items()}
    return result


# ── Forge: adjust / revert ───────────────────────────────────────────────────


class AdjustFilterModel(BaseModel):
    column: str = ""
    value: str = ""


class AdjustmentModel(BaseModel):
    sheet: str
    attribute: str
    action: str = Field("multiply", pattern="^(multiply|add|set)$")
    amount: float = 100.0
    filters: list[AdjustFilterModel] = []


class AdjustRequest(BaseModel):
    sessionId: str = "default"
    adjustments: list[AdjustmentModel]
    baseline: dict[str, Any] = {}
    model: dict[str, list[dict[str, Any]]] | None = Field(
        None, description="Inline model (UI); default = the session's static sheets."
    )
    apply: bool = Field(False, description="Write the changed sheets into the session.")


def _adjustments(req: AdjustRequest) -> list[dict[str, Any]]:
    return [a.model_dump() for a in req.adjustments]


def _write_sheets(session_id: str, model: dict[str, list[dict[str, Any]]], sheets: dict[str, list[dict[str, Any]]]) -> None:
    merged = {**model, **sheets}
    if model_store.merge_static_model(session_id, merged) is None:
        raise HTTPException(status_code=400, detail="No session to write into.")


@router.post("/api/forge/adjust")
def adjust(req: AdjustRequest) -> dict[str, Any]:
    """Bulk-adjust one numeric attribute (multiply % / add / set) with filters.

    Returns ``{sheets, changed, perAdjustment, baseline}`` — pass ``baseline`` to
    ``/api/forge/adjust/revert`` to restore the originals.
    """
    model = req.model if req.model is not None else _session_model(req.sessionId)
    result = fh.apply_adjustments(model, _adjustments(req), req.baseline)
    result["applied"] = False
    if req.apply and result["sheets"]:
        if req.model is not None:
            raise HTTPException(status_code=400, detail="`apply` works on the session model, not an inline one.")
        _write_sheets(req.sessionId, model, result["sheets"])
        result["applied"] = True
    return result


@router.post("/api/forge/adjust/revert")
def adjust_revert(req: AdjustRequest) -> dict[str, Any]:
    """Restore the cells the adjustments target to their original (baseline) value."""
    model = req.model if req.model is not None else _session_model(req.sessionId)
    result = fh.revert_adjustments(model, _adjustments(req), req.baseline)
    result["applied"] = False
    if req.apply and result["sheets"]:
        if req.model is not None:
            raise HTTPException(status_code=400, detail="`apply` works on the session model, not an inline one.")
        _write_sheets(req.sessionId, model, result["sheets"])
        result["applied"] = True
    return result


# ── Build: conversion templates ──────────────────────────────────────────────


@router.get("/api/build/conversions")
def list_conversions(session_id: str = "default") -> dict[str, Any]:
    """The conversion-technology templates plus the default anchor bus."""
    model = model_store.load_full_model(session_id, static_only=True) or {}
    return {
        "items": fh.CONVERSION_TEMPLATES,
        "total": len(fh.CONVERSION_TEMPLATES),
        "defaultAnchorBus": fh.default_anchor_bus(model),
    }


class ConversionRequest(BaseModel):
    sessionId: str = "default"
    templateId: str
    anchorBus: str | None = None
    name: str | None = None
    pNom: float = 100.0
    extendable: bool = False
    discountRate: float | None = Field(None, description="Written to the new row as discount_rate (PyPSA annuitises overnight_cost with it). Required when extendable; the UI sends Settings -> Discount rate.")
    model: dict[str, list[dict[str, Any]]] | None = None
    apply: bool = Field(False, description="Merge the fragment into the session model.")


@router.post("/api/build/conversion")
def build_conversion(req: ConversionRequest) -> dict[str, Any]:
    """Build (and optionally apply) the fragment that adds one conversion technology."""
    template = fh.get_template(req.templateId)
    if template is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown template {req.templateId!r}. Options: {[t['id'] for t in fh.CONVERSION_TEMPLATES]}.",
        )
    model = req.model if req.model is not None else _session_model(req.sessionId)
    anchor = req.anchorBus or fh.default_anchor_bus(model)
    if not anchor:
        raise HTTPException(status_code=400, detail="The model has no bus to anchor the conversion on.")
    try:
        fragment = fh.build_conversion_fragment(
            template, anchor_bus=anchor, p_nom=req.pNom, extendable=req.extendable, name=req.name, model=model,
            discount_rate=req.discountRate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    out: dict[str, Any] = {"fragment": fragment, "anchorBus": anchor, "applied": False}
    if req.apply:
        if req.model is not None:
            raise HTTPException(status_code=400, detail="`apply` works on the session model, not an inline one.")
        merged = fragment_merge.merge_fragment(model, fragment)
        _write_sheets(req.sessionId, model, {s: merged[s] for s in fragment["sheets"]})
        out["applied"] = True
    return out


# ── The single fragment merge ────────────────────────────────────────────────


class MergeFragmentRequest(BaseModel):
    sessionId: str = "default"
    fragment: dict[str, Any]
    model: dict[str, list[dict[str, Any]]] | None = Field(
        None, description="Inline model to merge into (UI); default = the session's full model."
    )
    apply: bool = Field(False, description="Replace the session model with the merged result.")


@router.post("/api/session/merge-fragment")
def merge_fragment_endpoint(req: MergeFragmentRequest) -> dict[str, Any]:
    """Merge a ``WorkbookFragment`` (importer / siting / PyPSA-Earth / conversion).

    Stateless when ``model`` is given (returns the merged ``model``); otherwise
    merges into the session's full model and, with ``apply``, saves it and
    returns the session meta instead of the model.
    """
    if req.model is not None and req.apply:
        raise HTTPException(status_code=400, detail="`apply` works on the session model, not an inline one.")
    # An empty session is a valid target (first import into a fresh working model).
    base = req.model if req.model is not None else (model_store.load_full_model(req.sessionId) or {})
    merged = fragment_merge.merge_fragment(base, req.fragment)
    out: dict[str, Any] = {
        "sheets": {name: len(rows) for name, rows in merged.items() if rows is not base.get(name)},
        "applied": False,
    }
    if req.apply:
        out["meta"] = model_store.resave_model(req.sessionId, merged)
        out["applied"] = True
    else:
        out["model"] = merged
    return out
