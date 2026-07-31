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

    Carries the solved result bundle (``result``) plus the scenario and run
    options that produced it, so the exported package round-trips the run window
    and settings — not just the topology. The server builds the full input +
    output xlsx so the heavy SheetJS workbook build no longer runs in (and OOMs)
    the browser tab.

    ``model`` is OPTIONAL and exists only for API clients holding a complete
    workbook. The Ragnarok frontend sends ``sessionId`` instead and the server
    loads the full model (time-series included) from the session store: the
    browser keeps static sheets only, so an inline ``model`` from the UI would
    export a project with no time-series data at all.

    ``sessionId`` also tells the server to embed that session's current Bifrost
    conversation into the package, so importing the project resumes the chat
    where it left off.
    """

    # `model` optional: a thin client sends `sessionId` and the server hydrates the
    # session's series into it. `result` defaults to empty — a model-only export
    # legitimately has no result, and requiring it (as Bifrost did) rejects that.
    model: dict[str, list[dict[str, Any]]] | None = None
    result: dict[str, Any] = {}
    scenario: dict[str, Any] = {}
    options: dict[str, Any] = {}
    sessionId: str | None = None
