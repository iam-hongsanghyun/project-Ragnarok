from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RunPayload(BaseModel):
    model: dict[str, list[dict[str, Any]]]
    scenario: dict[str, Any]
    options: dict[str, Any] | None = None


# ── Importer subsystem ──────────────────────────────────────────────────────


class ImportRunRequest(BaseModel):
    """``POST /api/import/run``: one-trip fetch.

    Returns ``{preview, fragment}`` together — the frontend uses ``preview``
    for the right-rail counts / sample / overlay and holds ``fragment`` in
    React state until the user clicks Add to workbook.
    """

    database_id: str
    country_iso: str
    filters: dict[str, Any] = {}
    convert_options: dict[str, Any] | None = None

