"""``/api/siting/*`` — power-system location optimisation (siting) scans.

One-trip, stateless scan matching the importer pattern (1 payload in → 1
result out): the browser posts a bounding box, technologies, cost assumptions,
and the grid buses it already holds; the server samples a candidate grid,
fetches cached keyless weather per point (the Open-Meteo importer's
``fetch_point``), and returns the candidate list + preview + a
``WorkbookFragment`` of extendable candidate assets. The frontend holds the
fragment in React state until the user clicks "Add candidates to model" — the
same client-side merge the Data view uses — and the ordinary capacity-
expansion solve then picks the winning sites. No session mutation happens
here.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..importers.databases.openmeteo_renewable.fetch import fetch_point
from ..importers.databases.openmeteo_renewable.sources import SOURCES
from ..importers.http import AsyncClientWrapper
from ..importers.protocol import PreviewSummary
from ..siting import MAX_CANDIDATES, build_siting_fragment, sample_grid

router = APIRouter(prefix="/api/siting", tags=["siting"])


class GridBus(BaseModel):
    """An existing bus candidates may connect to (PyPSA x=lon, y=lat)."""

    name: str
    x: float
    y: float


class SitingScanRequest(BaseModel):
    bbox: list[float] = Field(..., description="Candidate region [minLon, minLat, maxLon, maxLat] (WGS84).")
    technologies: list[str] = ["solar", "wind"]
    gridPoints: int = Field(25, description=f"Target number of candidate sites (max {MAX_CANDIDATES}).")
    dateFrom: str = "2019-01-01"
    dateTo: str = "2019-01-31"
    utcOffset: int = 0
    weatherSource: str = Field("open-meteo", description="Reanalysis source: open-meteo | pvgis | nasa-power.")
    performanceRatio: float = 0.9
    buses: list[GridBus] = Field(..., description="Existing grid buses (connection targets).")
    siteCapacityMw: float = Field(100.0, description="Per-site build ceiling (p_nom_max, MW).")
    capitalCostPerMw: dict[str, float] = Field(
        default_factory=dict, description="Generator capex per technology (currency/MW)."
    )
    connectionCostPerMwKm: float = Field(0.0, description="Grid-connection capex rate (currency/MW·km).")
    marginalCost: float = 0.0
    targetSnapshots: list[str] | None = Field(
        None,
        description="The model's existing snapshot labels. When given, CF series are "
        "tiled onto these labels and no new snapshots are introduced — the solve "
        "window keeps its demand data. Omit to land the weather window as new snapshots.",
    )


@router.post("/scan")
async def scan(req: SitingScanRequest) -> dict[str, Any]:
    """Sample candidates, fetch their weather, return candidates + fragment."""
    if len(req.bbox) != 4:
        raise HTTPException(422, "bbox must be [minLon, minLat, maxLon, maxLat].")
    min_lon, min_lat, max_lon, max_lat = (float(v) for v in req.bbox)
    if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0
            and -90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
        raise HTTPException(422, "bbox out of WGS84 range.")
    if max_lon < min_lon or max_lat < min_lat:
        raise HTTPException(422, "bbox min must not exceed max.")
    techs = [t for t in req.technologies if t in ("solar", "wind")]
    if not techs:
        raise HTTPException(422, "technologies must include 'solar' and/or 'wind'.")
    if not req.buses:
        raise HTTPException(422, "Need at least one existing grid bus to connect candidates to.")
    if req.weatherSource not in SOURCES:
        raise HTTPException(422, f"Unknown weatherSource {req.weatherSource!r}; one of {sorted(SOURCES)}.")
    if req.siteCapacityMw <= 0:
        raise HTTPException(422, "siteCapacityMw must be positive.")
    n = max(1, min(int(req.gridPoints), MAX_CANDIDATES))

    pts = sample_grid((min_lon, min_lat, max_lon, max_lat), n)
    http = AsyncClientWrapper()
    try:
        fetched = await asyncio.gather(
            *[fetch_point(http, lat, lon, req.dateFrom, req.dateTo, req.weatherSource) for lat, lon in pts]
        )
    except Exception as exc:  # noqa: BLE001 — upstream weather fetch failed
        raise HTTPException(502, f"weather fetch failed: {exc}") from exc
    finally:
        await http.aclose()

    sites = [{"lat": lat, "lon": lon, **res} for (lat, lon), res in zip(pts, fetched)]
    buses = [b.model_dump() for b in req.buses]
    # Provenance filters: drop the bulky passthrough lists, note target mode.
    filters = req.model_dump(exclude={"buses", "targetSnapshots"})
    filters["targetSnapshotCount"] = len(req.targetSnapshots or [])
    try:
        fragment, candidates = build_siting_fragment(
            sites, buses,
            technologies=techs,
            utc_offset=int(req.utcOffset),
            performance_ratio=float(req.performanceRatio),
            site_capacity_mw=float(req.siteCapacityMw),
            capital_cost_per_mw=dict(req.capitalCostPerMw),
            connection_cost_per_mw_km=float(req.connectionCostPerMwKm),
            marginal_cost=float(req.marginalCost),
            target_snapshots=req.targetSnapshots,
            filters=filters,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not candidates:
        raise HTTPException(
            502,
            "No candidate returned weather data — the source may not cover this "
            "region/window (PVGIS covers 2005–2020; reanalyses lag a few days).",
        )

    skipped = len(pts) - len(candidates)
    hours = len(fragment.snapshots or [])
    dists = [c["distanceKm"] for c in candidates]
    notes = [f"{len(candidates)} candidate site(s), {hours} hourly points."]
    if skipped:
        notes.append(f"{skipped} point(s) returned no weather data and were skipped.")
    for tech in techs:
        cfs = [c["meanCf"].get(tech, 0.0) for c in candidates]
        if cfs:
            notes.append(f"{tech.capitalize()} mean CF {min(cfs):.2f}–{max(cfs):.2f}.")
    if dists:
        notes.append(f"Grid distance {min(dists):.0f}–{max(dists):.0f} km.")
    preview = PreviewSummary(
        counts={
            "sites": len(candidates), "hours": hours,
            "generators": len(fragment.sheets.get("generators", [])),
            "links": len(fragment.sheets.get("links", [])),
        },
        samples={"sites": [{"lat": c["lat"], "lon": c["lon"]} for c in candidates[:8]]},
        notes=notes,
    )
    return {
        "candidates": candidates,
        "preview": preview.to_json(),
        "fragment": fragment.to_json(),
    }
