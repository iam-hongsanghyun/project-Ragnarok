"""``/api/project-file`` — a project as one SQLite file (``project.db``).

The format is specified in ``docs/project-file.md``: PyPSA and Ragnarok sheets in a catalog, plus every app
setting in ``_app_state``. These endpoints move such a file in and out of a session, and build one from a model
without touching any session (what an agent or another tool uses to author a project)::

    GET  /api/project-file?session_id=...        -> the session's project.db (download)
    POST /api/project-file?session_id=...        <- upload a project.db; it becomes the session's project
    POST /api/project-file/build                 -> a project.db built from {model, appState?, ...} (download)
    GET  /api/project-file/guide                 -> the format specification (markdown)
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import model_store, sqlite_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/project-file", tags=["project-file"])

_MEDIA = "application/vnd.sqlite3"
_GUIDE = Path(__file__).resolve().parents[3] / "docs" / "project-file.md"


def _file_response(path: Path, name: str) -> Response:
    return Response(
        content=path.read_bytes(),
        media_type=_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _download_name(meta: dict[str, Any]) -> str:
    stem = str(meta.get("filename") or "ragnarok").rsplit("/", 1)[-1]
    for ext in (".xlsx", ".xls", ".zip", ".db"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
    return f"{stem or 'ragnarok'}.db"


@router.get("")
def download(session_id: str = Query("default", alias="session_id")) -> Response:
    """The session's project file: model, settings and all (``docs/project-file.md``)."""
    if not model_store.USE_SQLITE:
        raise HTTPException(status_code=409, detail="Project files need the SQLite store (RAGNAROK_STORE=sqlite).")
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "project.db"
        meta = sqlite_store.export_file(session_id, dest)
        if meta is None:
            raise HTTPException(status_code=404, detail="No project is loaded in this session.")
        return _file_response(dest, _download_name(meta))


@router.post("")
async def upload(file: UploadFile = File(...), session_id: str = Query("default", alias="session_id")) -> dict:
    """Open an uploaded ``project.db`` as the session's project (an older layout is upgraded). Returns the meta."""
    if not model_store.USE_SQLITE:
        raise HTTPException(status_code=409, detail="Project files need the SQLite store (RAGNAROK_STORE=sqlite).")
    data = await file.read()
    from .. import journal

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "upload.db"
        src.write_bytes(data)
        try:
            sqlite_store.validate_file(src)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        meta = journal.record_external_replace(
            session_id, f"open project file {file.filename or 'project.db'!r}",
            lambda: sqlite_store.import_file(session_id, src),
        )
    logger.info("Opened project file %s into session %s", file.filename, session_id)
    return {"loaded": True, "meta": meta or {}, "appState": model_store.get_app_state(session_id) or {}}


class BuildPayload(BaseModel):
    """Body for ``POST /api/project-file/build``.

    ``model`` is ``{sheet: rows}`` in PyPSA names and units (``docs/project-file.md`` §3); ``appState`` is the
    settings to carry (``{key: value}``, §5); ``example`` (``{label, description, order}``) makes the file listable
    as a bundled example.
    """

    model: dict[str, list[dict[str, Any]]]
    appState: dict[str, str] | None = None
    filename: str = ""
    scenarioName: str = ""
    example: dict[str, Any] | None = None


@router.post("/build")
def build(payload: BuildPayload) -> Response:
    """Build a project file from a model with Ragnarok's own writer, without touching any session."""
    if not payload.model:
        raise HTTPException(status_code=400, detail="model is empty: give at least snapshots, buses and one component.")
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "project.db"
        try:
            meta = sqlite_store.build_file(
                payload.model, dest, app_state=payload.appState, filename=payload.filename,
                scenario_name=payload.scenarioName, example=payload.example,
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _file_response(dest, _download_name(meta))


@router.get("/guide")
def guide() -> dict:
    """The project-file format specification (``docs/project-file.md``) as markdown."""
    if not _GUIDE.exists():
        raise HTTPException(status_code=404, detail="docs/project-file.md is not in this checkout.")
    return {"path": "docs/project-file.md", "markdown": _GUIDE.read_text(encoding="utf-8")}
