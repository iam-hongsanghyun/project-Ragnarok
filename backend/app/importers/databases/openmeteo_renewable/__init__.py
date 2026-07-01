"""Open-Meteo renewable capacity-factor importer (I4).

Fetches hourly ERA5 weather (global, keyless, cached) at one or more points in the
selected region and converts it to wind / solar **capacity-factor** profiles,
landing a complete, runnable renewable fragment per point: a bus, a solar and/or
wind generator on it, and their ``generators-p_max_pu`` series.

The general, any-coordinate complement to the curated per-country packs (KPG193).
Source: Open-Meteo Archive API — CC-BY, no key, global ERA5. Weather→CF maths in
:mod:`.conversion`; the cached fetch in :mod:`.fetch`. ``grid_points`` samples a
grid across the region (default 1 = centroid) so a large country gets spatial
variation. To attach profiles to an *existing* fleet by coordinate, use the
attach-to-fleet transform (``POST /api/transform/renewable-profiles``) instead.
"""
from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from shapely.geometry import Point

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
from .conversion import mean_cf, solar_cf, wind_cf
from .fetch import fetch_point

_TECHS = [
    {"value": "solar", "label": "Solar PV"},
    {"value": "wind", "label": "Wind"},
]
_MAX_POINTS = 16

# Grouped by PROVIDER: each weather provider is its own Data-view source, and a
# provider's datasets share one group. Open-Meteo's renewable-CF dataset shares
# the "open_meteo" source with the synthetic-demand dataset (see openmeteo_demand);
# PVGIS and NASA POWER are their own single-dataset sources.
_SOURCES: dict[str, dict[str, Any]] = {
    "open-meteo": {
        "id": "openmeteo_renewable",
        "source_id": "open_meteo",
        "source_label": "Open-Meteo (global ERA5, keyless)",
        "name": "Open-Meteo — renewable capacity factors (any location)",
        "short_name": "Open-Meteo CF",
        "license": "CC-BY 4.0 (Open-Meteo / ERA5)",
        "homepage": "https://open-meteo.com/en/docs/historical-weather-api",
        "version_hint": "Archive API (ERA5)",
        "description": (
            "Hourly wind & solar capacity factors for any coordinate on Earth, derived "
            "from Open-Meteo's keyless global ERA5 reanalysis (cached). Lands a bus + "
            "solar/wind generator(s) with weather-driven p_max_pu profiles."
        ),
    },
    "pvgis": {
        "id": "pvgis_renewable",
        "source_id": "pvgis",
        "source_label": "PVGIS (EU JRC, keyless)",
        "name": "PVGIS — renewable capacity factors (EU JRC)",
        "short_name": "PVGIS CF",
        "license": "EU JRC PVGIS (free reuse)",
        "homepage": "https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis_en",
        "version_hint": "PVGIS hourly (SARAH/ERA5, 2005–2020)",
        "description": (
            "Hourly wind & solar capacity factors from the EU JRC's keyless PVGIS "
            "hourly radiation service (data 2005–2020; later years are mapped onto the "
            "nearest available year). Strongest over Europe, Africa and Asia. Lands a "
            "bus + solar/wind generator(s) with weather-driven p_max_pu profiles."
        ),
    },
    "nasa-power": {
        "id": "nasa_power_renewable",
        "source_id": "nasa_power",
        "source_label": "NASA POWER (global, keyless)",
        "name": "NASA POWER — renewable capacity factors (global)",
        "short_name": "NASA POWER CF",
        "license": "NASA POWER (public domain)",
        "homepage": "https://power.larc.nasa.gov/",
        "version_hint": "POWER Hourly (MERRA-2)",
        "description": (
            "Hourly wind & solar capacity factors from NASA's keyless POWER service "
            "(MERRA-2 reanalysis), global coverage. Lands a bus + solar/wind "
            "generator(s) with weather-driven p_max_pu profiles."
        ),
    },
}


def _meta_for(source_key: str) -> DatabaseMeta:
    cfg = _SOURCES[source_key]
    return DatabaseMeta(
        id=cfg["id"],
        name=cfg["name"],
        short_name=cfg["short_name"],
        category="generation",
        subcategory="Hourly profiles",
        source_id=cfg["source_id"],
        source_label=cfg["source_label"],
        license=cfg["license"],
        homepage=cfg["homepage"],
        version_hint=cfg["version_hint"],
        description=cfg["description"],
        targets=["carriers", "buses", "generators", "generators-p_max_pu"],
        country_coverage="global",
        requires_secrets=[],  # keyless
        filters=[
            Filter(id="date_from", label="From", kind="date", default="2019-01-01",
                   description="Weather window start. Reanalyses have a multi-day lag and "
                               "recent dates can miss irradiance; PVGIS covers 2005–2020."),
            Filter(id="date_to", label="To", kind="date", default="2019-01-31",
                   description="Weather window end."),
            Filter(id="utc_offset", label="Local UTC offset (hours)", kind="number",
                   default=0, min=-12, max=14, step=1, unit="h",
                   description="Shift snapshots from UTC to local time so the diurnal "
                               "profile lines up with local demand (e.g. 9 for Korea). "
                               "Weather is always fetched in UTC."),
            Filter(id="technologies", label="Technologies", kind="multiselect",
                   default=["solar", "wind"], options=_TECHS),
            Filter(id="grid_points", label="Sample points", kind="number",
                   default=1, min=1, max=_MAX_POINTS, step=1,
                   description="1 = region centroid; >1 samples a grid across the region "
                               "for spatial variation (one renewable site per point)."),
            Filter(id="capacity_mw", label="Capacity per generator (MW)", kind="number",
                   default=100.0, min=0.0, step=10.0, unit="MW"),
            Filter(id="performance_ratio", label="Solar performance ratio", kind="number",
                   default=0.9, min=0.1, max=1.0, step=0.05),
        ],
    )


# Back-compat: the Open-Meteo meta is importable as ``META``.
META = _meta_for("open-meteo")


def _iso(region: Region) -> str:
    return (region.country_iso or "REG").strip().upper() or "REG"


def _shift_label(label: str, offset_hours: int) -> str:
    """Shift a ``"YYYY-MM-DD HH:MM"`` snapshot label from UTC to local time."""
    if not offset_hours:
        return label
    try:
        dt = datetime.strptime(label, "%Y-%m-%d %H:%M")
    except ValueError:
        return label
    return (dt + timedelta(hours=offset_hours)).strftime("%Y-%m-%d %H:%M")


def _techs(filters: dict[str, Any]) -> list[str]:
    raw = filters.get("technologies")
    if isinstance(raw, str):
        raw = [raw]
    picked = [t for t in (raw or ["solar", "wind"]) if t in ("solar", "wind")]
    return picked or ["solar", "wind"]


def _sample_points(polygon: Any, n: int) -> list[tuple[float, float]]:
    """Up to ``n`` (lat, lon) sample points inside the region.

    ``n == 1`` returns the centroid; otherwise a roughly-square grid over the
    bounding box, kept to points inside the polygon (falling back to the centroid
    if the grid misses entirely — e.g. a thin/curved country).
    """
    n = max(1, min(int(n or 1), _MAX_POINTS))
    if n == 1:
        c = polygon.centroid
        return [(round(float(c.y), 4), round(float(c.x), 4))]
    minx, miny, maxx, maxy = polygon.bounds
    side = int(math.ceil(math.sqrt(n)))
    pts: list[tuple[float, float]] = []
    for i in range(side):
        for j in range(side):
            x = minx + (i + 0.5) / side * (maxx - minx)
            y = miny + (j + 0.5) / side * (maxy - miny)
            if polygon.contains(Point(x, y)):
                pts.append((round(y, 4), round(x, 4)))
    if not pts:
        c = polygon.centroid
        return [(round(float(c.y), 4), round(float(c.x), 4))]
    return pts[:n]


class OpenMeteoRenewable:
    """Weather→CF importer for one reanalysis source (``source_key``).

    One instance is registered per provider (Open-Meteo / PVGIS / NASA POWER) so
    each shows as its own Data-view source; the source is fixed per instance
    rather than chosen via a filter.
    """

    def __init__(self, source_key: str = "open-meteo") -> None:
        self._source = source_key
        self.meta = _meta_for(source_key)

    async def fetch(
        self, region: Region, filters: dict[str, Any], ctx: ImportContext
    ) -> FetchResult:
        pts = _sample_points(region.polygon, int(filters.get("grid_points") or 1))
        date_from = str(filters.get("date_from") or "2019-01-01")
        date_to = str(filters.get("date_to") or "2019-01-31")
        fetched = await asyncio.gather(
            *[fetch_point(ctx.http, lat, lon, date_from, date_to, self._source) for lat, lon in pts]
        )
        points = [{"lat": lat, "lon": lon, **res} for (lat, lon), res in zip(pts, fetched)]
        return FetchResult(self.meta.id, region, dict(filters), {"points": points})

    def preview(self, result: FetchResult) -> PreviewSummary:
        points = result.payload.get("points") or []
        times = points[0]["time"] if points else []
        techs = _techs(result.filters)
        pr = float(result.filters.get("performance_ratio") or 0.9)
        counts = {"hours": len(times), "sites": len(points), "generators": len(points) * len(techs)}
        notes = [f"{len(points)} site(s), {len(times)} hourly points."]
        if "solar" in techs:
            allcf = [c for pt in points for c in solar_cf(pt.get("ghi") or [], pr)]
            if allcf:
                notes.append(f"Solar mean CF ≈ {mean_cf(allcf):.2f}.")
        if "wind" in techs:
            allcf = [c for pt in points for c in wind_cf(pt.get("wind_ms") or [])]
            if allcf:
                notes.append(f"Wind mean CF ≈ {mean_cf(allcf):.2f}.")
        return PreviewSummary(
            counts=counts,
            samples={"sites": [{"lat": pt["lat"], "lon": pt["lon"]} for pt in points[:8]]},
            notes=notes,
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        points = result.payload.get("points") or []
        techs = _techs(result.filters)
        iso = _iso(result.region)
        offset = int(result.filters.get("utc_offset") or 0)
        pr = float(result.filters.get("performance_ratio") or 0.9)
        capacity = max(0.0, float(result.filters.get("capacity_mw") or 100.0))
        multi = len(points) > 1

        times = points[0]["time"] if points else []
        snapshots = [_shift_label(str(t).replace("T", " "), offset) for t in times]

        carriers: list[dict[str, Any]] = [{"name": "AC"}]
        carrier_seen = {"AC"}
        bus_rows: list[dict[str, Any]] = []
        gen_rows: list[dict[str, Any]] = []
        series_by_gen: dict[str, list[float]] = {}

        for idx, pt in enumerate(points, start=1):
            suffix = f"_{idx}" if multi else ""
            bus = f"re_{iso}{suffix}"
            lat, lon = pt["lat"], pt["lon"]
            made = False
            if "solar" in techs and any(pt.get("ghi") or []):
                gen = f"solar_{iso}{suffix}"
                series_by_gen[gen] = solar_cf(pt["ghi"], pr)
                gen_rows.append({"name": gen, "bus": bus, "carrier": "solar",
                                 "p_nom": capacity, "marginal_cost": 0.0, "x": lon, "y": lat})
                made = True
            if "wind" in techs and (pt.get("wind_ms") or []):
                gen = f"wind_{iso}{suffix}"
                series_by_gen[gen] = wind_cf(pt["wind_ms"])
                gen_rows.append({"name": gen, "bus": bus, "carrier": "wind",
                                 "p_nom": capacity, "marginal_cost": 0.0, "x": lon, "y": lat})
                made = True
            if made:
                bus_rows.append({"name": bus, "carrier": "AC", "x": lon, "y": lat})
                for c in (g["carrier"] for g in gen_rows if g["bus"] == bus):
                    if c not in carrier_seen:
                        carriers.append({"name": c, "co2_emissions": 0.0})
                        carrier_seen.add(c)

        frag = WorkbookFragment()
        if not series_by_gen or not snapshots:
            return frag

        p_max_pu_rows: list[dict[str, Any]] = []
        for i, snap in enumerate(snapshots):
            row: dict[str, Any] = {"snapshot": snap}
            for gen, cf in series_by_gen.items():
                if i < len(cf):
                    row[gen] = round(cf[i], 4)
            p_max_pu_rows.append(row)

        frag.sheets["carriers"] = carriers
        frag.sheets["buses"] = bus_rows
        frag.sheets["generators"] = gen_rows
        frag.sheets["generators-p_max_pu"] = p_max_pu_rows
        frag.snapshots = snapshots

        frag.provenance = Provenance(
            self.meta.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps({s: len(r) for s, r in frag.sheets.items()}, sort_keys=True),
        )
        return frag


def build() -> Database:
    return OpenMeteoRenewable("open-meteo")


def build_pvgis() -> Database:
    return OpenMeteoRenewable("pvgis")


def build_nasa_power() -> Database:
    return OpenMeteoRenewable("nasa-power")
