"""OSM transmission importer — query Overpass, normalise, convert to workbook.

Substations become ``buses``, ``power=line`` ways become ``lines`` (with
``r``/``x``/``b``/``s_nom`` from the shared standard-types catalogue).
Substations tagged with multiple voltage levels turn into a small set of
``transformers`` connecting per-voltage sibling buses at the same site.

Endpoint → substation snapping uses a great-circle distance with a small
tolerance (``_SNAP_KM``); endpoints with no nearby substation get a
synthetic bus at the endpoint coordinates so the imported network is always
connected.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ...convert import (
    build_provenance,
    dedupe_name,
    line_params_for_voltage,
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
from . import overpass
from .voltage import max_voltage_kv, parse_voltage_kv

_SNAP_KM = 5.0  # endpoint → substation snap radius
_EARTH_KM = 6371.0


# ── Parsed Overpass elements ─────────────────────────────────────────────────


@dataclass
class _Substation:
    osm_id: int
    osm_type: str  # node / way
    lat: float
    lon: float
    voltages_kv: list[float]
    name: str
    operator: str


@dataclass
class _Line:
    osm_id: int
    geometry: list[tuple[float, float]]  # (lat, lon)
    length_km: float
    voltage_kv: float
    frequency_hz: float
    circuits: int
    cables: int
    is_cable: bool
    name: str
    operator: str


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


def _parse_response(
    payload: dict[str, Any], *, min_voltage_kv: float
) -> _Parsed:
    parsed = _Parsed()
    elements = payload.get("elements", [])
    for el in elements:
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
                    name=str(tags.get("name") or "").strip(),
                    operator=str(tags.get("operator") or "").strip(),
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
                    cables=_int_tag(tags, "cables", 3),
                    is_cable=(power == "cable"),
                    name=str(tags.get("name") or "").strip(),
                    operator=str(tags.get("operator") or "").strip(),
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
                        "name": s.name or f"substation_{s.osm_id}",
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
                        "name": s.name or "",
                    }
                    for s in parsed.substations[:10]
                ],
            },
            notes=[
                f"{len(parsed.substations)} substations, {len(parsed.lines)} lines.",
            ],
            overlay=overlay,
        )

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment:
        parsed: _Parsed = result.payload["parsed"]
        region: Region = result.region
        fragment = WorkbookFragment()
        bus_rows: list[dict[str, Any]] = []
        line_rows: list[dict[str, Any]] = []
        transformer_rows: list[dict[str, Any]] = []
        bus_names: set[str] = set()
        line_names: set[str] = set()
        transformer_names: set[str] = set()

        # Substations → buses. A substation with N voltage levels emits one
        # bus per level (named ``<slug>_<kv>``) plus N-1 transformers between
        # consecutive levels at the same site.
        substation_buses: dict[tuple[int, float], str] = {}
        for s in parsed.substations:
            voltages = sorted(set(s.voltages_kv)) or [380.0]
            base = slugify_name(s.name or f"sub_{s.osm_id}", fallback="sub")
            for v in voltages:
                key_name = f"{base}_{int(round(v))}kv"
                bus_name = dedupe_name(key_name, bus_names)
                substation_buses[(s.osm_id, v)] = bus_name
                bus_rows.append(
                    {
                        "name": bus_name,
                        "v_nom": v,
                        "x": s.lon,
                        "y": s.lat,
                        "carrier": "AC",
                        "country": region.country_iso,
                    }
                )
            for v_lower, v_upper in zip(voltages, voltages[1:]):
                t_name = dedupe_name(
                    f"{base}_tx_{int(round(v_lower))}_{int(round(v_upper))}",
                    transformer_names,
                )
                transformer_rows.append(
                    {
                        "name": t_name,
                        "bus0": substation_buses[(s.osm_id, v_lower)],
                        "bus1": substation_buses[(s.osm_id, v_upper)],
                        "s_nom": 1000.0,
                        "source": "OSM",
                    }
                )

        # Lines → match endpoints to substations (or synthesize buses).
        synthesised_bus_count = 0
        for line in parsed.lines:
            start_lat, start_lon = line.geometry[0]
            end_lat, end_lon = line.geometry[-1]
            bus0 = _resolve_endpoint(
                start_lat,
                start_lon,
                line.voltage_kv,
                parsed.substations,
                substation_buses,
                bus_rows,
                bus_names,
                region.country_iso,
            )
            bus1 = _resolve_endpoint(
                end_lat,
                end_lon,
                line.voltage_kv,
                parsed.substations,
                substation_buses,
                bus_rows,
                bus_names,
                region.country_iso,
            )
            if bus0[1]:
                synthesised_bus_count += 1
            if bus1[1]:
                synthesised_bus_count += 1
            params = line_params_for_voltage(
                line.voltage_kv, line.length_km, num_parallel=line.circuits
            )
            line_name = dedupe_name(
                slugify_name(line.name or f"osm_line_{line.osm_id}", fallback="line"),
                line_names,
            )
            line_rows.append(
                {
                    "name": line_name,
                    "bus0": bus0[0],
                    "bus1": bus1[0],
                    "length": line.length_km,
                    "v_nom": line.voltage_kv,
                    "num_parallel": line.circuits,
                    "r": params["r"],
                    "x": params["x"],
                    "b": params["b"],
                    "s_nom": params["s_nom"],
                    "carrier": "DC" if abs(line.frequency_hz) < 1e-6 else "AC",
                    "source": "OSM",
                }
            )
        if bus_rows:
            fragment.sheets["buses"] = bus_rows
        if line_rows:
            fragment.sheets["lines"] = line_rows
        if transformer_rows:
            fragment.sheets["transformers"] = transformer_rows

        row_counts = {sheet: len(rows) for sheet, rows in fragment.sheets.items()}
        row_counts["synthesised_buses"] = synthesised_bus_count
        fragment.provenance = build_provenance(
            database_id=self.meta.id,
            region=region,
            filters=result.filters,
            options=options,
            fetch_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            row_counts=row_counts,
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
    """Return ``(bus_name, synthesised)``.

    Tries to snap to the nearest substation that also carries the line's
    voltage; falls back to nearest substation at any voltage; finally
    synthesises a bus at the endpoint coordinates.
    """
    nearest = _nearest_substation(lat, lon, substations)
    if nearest is not None and nearest[1] <= _SNAP_KM:
        s, _ = nearest
        # Prefer the bus at exactly the same voltage if it exists.
        candidate_key = (s.osm_id, v_nom_kv)
        if candidate_key in substation_buses:
            return substation_buses[candidate_key], False
        # Otherwise snap to whichever voltage the substation does carry.
        for v in sorted(s.voltages_kv):
            if (s.osm_id, v) in substation_buses:
                return substation_buses[(s.osm_id, v)], False
    # Synthesise a bus at the endpoint coordinates.
    synth = dedupe_name(
        f"endpoint_{abs(int(lat * 1000))}_{abs(int(lon * 1000))}",
        bus_names,
    )
    bus_rows.append(
        {
            "name": synth,
            "v_nom": v_nom_kv,
            "x": lon,
            "y": lat,
            "carrier": "AC",
            "country": country_iso,
            "synthesised": True,
        }
    )
    return synth, True
