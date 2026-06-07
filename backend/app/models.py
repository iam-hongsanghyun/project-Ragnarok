from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RunPayload(BaseModel):
    model: dict[str, list[dict[str, Any]]]
    scenario: dict[str, Any]
    options: dict[str, Any] | None = None


class ExportProjectPayload(BaseModel):
    """Body for ``POST /api/export/project``.

    Carries the in-memory workbook (``model``) and the solved result bundle
    (``result``). The server builds the full input + output xlsx so the heavy
    SheetJS workbook build no longer runs in (and OOMs) the browser tab.
    """

    model: dict[str, list[dict[str, Any]]]
    result: dict[str, Any]
