"""Open-Meteo renewable capacity-factor importer (I4).

Fetches hourly ERA5 weather (global, keyless) at the selected region's
representative point and converts it to wind / solar **capacity-factor** profiles,
landing a complete, runnable renewable fragment: a bus at that point, a solar
and/or wind generator on it, and their ``generators-p_max_pu`` series.

This is the general, any-coordinate complement to the curated per-country packs
(KPG193). Source: Open-Meteo Archive API — CC-BY, no API key, global ERA5
reanalysis. The weather→CF maths live in :mod:`.conversion` (a first-order plane-
of-array solar proxy + a generic turbine power curve); it gives a realistic
*shape* and plausible yield for a ``p_max_pu`` series, not a plant-engineering
tool. One representative point per region for now — per-bus / polygon sampling is
a follow-on.
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
from .conversion import combined_ghi, mean_cf, solar_cf, wind_cf

_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Open-Meteo hourly variables. GHI (W/m²) for solar — request the components too
# since ``shortwave_radiation`` is occasionally null for recent dates while
# ``direct``/``diffuse`` are present (see conversion.combined_ghi). 100 m wind
# speed (hub height) for wind, forced to m/s (the API defaults to km/h).
_HOURLY_VARS = "shortwave_radiation,direct_radiation,diffuse_radiation,wind_speed_100m"

_TECHS = [
    {"value": "solar", "label": "Solar PV"},
    {"value": "wind", "label": "Wind"},
]

META = DatabaseMeta(
    id="openmeteo_renewable",
    name="Open-Meteo — renewable capacity factors (any location)",
    short_name="Open-Meteo CF",
    category="generation",
    subcategory="Hourly profiles",
    license="CC-BY 4.0 (Open-Meteo / ERA5)",
    homepage="https://open-meteo.com/en/docs/historical-weather-api",
    version_hint="Archive API (ERA5)",
    description=(
        "Hourly wind & solar capacity factors for any coordinate on Earth, derived "
        "from Open-Meteo's keyless global ERA5 reanalysis. Lands a bus + solar/wind "
        "generator(s) with weather-driven p_max_pu profiles."
    ),
    targets=["carriers", "buses", "generators", "generators-p_max_pu"],
    country_coverage="global",
    requires_secrets=[],  # keyless
    filters=[
        Filter(id="date_from", label="From", kind="date", default="2022-01-01",
               description="Weather window start. ERA5 has a multi-day lag and recent "
                           "dates can miss irradiance — 2022 or earlier is safest."),
        Filter(id="date_to", label="To", kind="date", default="2022-01-31",
               description="Weather window end."),
        Filter(id="technologies", label="Technologies", kind="multiselect",
               default=["solar", "wind"], options=_TECHS),
        Filter(id="capacity_mw", label="Capacity per generator (MW)", kind="number",
               default=100.0, min=0.0, step=10.0, unit="MW"),
        Filter(id="performance_ratio", label="Solar performance ratio", kind="number",
               default=0.9, min=0.1, max=1.0, step=0.05),
    ],
)


def _iso(region: Region) -> str:
    return (region.country_iso or "REG").strip().upper() or "REG"


def _techs(filters: dict[str, Any]) -> list[str]:
    raw = filters.get("technologies")
    if isinstance(raw, str):
        raw = [raw]
    picked = [t for t in (raw or ["solar", "wind"]) if t in ("solar", "wind")]
    return picked or ["solar", "wind"]


class OpenMeteoRenewable:
    meta = META

    async def fetch(
        self, region: Region, filters: dict[str, Any], ctx: ImportContext
    ) -> FetchResult:
        c = region.polygon.centroid
        lat, lon = round(float(c.y), 4), round(float(c.x), 4)
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": str(filters.get("date_from") or "2022-01-01"),
            "end_date": str(filters.get("date_to") or "2022-01-31"),
            "hourly": _HOURLY_VARS,
            "wind_speed_unit": "ms",
            "timezone": "UTC",
        }
        body = await ctx.http.get_json(_ARCHIVE_URL, params=params)
        hourly = (body or {}).get("hourly") or {}
        return FetchResult(
            META.id, region, dict(filters),
            {"hourly": hourly, "lat": lat, "lon": lon},
        )

    def preview(self, result: FetchResult) -> PreviewSummary:
        hourly = result.payload.get("hourly") or {}
        times = hourly.get("time") or []
        techs = _techs(result.filters)
        pr = float(result.filters.get("performance_ratio") or 0.9)
        counts = {"hours": len(times), "generators": len(techs)}
        notes = [f"{len(times)} hourly points at ({result.payload['lat']:.2f}, {result.payload['lon']:.2f})."]
        ghi = combined_ghi(hourly.get("shortwave_radiation"), hourly.get("direct_radiation"), hourly.get("diffuse_radiation"))
        if "solar" in techs and any(ghi):
            notes.append(f"Solar mean CF ≈ {mean_cf(solar_cf(ghi, pr)):.2f}.")
        if "wind" in techs and hourly.get("wind_speed_100m"):
            notes.append(f"Wind mean CF ≈ {mean_cf(wind_cf(hourly['wind_speed_100m'])):.2f}.")
        return PreviewSummary(counts=counts, samples={"hours": [{"time": t} for t in times[:24]]}, notes=notes)

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        hourly = result.payload.get("hourly") or {}
        times = list(hourly.get("time") or [])
        techs = _techs(result.filters)
        iso = _iso(result.region)
        pr = float(result.filters.get("performance_ratio") or 0.9)
        capacity = max(0.0, float(result.filters.get("capacity_mw") or 100.0))
        bus = f"re_{iso}"

        # Per-technology CF series, aligned to the hourly time axis.
        series: dict[str, list[float]] = {}
        if "solar" in techs:
            ghi = combined_ghi(
                hourly.get("shortwave_radiation"), hourly.get("direct_radiation"), hourly.get("diffuse_radiation")
            )
            if any(ghi):
                series[f"solar_{iso}"] = solar_cf(ghi, pr)
        if "wind" in techs and hourly.get("wind_speed_100m"):
            series[f"wind_{iso}"] = wind_cf(hourly["wind_speed_100m"])

        snapshots = [str(t).replace("T", " ") for t in times]
        p_max_pu_rows: list[dict[str, Any]] = []
        for i, snap in enumerate(snapshots):
            row: dict[str, Any] = {"snapshot": snap}
            for gen, cf in series.items():
                if i < len(cf):
                    row[gen] = round(cf[i], 4)
            p_max_pu_rows.append(row)

        frag = WorkbookFragment()
        if not series or not snapshots:
            return frag  # nothing usable came back

        carriers = [{"name": "AC"}]
        gen_rows: list[dict[str, Any]] = []
        for gen in series:
            carrier = "solar" if gen.startswith("solar_") else "wind"
            carriers.append({"name": carrier, "co2_emissions": 0.0})
            gen_rows.append({
                "name": gen, "bus": bus, "carrier": carrier,
                "p_nom": capacity, "marginal_cost": 0.0,
                "x": result.payload["lon"], "y": result.payload["lat"],
            })

        frag.sheets["carriers"] = carriers
        frag.sheets["buses"] = [{
            "name": bus, "carrier": "AC",
            "x": result.payload["lon"], "y": result.payload["lat"],
        }]
        frag.sheets["generators"] = gen_rows
        frag.sheets["generators-p_max_pu"] = p_max_pu_rows
        frag.snapshots = snapshots

        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps({s: len(r) for s, r in frag.sheets.items()}, sort_keys=True),
        )
        return frag


def build() -> Database:
    return OpenMeteoRenewable()
