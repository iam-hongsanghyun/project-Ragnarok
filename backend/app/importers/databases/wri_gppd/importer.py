"""WRI Global Power Plant Database — fetch + convert (self-contained).

This module is intentionally isolated: no imports from a shared `convert/`
package. Slug / dedupe / provenance / fuel mapping all live here. Output
generator rows carry **every column** from the upstream CSV alongside the
schema-required name / bus / carrier / p_nom / coordinates. Optional PyPSA
attributes (`marginal_cost`, `efficiency`, `co2_emissions`, `capital_cost`,
`lifetime`, …) are **never fabricated** — empty cells fall through to
PyPSA's own component defaults at solve time.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import Point

from ...protocol import (
    ConvertOptions,
    DatabaseMeta,
    FetchResult,
    PreviewSummary,
    Provenance,
    Region,
    WorkbookFragment,
)

_log = logging.getLogger(__name__)

# Canonical CSV from the WRI repo mirror. The portal-side S3 URL is rotated
# between releases; the GitHub copy is stable across the v1.3.0 cohort.
_DEFAULT_URL = (
    "https://raw.githubusercontent.com/wri/global-power-plant-database"
    "/master/output_database/global_power_plant_database.csv"
)

# Module-local fetch cache (CSV bytes). One process = one fetch.
_CACHED_CSV: bytes | None = None


def _csv_url() -> str:
    return os.environ.get("RAGNAROK_WRI_GPPD_URL", _DEFAULT_URL)


def _csv_local_override() -> Path | None:
    override = os.environ.get("RAGNAROK_WRI_GPPD_PATH")
    return Path(override).expanduser() if override else None


def _load_csv_bytes() -> bytes:
    """Fetch (or read cached) GPPD CSV bytes."""
    global _CACHED_CSV
    if _CACHED_CSV is not None:
        return _CACHED_CSV
    override = _csv_local_override()
    if override is not None and override.exists():
        _log.info("loading WRI GPPD from local override: %s", override)
        _CACHED_CSV = override.read_bytes()
        return _CACHED_CSV
    url = _csv_url()
    _log.info("fetching WRI GPPD from %s", url)
    with urllib.request.urlopen(url, timeout=120) as resp:
        _CACHED_CSV = resp.read()
    return _CACHED_CSV


def reset_cache() -> None:
    """Clear the cached CSV (used by tests)."""
    global _CACHED_CSV
    _CACHED_CSV = None


# ── Carrier mapping (WRI primary_fuel → Ragnarok carrier) ────────────────────

_CARRIER_MAP_PATH = Path(__file__).resolve().parent / "carrier_map.json"


def _carrier_mapping() -> dict[str, str]:
    raw = json.loads(_CARRIER_MAP_PATH.read_text())
    return dict(raw.get("fuel_to_carrier", {}))


def _map_fuel(fuel: str | None, mapping: dict[str, str]) -> str:
    """Case-insensitive lookup; unknown fuels return 'Other'."""
    if not fuel:
        return "Other"
    key = str(fuel).strip().lower()
    for src, ragnarok in mapping.items():
        if src.strip().lower() == key:
            return ragnarok
    return "Other"


# ── Slug + dedupe (inlined per-module; no cross-source sharing) ──────────────

_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


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


# ── Row parsing ──────────────────────────────────────────────────────────────


@dataclass
class _Plant:
    """All upstream WRI columns are stored verbatim in ``raw``. The typed
    fields are the ones we actually filter on; preview + sheet conversion
    use ``raw`` directly so no upstream data is dropped on the floor."""

    name: str
    capacity_mw: float
    lat: float
    lon: float
    primary_fuel: str
    country_iso: str
    commissioning_year: int | None
    owner: str
    raw: dict[str, str]


def _parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: str | None) -> int | None:
    f = _parse_float(value)
    return int(f) if f is not None else None


def _iter_rows(csv_bytes: bytes) -> Iterable[dict[str, str]]:
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        yield row


# ── Database implementation ──────────────────────────────────────────────────


@dataclass
class WRIGPPDImporter:
    meta: DatabaseMeta

    def fetch(self, region: Region, filters: dict[str, Any]) -> FetchResult:
        mapping = _carrier_mapping()
        csv_bytes = _load_csv_bytes()
        plants: list[_Plant] = []
        country_iso = region.country_iso
        polygon = region.polygon
        minx, miny, maxx, maxy = polygon.bounds

        wanted_fuels = {str(c).lower() for c in (filters.get("fuels") or []) if c}
        min_mw = _parse_float(str(filters.get("min_capacity_mw", "") or ""))
        max_mw = _parse_float(str(filters.get("max_capacity_mw", "") or ""))
        year_from = _parse_int(str(filters.get("commissioned_from", "") or ""))
        year_to = _parse_int(str(filters.get("commissioned_to", "") or ""))
        owner_q = str(filters.get("owner_contains") or "").strip().lower()

        for row in _iter_rows(csv_bytes):
            lat = _parse_float(row.get("latitude"))
            lon = _parse_float(row.get("longitude"))
            if lat is None or lon is None:
                continue
            # Cheap bbox prefilter before the point-in-polygon test.
            if lon < minx or lon > maxx or lat < miny or lat > maxy:
                continue
            if not polygon.contains(Point(lon, lat)):
                continue
            capacity = _parse_float(row.get("capacity_mw"))
            if capacity is None or capacity <= 0:
                continue
            if min_mw is not None and capacity < min_mw:
                continue
            if max_mw is not None and capacity > max_mw:
                continue
            year = _parse_int(row.get("commissioning_year"))
            if year_from is not None and (year is None or year < year_from):
                continue
            if year_to is not None and (year is None or year > year_to):
                continue
            owner = (row.get("owner") or "").strip()
            if owner_q and owner_q not in owner.lower():
                continue
            primary_fuel = (row.get("primary_fuel") or "").strip()
            carrier = _map_fuel(primary_fuel, mapping)
            if wanted_fuels and carrier.lower() not in wanted_fuels:
                continue
            plants.append(
                _Plant(
                    name=(row.get("name") or "").strip() or row.get("gppd_idnr", "plant"),
                    capacity_mw=capacity,
                    lat=lat,
                    lon=lon,
                    primary_fuel=primary_fuel,
                    country_iso=country_iso,
                    commissioning_year=year,
                    owner=owner,
                    raw=dict(row),
                )
            )
        return FetchResult(
            database_id=self.meta.id,
            region=region,
            filters=dict(filters),
            payload={"plants": plants},
        )

    def preview(self, result: FetchResult) -> PreviewSummary:
        plants: list[_Plant] = result.payload["plants"]
        mapping = _carrier_mapping()
        by_carrier: dict[str, int] = {}
        total_capacity = 0.0
        for p in plants:
            carrier = _map_fuel(p.primary_fuel, mapping)
            by_carrier[carrier] = by_carrier.get(carrier, 0) + 1
            total_capacity += p.capacity_mw
        samples = [
            {
                "name": p.name,
                "carrier": _map_fuel(p.primary_fuel, mapping),
                "capacity_mw": p.capacity_mw,
                "lat": p.lat,
                "lon": p.lon,
            }
            for p in plants[:10]
        ]
        overlay = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [p.lon, p.lat]},
                    "properties": {
                        "name": p.name,
                        "carrier": _map_fuel(p.primary_fuel, mapping),
                        "capacity_mw": p.capacity_mw,
                        "kind": "generator",
                    },
                }
                for p in plants
            ],
        }
        return PreviewSummary(
            counts={
                "generators": len(plants),
                "total_capacity_mw": int(round(total_capacity)),
                **{f"carrier:{k}": v for k, v in by_carrier.items()},
            },
            samples={"generators": samples},
            notes=[f"{len(plants)} plants matched."],
            overlay=overlay,
        )

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment:
        plants: list[_Plant] = result.payload["plants"]
        mapping = _carrier_mapping()
        fragment = WorkbookFragment()
        gen_rows: list[dict[str, Any]] = []
        bus_rows: list[dict[str, Any]] = []
        carrier_rows: list[dict[str, Any]] = []
        used_carriers: set[str] = set()
        taken_names: set[str] = set()
        taken_bus_names: set[str] = set()
        for plant in plants:
            base_name = _slug(plant.name, fallback="plant")
            name = _dedupe(base_name, taken_names)
            carrier = _map_fuel(plant.primary_fuel, mapping)
            bus_name = ""
            if options.create_buses_for_plants:
                bus_name = _dedupe(name + options.plant_bus_suffix, taken_bus_names)
                bus_rows.append(
                    {
                        "name": bus_name,
                        # Bus.v_nom: WRI does not provide voltage, leave empty
                        # (PyPSA default = 1.0). User overrides in Build view.
                        "x": plant.lon,
                        "y": plant.lat,
                        "country": plant.country_iso,
                        # carrier intentionally unset — PyPSA default "AC".
                    }
                )
            # Schema-required identification + everything WRI ships, verbatim.
            # marginal_cost / efficiency / co2_emissions / capital_cost /
            # lifetime / p_nom_extendable / p_min_pu / p_max_pu are
            # INTENTIONALLY ABSENT — PyPSA's own defaults handle unset cells.
            gen_row: dict[str, Any] = {
                "name": name,
                "bus": bus_name,
                "carrier": carrier,
                "p_nom": plant.capacity_mw,
                "x": plant.lon,
                "y": plant.lat,
            }
            for col, val in plant.raw.items():
                # Don't clobber the schema-required columns we just set.
                if col in gen_row:
                    continue
                if val == "" or val is None:
                    continue
                gen_row[col] = val
            gen_row["source"] = "WRI GPPD"
            gen_rows.append(gen_row)
            if carrier not in used_carriers:
                used_carriers.add(carrier)
                # No co2_emissions / marginal_cost / capital_cost set here —
                # PyPSA defaults apply at solve time. The user supplies cost
                # data in Build view when they need cost-aware studies.
                carrier_rows.append({"name": carrier})

        if gen_rows:
            fragment.sheets["generators"] = gen_rows
        if bus_rows:
            fragment.sheets["buses"] = bus_rows
        if carrier_rows:
            fragment.sheets["carriers"] = carrier_rows

        row_counts = {sheet: len(rows) for sheet, rows in fragment.sheets.items()}
        fragment.provenance = Provenance(
            database_id=self.meta.id,
            country_iso=result.region.country_iso,
            country_name=result.region.country_name,
            filters_json=json.dumps(result.filters, sort_keys=True, default=str),
            convert_options_json=json.dumps(options.__dict__, sort_keys=True, default=str),
            fetch_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            row_counts_json=json.dumps(row_counts, sort_keys=True),
        )
        return fragment
