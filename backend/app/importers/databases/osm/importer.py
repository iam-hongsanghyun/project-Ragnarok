"""OSM transmission importer — Overpass → workbook (self-contained).

This module is intentionally isolated: no imports from a shared ``convert/``
package. Slug / dedupe / provenance / line-type mapping all live here.

Output rows preserve **every OSM tag** verbatim on each substation-derived
bus row and each ``power=line/cable`` row. Optional PyPSA attributes
(``r`` / ``x`` / ``b`` / ``s_nom`` / ``carrier`` / …) are **never
fabricated** — empty cells fall through to PyPSA defaults. Lines set
``type`` to a PyPSA standard-type name (from ``line_types.json``) for
common voltages so PyPSA's own catalogue supplies the electrical params
at solve time.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...protocol import (
    ConvertOptions,
    DatabaseMeta,
    FetchResult,
    PreviewSummary,
    Provenance,
    Region,
    WorkbookFragment,
)
from . import overpass
from .voltage import parse_voltage_kv

_SNAP_KM = 5.0
_EARTH_KM = 6371.0

# ── Line-type mapping (OSM voltage → PyPSA standard-type name) ───────────────
# Not a defaults table — the numeric r/x/b/s_nom values live in PyPSA's
# own line_types catalogue. We only choose *which* catalogue entry to ref
# per voltage class. Voltages not listed → no `type` set → PyPSA defaults
# apply at solve time.

_LINE_TYPES_PATH = Path(__file__).resolve().parent / "line_types.json"


def _line_type_mapping() -> dict[int, str]:
    raw = json.loads(_LINE_TYPES_PATH.read_text())
    return {int(k): str(v) for k, v in raw.get("voltage_kv_to_type", {}).items()}


def _line_type_for(voltage_kv: float, mapping: dict[int, str]) -> str:
    return mapping.get(int(round(voltage_kv)), "")


# ── Slug + dedupe (inlined) ──────────────────────────────────────────────────

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


# ── Parsed Overpass elements (carry full OSM tag dicts) ──────────────────────


@dataclass
class _Substation:
    osm_id: int
    osm_type: str
    lat: float
    lon: float
    voltages_kv: list[float]
    tags: dict[str, str]  # full OSM tag set, preserved verbatim


@dataclass
class _Line:
    osm_id: int
    geometry: list[tuple[float, float]]
    length_km: float
    voltage_kv: float
    frequency_hz: float
    circuits: int
    is_cable: bool
    tags: dict[str, str]  # full OSM tag set, preserved verbatim


@dataclass
class _Parsed:
    substations: list[_Substation] = field(default_factory=list)
    lines: list[_Line] = field(default_factory=list)


# ── Geometry helpers ─────────────────────────────────────────────────────────


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    dlat = lat2r - lat1r
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_KM * math.asin(math.sqrt(a))


def _polyline_length_km(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:]):
        total += _haversine_km(lat1, lon1, lat2, lon2)
    return total


def _element_center(el: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return float(el["lat"]), float(el["lon"])
    geom = el.get("geometry") or []
    if geom:
        lats = [float(p["lat"]) for p in geom]
        lons = [float(p["lon"]) for p in geom]
        return sum(lats) / len(lats), sum(lons) / len(lons)
    center = el.get("center")
    if center:
        return float(center["lat"]), float(center["lon"])
    return None


def _int_tag(tags: dict[str, Any], key: str, default: int = 1) -> int:
    raw = tags.get(key)
    if raw in (None, ""):
        return default
    try:
        return max(int(str(raw).split(";")[0]), 1)
    except (TypeError, ValueError):
        return default


def _float_tag(tags: dict[str, Any], key: str, default: float) -> float:
    raw = tags.get(key)
    if raw in (None, ""):
        return default
    try:
        return float(str(raw).split(";")[0])
    except (TypeError, ValueError):
        return default


# ── Overpass → parsed model ──────────────────────────────────────────────────


def _parse_response(payload: dict[str, Any], *, min_voltage_kv: float) -> _Parsed:
    parsed = _Parsed()
    for el in payload.get("elements", []):
        tags = el.get("tags") or {}
        power = tags.get("power")
        voltages = parse_voltage_kv(tags.get("voltage"))
        if power == "substation":
            if voltages and max(voltages) < min_voltage_kv:
                continue
            center = _element_center(el)
            if center is None:
                continue
            parsed.substations.append(
                _Substation(
                    osm_id=int(el.get("id", 0)),
                    osm_type=str(el.get("type", "node")),
                    lat=center[0],
                    lon=center[1],
                    voltages_kv=voltages,
                    tags=dict(tags),
                )
            )
            continue
        if power in {"line", "cable"}:
            if not voltages:
                continue
            v_max = max(voltages)
            if v_max < min_voltage_kv:
                continue
            geom = el.get("geometry") or []
            points = [(float(p["lat"]), float(p["lon"])) for p in geom]
            if len(points) < 2:
                continue
            length_km = _polyline_length_km(points)
            if length_km <= 0:
                continue
            parsed.lines.append(
                _Line(
                    osm_id=int(el.get("id", 0)),
                    geometry=points,
                    length_km=length_km,
                    voltage_kv=v_max,
                    frequency_hz=_float_tag(tags, "frequency", 50.0),
                    circuits=_int_tag(tags, "circuits", 1),
                    is_cable=(power == "cable"),
                    tags=dict(tags),
                )
            )
    return parsed


def _nearest_substation(
    lat: float, lon: float, substations: list[_Substation]
) -> tuple[_Substation, float] | None:
    if not substations:
        return None
    best: tuple[_Substation, float] | None = None
    for s in substations:
        d = _haversine_km(lat, lon, s.lat, s.lon)
        if best is None or d < best[1]:
            best = (s, d)
    return best


# ── Database implementation ──────────────────────────────────────────────────


@dataclass
class OSMImporter:
    meta: DatabaseMeta

    def fetch(self, region: Region, filters: dict[str, Any]) -> FetchResult:
        min_kv = float(filters.get("min_voltage_kv") or 0)
        include_cables = bool(filters.get("include_cables", True))
        include_dc = bool(filters.get("include_dc", True))
        query = overpass.build_query(
            region.polygon,
            include_cables=include_cables,
            include_dc=include_dc,
            min_voltage_v=int(min_kv * 1000),
        )
        payload = overpass.post_query(query)
        parsed = _parse_response(payload, min_voltage_kv=min_kv)
        return FetchResult(
            database_id=self.meta.id,
            region=region,
            filters=dict(filters),
            payload={"parsed": parsed, "raw_count": len(payload.get("elements", []))},
        )

    def preview(self, result: FetchResult) -> PreviewSummary:
        parsed: _Parsed = result.payload["parsed"]
        voltages: dict[str, int] = {}
        for line in parsed.lines:
            key = f"{int(round(line.voltage_kv))} kV"
            voltages[key] = voltages.get(key, 0) + 1
        total_length = sum(line.length_km for line in parsed.lines)
        overlay = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon, lat] for lat, lon in line.geometry],
                    },
                    "properties": {
                        "kind": "line",
                        "voltage_kv": line.voltage_kv,
                        "length_km": line.length_km,
                    },
                }
                for line in parsed.lines
            ]
            + [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [s.lon, s.lat]},
                    "properties": {
                        "kind": "substation",
                        "voltages_kv": s.voltages_kv,
                        "name": (s.tags.get("name") or "").strip() or f"substation_{s.osm_id}",
                    },
                }
                for s in parsed.substations
            ],
        }
        return PreviewSummary(
            counts={
                "substations": len(parsed.substations),
                "lines": len(parsed.lines),
                "total_length_km": int(round(total_length)),
                **{f"voltage:{k}": v for k, v in sorted(voltages.items())},
            },
            samples={
                "lines": [
                    {
                        "osm_id": line.osm_id,
                        "voltage_kv": line.voltage_kv,
                        "length_km": round(line.length_km, 2),
                        "circuits": line.circuits,
                    }
                    for line in parsed.lines[:10]
                ],
                "substations": [
                    {
                        "osm_id": s.osm_id,
                        "voltages_kv": s.voltages_kv,
                        "name": (s.tags.get("name") or "").strip(),
                    }
                    for s in parsed.substations[:10]
                ],
            },
            notes=[f"{len(parsed.substations)} substations, {len(parsed.lines)} lines."],
            overlay=overlay,
        )

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment:
        parsed: _Parsed = result.payload["parsed"]
        region: Region = result.region
        type_map = _line_type_mapping()
        fragment = WorkbookFragment()
        bus_rows: list[dict[str, Any]] = []
        line_rows: list[dict[str, Any]] = []
        transformer_rows: list[dict[str, Any]] = []
        bus_names: set[str] = set()
        line_names: set[str] = set()
        transformer_names: set[str] = set()

        # Substations → buses. A substation with N voltage levels emits one
        # bus per level (named ``<slug>_<kv>``) plus N-1 transformers between
        # consecutive levels at the same site. ALL OSM tags preserved on each
        # bus row.
        substation_buses: dict[tuple[int, float], str] = {}
        for s in parsed.substations:
            voltages = sorted(set(s.voltages_kv)) or [380.0]
            base = _slug(s.tags.get("name") or f"sub_{s.osm_id}", fallback="sub")
            for v in voltages:
                key_name = f"{base}_{int(round(v))}kv"
                bus_name = _dedupe(key_name, bus_names)
                substation_buses[(s.osm_id, v)] = bus_name
                row: dict[str, Any] = {
                    "name": bus_name,
                    "v_nom": v,
                    "x": s.lon,
                    "y": s.lat,
                    "country": region.country_iso,
                    "osm_id": s.osm_id,
                    "osm_type": s.osm_type,
                }
                # All OSM tags verbatim.
                for tk, tv in s.tags.items():
                    if tk in row or tv == "":
                        continue
                    row[f"osm_{tk}"] = tv
                row["source"] = "OSM"
                bus_rows.append(row)
            # Transformers between voltage levels at the same substation —
            # ``s_nom`` INTENTIONALLY UNSET. PyPSA's Transformer.s_nom
            # defaults to 0; user sizes via Build view or T3.
            for v_lower, v_upper in zip(voltages, voltages[1:]):
                t_name = _dedupe(
                    f"{base}_tx_{int(round(v_lower))}_{int(round(v_upper))}",
                    transformer_names,
                )
                transformer_rows.append(
                    {
                        "name": t_name,
                        "bus0": substation_buses[(s.osm_id, v_lower)],
                        "bus1": substation_buses[(s.osm_id, v_upper)],
                        "osm_substation_id": s.osm_id,
                        "source": "OSM",
                    }
                )

        # Lines → match endpoints to substations (or synthesise buses).
        synthesised_bus_count = 0
        for line in parsed.lines:
            start_lat, start_lon = line.geometry[0]
            end_lat, end_lon = line.geometry[-1]
            bus0, b0_synth = _resolve_endpoint(
                start_lat, start_lon, line.voltage_kv,
                parsed.substations, substation_buses, bus_rows, bus_names,
                region.country_iso,
            )
            bus1, b1_synth = _resolve_endpoint(
                end_lat, end_lon, line.voltage_kv,
                parsed.substations, substation_buses, bus_rows, bus_names,
                region.country_iso,
            )
            if b0_synth:
                synthesised_bus_count += 1
            if b1_synth:
                synthesised_bus_count += 1
            line_name = _dedupe(
                _slug(line.tags.get("name") or f"osm_line_{line.osm_id}", fallback="line"),
                line_names,
            )
            type_ref = _line_type_for(line.voltage_kv, type_map)
            # r, x, b, s_nom INTENTIONALLY UNSET. PyPSA fills them from
            # `type` at solve time when type_ref is set; otherwise PyPSA's
            # own component defaults apply.
            row = {
                "name": line_name,
                "bus0": bus0,
                "bus1": bus1,
                "length": line.length_km,
                "v_nom": line.voltage_kv,
                "num_parallel": line.circuits,
                "osm_id": line.osm_id,
                "is_cable": line.is_cable,
            }
            if type_ref:
                row["type"] = type_ref
            for tk, tv in line.tags.items():
                key = f"osm_{tk}"
                if key in row or tv == "":
                    continue
                row[key] = tv
            row["source"] = "OSM"
            line_rows.append(row)

        if bus_rows:
            fragment.sheets["buses"] = bus_rows
        if line_rows:
            fragment.sheets["lines"] = line_rows
        if transformer_rows:
            fragment.sheets["transformers"] = transformer_rows

        row_counts = {sheet: len(rows) for sheet, rows in fragment.sheets.items()}
        row_counts["synthesised_buses"] = synthesised_bus_count
        fragment.provenance = Provenance(
            database_id=self.meta.id,
            country_iso=region.country_iso,
            country_name=region.country_name,
            filters_json=json.dumps(result.filters, sort_keys=True, default=str),
            convert_options_json=json.dumps(options.__dict__, sort_keys=True, default=str),
            fetch_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            row_counts_json=json.dumps(row_counts, sort_keys=True),
        )
        return fragment


def _resolve_endpoint(
    lat: float,
    lon: float,
    v_nom_kv: float,
    substations: list[_Substation],
    substation_buses: dict[tuple[int, float], str],
    bus_rows: list[dict[str, Any]],
    bus_names: set[str],
    country_iso: str,
) -> tuple[str, bool]:
    """Return ``(bus_name, synthesised)``."""
    nearest = _nearest_substation(lat, lon, substations)
    if nearest is not None and nearest[1] <= _SNAP_KM:
        s, _ = nearest
        candidate_key = (s.osm_id, v_nom_kv)
        if candidate_key in substation_buses:
            return substation_buses[candidate_key], False
        for v in sorted(s.voltages_kv):
            if (s.osm_id, v) in substation_buses:
                return substation_buses[(s.osm_id, v)], False
    # Synthesise a bus at the endpoint coordinates. v_nom comes from the line.
    synth = _dedupe(
        f"endpoint_{abs(int(lat * 1000))}_{abs(int(lon * 1000))}",
        bus_names,
    )
    bus_rows.append(
        {
            "name": synth,
            "v_nom": v_nom_kv,
            "x": lon,
            "y": lat,
            "country": country_iso,
            "synthesised": True,
            "source": "OSM",
        }
    )
    return synth, True
