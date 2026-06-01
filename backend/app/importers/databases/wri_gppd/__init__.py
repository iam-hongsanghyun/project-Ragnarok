"""WRI Global Power Plant Database — fetch + convert.

Port of the browser module. Single CSV mirror in the WRI GitHub repo,
filtered to the selected country by shapely point-in-polygon, then user
filters (fuels, capacity, commissioning year, owner). Every upstream CSV
column is preserved on each generator row; no PyPSA attribute is
fabricated.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
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

_DEFAULT_URL = (
    "https://raw.githubusercontent.com/wri/global-power-plant-database"
    "/master/output_database/global_power_plant_database.csv"
)
_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")
_CARRIER_MAP_PATH = Path(__file__).resolve().parent / "carrier_map.json"

# Module-local CSV cache (one process = one download).
_CACHED_CSV: bytes | None = None


def _csv_url() -> str:
    return os.environ.get("RAGNAROK_WRI_GPPD_URL", _DEFAULT_URL)


def _carrier_mapping() -> dict[str, str]:
    raw = json.loads(_CARRIER_MAP_PATH.read_text())
    return dict(raw.get("fuel_to_carrier", {}))


def _map_fuel(fuel: str | None, mapping: dict[str, str]) -> str:
    if not fuel:
        return "Other"
    key = str(fuel).strip().lower()
    for src, target in mapping.items():
        if src.strip().lower() == key:
            return target
    return "Other"


def _slug(raw: str | None, fallback: str = "asset") -> str:
    if not raw:
        return fallback
    s = _NAME_RE.sub("_", str(raw).strip()).strip("_")
    return s or fallback


def _dedupe(name: str, taken: set[str]) -> str:
    if name not in taken:
        taken.add(name)
        return name
    i = 2
    while f"{name}_{i}" in taken:
        i += 1
    final = f"{name}_{i}"
    taken.add(final)
    return final


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    f = _to_float(v)
    return int(f) if f is not None else None


META = DatabaseMeta(
    id="wri_gppd",
    name="WRI Global Power Plant Database",
    short_name="WRI GPPD",
    category="generation",
    subcategory="Power plants (per-asset)",
    license="CC-BY 4.0",
    homepage="https://datasets.wri.org/dataset/globalpowerplantdatabase",
    version_hint="v1.3.0",
    description=(
        "~35,000 power plants worldwide with name, capacity, fuel, lat/lon, "
        "owner, commissioning year. Single CSV, no auth."
    ),
    targets=["generators", "buses", "carriers"],
    country_coverage="global",
    filters=[
        Filter(id="fuels", label="Fuels", kind="multiselect", default=[], options=[
            {"value": c, "label": c} for c in
            ["Coal", "Gas", "Oil", "Nuclear", "Hydro", "Wind", "Solar",
             "Biomass", "Geothermal", "Waste", "Storage", "Other"]
        ], description="Leave empty to include every carrier."),
        Filter(id="min_capacity_mw", label="Min capacity", kind="number", default=0, min=0, step=10, unit="MW"),
        Filter(id="max_capacity_mw", label="Max capacity", kind="number", default=None, min=0, step=50, unit="MW",
               description="Leave empty for no upper bound."),
        Filter(id="commissioned_from", label="Commissioned from", kind="number", default=None, min=1900, max=2100, step=1),
        Filter(id="commissioned_to", label="Commissioned to", kind="number", default=None, min=1900, max=2100, step=1),
        Filter(id="owner_contains", label="Owner contains", kind="select", default="", options=[],
               description="Substring filter on the owner column (case-insensitive)."),
    ],
)


class WriGppd:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        global _CACHED_CSV
        if _CACHED_CSV is None:
            _CACHED_CSV = await ctx.http.get_bytes(_csv_url())
        text = _CACHED_CSV.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))

        polygon = region.polygon
        minx, miny, maxx, maxy = region.bbox
        mapping = _carrier_mapping()
        wanted = {str(c).lower() for c in (filters.get("fuels") or []) if c}
        min_mw = _to_float(filters.get("min_capacity_mw"))
        max_mw = _to_float(filters.get("max_capacity_mw"))
        yr_from = _to_int(filters.get("commissioned_from"))
        yr_to = _to_int(filters.get("commissioned_to"))
        owner_q = str(filters.get("owner_contains") or "").strip().lower()

        plants: list[dict[str, Any]] = []
        for row in reader:
            lat = _to_float(row.get("latitude"))
            lon = _to_float(row.get("longitude"))
            if lat is None or lon is None:
                continue
            if lon < minx or lon > maxx or lat < miny or lat > maxy:
                continue
            if not polygon.contains(Point(lon, lat)):
                continue
            cap = _to_float(row.get("capacity_mw"))
            if cap is None or cap <= 0:
                continue
            if min_mw is not None and cap < min_mw:
                continue
            if max_mw is not None and cap > max_mw:
                continue
            year = _to_int(row.get("commissioning_year"))
            if yr_from is not None and (year is None or year < yr_from):
                continue
            if yr_to is not None and (year is None or year > yr_to):
                continue
            owner = (row.get("owner") or "").strip()
            if owner_q and owner_q not in owner.lower():
                continue
            primary_fuel = (row.get("primary_fuel") or "").strip()
            carrier = _map_fuel(primary_fuel, mapping)
            if wanted and carrier.lower() not in wanted:
                continue
            plants.append({
                "name": (row.get("name") or "").strip() or row.get("gppd_idnr", "plant"),
                "capacity_mw": cap, "lat": lat, "lon": lon,
                "primary_fuel": primary_fuel, "carrier": carrier,
                "raw": dict(row),
            })
        return FetchResult(META.id, region, dict(filters), {"plants": plants})

    def preview(self, result: FetchResult) -> PreviewSummary:
        plants = result.payload["plants"]
        by_carrier: dict[str, int] = {}
        total = 0.0
        for p in plants:
            by_carrier[p["carrier"]] = by_carrier.get(p["carrier"], 0) + 1
            total += p["capacity_mw"]
        counts: dict[str, int] = {"generators": len(plants), "total_capacity_mw": int(round(total))}
        for k, v in by_carrier.items():
            counts[f"carrier:{k}"] = v
        overlay = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                 "properties": {"name": p["name"], "carrier": p["carrier"],
                                "capacity_mw": p["capacity_mw"], "kind": "generator"}}
                for p in plants
            ],
        }
        return PreviewSummary(
            counts=counts,
            samples={"generators": [
                {"name": p["name"], "carrier": p["carrier"], "capacity_mw": p["capacity_mw"],
                 "lat": p["lat"], "lon": p["lon"]}
                for p in plants[:10]
            ]},
            notes=[f"{len(plants)} plants matched."],
            overlay=overlay,
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        plants = result.payload["plants"]
        frag = WorkbookFragment()
        gen_rows: list[dict[str, Any]] = []
        bus_rows: list[dict[str, Any]] = []
        carrier_rows: list[dict[str, Any]] = []
        used: set[str] = set()
        taken_names: set[str] = set()
        taken_buses: set[str] = set()
        for p in plants:
            name = _dedupe(_slug(p["name"], "plant"), taken_names)
            carrier = p["carrier"]
            bus_name = ""
            if options.create_buses_for_plants:
                bus_name = _dedupe(name + options.plant_bus_suffix, taken_buses)
                bus_rows.append({"name": bus_name, "x": p["lon"], "y": p["lat"],
                                 "country": result.region.country_iso})
            gen: dict[str, Any] = {
                "name": name, "bus": bus_name, "carrier": carrier,
                "p_nom": p["capacity_mw"], "x": p["lon"], "y": p["lat"],
            }
            for col, val in p["raw"].items():
                if col in gen or val == "" or val is None:
                    continue
                gen[col] = val
            gen["source"] = "WRI GPPD"
            gen_rows.append(gen)
            if carrier not in used:
                used.add(carrier)
                carrier_rows.append({"name": carrier})
        if gen_rows:
            frag.sheets["generators"] = gen_rows
        if bus_rows:
            frag.sheets["buses"] = bus_rows
        if carrier_rows:
            frag.sheets["carriers"] = carrier_rows
        row_counts = {s: len(r) for s, r in frag.sheets.items()}
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return WriGppd()
