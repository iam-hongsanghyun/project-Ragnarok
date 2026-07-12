"""``/api/forge/query/*`` — the Forge **Query & Edit** tool.

A database-query-like bulk edit: select a component + attribute (static or
temporal), narrow rows with ANDed filters (each on the target *or* a one-hop
linked component), and edit — set / add / multiply / derive-from-attribute.

``preview`` returns match counts + a before/after sample (no mutation); ``apply``
writes through the session store (``patch_sheet`` for static, ``transform_series``
for temporal). The heavy lifting is the pure resolver in :mod:`..forge_resolver`;
this router is a thin session-loading + execution wrapper (mirrors the
pure ``cluster_model`` / thin ``cluster_network`` split in :mod:`.transforms`).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import forge_resolver as fr
from .. import model_store

router = APIRouter(prefix="/api/forge", tags=["forge"])


class JoinPathModel(BaseModel):
    component: str
    ref_column: str


class FilterModel(BaseModel):
    column: str
    op: Literal["eq", "ne", "contains", "in", "gt", "lt", "ge", "le"]
    value: Any | None = None
    values: list[Any] | None = None
    join: JoinPathModel | None = None


class EditModel(BaseModel):
    op: Literal["set", "add", "multiply", "derive"]
    amount: float | None = None
    source_attr: str | None = None
    coefficient: float = 1.0
    constant: float = 0.0
    # Temporal `add` semantics (ignored otherwise): MW-per-snapshot vs
    # MWh-over-period, applied to each matched series or split across them.
    unit: Literal["mw", "mwh"] = "mw"
    scope: Literal["each", "total"] = "each"
    split: Literal["proportional", "equal"] = "proportional"


class QueryEditRequest(BaseModel):
    sessionId: str = "default"
    target: str
    attribute: str
    temporal: bool = False
    filters: list[FilterModel] = []
    edit: EditModel


def _to_query(req: QueryEditRequest) -> fr.Query:
    """Map the wire model onto the resolver's plain dataclasses."""
    filters = [
        fr.Filter(
            column=f.column,
            op=f.op,
            value=f.value,
            values=f.values,
            join=fr.JoinPath(component=f.join.component, ref_column=f.join.ref_column)
            if f.join
            else None,
        )
        for f in req.filters
    ]
    edit = fr.Edit(
        op=req.edit.op,
        amount=req.edit.amount,
        source_attr=req.edit.source_attr,
        coefficient=req.edit.coefficient,
        constant=req.edit.constant,
        unit=req.edit.unit,
        scope=req.edit.scope,
        split=req.edit.split,
    )
    return fr.Query(
        target=req.target,
        attribute=req.attribute,
        temporal=req.temporal,
        filters=filters,
        edit=edit,
    )


def _load_model(session_id: str) -> dict[str, list[dict[str, Any]]]:
    model = model_store.load_full_model(session_id)
    if not model:
        raise HTTPException(status_code=400, detail="No working model in this session.")
    return model


@router.post("/query/preview")
def query_preview(req: QueryEditRequest) -> dict[str, Any]:
    """Match count + before/after sample. No mutation."""
    model = _load_model(req.sessionId)
    try:
        return fr.preview(model, _to_query(req))
    except fr.ForgeQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/query/apply")
def query_apply(req: QueryEditRequest) -> dict[str, Any]:
    """Resolve the query and write the edit into the session."""
    model = _load_model(req.sessionId)
    query = _to_query(req)
    try:
        names = fr.match_target_names(model, query.target, query.filters)
        if query.temporal:
            action = fr.resolve_temporal(model, query.target, query.attribute, names, query.edit)
            sheet = action["sheet"]
            present = action.get("present", 0)
            for op, params in action["steps"]:
                if model_store.transform_series(req.sessionId, sheet, op, params) is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Time-series sheet {sheet!r} not found in session.",
                    )
            return {
                "matched": len(names),
                "temporal": True,
                "seriesSheet": sheet,
                "changed": present,
            }
        ops = fr.resolve_static_ops(model, query.target, query.attribute, names, query.edit)
        if ops:
            result = model_store.patch_sheet(req.sessionId, query.target, ops)
            if result is None:
                raise HTTPException(
                    status_code=404, detail=f"Sheet {query.target!r} not found in session."
                )
        return {
            "matched": len(names),
            "temporal": False,
            "sheet": query.target,
            "changed": len(ops),
        }
    except fr.ForgeQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
