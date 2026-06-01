"""Contract between the importer registry, the FastAPI router, and each
database module.

A database module is a small object with:

  • ``meta``  — identity, category, filter schema, country coverage,
                and which user secrets (API keys) it needs.
  • ``fetch(region, filters, ctx)``  — hit the upstream, return raw parsed
                data in a ``FetchResult``. Async (I/O bound).
  • ``preview(result)``  — cheap counts / samples / map overlay for the
                right rail.
  • ``to_sheets(result, options)``  — pure conversion to a
                ``WorkbookFragment`` (sheet rows + provenance).

The shapes mirror the JSON the frontend already consumes (the browser
importers produced the same ``DatabaseMeta`` / ``PreviewSummary`` /
``WorkbookFragment``), so the Data-view UI needs no rework — only its
data source flips from the in-browser registry to ``/api/import/*``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .context import ImportContext  # noqa: F401  (re-exported for modules)


# ── Filter schema ────────────────────────────────────────────────────────────

# Kinds the frontend FilterPanel renders. Adding a kind is one branch on
# each side.
FilterKind = str  # "number" | "select" | "multiselect" | "range" | "toggle" | "date"


@dataclass(frozen=True)
class Filter:
    """One field in a database's right-rail form."""

    id: str
    label: str
    kind: FilterKind
    default: Any = None
    options: list[dict[str, Any]] | None = None  # select / multiselect
    min: float | str | None = None
    max: float | str | None = None
    step: float | None = None
    unit: str | None = None
    description: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "default": self.default,
        }
        if self.options is not None:
            out["options"] = list(self.options)
        if self.min is not None:
            out["min"] = self.min
        if self.max is not None:
            out["max"] = self.max
        if self.step is not None:
            out["step"] = self.step
        if self.unit is not None:
            out["unit"] = self.unit
        if self.description is not None:
            out["description"] = self.description
        return out


# ── Metadata ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DatabaseMeta:
    """Static metadata for one registered database."""

    id: str
    name: str
    category: str  # "transmission" | "generation" | "demand" | "costs" | …
    license: str
    homepage: str
    version_hint: str
    targets: list[str]
    filters: list[Filter] = field(default_factory=list)
    available: bool = True
    unavailable_reason: str | None = None
    description: str = ""
    short_name: str = ""
    subcategory: str = ""
    country_coverage: list[str] | str = "global"
    # Source grouping: many datasets can belong to one source/database. The
    # frontend groups by ``source_id`` (Country → Database → Datasets) and lets
    # the user multi-select datasets of a source to fetch together. Singletons
    # leave these empty and fall back to ``id`` / ``name`` in ``to_json``.
    source_id: str = ""
    source_label: str = ""
    # Other dataset ids this dataset's output references (same source). The
    # batch fetch auto-includes them so a profile is never imported without the
    # static components it attaches to — keeping every fetch PyPSA-ready.
    depends_on: list[str] = field(default_factory=list)
    # Names of user-supplied API keys this database needs (BYOK). The
    # frontend collects them from the Settings store and ships them in the
    # request body; the backend uses them per-request and never persists.
    requires_secrets: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "short_name": self.short_name or self.name,
            "source_id": self.source_id or self.id,
            "source_label": self.source_label or self.name,
            "category": self.category,
            "subcategory": self.subcategory,
            "license": self.license,
            "homepage": self.homepage,
            "version_hint": self.version_hint,
            "targets": list(self.targets),
            "filters": [f.to_json() for f in self.filters],
            "available": self.available,
            "description": self.description,
            "requires_secrets": list(self.requires_secrets),
            "depends_on": list(self.depends_on),
            "country_coverage": (
                "global"
                if self.country_coverage == "global"
                else list(self.country_coverage)
            ),
        }
        if self.unavailable_reason is not None:
            out["unavailable_reason"] = self.unavailable_reason
        return out


# ── Region + results ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Region:
    """A geographic selection. Carries the polygon (shapely geometry)."""

    country_iso: str  # ISO-3166-1 alpha-3
    country_name: str
    polygon: Any  # shapely BaseGeometry, WGS84 lat/lon

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        minx, miny, maxx, maxy = self.polygon.bounds
        return float(minx), float(miny), float(maxx), float(maxy)


@dataclass
class FetchResult:
    """Opaque container for whatever a module's fetch returned."""

    database_id: str
    region: Region
    filters: dict[str, Any]
    payload: Any
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreviewSummary:
    """Cheap summary for the right rail before the user commits."""

    counts: dict[str, int] = field(default_factory=dict)
    samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    overlay: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "counts": dict(self.counts),
            "samples": {k: list(v) for k, v in self.samples.items()},
            "notes": list(self.notes),
            "overlay": dict(self.overlay),
        }


# ── Conversion ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ConvertOptions:
    """Cross-database conversion knobs."""

    create_buses_for_plants: bool = True
    plant_bus_suffix: str = "_bus"
    plant_bus_snap_km: float = 25.0


@dataclass(frozen=True)
class Provenance:
    """One row appended to the import-provenance sheet."""

    database_id: str
    country_iso: str
    country_name: str
    filters_json: str
    convert_options_json: str
    fetch_timestamp: str  # ISO-8601 UTC
    row_counts_json: str


@dataclass
class WorkbookFragment:
    """Result of a successful fetch + convert. Merged into the workbook by
    the frontend (carriers union, dedupe-on-name, append)."""

    sheets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    provenance: Provenance | None = None
    snapshots: list[str] | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"sheets": self.sheets}
        if self.provenance is not None:
            out["provenance"] = {
                "database_id": self.provenance.database_id,
                "country_iso": self.provenance.country_iso,
                "country_name": self.provenance.country_name,
                "filters_json": self.provenance.filters_json,
                "convert_options_json": self.provenance.convert_options_json,
                "fetch_timestamp": self.provenance.fetch_timestamp,
                "row_counts_json": self.provenance.row_counts_json,
            }
        if self.snapshots is not None:
            out["snapshots"] = list(self.snapshots)
        return out


# ── Database protocol ────────────────────────────────────────────────────────


@runtime_checkable
class Database(Protocol):
    """Per-source importer module contract.

    Instantiated once by the registry and reused across requests. Modules
    must be cheap to construct (no network in ``__init__``); upstream
    connections open inside ``fetch``.
    """

    meta: DatabaseMeta

    async def fetch(
        self, region: Region, filters: dict[str, Any], ctx: ImportContext
    ) -> FetchResult: ...

    def preview(self, result: FetchResult) -> PreviewSummary: ...

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment: ...
