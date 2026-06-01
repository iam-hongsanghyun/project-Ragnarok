"""Server-side external-data importer subsystem.

The browser POSTs a filter blob to ``/api/import/run``; fetch + convert
run here in Python (pandas / shapely / httpx) so heavy datasets,
CORS-blocked sources, and per-user API keys are all handled server-side.
The frontend's only contract is the ``/api/import/*`` endpoints.
"""
from .context import ImportContext
from .protocol import (
    ConvertOptions,
    Database,
    DatabaseMeta,
    FetchResult,
    Filter,
    PreviewSummary,
    Provenance,
    Region,
    WorkbookFragment,
)
from .registry import (
    available_databases,
    available_sources,
    get_database,
    registered_databases,
)

__all__ = [
    "ImportContext",
    "ConvertOptions",
    "Database",
    "DatabaseMeta",
    "FetchResult",
    "Filter",
    "PreviewSummary",
    "Provenance",
    "Region",
    "WorkbookFragment",
    "available_databases",
    "available_sources",
    "get_database",
    "registered_databases",
]
