"""Database protocol + shared dataclasses for the importer subsystem.

The shape is deliberately small. A database module has three responsibilities:

1. Declare its identity, category, and filter schema (``DatabaseMeta``,
   ``Filter``). The registry exposes this to the frontend so the right-rail
   form can render with no code per source.
2. ``fetch(region, filters)`` — hit the upstream and return raw parsed data in
   a ``FetchResult``. No conversion to the workbook schema here.
3. ``to_sheets(result, options)`` — pure-function conversion from the raw
   ``FetchResult`` to a ``WorkbookFragment`` (sheet rows + provenance row).

Keeping fetch and convert separated lets the preview endpoint return cheap
counts (``preview()``) without forcing the full conversion, and lets future
work re-run conversion with different ``ConvertOptions`` (e.g. bus-snap
tolerance) without re-fetching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from shapely.geometry.base import BaseGeometry


# ── Filter schema ────────────────────────────────────────────────────────────

# Filter kinds the frontend FilterPanel knows how to render. Adding a new kind
# is a one-branch change on both sides.
FilterKind = str  # "number" | "select" | "multiselect" | "range" | "toggle"


@dataclass(frozen=True)
class Filter:
    """One field in a database's right-rail form."""

    id: str
    label: str
    kind: FilterKind
    default: Any = None
    options: list[dict[str, Any]] | None = None  # for select / multiselect
    min: float | None = None
    max: float | None = None
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
    category: str  # "transmission" | "generation" | "demand"
    license: str
    homepage: str
    version_hint: str  # free text — "live", "v1.3.0", etc.
    targets: list[str]  # workbook sheets this database can write to
    filters: list[Filter] = field(default_factory=list)
    available: bool = True
    unavailable_reason: str | None = None
    description: str = ""
    subcategory: str = ""  # Optional second-level grouping inside `category`
    """Free-text second-level grouping, used by the frontend tree (e.g.
    'Power plants', 'Annual aggregates', 'Hourly profiles'). Empty string
    means the database sits directly under its category."""

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "subcategory": self.subcategory,
            "license": self.license,
            "homepage": self.homepage,
            "version_hint": self.version_hint,
            "targets": list(self.targets),
            "filters": [f.to_json() for f in self.filters],
            "available": self.available,
            "description": self.description,
        }
        if self.unavailable_reason is not None:
            out["unavailable_reason"] = self.unavailable_reason
        return out


# ── Region + results ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Region:
    """A geographic selection. Always carries the polygon."""

    country_iso: str  # ISO-3166-1 alpha-3
    country_name: str
    polygon: BaseGeometry  # WGS84 lat/lon

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """``(min_lon, min_lat, max_lon, max_lat)`` for HTTP queries."""
        minx, miny, maxx, maxy = self.polygon.bounds
        return float(minx), float(miny), float(maxx), float(maxy)


@dataclass
class FetchResult:
    """Opaque container for whatever a module's fetch returned.

    The shape is intentionally untyped — different sources return different
    things (a DataFrame, a parsed Overpass JSON, a path to a downloaded
    netCDF). The conversion step is what unifies them.
    """

    database_id: str
    region: Region
    filters: dict[str, Any]
    payload: Any
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreviewSummary:
    """Cheap summary surfaced in the right rail before the user commits."""

    counts: dict[str, int] = field(default_factory=dict)
    samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    overlay: dict[str, Any] = field(default_factory=dict)
    """Optional map overlay payload (e.g. a GeoJSON FeatureCollection) for the
    main map preview layer. Shape is up to the database; the frontend just
    renders Leaflet layers from the geometries it recognises."""

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
    """Cross-database conversion knobs (see ``convert.sheets`` for usage)."""

    # When True, generators land on per-plant synthetic buses. When False,
    # converters that have no other choice may emit only the generator rows
    # and skip bus creation (the caller will reconcile later).
    create_buses_for_plants: bool = True
    # Per-plant bus suffix.
    plant_bus_suffix: str = "_bus"
    # Used by the frontend when reconciling plants ↔ grid in a later step.
    plant_bus_snap_km: float = 25.0


@dataclass(frozen=True)
class Provenance:
    """One row appended to the ``RAGNAROK_Provenance`` import-provenance sheet."""

    database_id: str
    country_iso: str
    country_name: str
    filters_json: str
    convert_options_json: str
    fetch_timestamp: str  # ISO-8601 UTC, supplied by the caller (no Date.now in workflows)
    row_counts_json: str


@dataclass
class WorkbookFragment:
    """The cross-database result of a successful fetch + convert.

    Sheet rows are merged into the current workbook by the frontend (carriers
    union, dedupe-on-name, append). The provenance row is appended to the
    existing ``RAGNAROK_Provenance`` sheet.
    """

    sheets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    provenance: Provenance | None = None

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
        return out


# ── Database protocol ────────────────────────────────────────────────────────


@runtime_checkable
class Database(Protocol):
    """Per-source importer module contract.

    Each module is instantiated once by the registry and reused across
    requests. Modules must be cheap to construct (no network calls in
    ``__init__``); upstream connections are opened inside ``fetch``.
    """

    meta: DatabaseMeta

    def fetch(self, region: Region, filters: dict[str, Any]) -> FetchResult: ...

    def preview(self, result: FetchResult) -> PreviewSummary: ...

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment: ...
