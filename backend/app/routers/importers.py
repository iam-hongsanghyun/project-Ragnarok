"""``/api/import/*`` — the external-data importer subsystem.

The Data view's three-pane shell routes through these endpoints. The
browser sends only a filter blob (+ any BYOK secrets); fetch and convert
run here. The frontend's entire outside world for data import is this
one router.

  GET  /api/import/databases                  — registry (left rail tree)
  GET  /api/import/countries                  — country index (map search)
  GET  /api/import/boundaries/countries.geojson — polygons (the world map)
  POST /api/import/run                        — fetch + preview + fragment

``POST /run`` is one trip: it returns the preview (right-rail counts /
samples / overlay) AND the workbook fragment together, matching the
main modelling pattern (1 payload in → 1 result out). The frontend holds
the fragment in React state until the user clicks Add to workbook — no
second network call.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..importers import (
    ConvertOptions,
    ImportContext,
    available_databases,
    available_sources,
    registered_databases,
)
from ..importers import region as region_mod
from ..importers.combine import combine_fragments, combine_previews
from ..importers.http import AsyncClientWrapper


router = APIRouter(prefix="/api/import", tags=["import"])


class ImportRunRequest(BaseModel):
    # Datasets of one source to fetch together (Country → Database → Datasets).
    dataset_ids: list[str] = []
    # Back-compat single-dataset form (older clients): treated as [database_id].
    database_id: str | None = None
    country_iso: str
    filters: dict[str, Any] = {}
    convert_options: dict[str, Any] | None = None
    # BYOK: per-user API keys, used for this request only, never persisted.
    secrets: dict[str, str] = {}


@router.get("/databases")
def list_databases() -> dict[str, Any]:
    """Flat registry contents (one entry per dataset)."""
    return {"databases": available_databases()}


@router.get("/sources")
def list_sources() -> dict[str, Any]:
    """Datasets grouped by source for the Country → Database → Datasets tree,
    each with its ``common_filters`` (settings shared by ≥2 of its datasets)."""
    return {"sources": available_sources()}


def _resolve_dataset_order(requested: list[str]) -> list[str]:
    """Expand the requested datasets with their declared ``depends_on`` and
    return them dependency-first (so a profile's static anchor is fetched and
    combined before the profile). Guards against unknown ids and cycles."""
    dbs = registered_databases()
    ordered: list[str] = []
    visiting: set[str] = set()

    def visit(did: str) -> None:
        if did in ordered or did in visiting:
            return
        db = dbs.get(did)
        if db is None:
            raise KeyError(f"unknown dataset id: {did!r}")
        visiting.add(did)
        for dep in db.meta.depends_on:
            visit(dep)
        visiting.discard(did)
        ordered.append(did)

    for did in requested:
        visit(did)
    return ordered


@router.get("/countries")
async def list_countries() -> dict[str, Any]:
    """Country index for the map search box. Warms the boundaries cache
    on first call (so the very first request may fetch Natural Earth)."""
    await _ensure_boundaries_warm()
    try:
        return {"countries": region_mod.country_list()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/boundaries/countries.geojson")
async def boundaries() -> Response:
    """Country polygons GeoJSON for the Data-view map."""
    await _ensure_boundaries_warm()
    try:
        data = region_mod.boundaries_geojson_bytes()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="application/geo+json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/run")
async def run_import(payload: ImportRunRequest) -> dict[str, Any]:
    """One-trip fetch of one or more datasets of a source → one combined,
    PyPSA-aligned fragment + one preview.

    The selected datasets are expanded with their dependencies and fetched
    with the *same* shared filters, so e.g. every KPG193 dataset resolves the
    same version/year and their bus-derived names line up. Their fragments are
    folded together (``combine_fragments``) into one result.
    """
    requested = list(payload.dataset_ids) or (
        [payload.database_id] if payload.database_id else []
    )
    if not requested:
        raise HTTPException(status_code=400, detail="no dataset_ids provided")

    try:
        order = _resolve_dataset_order(requested)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    dbs = registered_databases()
    for did in order:
        meta = dbs[did].meta
        if not meta.available:
            raise HTTPException(
                status_code=503,
                detail=f"dataset {did!r} unavailable: {meta.unavailable_reason}",
            )

    await _ensure_boundaries_warm()
    try:
        region = region_mod.get_region(payload.country_iso)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    opts_dict = payload.convert_options or {}
    options = ConvertOptions(
        create_buses_for_plants=bool(opts_dict.get("create_buses_for_plants", True)),
        plant_bus_suffix=str(opts_dict.get("plant_bus_suffix", "_bus")),
        plant_bus_snap_km=float(opts_dict.get("plant_bus_snap_km", 25.0)),
    )

    http = AsyncClientWrapper(secrets=list(payload.secrets.values()))
    ctx = ImportContext(
        secrets=dict(payload.secrets), http=http, request_id=str(uuid.uuid4())[:8],
    )
    fragments = []
    previews = []
    try:
        for did in order:
            db = dbs[did]
            result = await db.fetch(region, dict(payload.filters), ctx)
            previews.append(db.preview(result))
            fragments.append(db.to_sheets(result, options))
    except PermissionError as exc:
        # Missing required API key — actionable 400, not a 502.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"import failed: {exc}") from exc
    finally:
        await http.aclose()

    source_id = dbs[order[0]].meta.source_id or dbs[order[0]].meta.id
    fragment = combine_fragments(
        fragments,
        source_id=source_id,
        country_iso=region.country_iso,
        country_name=region.country_name,
        filters=dict(payload.filters),
        dataset_ids=order,
    )
    summary = combine_previews(fragment, previews)

    return {
        "source_id": source_id,
        "dataset_ids": order,
        "country_iso": region.country_iso,
        "preview": summary.to_json(),
        "fragment": fragment.to_json(),
    }


# ── Boundaries warm helper ───────────────────────────────────────────────────

_boundaries_warmed = False


async def _ensure_boundaries_warm() -> None:
    """Fetch + cache the Natural Earth boundaries once per process.

    The first importer interaction (country list, run, or geojson) pays
    the ~3 MB download; everything after reads the on-disk cache.
    """
    global _boundaries_warmed
    if _boundaries_warmed:
        return
    http = AsyncClientWrapper()
    try:
        await region_mod.ensure_boundaries(http)
        _boundaries_warmed = True
    finally:
        await http.aclose()
