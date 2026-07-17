"""Siting core — pure candidate-grid and fragment maths (no I/O).

Turns a bounding box + fetched per-site weather into a workbook fragment of
*extendable* candidate assets: per site a candidate bus, one extendable
generator per technology (``p_nom=0``, ``p_nom_extendable=True``, capped by
``p_nom_max``), and one extendable connection Link to the nearest existing grid
bus whose ``capital_cost`` scales with haversine distance. The ordinary
capacity-expansion solve then *is* the siting optimisation: the LP builds
capacity only where resource quality beats capex + grid-access cost.

Weather → capacity-factor conversion is shared with the Open-Meteo importer
(:mod:`backend.app.importers.databases.openmeteo_renewable.conversion`), so a
siting scan and a plain renewable import produce identical CF series for the
same coordinate.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from ..importers.databases.openmeteo_renewable.conversion import mean_cf, solar_cf, wind_cf
from ..importers.protocol import Provenance, WorkbookFragment

# Candidate-count ceiling: N sites × 8760 snapshots grows the expansion LP
# fast; siting tolerates temporal coarsening far better than it tolerates an
# unsolvable LP. (The importer's analogue is ``_MAX_POINTS = 16``.)
MAX_CANDIDATES = 200

_EARTH_RADIUS_KM = 6371.0

_TECHS = ("solar", "wind")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in km.

    Algorithm:
        $$ d = 2R \\arcsin\\sqrt{\\sin^2\\tfrac{\\Delta\\phi}{2}
               + \\cos\\phi_1\\cos\\phi_2\\sin^2\\tfrac{\\Delta\\lambda}{2}} $$
        ASCII: d = 2*R*asin(sqrt(sin²(dlat/2) + cos(lat1)*cos(lat2)*sin²(dlon/2)))

    where $R$ = 6371 km (mean Earth radius), $\\phi$ = latitude and
    $\\lambda$ = longitude in radians.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def sample_grid(bbox: tuple[float, float, float, float], n: int) -> list[tuple[float, float]]:
    """Up to ``n`` (lat, lon) cell-centre points on a roughly-square grid.

    ``bbox`` is ``(min_lon, min_lat, max_lon, max_lat)`` — the same order the
    importer subsystem uses for country bboxes. ``n == 1`` returns the centre.
    A degenerate bbox (zero width/height) collapses to its centre point.
    """
    min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox)
    n = max(1, min(int(n or 1), MAX_CANDIDATES))
    if n == 1 or (max_lon <= min_lon and max_lat <= min_lat):
        return [(round((min_lat + max_lat) / 2, 4), round((min_lon + max_lon) / 2, 4))]
    side = int(math.ceil(math.sqrt(n)))
    pts: list[tuple[float, float]] = []
    for j in range(side):
        for i in range(side):
            lon = min_lon + (i + 0.5) / side * (max_lon - min_lon)
            lat = min_lat + (j + 0.5) / side * (max_lat - min_lat)
            pts.append((round(lat, 4), round(lon, 4)))
    return pts[:n]


def nearest_bus(lat: float, lon: float, buses: list[dict[str, Any]]) -> tuple[str, float]:
    """The closest grid bus (by haversine) and its distance in km.

    ``buses`` rows carry ``name`` plus PyPSA-standard ``x`` (lon) / ``y`` (lat).
    Rows without both coordinates are skipped; raises ``ValueError`` when no
    bus has usable coordinates (a candidate must connect *somewhere*).
    """
    best: tuple[str, float] | None = None
    for row in buses:
        name = str(row.get("name") or "").strip()
        x, y = row.get("x"), row.get("y")
        if not name or x is None or x == "" or y is None or y == "":
            continue
        d = haversine_km(lat, lon, float(y), float(x))
        if best is None or d < best[1]:
            best = (name, d)
    if best is None:
        raise ValueError("No grid bus with x/y coordinates to connect candidates to.")
    return best[0], round(best[1], 1)


def _shift_label(label: str, offset_hours: int) -> str:
    """Shift a ``"YYYY-MM-DD HH:MM"`` snapshot label from UTC to local time."""
    if not offset_hours:
        return label
    try:
        dt = datetime.strptime(label, "%Y-%m-%d %H:%M")
    except ValueError:
        return label
    return (dt + timedelta(hours=offset_hours)).strftime("%Y-%m-%d %H:%M")


def build_siting_fragment(
    sites: list[dict[str, Any]],
    buses: list[dict[str, Any]],
    *,
    technologies: list[str],
    utc_offset: int = 0,
    performance_ratio: float = 0.9,
    site_capacity_mw: float = 100.0,
    capital_cost_per_mw: dict[str, float] | None = None,
    connection_cost_per_mw_km: float = 0.0,
    marginal_cost: float = 0.0,
    target_snapshots: list[str] | None = None,
    filters: dict[str, Any] | None = None,
) -> tuple[WorkbookFragment, list[dict[str, Any]]]:
    """Convert fetched per-site weather into extendable candidate assets.

    Args:
        sites: fetched weather per candidate — ``{"lat", "lon", "time",
            "ghi" [W/m²], "wind_ms" [m/s]}`` (the ``fetch_point`` shape).
            Sites with an empty ``time`` (upstream fetch failure) are skipped.
        buses: existing grid buses (``name``/``x``/``y``) to connect to.
        technologies: subset of ``("solar", "wind")`` — one extendable
            generator per technology per site.
        utc_offset: hours to shift snapshot labels from UTC to local time.
        performance_ratio: flat solar derate η (see ``solar_cf``).
        site_capacity_mw: per-site build ceiling (``p_nom_max``, MW). Without
            a cap the LP dumps everything at the single best site.
        capital_cost_per_mw: per-technology generator capex (currency/MW),
            written to ``capital_cost``; missing technologies default to 0.
        connection_cost_per_mw_km: grid-connection capex rate
            (currency/MW·km); the Link's ``capital_cost`` is this × distance.
        marginal_cost: generator operating cost (currency/MWh), usually 0.
        target_snapshots: the model's EXISTING snapshot labels. When given, CF
            series are tiled positionally onto these labels and the fragment
            introduces no new snapshots — so the solve window keeps its demand
            data. (Importing the weather window as new snapshots would union
            them into the model where the load series has no values: the LP
            then sees zero demand there and correctly builds nothing.) When
            omitted, the fetched window lands as new snapshots.
        filters: echoed into the provenance row for reproducibility.

    Returns:
        ``(fragment, candidates)`` — the workbook fragment (buses, generators,
        links, carriers, ``generators-p_max_pu``, snapshots, provenance) and
        one metadata row per kept candidate: ``{"id", "lat", "lon", "siteBus",
        "gridBus", "distanceKm", "connectionCostPerMw", "meanCf": {tech: cf}}``.
    """
    techs = [t for t in technologies if t in _TECHS] or list(_TECHS)
    costs = capital_cost_per_mw or {}
    cap = max(0.0, float(site_capacity_mw))

    kept = [s for s in sites if s.get("time")]
    frag = WorkbookFragment()
    candidates: list[dict[str, Any]] = []
    if not kept:
        return frag, candidates

    times = kept[0]["time"]
    if target_snapshots:
        snapshots = [str(s) for s in target_snapshots]
    else:
        snapshots = [_shift_label(str(t).replace("T", " "), int(utc_offset)) for t in times]

    carriers: list[dict[str, Any]] = [{"name": "AC"}]
    carriers += [{"name": t, "co2_emissions": 0.0} for t in techs]
    bus_rows: list[dict[str, Any]] = []
    gen_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []
    series_by_gen: dict[str, list[float]] = {}

    for idx, site in enumerate(kept, start=1):
        lat, lon = float(site["lat"]), float(site["lon"])
        grid_bus, dist_km = nearest_bus(lat, lon, buses)
        site_bus = f"siting_site_{idx}"
        conn_cost = round(float(connection_cost_per_mw_km) * dist_km, 2)

        mean_by_tech: dict[str, float] = {}
        for tech in techs:
            cf = (
                solar_cf(site.get("ghi") or [], performance_ratio)
                if tech == "solar"
                else wind_cf(site.get("wind_ms") or [])
            )
            gen = f"siting_{tech}_{idx}"
            series_by_gen[gen] = cf
            mean_by_tech[tech] = round(mean_cf(cf), 4)
            gen_rows.append({
                "name": gen, "bus": site_bus, "carrier": tech,
                "p_nom": 0.0, "p_nom_extendable": True, "p_nom_max": cap,
                "capital_cost": float(costs.get(tech) or 0.0),
                "marginal_cost": float(marginal_cost),
                "x": lon, "y": lat,
            })

        bus_rows.append({"name": site_bus, "carrier": "AC", "x": lon, "y": lat})
        # One shared interconnection per site: the technologies on the site
        # compete for (and jointly pay for) the same grid-access capacity.
        link_rows.append({
            "name": f"siting_conn_{idx}", "bus0": site_bus, "bus1": grid_bus,
            "carrier": "AC", "p_nom": 0.0, "p_nom_extendable": True,
            "p_nom_max": cap, "capital_cost": conn_cost, "efficiency": 1.0,
            "length": dist_km, "x": lon, "y": lat,
        })
        candidates.append({
            "id": idx, "lat": lat, "lon": lon,
            "siteBus": site_bus, "gridBus": grid_bus, "distanceKm": dist_km,
            "connectionCostPerMw": conn_cost, "meanCf": mean_by_tech,
        })

    # Tiled indexing: in target-snapshot mode the model window can be longer or
    # shorter than the fetched weather window, so the CF sequence repeats to
    # cover it (identity when the fragment lands its own snapshots).
    p_max_pu_rows: list[dict[str, Any]] = []
    for i, snap in enumerate(snapshots):
        row: dict[str, Any] = {"snapshot": snap}
        for gen, cf in series_by_gen.items():
            if cf:
                row[gen] = round(cf[i % len(cf)], 4)
        p_max_pu_rows.append(row)

    frag.sheets["carriers"] = carriers
    frag.sheets["buses"] = bus_rows
    frag.sheets["generators"] = gen_rows
    frag.sheets["links"] = link_rows
    frag.sheets["generators-p_max_pu"] = p_max_pu_rows
    frag.snapshots = snapshots
    frag.provenance = Provenance(
        "siting_scan", "", "Siting scan",
        json.dumps(filters or {}, sort_keys=True, default=str),
        json.dumps({
            "technologies": techs, "site_capacity_mw": cap,
            "capital_cost_per_mw": {t: float(costs.get(t) or 0.0) for t in techs},
            "connection_cost_per_mw_km": float(connection_cost_per_mw_km),
        }, sort_keys=True),
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        json.dumps({s: len(r) for s, r in frag.sheets.items()}, sort_keys=True),
    )
    return frag, candidates
