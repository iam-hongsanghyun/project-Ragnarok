from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RunPayload(BaseModel):
    """Body for ``POST /api/run`` / ``/api/queue`` / ``/api/validate``.

    ``model`` is the full workbook. As the working model moves server-side, a
    run may instead reference a stored session via ``sessionId`` (then ``model``
    is optional and the backend loads it from the session store). The legacy
    full-``model`` form is still accepted for back-compat.
    """

    model: dict[str, list[dict[str, Any]]] | None = None
    scenario: dict[str, Any] = {}
    options: dict[str, Any] | None = None
    sessionId: str | None = None


class SessionModelPayload(BaseModel):
    """Body for ``POST /api/session/model`` — ingest a full model into a session.

    Sent either by the frontend (after opening a workbook) or relayed by a plugin
    build result. The backend persists it and returns only the lightweight meta,
    so the browser keeps almost nothing in memory.
    """

    model: dict[str, list[dict[str, Any]]]
    filename: str = ""
    scenarioName: str = ""
    sessionId: str = "default"


class ExportProjectPayload(BaseModel):
    """Body for ``POST /api/export/project``.

    Carries the in-memory workbook (``model``) and the solved result bundle
    (``result``). The server builds the full input + output xlsx so the heavy
    SheetJS workbook build no longer runs in (and OOMs) the browser tab.
    """

    model: dict[str, list[dict[str, Any]]]
    result: dict[str, Any]
