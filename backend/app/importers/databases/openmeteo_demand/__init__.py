"""Synthetic hourly demand importer (I3-lite) — any region, keyless.

Fetches hourly temperature from Open-Meteo's global ERA5 archive at the region's
representative point, turns it into a demand shape (:mod:`.demand`), scales it to
a target annual demand, and lands a bus + load + ``loads-p_set``. The any-region
complement to the measured hourly-demand importers (ENTSO-E / EIA / KPG193).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ...context import ImportContext
from ...protocol import (
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
from ..openmeteo_renewable.cache import cache_key, get as cache_get, put as cache_put, snap
from .demand import demand_shape, scale_to_annual

_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

META = DatabaseMeta(
    id="openmeteo_demand",
    name="Open-Meteo — synthetic hourly demand (any location)",
    short_name="Open-Meteo demand",
    category="demand",
    subcategory="Hourly profiles",
    license="CC-BY 4.0 (Open-Meteo / ERA5)",
    homepage="https://open-meteo.com/en/docs/historical-weather-api",
    version_hint="Archive API (ERA5)",
    description=(
        "A weather-consistent hourly demand profile for any coordinate, built from "
        "Open-Meteo temperature (base + heating/cooling response) and scaled to a "
        "target annual demand. A heuristic for regions with no measured hourly load."
    ),
    targets=["carriers", "buses", "loads", "loads-p_set"],
    country_coverage="global",
    requires_secrets=[],
    filters=[
        Filter(id="date_from", label="From", kind="date", default="2022-01-01",
               description="Weather window start (ERA5; 2022 or earlier is safest)."),
        Filter(id="date_to", label="To", kind="date", default="2022-12-31",
               description="Weather window end. A full year gives the most realistic profile."),
        Filter(id="annual_demand_gwh", label="Annual demand (GWh)", kind="number",
               default=10.0, min=0.0, step=1.0, unit="GWh",
               description="Total yearly energy the profile is scaled to."),
        Filter(id="base_fraction", label="Base load fraction", kind="number",
               default=0.5, min=0.0, max=1.0, step=0.05,
               description="Weather-independent share of the shape (0 = pure temperature response)."),
        Filter(id="t_comfort", label="Comfort temperature (°C)", kind="number",
               default=18.0, min=0.0, max=30.0, step=1.0,
               description="Below → heating demand; above → cooling demand."),
    ],
)


def _iso(region: Region) -> str:
    return (region.country_iso or "REG").strip().upper() or "REG"


async def _fetch_temperature(http: Any, lat: float, lon: float, date_from: str, date_to: str) -> dict[str, Any]:
    glat, glon = snap(lat), snap(lon)
    key = cache_key(glat, glon, date_from, date_to, "temperature_2m")
    hit = cache_get(key)
    if hit is not None:
        return hit
    body = await http.get_json(_ARCHIVE_URL, params={
        "latitude": glat, "longitude": glon, "start_date": date_from, "end_date": date_to,
        "hourly": "temperature_2m", "timezone": "UTC",
    })
    h = (body or {}).get("hourly") or {}
    res = {
        "time": [str(t).replace("T", " ") for t in (h.get("time") or [])],
        "temp": [None if v is None else float(v) for v in (h.get("temperature_2m") or [])],
    }
    if res["time"]:
        cache_put(key, res)
    return res


class OpenMeteoDemand:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        c = region.polygon.centroid
        weather = await _fetch_temperature(
            ctx.http, float(c.y), float(c.x),
            str(filters.get("date_from") or "2022-01-01"),
            str(filters.get("date_to") or "2022-12-31"),
        )
        return FetchResult(META.id, region, dict(filters), {
            "lat": round(float(c.y), 4), "lon": round(float(c.x), 4), **weather,
        })

    def _pset(self, result: FetchResult) -> list[float]:
        f = result.filters
        shape = demand_shape(
            result.payload.get("temp") or [],
            base_fraction=float(f.get("base_fraction", 0.5) or 0.0),
            t_comfort=float(f.get("t_comfort", 18.0) or 18.0),
        )
        return scale_to_annual(shape, float(f.get("annual_demand_gwh", 10.0) or 0.0) * 1000.0)

    def preview(self, result: FetchResult) -> PreviewSummary:
        times = result.payload.get("time") or []
        pset = self._pset(result)
        peak = max(pset) if pset else 0.0
        energy = sum(pset)  # MWh over the window (hourly weights)
        return PreviewSummary(
            counts={"hours": len(times), "loads": 1},
            samples={"hours": [{"time": t} for t in times[:24]]},
            notes=[
                f"{len(times)} hourly points at ({result.payload['lat']:.2f}, {result.payload['lon']:.2f}).",
                f"Peak {peak:.0f} MW, {energy / 1000:.1f} GWh over the window.",
            ],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        times = result.payload.get("time") or []
        pset = self._pset(result)
        frag = WorkbookFragment()
        if not times or not pset:
            return frag
        iso = _iso(result.region)
        bus, load = f"load_{iso}", f"demand_{iso}"
        frag.sheets["carriers"] = [{"name": "AC"}]
        frag.sheets["buses"] = [{"name": bus, "carrier": "AC", "x": result.payload["lon"], "y": result.payload["lat"]}]
        frag.sheets["loads"] = [{"name": load, "bus": bus}]
        frag.sheets["loads-p_set"] = [
            {"snapshot": t, load: round(pset[i], 3)} for i, t in enumerate(times) if i < len(pset)
        ]
        frag.snapshots = list(times)
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps({s: len(r) for s, r in frag.sheets.items()}, sort_keys=True),
        )
        return frag


def build() -> Database:
    return OpenMeteoDemand()
