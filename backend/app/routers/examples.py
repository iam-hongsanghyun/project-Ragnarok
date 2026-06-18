"""``/api/examples`` — bundled starter projects (SQLite ``project.db`` files).

Each example is a directory under ``backend/data/examples/<id>/`` holding a
``project.db`` (the very same per-session SQLite the working store uses) and an
optional ``meta.json`` (``{label, description, order}``). The welcome screen's
"Start with Examples" lists these and loads one into the active session by
copying its ``project.db`` over the session's — so the editor opens a real,
ready-to-solve model with zero client-side parsing. Drop a new folder in to add
an example; no code change needed.
"""
from __future__ import annotations

import json
import logging
import shutil

from fastapi import APIRouter, HTTPException, Query

from .. import model_store, session_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/examples", tags=["examples"])

# Tracked (committed) — sits beside the runtime session/ dir but is NOT ignored.
EXAMPLES_DIR = session_store.SESSION_DIR.parent / "examples"


def _is_safe_id(example_id: str) -> bool:
    return bool(example_id) and "/" not in example_id and "\\" not in example_id and ".." not in example_id


def _read_meta(example_id: str) -> dict:
    path = EXAMPLES_DIR / example_id / "meta.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@router.get("")
def list_examples() -> dict:
    """List bundled examples (every ``<id>/`` that has a ``project.db``)."""
    out: list[dict] = []
    if EXAMPLES_DIR.is_dir():
        for d in sorted(EXAMPLES_DIR.iterdir()):
            if not d.is_dir() or not (d / "project.db").exists():
                continue
            meta = _read_meta(d.name)
            out.append({
                "id": d.name,
                "label": str(meta.get("label") or d.name),
                "description": str(meta.get("description") or ""),
                "order": meta.get("order", 100),
            })
    out.sort(key=lambda e: (e.get("order", 100), e["label"]))
    return {"examples": out}


@router.post("/{example_id}/load")
def load_example(example_id: str, session_id: str = Query("default", alias="session_id")) -> dict:
    """Load an example into the session by copying its ``project.db`` over the
    session's, then return the session meta (so the client can rehydrate)."""
    if not _is_safe_id(example_id):
        raise HTTPException(status_code=400, detail="Invalid example id.")
    src = EXAMPLES_DIR / example_id / "project.db"
    if not src.exists():
        raise HTTPException(status_code=404, detail="Example not found.")

    dest_dir = session_store.SESSION_DIR / session_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    # The copied project.db is authoritative — drop any legacy JSON/Parquet
    # session files so the SQLite store doesn't see a split-brain session.
    for legacy in ("static", "series"):
        legacy_dir = dest_dir / legacy
        if legacy_dir.is_dir():
            shutil.rmtree(legacy_dir, ignore_errors=True)
    tmp = dest_dir / "project.db.tmp"
    shutil.copy2(src, tmp)
    tmp.replace(dest_dir / "project.db")

    meta = model_store.get_meta(session_id) or {}
    logger.info("Loaded example %s into session %s", example_id, session_id)
    return {"loaded": True, "id": example_id, "label": str(_read_meta(example_id).get("label") or example_id), "meta": meta}
