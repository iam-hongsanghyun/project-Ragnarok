"""External-data importer subsystem.

Each ``Database`` module lives under :mod:`databases.<id>` and is registered in
``databases.json``. The registry merges that index with each module's own
``config.json`` and exposes everything via ``GET /api/import/databases`` for
the frontend Data view.

See ``docs/TODO.md`` items ``I1`` (location-based bootstrap) and ``I2`` (PyPSA-
Earth importer) for the roadmap context.
"""
from __future__ import annotations

from .protocol import (
    ConvertOptions,
    Database,
    DatabaseMeta,
    FetchResult,
    Filter,
    PreviewSummary,
    Provenance,
    WorkbookFragment,
)
from .registry import (
    available_databases,
    get_database,
    list_database_metas,
    registered_databases,
)

__all__ = [
    "ConvertOptions",
    "Database",
    "DatabaseMeta",
    "FetchResult",
    "Filter",
    "PreviewSummary",
    "Provenance",
    "WorkbookFragment",
    "available_databases",
    "get_database",
    "list_database_metas",
    "registered_databases",
]
