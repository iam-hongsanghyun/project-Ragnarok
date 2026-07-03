"""Hydro inflow attachment (I4 remainder) — GloFAS river discharge → ``storage_units-inflow``.

The last missing renewable profile: natural water inflow for hydro storage.
Source: the keyless Open-Meteo **Flood API** (GloFAS reanalysis), daily
``river_discharge`` (m³/s) at any coordinate — same fetch-per-0.1°-cell pattern
as the weather profiles, cached forever via the D1 general cache (the archive is
immutable).

Discharge → inflow (MW): converting m³/s to power needs the head, which the
model doesn't know. Instead the discharge series provides the *shape* and the
user provides the *level*: each unit's inflow is scaled so its window-mean
equals ``target_cf × p_nom`` —

    $$ \\text{inflow}_{u,t} = \\bar{P}_u \\; c \\; \\frac{d_t}{\\overline{d}} $$
    ASCII: inflow[u,t] = p_nom * cf * discharge[t] / mean(discharge)

Symbols: c = target capacity factor [-] (hydro typically 0.3–0.5), d_t = daily
discharge expanded to hours [m³/s]. A zero/dry discharge series falls back to a
flat ``cf × p_nom`` with a note. Daily values are repeated across the day
(inflow is slow-moving); labels can be shifted to local time like the weather
profiles. PHS/pumped units are excluded by default (no natural inflow).
"""
from __future__ import annotations

from typing import Any

from ...cache import cache_get, cache_put
from . import _shift_label
from .attach import _coord, _num, point_key
from .cache import snap

_FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"

HYDRO_HINTS = ("hydro", "ror", "reservoir", "water")
EXCLUDE_HINTS = ("phs", "pump")  # pumped storage has no natural inflow


def is_hydro_carrier(carrier: str) -> bool:
    cl = str(carrier or "").lower()
    if any(h in cl for h in EXCLUDE_HINTS):
        return False
    return any(h in cl for h in HYDRO_HINTS)


def resolve_hydro_targets(
    model: dict[str, list[dict[str, Any]]],
    hydro_carriers: list[str] | None = None,
) -> tuple[list[tuple[str, float, float, float]], list[str]]:
    """Hydro storage units to attach: ``([(name, p_nom, lat, lon)], skipped)``.

    Explicit ``hydro_carriers`` override the substring classifier. Coordinate
    resolution follows the I4 chain: unit x/y → its bus's x/y.
    """
    units = model.get("storage_units") or []
    buses = {str(b.get("name")): b for b in (model.get("buses") or [])}
    explicit = {str(c).lower() for c in (hydro_carriers or [])}

    targets: list[tuple[str, float, float, float]] = []
    skipped: list[str] = []
    for u in units:
        name = str(u.get("name") or "")
        if not name:
            continue
        carrier = str(u.get("carrier") or "")
        if explicit:
            if carrier.lower() not in explicit:
                continue
        elif not is_hydro_carrier(carrier):
            continue
        p_nom = _num(u.get("p_nom")) or 0.0
        if p_nom <= 0:
            skipped.append(name)
            continue
        lat, lon = _coord(u, buses)
        if lat is None or lon is None:
            skipped.append(name)
            continue
        targets.append((name, p_nom, lat, lon))
    return targets, skipped


async def fetch_discharge(
    http: Any, lat: float, lon: float, date_from: str, date_to: str
) -> dict[str, Any]:
    """Daily GloFAS river discharge at a point (D1-cached forever — immutable)."""
    key = {"lat": snap(lat), "lon": snap(lon), "from": date_from, "to": date_to}
    cached = cache_get("open_meteo_flood", key)
    if cached is not None:
        return cached
    body = await http.get_json(_FLOOD_URL, params={
        "latitude": snap(lat), "longitude": snap(lon),
        "daily": "river_discharge",
        "start_date": date_from, "end_date": date_to,
    })
    daily = (body or {}).get("daily") or {}
    out = {"time": daily.get("time") or [], "discharge": daily.get("river_discharge") or []}
    cache_put("open_meteo_flood", key, out)  # ttl None: reanalysis archive is immutable
    return out


def build_inflow_rows(
    targets: list[tuple[str, float, float, float]],
    discharge_by_key: dict[str, dict[str, Any]],
    *,
    target_cf: float = 0.35,
    utc_offset: int = 0,
) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
    """Assemble ``storage_units-inflow`` rows (hourly, MW).

    Returns ``(rows, snapshots, attached, notes)``. Daily discharge repeats
    across each day's 24 hours; each unit's series is scaled to a window-mean of
    ``target_cf × p_nom`` (flat fallback when the series is dry).
    """
    cf = max(0.0, float(target_cf))
    series: dict[str, list[float]] = {}
    days: list[str] = []
    notes: list[str] = []
    for name, p_nom, lat, lon in targets:
        pt = discharge_by_key.get(point_key(lat, lon))
        if not pt or not pt.get("time"):
            continue
        if not days:
            days = [str(d) for d in pt["time"]]
        d = [max(0.0, _num(v) or 0.0) for v in (pt.get("discharge") or [])]
        mean_d = (sum(d) / len(d)) if d else 0.0
        if mean_d > 1e-9:
            series[name] = [p_nom * cf * v / mean_d for v in d]
        else:
            series[name] = [p_nom * cf] * len(days)
            notes.append(f"{name}: dry/zero discharge series — flat inflow at cf {cf:g}.")

    snapshots: list[str] = []
    rows: list[dict[str, Any]] = []
    for i, day in enumerate(days):
        for hour in range(24):
            label = _shift_label(f"{day} {hour:02d}:00", utc_offset)
            snapshots.append(label)
            row: dict[str, Any] = {"snapshot": label}
            for name, vals in series.items():
                if i < len(vals):
                    row[name] = round(vals[i], 4)
            rows.append(row)
    return rows, snapshots, list(series), notes
