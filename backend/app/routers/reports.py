"""``/api/reports/*`` — perspective-based report documents from stored runs.

Thin HTTP surface over :mod:`backend.app.reporting`: the assembler selects and
frames what the run already stores, so every endpoint here is read-only and
deterministic given the run. The AI authoring layer (Bifrost) consumes these
same documents via the MCP surface and writes prose around them — numbers only
ever come from here.

Endpoints:

    GET /api/reports/perspectives          — perspectives with section outlines.
    GET /api/reports/{run_name}/{pid}      — the assembled report document;
                                             ``run_name`` may be ``latest``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from .. import reporting

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/perspectives")
def list_perspectives() -> dict[str, Any]:
    """Every report perspective with its audience and section outline."""
    return {"perspectives": reporting.list_perspectives()}


@router.get("/{run_name}/{perspective}")
def get_report(run_name: str, perspective: str) -> dict[str, Any]:
    """Assemble the report document for a stored run under a perspective."""
    try:
        document = reporting.build_report(run_name, perspective)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    return document
