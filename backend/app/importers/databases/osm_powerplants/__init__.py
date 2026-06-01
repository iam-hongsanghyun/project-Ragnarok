"""OpenStreetMap power plants → PyPSA generators (Overpass).

A dataset of the ``osm`` source (sibling of the grid-topology dataset).
Queries Overpass for ``power=plant`` facilities within the selected
country and emits one PyPSA Generator per plant, each on its own bus —
so the output is self-contained and PyPSA-ready (same pattern as the WRI
Global Power Plant Database, but live from OSM).

Facility-level (``power=plant``) only — individual ``power=generator``
units inside a plant are deliberately not queried, to avoid
double-counting a plant's capacity.

Capacity comes from ``plant:output:electricity`` (parsed W/kW/MW/GW →
MW); when it's absent or unparseable the generator's ``p_nom`` is left
empty (PyPSA's default), never guessed. Carrier comes from
``plant:source`` (wind / solar / coal / gas / hydro / nuclear / …).
"""
from __future__ import annotations

import json
import re
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
from ..osm import (
    OSM_SOURCE_ID,
    OSM_SOURCE_LABEL,
    _DEFAULT_TIMEOUT_S,
    _dedupe,
    _element_center,
    _overpass_url,
    _poly_filter,
    _slug,
)

# number + optional SI power unit (W/kW/MW/GW). OSM `plant:output:electricity`
# values look like "1300 MW", "0.5 MWp", "300000000 W", "2 GW".
_POWER_RE = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*([kKmMgG]?[wW])?")

# Common OSM plant:source values, offered as a filter (empty = all).
_SOURCES = [
    "solar", "wind", "hydro", "coal", "gas", "oil", "nuclear",
    "biomass", "geothermal", "waste", "tidal", "battery", "diesel",
]


def _parse_power_mw(value: Any) -> float | None:
    """Parse an OSM power string to MW. Returns ``None`` when absent, unitless,
    or unparseable — the caller leaves p_nom empty rather than guess."""
    if value is None or value == "":
        return None
    head = str(value).split(";")[0].strip()
    m = _POWER_RE.search(head)
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    if unit == "gw":
        return num * 1000.0
    if unit == "mw":
        return num
    if unit == "kw":
        return num / 1000.0
    if unit == "w":
        return num / 1_000_000.0
    return None  # no unit → ambiguous, skip


def _build_query(geom: Any, timeout_s: int = _DEFAULT_TIMEOUT_S) -> str:
    poly = _poly_filter(geom)
    parts = [
        f'node["power"="plant"](poly:"{poly}");',
        f'way["power"="plant"](poly:"{poly}");',
        f'relation["power"="plant"](poly:"{poly}");',
    ]
    return f'[out:json][timeout:{timeout_s}];({"".join(parts)});out center tags;'


def _parse_plants(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for el in payload.get("elements") or []:
        tags = el.get("tags") or {}
        if tags.get("power") != "plant":
            continue
        center = _element_center(el)
        if center is None:
            continue
        lat, lon = center
        source = (
            str(tags.get("plant:source") or tags.get("plant:method") or "")
            .split(";")[0].strip().lower()
        )
        osm_id = f"{el.get('type', 'n')}{el.get('id', '')}"
        name = (tags.get("name") or "").strip() or f"plant_{osm_id}"
        out.append({
            "osm_id": osm_id,
            "name": name,
            "lat": lat,
            "lon": lon,
            "carrier": source,
            "p_nom": _parse_power_mw(tags.get("plant:output:electricity")),
        })
    return out


META = DatabaseMeta(
    id="osm_powerplants",
    name="OpenStreetMap — power plants",
    short_name="Power plants",
    source_id=OSM_SOURCE_ID,
    source_label=OSM_SOURCE_LABEL,
    category="generation",
    subcategory="Power plants (per-asset)",
    license="ODbL",
    homepage="https://www.openstreetmap.org",
    version_hint="live",
    description=(
        "Power plants tagged in OpenStreetMap (power=plant) in the selected "
        "country → one PyPSA Generator per facility, each on its own bus "
        "(self-contained, like WRI GPPD). Capacity from "
        "plant:output:electricity (left empty when untagged); carrier from "
        "plant:source. Facility-level only, to avoid double-counting."
    ),
    targets=["generators", "buses", "carriers"],
    available=True,
    country_coverage="global",
    requires_secrets=[],
    filters=[
        Filter(
            id="min_capacity_mw", label="Min capacity", kind="number",
            default=0, min=0, step=10, unit="MW",
            description=(
                "Drop plants below this capacity. 0 includes everything, "
                "including plants whose capacity isn't tagged."
            ),
        ),
        Filter(
            id="sources", label="Sources", kind="multiselect", default=[],
            options=[{"value": s, "label": s} for s in _SOURCES],
            description="Limit to these plant:source values. Empty = all.",
        ),
    ],
)


class OsmPowerPlants:
    meta = META

    async def fetch(
        self, region: Region, filters: dict[str, Any], ctx: ImportContext
    ) -> FetchResult:
        query = _build_query(region.polygon)
        text = await ctx.http.post_text(_overpass_url(), data={"data": query})
        payload = json.loads(text)
        raw = len(payload.get("elements") or [])
        plants = _parse_plants(payload)

        try:
            min_mw = float(filters.get("min_capacity_mw") or 0)
        except (TypeError, ValueError):
            min_mw = 0.0
        wanted = {str(s).lower() for s in (filters.get("sources") or []) if s}

        kept: list[dict[str, Any]] = []
        for p in plants:
            if wanted and p["carrier"] not in wanted:
                continue
            if min_mw > 0:
                # Can only honour the floor for plants whose capacity is known.
                if p["p_nom"] is None or p["p_nom"] < min_mw:
                    continue
            kept.append(p)

        return FetchResult(
            META.id, region, dict(filters),
            {"plants": kept, "raw_count": raw},
        )

    def _build_sheets(self, result: FetchResult) -> dict[str, list[dict[str, Any]]]:
        taken: set[str] = set()
        buses: list[dict[str, Any]] = []
        generators: list[dict[str, Any]] = []
        carriers: set[str] = set()
        for p in result.payload["plants"]:
            gen_name = _dedupe(_slug(p["name"], f"plant_{p['osm_id']}"), taken)
            bus_name = f"{gen_name}_bus"
            buses.append({
                "name": bus_name, "x": p["lon"], "y": p["lat"],
                "carrier": "AC", "country": result.region.country_iso,
                "source": "OSM",
            })
            generators.append({
                "name": gen_name, "bus": bus_name,
                "carrier": p["carrier"], "control": "PV",
                "p_nom": (p["p_nom"] if p["p_nom"] is not None else ""),
                "p_min_pu": 0, "p_max_pu": 1,
                "osm_id": p["osm_id"], "source": "OSM",
            })
            if p["carrier"]:
                carriers.add(p["carrier"])
        carriers.add("AC")
        sheets: dict[str, list[dict[str, Any]]] = {
            "carriers": [{"name": c} for c in sorted(carriers)],
        }
        if buses:
            sheets["buses"] = buses
        if generators:
            sheets["generators"] = generators
        return sheets

    def preview(self, result: FetchResult) -> PreviewSummary:
        sheets = self._build_sheets(result)
        gens = sheets.get("generators", [])
        by_carrier: dict[str, int] = {}
        total = 0.0
        for g in gens:
            c = g.get("carrier") or "(untagged)"
            by_carrier[c] = by_carrier.get(c, 0) + 1
            try:
                total += float(g.get("p_nom") or 0)
            except (TypeError, ValueError):
                pass
        counts: dict[str, int] = {
            "generators": len(gens),
            "buses": len(sheets.get("buses", [])),
            "capacity_mw": int(round(total)),
        }
        for c in sorted(by_carrier):
            counts[f"carrier:{c}"] = by_carrier[c]

        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                "properties": {
                    "kind": "plant", "name": p["name"], "carrier": p["carrier"],
                },
            }
            for p in result.payload["plants"]
        ]
        return PreviewSummary(
            counts=counts,
            samples={"generators": [
                {"name": g.get("name"), "carrier": g.get("carrier"), "p_nom": g.get("p_nom")}
                for g in gens[:10]
            ]},
            notes=[
                f"OSM: {result.payload['raw_count']} raw elements → "
                f"{len(gens)} power plants."
            ],
            overlay={"type": "FeatureCollection", "features": features},
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        sheets = self._build_sheets(result)
        frag = WorkbookFragment(sheets=sheets)
        row_counts = {s: len(r) for s, r in sheets.items()}
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return OsmPowerPlants()
