from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RunPayload(BaseModel):
    model: dict[str, list[dict[str, Any]]]
    scenario: dict[str, Any]
    options: dict[str, Any] | None = None


# ── Importer subsystem ──────────────────────────────────────────────────────


class ImportPreviewRequest(BaseModel):
    """``POST /api/import/preview``: ``{database_id, country_iso, filters}``."""

    database_id: str
    country_iso: str
    filters: dict[str, Any] = {}


class ImportFetchRequest(BaseModel):
    """``POST /api/import/fetch``: same shape + ``convert_options``."""

    database_id: str
    country_iso: str
    filters: dict[str, Any] = {}
    convert_options: dict[str, Any] | None = None

