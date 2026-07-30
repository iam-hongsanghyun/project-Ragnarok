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
    """Body for ``POST /api/export/project`` and ``POST /api/export/workbook``.

    Carries the in-memory workbook (``model``) and the solved result bundle
    (``result``). The server builds the full input + output xlsx so the heavy
    SheetJS workbook build no longer runs in (and OOMs) the browser tab.

    ``sessionId`` lets the server re-attach the time-series sheets the browser
    does not hold (they live in the session db and page into the grid), so an
    export is complete rather than input-static-only.

    ``scenario`` / ``options`` are the same dicts a run submits. They are what
    the exported workbook's ``RAGNAROK_Constraints`` / ``RAGNAROK_Settings`` /
    ``RAGNAROK_RunState`` sheets are written from, and what a re-import reads the
    run window (``snapshotStart`` / ``snapshotEnd`` / ``snapshotWeight``) back
    out of — omit them and a re-imported project opens with a 0-snapshot window.
    """

    model: dict[str, list[dict[str, Any]]]
    result: dict[str, Any] = {}
    scenario: dict[str, Any] = {}
    options: dict[str, Any] = {}
    sessionId: str | None = None
