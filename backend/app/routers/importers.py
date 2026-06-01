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
    get_database,
)
from ..importers import region as region_mod
from ..importers.http import AsyncClientWrapper


router = APIRouter(prefix="/api/import", tags=["import"])


class ImportRunRequest(BaseModel):
    database_id: str
    country_iso: str
    filters: dict[str, Any] = {}
    convert_options: dict[str, Any] | None = None
    # BYOK: per-user API keys, used for this request only, never persisted.
    secrets: dict[str, str] = {}


@router.get("/databases")
def list_databases() -> dict[str, Any]:
    """Registry contents — what the left-rail tree renders."""
    return {"databases": available_databases()}


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
    """One-trip fetch: preview + workbook fragment together."""
    try:
        db = get_database(payload.database_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not db.meta.available:
        raise HTTPException(
            status_code=503,
            detail=f"database {payload.database_id!r} unavailable: "
                   f"{db.meta.unavailable_reason}",
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
    try:
        result = await db.fetch(region, dict(payload.filters), ctx)
        summary = db.preview(result)
        fragment = db.to_sheets(result, options)
    except PermissionError as exc:
        # Missing required API key — actionable 400, not a 502.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"import failed: {exc}") from exc
    finally:
        await http.aclose()

    return {
        "database_id": db.meta.id,
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
