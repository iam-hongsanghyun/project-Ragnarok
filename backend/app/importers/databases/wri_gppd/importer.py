"""WRI Global Power Plant Database — fetch + convert.

We hit the canonical CSV (URL is env-configurable), filter by polygon + user
filters, then emit ``generators``, ``buses`` (one per plant), and ``carriers``
rows. The full CSV is ~35k rows, so we cache the bytes once per process
lifetime.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import Point

from ...convert import (
    build_provenance,
    carrier_defaults_for,
    dedupe_name,
    map_fuel_to_carrier,
    merge_carriers_into_fragment,
    slugify_name,
)
from ...protocol import (
    ConvertOptions,
    DatabaseMeta,
    FetchResult,
    PreviewSummary,
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


# ── Carrier mapping ──────────────────────────────────────────────────────────

_CARRIER_MAP_PATH = Path(__file__).resolve().parent / "carrier_map.json"


def _carrier_mapping() -> dict[str, str]:
    raw = json.loads(_CARRIER_MAP_PATH.read_text())
    return dict(raw.get("fuel_to_carrier", {}))


# ── Row parsing ──────────────────────────────────────────────────────────────


@dataclass
class _Plant:
    name: str
    capacity_mw: float
    lat: float
    lon: float
    primary_fuel: str
    country_iso: str
    commissioning_year: int | None
    owner: str


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
            carrier = map_fuel_to_carrier(primary_fuel, mapping=mapping)
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
            carrier = map_fuel_to_carrier(p.primary_fuel, mapping=mapping)
            by_carrier[carrier] = by_carrier.get(carrier, 0) + 1
            total_capacity += p.capacity_mw
        samples = [
            {
                "name": p.name,
                "carrier": map_fuel_to_carrier(p.primary_fuel, mapping=mapping),
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
                        "carrier": map_fuel_to_carrier(p.primary_fuel, mapping=mapping),
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
            notes=[
                f"{len(plants)} plants matched.",
            ],
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
            base_name = slugify_name(plant.name, fallback="plant")
            name = dedupe_name(base_name, taken_names)
            carrier = map_fuel_to_carrier(plant.primary_fuel, mapping=mapping)
            defaults = carrier_defaults_for(carrier)
            bus_name = name + options.plant_bus_suffix if options.create_buses_for_plants else ""
            if options.create_buses_for_plants:
                bus_name = dedupe_name(bus_name, taken_bus_names)
                bus_rows.append(
                    {
                        "name": bus_name,
                        "v_nom": 380.0,
                        "x": plant.lon,
                        "y": plant.lat,
                        "carrier": "AC",
                        "country": plant.country_iso,
                    }
                )
            gen_rows.append(
                {
                    "name": name,
                    "bus": bus_name,
                    "carrier": carrier,
                    "p_nom": plant.capacity_mw,
                    "p_nom_extendable": False,
                    "marginal_cost": defaults.get("marginal_cost"),
                    "efficiency": defaults.get("efficiency"),
                    "x": plant.lon,
                    "y": plant.lat,
                    "commissioning_year": plant.commissioning_year,
                    "owner": plant.owner or None,
                    "source": "WRI GPPD",
                }
            )
            if carrier not in used_carriers:
                used_carriers.add(carrier)
                carrier_rows.append(
                    {
                        "name": carrier,
                        "co2_emissions": defaults.get("co2_emissions"),
                        "color": defaults.get("color"),
                    }
                )
        if gen_rows:
            fragment.sheets["generators"] = gen_rows
        if bus_rows:
            fragment.sheets["buses"] = bus_rows
        merge_carriers_into_fragment(fragment, carrier_rows)
        row_counts = {sheet: len(rows) for sheet, rows in fragment.sheets.items()}
        fragment.provenance = build_provenance(
            database_id=self.meta.id,
            region=result.region,
            filters=result.filters,
            options=options,
            fetch_timestamp=_now_iso(),
            row_counts=row_counts,
        )
        return fragment


def _now_iso() -> str:
    """Centralised place to obtain a fetch timestamp.

    Wrapped so tests can monkeypatch this without touching ``datetime`` globally.
    """
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
