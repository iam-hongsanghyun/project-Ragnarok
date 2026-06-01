"""OpenStreetMap transmission importer — Overpass to workbook.

Faithful port of the browser-side OSM importer (``frontend/.../lib/importers/
osm/*.ts``). The Overpass query is built from the selected region polygon,
POSTed to the public mirror, and parsed into substations + lines. A
PyPSA-Earth-style topology cleanup pipeline (every step gated by a per-step
toggle in the right rail) turns the raw OSM ways into buses + lines +
transformers.

Output rows preserve every OSM tag verbatim as ``osm_*`` columns. Optional
PyPSA attributes (r / x / b / s_nom / carrier / ...) are never fabricated;
empty cells fall through to PyPSA defaults. Lines set ``type`` to a PyPSA
standard-type name (from ``line_types.json``) for common voltages.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
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

# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_DEFAULT_TIMEOUT_S = 180

# OpenStreetMap is a multi-dataset source: grid topology (this module) and
# power plants (the osm_powerplants sibling). They share a source so the UI
# groups them under one database.
OSM_SOURCE_ID = "osm"
OSM_SOURCE_LABEL = "OpenStreetMap (Overpass)"
_EARTH_KM = 6371.0
_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")
_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_VOLTS_THRESHOLD = 1000.0
_LINE_TYPES_PATH = Path(__file__).resolve().parent / "line_types.json"


def _overpass_url() -> str:
    return os.environ.get("RAGNAROK_OVERPASS_URL", _DEFAULT_OVERPASS_URL)


# ── Voltage tag parser (port of voltage.ts) ──────────────────────────────────


def _coerce_to_kv(raw: float) -> float:
    return raw / 1000.0 if raw >= _VOLTS_THRESHOLD else raw


def _maybe_float(token: str) -> float | None:
    trimmed = token.strip()
    if not trimmed:
        return None
    match = _NUM_RE.search(trimmed.replace(",", "."))
    if not match:
        return None
    try:
        v = float(match.group(0))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def parse_voltage_kv(value: Any) -> list[float]:
    """Parse a raw OSM ``voltage`` tag into a list of voltages in kV.

    Returns an empty list for missing / unparseable values. Any bare number
    >= 1000 is interpreted as volts (divided by 1000); anything smaller is
    taken as kV.
    """
    if not value:
        return []
    text = str(value).strip().lower()
    if not text or text in ("unknown", "none", "n/a"):
        return []
    # Strip explicit "kv" / "volts" / "v" markers — the magnitude tells us
    # the unit anyway. Order matters: "kv" and "volts" before bare "v".
    text = text.replace("kv", "").replace("volts", "").replace("v", "")
    seen: set[float] = set()
    out: list[float] = []
    for chunk in re.split(r"[;,]", text):
        v = _maybe_float(chunk)
        if v is None:
            continue
        kv = round(_coerce_to_kv(v) * 10000) / 10000
        if kv <= 0 or kv in seen:
            continue
        seen.add(kv)
        out.append(kv)
    return out


# ── Geometry + naming helpers (port of topology_helpers.ts) ───────────────────


def _slug(raw: Any, fallback: str = "asset") -> str:
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


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    dlat = lat2r - lat1r
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    )
    return 2 * _EARTH_KM * math.asin(math.sqrt(a))


def _polyline_length_km(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(len(points) - 1):
        lat1, lon1 = points[i]
        lat2, lon2 = points[i + 1]
        total += _haversine_km(lat1, lon1, lat2, lon2)
    return total


def _line_type_mapping() -> dict[int, str]:
    raw = json.loads(_LINE_TYPES_PATH.read_text()).get("voltage_kv_to_type", {})
    return {int(k): str(v) for k, v in raw.items()}


def _line_type_for(voltage_kv: float, mapping: dict[int, str]) -> str:
    return mapping.get(round(voltage_kv), "")


# ── Tag helpers (port of convert.ts) ──────────────────────────────────────────


def _element_center(el: dict[str, Any]) -> tuple[float, float] | None:
    lat = el.get("lat")
    lon = el.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return (float(lat), float(lon))
    geom = el.get("geometry") or []
    if geom:
        lats = 0.0
        lons = 0.0
        for p in geom:
            lats += p["lat"]
            lons += p["lon"]
        return (lats / len(geom), lons / len(geom))
    center = el.get("center")
    if center:
        return (center["lat"], center["lon"])
    return None


def _int_tag(tags: dict[str, Any], key: str, default: int = 1) -> int:
    raw = tags.get(key)
    if raw is None or raw == "":
        return default
    head = str(raw).split(";")[0]
    try:
        v = int(head)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


def _float_tag(tags: dict[str, Any], key: str, default: float) -> float:
    raw = tags.get(key)
    if raw is None or raw == "":
        return default
    head = str(raw).split(";")[0]
    try:
        v = float(head)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


# ── Overpass query builder (port of fetch.ts) ─────────────────────────────────


def _largest_ring(geom: Any) -> list[tuple[float, float]]:
    """Largest exterior ring of a shapely (Multi)Polygon as ``[(lat, lon), ...]``.

    Shapely stores coordinates as (lon, lat); Overpass expects "lat lon" pairs.
    """
    rings: list[list[tuple[float, float]]] = []
    geom_type = geom.geom_type
    if geom_type == "Polygon":
        rings.append(list(geom.exterior.coords))
    elif geom_type == "MultiPolygon":
        for poly in geom.geoms:
            rings.append(list(poly.exterior.coords))
    else:
        raise ValueError(f"region polygon has unsupported type: {geom_type}")
    if not rings:
        raise ValueError("region polygon has no exterior ring")
    best = rings[0]
    for r in rings:
        if len(r) > len(best):
            best = r
    if len(best) < 3:
        raise ValueError("region polygon ring has fewer than 3 vertices")
    # Coords are (lon, lat); emit (lat, lon).
    return [(float(lat), float(lon)) for (lon, lat) in best]


def _poly_filter(geom: Any) -> str:
    return " ".join(f"{lat} {lon}" for (lat, lon) in _largest_ring(geom))


def build_query(
    geom: Any,
    include_cables: bool,
    include_dc: bool,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> str:
    poly = _poly_filter(geom)
    # Tag-presence filter (`["voltage"]`) is enough — voltage normalisation
    # and the user's min_voltage threshold are re-applied client-side.
    voltage_filter = '["voltage"]'
    # HVDC opt-out: drop lines where `frequency` is explicitly "0".
    dc_clause = "" if include_dc else '["frequency"!="0"]'
    parts = [
        f'way["power"="line"]{voltage_filter}{dc_clause}(poly:"{poly}");',
    ]
    if include_cables:
        parts.append(
            f'way["power"="cable"]{voltage_filter}{dc_clause}(poly:"{poly}");'
        )
    # Require ["voltage"] on substations too — a substation without a
    # parseable voltage cannot survive the client-side min_voltage filter, so
    # the threshold is free to push to the server.
    parts.append(f'node["power"="substation"]{voltage_filter}(poly:"{poly}");')
    parts.append(f'way["power"="substation"]{voltage_filter}(poly:"{poly}");')
    return f"[out:json][timeout:{timeout_s}];({''.join(parts)});out body geom;"


# ── Overpass response parser (port of convert.ts parseResponse) ───────────────


def _parse_response(payload: dict[str, Any], min_voltage_kv: float) -> dict[str, Any]:
    substations: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for el in payload.get("elements") or []:
        tags = el.get("tags") or {}
        power = tags.get("power")
        voltages = parse_voltage_kv(tags.get("voltage"))
        if power == "substation":
            # Require a parseable voltage and that its max clears the user's
            # threshold. Substations without voltage are LV distribution noise.
            if not voltages:
                continue
            if max(voltages) < min_voltage_kv:
                continue
            center = _element_center(el)
            if not center:
                continue
            tags_as_str = {
                k: str(v) for k, v in tags.items() if v is not None
            }
            substations.append(
                {
                    "osm_id": int(el.get("id") or 0),
                    "osm_type": str(el.get("type") or "node"),
                    "lat": center[0],
                    "lon": center[1],
                    "voltages_kv": voltages,
                    "tags": tags_as_str,
                }
            )
            continue
        if power in ("line", "cable"):
            if not voltages:
                continue
            v_max = max(voltages)
            if v_max < min_voltage_kv:
                continue
            geom = el.get("geometry") or []
            points = [(p["lat"], p["lon"]) for p in geom]
            if len(points) < 2:
                continue
            length_km = _polyline_length_km(points)
            if length_km <= 0:
                continue
            # OSM node IDs along the way. Endpoint node IDs are the gold-
            # standard merge key — two ways meeting at the same OSM node are
            # bit-identical at that endpoint.
            nodes = [int(n) for n in (el.get("nodes") or [])]
            tags_as_str = {
                k: str(v) for k, v in tags.items() if v is not None
            }
            lines.append(
                {
                    "osm_id": int(el.get("id") or 0),
                    "geometry": points,
                    "nodes": nodes,
                    "length_km": length_km,
                    "voltage_kv": v_max,
                    "frequency_hz": _float_tag(tags, "frequency", 50.0),
                    "circuits": _int_tag(tags, "circuits", 1),
                    "is_cable": power == "cable",
                    "tags": tags_as_str,
                }
            )
    return {"substations": substations, "lines": lines}


# ── Topology options (port of resolveTopologyOptions) ─────────────────────────


def _as_bool(v: Any, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return default


def _as_number(v: Any, default: float) -> float:
    if v is None or v == "":
        return default
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return n if math.isfinite(n) else default


def resolve_topology_options(filters: dict[str, Any]) -> dict[str, Any]:
    """Resolve cleanup options from the user's filter blob.

    Each step has its own toggle; defaults are all ON (= the full-cleanup
    pipeline modelled on PyPSA-Earth's ``build_osm_network``).
    """
    return {
        "merge_fragments": _as_bool(filters.get("merge_fragments"), True),
        "cluster_substations": _as_bool(filters.get("cluster_substations"), True),
        "cluster_eps_km": _as_number(filters.get("cluster_eps_km"), 5),
        "add_line_endings": _as_bool(filters.get("add_line_endings"), True),
        "snap_endpoints": _as_bool(filters.get("snap_endpoints"), True),
        "split_at_substations": _as_bool(filters.get("split_at_substations"), True),
        "split_tolerance_km": _as_number(filters.get("split_tolerance_m"), 100) / 1000,
        "emit_transformers": _as_bool(filters.get("emit_transformers"), True),
        "collapse_parallels": _as_bool(filters.get("collapse_parallels"), True),
    }


# ── Stitch contiguous OSM ways (port of mergeContiguousLines) ─────────────────


def _group_key(line: dict[str, Any]) -> str:
    dc_mark = "DC" if abs(line["frequency_hz"]) <= 0.1 else "AC"
    return f"{round(line['voltage_kv'])}|{dc_mark}"


def _concat_lines(a: dict[str, Any], b: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode == "append-fwd":
        coords = a["geometry"] + b["geometry"][1:]
        nodes = a["nodes"] + b["nodes"][1:]
    elif mode == "append-rev":
        coords = a["geometry"] + list(reversed(b["geometry"][:-1]))
        nodes = a["nodes"] + list(reversed(b["nodes"][:-1]))
    elif mode == "prepend-fwd":
        coords = b["geometry"] + a["geometry"][1:]
        nodes = b["nodes"] + a["nodes"][1:]
    else:  # prepend-rev
        coords = list(reversed(b["geometry"])) + a["geometry"][1:]
        nodes = list(reversed(b["nodes"])) + a["nodes"][1:]
    # Preserve provenance: the merged line carries every component osm_id.
    a_ids = (a["tags"].get("osm_merged_ids") or str(a["osm_id"])).split(",")
    b_ids = (b["tags"].get("osm_merged_ids") or str(b["osm_id"])).split(",")
    merged: list[str] = []
    seen: set[str] = set()
    for i in [*a_ids, *b_ids]:
        if i not in seen:
            seen.add(i)
            merged.append(i)
    out = dict(a)
    out["geometry"] = coords
    out["nodes"] = nodes
    out["length_km"] = _polyline_length_km(coords)
    out["circuits"] = max(a["circuits"], b["circuits"])
    out["is_cable"] = a["is_cable"] and b["is_cable"]  # overhead wins
    out["tags"] = {**a["tags"], "osm_merged_ids": ",".join(merged)}
    return out


def _merge_contiguous_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        groups.setdefault(_group_key(line), []).append(line)

    out: list[dict[str, Any]] = []
    for group in groups.values():
        # Greedy: take a line, repeatedly absorb any remaining line that
        # shares an endpoint NODE ID with the current one.
        remaining = list(group)
        while remaining:
            current = remaining.pop(0)
            absorbed = True
            while absorbed:
                absorbed = False
                for i in range(len(remaining)):
                    other = remaining[i]
                    if len(current["nodes"]) < 2 or len(other["nodes"]) < 2:
                        continue
                    ms = current["nodes"][0]
                    me = current["nodes"][-1]
                    os_ = other["nodes"][0]
                    oe = other["nodes"][-1]
                    if me == os_:
                        current = _concat_lines(current, other, "append-fwd")
                    elif me == oe:
                        current = _concat_lines(current, other, "append-rev")
                    elif ms == oe:
                        current = _concat_lines(current, other, "prepend-fwd")
                    elif ms == os_:
                        current = _concat_lines(current, other, "prepend-rev")
                    else:
                        continue
                    remaining.pop(i)
                    absorbed = True
                    break
            out.append(current)
    return out


# ── DBSCAN-equivalent clustering (port of clusterSubstations) ─────────────────


def _cluster_substations(subs: list[dict[str, Any]], eps_km: float) -> list[int]:
    parent = list(range(len(subs)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(subs)):
        for j in range(i + 1, len(subs)):
            d = _haversine_km(
                subs[i]["lat"], subs[i]["lon"], subs[j]["lat"], subs[j]["lon"]
            )
            if d <= eps_km:
                union(i, j)
    # Compact root indices to dense 0..k station_ids.
    roots: dict[int, int] = {}
    station_of = [0] * len(subs)
    for i in range(len(subs)):
        r = find(i)
        if r not in roots:
            roots[r] = len(roots)
        station_of[i] = roots[r]
    return station_of


# ── Project point onto segment (port of projectOntoSegment) ───────────────────


def _project_onto_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> tuple[float, tuple[float, float]]:
    dx = bx - ax
    dy = by - ay
    len2 = dx * dx + dy * dy
    if len2 == 0:
        return (0.0, (ax, ay))
    t = ((px - ax) * dx + (py - ay) * dy) / len2
    tc = max(0.0, min(1.0, t))
    return (tc, (ax + tc * dx, ay + tc * dy))


# ── Pre-split lines at intermediate substations (port of splitLineAtSubstations)


def _split_line_at_substations(
    line: dict[str, Any], subs: list[dict[str, Any]], tolerance_km: float
) -> dict[str, Any]:
    splits: list[dict[str, Any]] = []
    line_kv = round(line["voltage_kv"])
    geometry = line["geometry"]
    for s in range(len(geometry) - 1):
        a_lat, a_lon = geometry[s]
        b_lat, b_lon = geometry[s + 1]
        for si in range(len(subs)):
            sub = subs[si]
            # Only split at substations operating at the line's voltage.
            if not any(round(v) == line_kv for v in sub["voltages_kv"]):
                continue
            t, foot = _project_onto_segment(
                sub["lon"], sub["lat"], a_lon, a_lat, b_lon, b_lat
            )
            # Skip projections at the very ends (those are endpoints).
            if t <= 0.001 or t >= 0.999:
                continue
            d = _haversine_km(sub["lat"], sub["lon"], foot[1], foot[0])
            if d > tolerance_km:
                continue
            splits.append(
                {
                    "seg_index": s,
                    "t": t,
                    "point": (sub["lat"], sub["lon"]),
                    "sub_idx": si,
                }
            )
    if not splits:
        return {"parts": [line], "split_sub_indices": []}
    # Order splits along the line.
    splits.sort(key=lambda sp: (sp["seg_index"], sp["t"]))
    # Deduplicate near-identical splits (within ~10 m).
    uniq: list[dict[str, Any]] = []
    for sp in splits:
        if uniq:
            last = uniq[-1]
            if (
                _haversine_km(
                    last["point"][0], last["point"][1], sp["point"][0], sp["point"][1]
                )
                < 0.01
            ):
                continue
        uniq.append(sp)

    # Walk geometry, breaking at each split point.
    parts: list[dict[str, Any]] = []
    split_subs: list[int] = []
    current: list[tuple[float, float]] = [geometry[0]]
    cursor_seg = 0
    for sp in uniq:
        while cursor_seg < sp["seg_index"]:
            current.append(geometry[cursor_seg + 1])
            cursor_seg += 1
        current.append(sp["point"])
        part = dict(line)
        part["geometry"] = current
        part["length_km"] = _polyline_length_km(current)
        parts.append(part)
        split_subs.append(sp["sub_idx"])
        current = [sp["point"]]
    # Finish the tail.
    while cursor_seg < len(geometry) - 1:
        current.append(geometry[cursor_seg + 1])
        cursor_seg += 1
    if len(current) >= 2:
        part = dict(line)
        part["geometry"] = current
        part["length_km"] = _polyline_length_km(current)
        parts.append(part)
    return {"parts": parts, "split_sub_indices": split_subs}


# ── Nearest cluster bus for an endpoint (port of nearestBusForVoltage) ────────


def _station_key(station_id: int, voltage_kv: float) -> str:
    return f"{station_id}|{round(voltage_kv)}"


def _nearest_bus_for_voltage(
    lat: float,
    lon: float,
    voltage_kv: float,
    subs: list[dict[str, Any]],
    station_of: list[int],
    station_buses: dict[str, str],
    max_distance_km: float = math.inf,
) -> str | None:
    best_bus: str | None = None
    best_d = math.inf
    # First pass: prefer a bus at this voltage in any nearby cluster.
    for i in range(len(subs)):
        s = subs[i]
        bus = station_buses.get(_station_key(station_of[i], voltage_kv))
        if not bus:
            continue
        d = _haversine_km(lat, lon, s["lat"], s["lon"])
        if d > max_distance_km:
            continue
        if d < best_d:
            best_d = d
            best_bus = bus
    if best_bus:
        return best_bus
    # Fallback: any bus in any cluster (different voltage), still within
    # max_distance_km so the "snap with cap" mode doesn't reach across the map.
    for i in range(len(subs)):
        s = subs[i]
        d = _haversine_km(lat, lon, s["lat"], s["lon"])
        if d > max_distance_km:
            continue
        if d >= best_d:
            continue
        for k, v in station_buses.items():
            if k.startswith(f"{station_of[i]}|"):
                best_bus = v
                best_d = d
                break
    return best_bus


# ── Build PyPSA-Earth-style sheets (port of buildPyPSAEarthStyleSheets) ───────


def build_pypsa_earth_style_sheets(
    parsed: dict[str, Any],
    region: Region,
    type_map: dict[int, str],
    opts: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    subs: list[dict[str, Any]] = list(parsed["substations"])

    # Step 1: stitch contiguous OSM ways into logical lines (optional).
    merged_lines = (
        _merge_contiguous_lines(parsed["lines"])
        if opts["merge_fragments"]
        else list(parsed["lines"])
    )

    # Step 2: synthesise a substation at every line endpoint not within the
    # cluster radius of a real one (optional).
    if opts["add_line_endings"]:
        for line in merged_lines:
            geom = line["geometry"]
            for endpoint in (geom[0], geom[-1]):
                lat, lon = endpoint
                near = False
                for s in subs:
                    if _haversine_km(lat, lon, s["lat"], s["lon"]) <= opts["cluster_eps_km"]:
                        near = True
                        break
                if not near:
                    subs.append(
                        {
                            "osm_id": 0,
                            "osm_type": "synthetic_endpoint",
                            "lat": lat,
                            "lon": lon,
                            "voltages_kv": [line["voltage_kv"]],
                            "tags": {"name": "", "power": "substation_synthetic"},
                        }
                    )

    # Step 3: DBSCAN cluster (optional). When off, each substation is its own
    # "cluster" (station_id = its index).
    station_of = (
        _cluster_substations(subs, opts["cluster_eps_km"])
        if opts["cluster_substations"]
        else list(range(len(subs)))
    )
    n_stations = (max(station_of) + 1) if station_of else 0

    # For each station_id, the union of voltages present at all members.
    station_voltages: list[set[int]] = [set() for _ in range(n_stations)]
    station_centroid: list[list[float]] = [
        [0.0, 0.0, 0.0] for _ in range(n_stations)
    ]  # [lat_sum, lon_sum, count]
    station_tags: list[dict[str, str]] = [{} for _ in range(n_stations)]
    station_osm_ids: list[list[int]] = [[] for _ in range(n_stations)]
    for i in range(len(subs)):
        st = station_of[i]
        for v in subs[i]["voltages_kv"]:
            station_voltages[st].add(round(v))
        station_centroid[st][0] += subs[i]["lat"]
        station_centroid[st][1] += subs[i]["lon"]
        station_centroid[st][2] += 1
        # Keep tags from the first real substation in the cluster (synthetic
        # endpoints carry empty tag dicts).
        if not station_tags[st] and subs[i]["osm_id"] != 0:
            for k, v in subs[i]["tags"].items():
                if v:
                    station_tags[st][k] = v
        if subs[i]["osm_id"] != 0:
            station_osm_ids[st].append(subs[i]["osm_id"])

    # Emit one bus per (station_id, voltage).
    bus_rows: list[dict[str, Any]] = []
    bus_names: set[str] = set()
    station_buses: dict[str, str] = {}
    transformer_rows: list[dict[str, Any]] = []
    transformer_names: set[str] = set()

    for st in range(n_stations):
        if station_centroid[st][2] == 0:
            continue
        lat_c = station_centroid[st][0] / station_centroid[st][2]
        lon_c = station_centroid[st][1] / station_centroid[st][2]
        voltages = sorted(station_voltages[st])
        if not voltages:
            continue
        base = _slug(station_tags[st].get("name") or f"station_{st}", "station")
        for v in voltages:
            name = _dedupe(f"{base}_{v}kv", bus_names)
            station_buses[_station_key(st, v)] = name
            row: dict[str, Any] = {
                "name": name,
                "v_nom": v,
                "x": lon_c,
                "y": lat_c,
                "country": region.country_iso,
                "station_id": st,
                "osm_substation_ids": ";".join(str(x) for x in station_osm_ids[st]),
            }
            for tk, tv in station_tags[st].items():
                key = f"osm_{tk}"
                if key in row:
                    continue
                row[key] = tv
            row["source"] = "OSM (cleaned)"
            bus_rows.append(row)
        # Step 4: transformers between consecutive voltage levels (optional).
        if opts["emit_transformers"]:
            for i in range(len(voltages) - 1):
                v_low = voltages[i]
                v_high = voltages[i + 1]
                t_name = _dedupe(f"{base}_tx_{v_low}_{v_high}", transformer_names)
                transformer_rows.append(
                    {
                        "name": t_name,
                        "bus0": station_buses[_station_key(st, v_low)],
                        "bus1": station_buses[_station_key(st, v_high)],
                        "station_id": st,
                        "source": "OSM (cleaned)",
                    }
                )

    # Step 5: split each line at intermediate substations (optional), then
    # snap endpoints. When snap_endpoints is on, the snap has NO distance cap;
    # when off, a 5 km cap limits it (endpoints with nothing within 5 km drop
    # their lines).
    snap_max_km = math.inf if opts["snap_endpoints"] else 5.0
    line_rows: list[dict[str, Any]] = []
    line_names: set[str] = set()
    for line in merged_lines:
        split = (
            _split_line_at_substations(line, subs, opts["split_tolerance_km"])
            if opts["split_at_substations"]
            else {"parts": [line], "split_sub_indices": []}
        )
        n_parts = len(split["parts"])
        for pi in range(n_parts):
            part = split["parts"][pi]
            geom = part["geometry"]
            start_lat, start_lon = geom[0]
            end_lat, end_lon = geom[-1]
            bus0 = _nearest_bus_for_voltage(
                start_lat, start_lon, part["voltage_kv"],
                subs, station_of, station_buses, snap_max_km,
            )
            bus1 = _nearest_bus_for_voltage(
                end_lat, end_lon, part["voltage_kv"],
                subs, station_of, station_buses, snap_max_km,
            )
            if not bus0 or not bus1 or bus0 == bus1:
                continue  # drop self-loops
            part_name = part["tags"].get("name")
            if part_name:
                raw_name = f"{part_name}_p{pi}" if n_parts > 1 else part_name
            else:
                raw_name = f"osm_line_{part['osm_id']}_p{pi}"
            line_name = _dedupe(_slug(raw_name, "line"), line_names)
            type_ref = _line_type_for(part["voltage_kv"], type_map)
            row = {
                "name": line_name,
                "bus0": bus0,
                "bus1": bus1,
                "length": part["length_km"],
                "v_nom": part["voltage_kv"],
                "num_parallel": part["circuits"],
                "osm_id": part["osm_id"],
                "is_cable": part["is_cable"],
            }
            if type_ref:
                row["type"] = type_ref
            if n_parts > 1:
                row["osm_split_part"] = pi
            for tk, tv in part["tags"].items():
                if not tv:
                    continue
                key = f"osm_{tk}"
                if key in row:
                    continue
                row[key] = tv
            row["source"] = "OSM (cleaned)"
            line_rows.append(row)

    # Step 6: collapse parallel & redundant connections (optional). Group by
    # (min(bus0,bus1), max(bus0,bus1), v_nom) and take MAX (not SUM) of
    # num_parallel and MAX length.
    if opts["collapse_parallels"]:
        def pair_key(a: str, b: str, v: float) -> str:
            lo, hi = (a, b) if a < b else (b, a)
            return f"{lo}|{hi}|{round(v)}"

        by_pair: dict[str, list[dict[str, Any]]] = {}
        for row in line_rows:
            key = pair_key(str(row["bus0"]), str(row["bus1"]), float(row["v_nom"]))
            by_pair.setdefault(key, []).append(row)
        collapsed_line_rows: list[dict[str, Any]] = []
        for group in by_pair.values():
            if len(group) == 1:
                collapsed_line_rows.append(group[0])
                continue
            head = group[0]
            np_val = 0
            length = 0.0
            osm_ids: set[str] = set()
            for r in group:
                npv = r.get("num_parallel") or 1
                try:
                    npv = float(npv)
                except (TypeError, ValueError):
                    npv = 1
                if npv > np_val:
                    np_val = npv
                lv = r.get("length") or 0
                try:
                    lv = float(lv)
                except (TypeError, ValueError):
                    lv = 0.0
                if lv > length:
                    length = lv
                if r.get("osm_id") is not None:
                    osm_ids.add(str(r["osm_id"]))
                merged = r.get("osm_merged_ids")
                if isinstance(merged, str) and merged:
                    for mid in merged.split(","):
                        osm_ids.add(mid)
            collapsed = dict(head)
            collapsed["num_parallel"] = np_val
            collapsed["length"] = length
            collapsed["osm_merged_ids"] = ",".join(osm_ids)
            collapsed["osm_collapsed_count"] = len(group)
            collapsed.pop("osm_split_part", None)
            collapsed_line_rows.append(collapsed)
    else:
        collapsed_line_rows = line_rows

    sheets: dict[str, list[dict[str, Any]]] = {}
    if bus_rows:
        sheets["buses"] = bus_rows
    if collapsed_line_rows:
        sheets["lines"] = collapsed_line_rows
    if transformer_rows:
        sheets["transformers"] = transformer_rows
    return sheets


# ── Metadata (mirror of meta.ts) ──────────────────────────────────────────────

META = DatabaseMeta(
    id="osm",
    name="OpenStreetMap (Overpass) — grid topology",
    short_name="Grid topology",
    source_id=OSM_SOURCE_ID,
    source_label=OSM_SOURCE_LABEL,
    category="transmission",
    subcategory="Live grid topology",
    license="ODbL",
    homepage="https://www.openstreetmap.org",
    version_hint="live",
    description=(
        "Power infrastructure tagged in OpenStreetMap (power=line / cable / "
        "substation). Voltage thresholds are user-tunable; output lands as "
        "buses + lines + transformers."
    ),
    targets=["buses", "lines", "transformers"],
    available=True,
    country_coverage="global",
    requires_secrets=[],
    filters=[
        Filter(
            id="min_voltage_kv", label="Min voltage", kind="number",
            default=110, min=1, max=1500, step=10, unit="kV",
        ),
        Filter(
            id="include_cables", label="Include cables", kind="toggle",
            default=True,
            description="Underground cables in addition to overhead lines.",
        ),
        Filter(
            id="include_dc", label="Include HVDC", kind="toggle", default=True,
        ),
        Filter(
            id="merge_fragments", label="Merge OSM fragments by shared node",
            kind="toggle", default=True,
            description=(
                "Stitch OSM ways that share an endpoint node into a single "
                "logical line. Off then one row per OSM way."
            ),
        ),
        Filter(
            id="cluster_substations",
            label="Cluster nearby substations into stations", kind="toggle",
            default=True,
            description=(
                "DBSCAN-cluster substations within \"Cluster radius\" then one "
                "station_id per cluster, one bus per (station, voltage)."
            ),
        ),
        Filter(
            id="cluster_eps_km", label="Cluster radius", kind="number",
            default=5, min=0, step=0.5, unit="km",
            description=(
                "Two OSM substations within this distance collapse to the same "
                "station. Only used when \"Cluster nearby substations\" is on."
            ),
        ),
        Filter(
            id="add_line_endings", label="Synthesize endpoint substations",
            kind="toggle", default=True,
            description=(
                "Create a substation at every line endpoint that doesn't fall "
                "near a real one."
            ),
        ),
        Filter(
            id="snap_endpoints",
            label="Snap line endpoints to nearest bus (no cap)", kind="toggle",
            default=True,
            description=(
                "Force every line endpoint to its nearest cluster bus, with no "
                "distance ceiling. Off then 5 km cap."
            ),
        ),
        Filter(
            id="split_at_substations",
            label="Split lines at intermediate substations", kind="toggle",
            default=True,
            description=(
                "When a line passes near a substation operating at the same "
                "voltage, break the line there. Off then through-lines stay "
                "unsplit."
            ),
        ),
        Filter(
            id="split_tolerance_m", label="Split tolerance", kind="number",
            default=100, min=0, step=10, unit="m",
            description=(
                "A substation must lie within this distance of a line's path to "
                "trigger a split."
            ),
        ),
        Filter(
            id="emit_transformers",
            label="Emit transformers at multi-voltage stations", kind="toggle",
            default=True,
            description=(
                "Add a Transformer row between consecutive voltage levels at "
                "each station that has more than one voltage."
            ),
        ),
        Filter(
            id="collapse_parallels", label="Collapse parallel lines by bus pair",
            kind="toggle", default=True,
            description=(
                "Group all lines connecting the same (bus0, bus1, voltage) into "
                "one row with num_parallel = max. Off then keep every parallel "
                "circuit as a separate row."
            ),
        ),
    ],
)


# ── Public module ─────────────────────────────────────────────────────────────


class Osm:
    """Faithful port of the browser-side OSM Overpass importer.

    fetch() pre-builds the workbook sheets according to the cleanup toggles
    and stores them in the payload alongside the raw parsed OSM, so preview()
    and to_sheets() report counts identical to what lands in the workbook.
    """

    meta = META

    async def fetch(
        self, region: Region, filters: dict[str, Any], ctx: ImportContext
    ) -> FetchResult:
        min_kv = float(filters.get("min_voltage_kv") or 0)
        include_cables = filters.get("include_cables") is not False
        include_dc = filters.get("include_dc") is not False
        query = build_query(region.polygon, include_cables, include_dc)
        text = await ctx.http.post_text(
            _overpass_url(), data={"data": query}
        )
        payload = json.loads(text)
        parsed = _parse_response(payload, min_kv)

        # Build the sheets ONCE here so preview and to_sheets agree on counts.
        opts = resolve_topology_options(filters)
        type_map = _line_type_mapping()
        sheets = build_pypsa_earth_style_sheets(parsed, region, type_map, opts)

        return FetchResult(
            database_id=META.id,
            region=region,
            filters=dict(filters),
            payload={
                "parsed": parsed,
                "raw_count": len(payload.get("elements") or []),
                "sheets": sheets,
                "resolved_options": opts,
            },
        )

    def preview(self, result: FetchResult) -> PreviewSummary:
        parsed = result.payload["parsed"]
        sheets = result.payload["sheets"]
        line_rows = sheets.get("lines", [])
        bus_rows = sheets.get("buses", [])
        transformer_rows = sheets.get("transformers", [])

        # Voltage histogram on the FINAL line rows (post-cleanup).
        voltages: dict[str, int] = {}
        total_length = 0.0
        for row in line_rows:
            try:
                v = round(float(row.get("v_nom") or 0))
            except (TypeError, ValueError):
                v = 0
            key = f"{v} kV"
            voltages[key] = voltages.get(key, 0) + 1
            try:
                total_length += float(row.get("length") or 0)
            except (TypeError, ValueError):
                pass

        # Map overlay draws raw OSM geometry so the user can compare to OSM on
        # the tile basemap underneath. Geometry stored as (lat, lon); GeoJSON
        # coordinates are [lon, lat].
        features: list[dict[str, Any]] = []
        for line in parsed["lines"]:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon, lat] for (lat, lon) in line["geometry"]],
                    },
                    "properties": {
                        "kind": "line",
                        "voltage_kv": line["voltage_kv"],
                        "length_km": line["length_km"],
                    },
                }
            )
        for s in parsed["substations"]:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                    "properties": {
                        "kind": "substation",
                        "voltages_kv": s["voltages_kv"],
                        "name": (s["tags"].get("name") or "").strip()
                        or f"substation_{s['osm_id']}",
                    },
                }
            )
        overlay = {"type": "FeatureCollection", "features": features}

        counts: dict[str, int] = {
            "buses": len(bus_rows),
            "lines": len(line_rows),
            "transformers": len(transformer_rows),
            "length_km": int(round(total_length)),
        }
        for k in sorted(voltages.keys()):
            counts[f"voltage:{k}"] = voltages[k]

        # Single-line provenance note: raw OSM counts vs final workbook rows.
        raw_subs = len(parsed["substations"])
        raw_lines = len(parsed["lines"])
        final_subs = len(bus_rows)
        final_lines = len(line_rows)
        sub_delta = f" then {final_subs}" if final_subs != raw_subs else ""
        line_delta = f" then {final_lines}" if final_lines != raw_lines else ""
        raw_summary = (
            f"OSM input: {raw_subs}{sub_delta} substations - "
            f"{raw_lines}{line_delta} lines"
        )

        def _round2(v: Any) -> float:
            try:
                return round(float(v or 0) * 100) / 100
            except (TypeError, ValueError):
                return 0.0

        return PreviewSummary(
            counts=counts,
            samples={
                "lines": [
                    {
                        "name": row.get("name"),
                        "bus0": row.get("bus0"),
                        "bus1": row.get("bus1"),
                        "v_nom": row.get("v_nom"),
                        "length_km": _round2(row.get("length")),
                        "num_parallel": row.get("num_parallel"),
                    }
                    for row in line_rows[:10]
                ],
                "substations": [
                    {
                        "name": row.get("name"),
                        "v_nom": row.get("v_nom"),
                        "country": row.get("country"),
                    }
                    for row in bus_rows[:10]
                ],
            },
            notes=[raw_summary],
            overlay=overlay,
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        # Sheets were already built in fetch() — just package them with
        # provenance now.
        sheets = result.payload["sheets"]
        resolved_options = result.payload["resolved_options"]
        region = result.region
        row_counts: dict[str, int] = {k: len(v) for k, v in sheets.items()}
        row_counts["raw_osm_lines"] = len(result.payload["parsed"]["lines"])
        row_counts["raw_osm_substations"] = len(result.payload["parsed"]["substations"])

        frag = WorkbookFragment(sheets=sheets)
        frag.provenance = Provenance(
            database_id=META.id,
            country_iso=region.country_iso,
            country_name=region.country_name,
            filters_json=json.dumps(result.filters, sort_keys=True, default=str),
            convert_options_json=json.dumps(resolved_options, sort_keys=True, default=str),
            fetch_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            row_counts_json=json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return Osm()
