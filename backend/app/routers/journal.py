"""``/api/session/journal`` — the mutation audit trail (timeline, diffs, undo).

Read side backs the Assistant timeline; write side is undo/revert. All heavy
diff payloads are fetched lazily per entry (`/{id}/diff`) so listing 50 entries
never ships 50 sheet diffs. See :mod:`backend.app.journal` for semantics.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import journal

router = APIRouter(prefix="/api/session/journal", tags=["journal"])


@router.get("")
def list_journal(
    session_id: str = Query("default", alias="session_id"),
    limit: int = Query(50, ge=1, le=500),
    before: int | None = Query(None, ge=1, description="Return entries with id < before (paging)."),
) -> dict:
    """Newest-first journal entries + the current session version."""
    return {
        "version": journal.current_version(session_id),
        "entries": journal.list_entries(session_id, limit=limit, before=before),
    }


@router.get("/{entry_id}/diff")
def get_entry_diff(
    entry_id: int,
    session_id: str = Query("default", alias="session_id"),
) -> dict:
    """The detailed (capped) diff for one entry."""
    diff = journal.entry_diff(session_id, entry_id)
    if diff is None:
        raise HTTPException(status_code=404, detail=f"Journal entry {entry_id} not found.")
    return diff


@router.post("/{entry_id}/undo")
def undo_entry(
    entry_id: int,
    session_id: str = Query("default", alias="session_id"),
) -> dict:
    """Undo a single entry (blocked with 409 when a later entry overlaps)."""
    try:
        return journal.undo(session_id, entry_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except journal.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class RevertRequest(BaseModel):
    """Body for ``POST /api/session/journal/revert``."""

    toVersion: int
    sessionId: str = "default"


@router.post("/revert")
def revert_journal(payload: RevertRequest) -> dict:
    """Undo every entry newer than ``toVersion`` (newest first)."""
    try:
        return journal.revert_to(payload.sessionId, payload.toVersion)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("")
def purge_journal(session_id: str = Query("default", alias="session_id")) -> dict:
    """Delete the session's journal + undo snapshots (audit trail included)."""
    journal.purge(session_id)
    return {"purged": True}
