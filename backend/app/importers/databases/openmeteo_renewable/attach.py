"""Attach Open-Meteo renewable profiles to an EXISTING fleet by coordinate (I4).

The importer *creates* renewable generators; this attaches profiles to the
generators a user already has. It resolves each renewable generator's query point
(its own ``x``/``y``, else its bus's ``x``/``y``), and lands
``generators-p_max_pu`` per generator from that point's capacity factor. A
session-model transform (needs the working model), not an importer — the async
weather fetch + dedup-by-grid-cell orchestration lives in the transforms router.

Pure functions here (no I/O) so the resolution + assembly are unit-testable; the
endpoint supplies the fetched weather.
"""
from __future__ import annotations

from typing import Any

from .cache import snap
from .conversion import solar_cf, wind_cf

# Carrier-name hints when the user doesn't pass explicit carrier sets.
_SOLAR_HINTS = ("solar", "pv")
_WIND_HINTS = ("wind", "onwind", "offwind")


def classify(carrier: str) -> str | None:
    """Map a carrier name to ``solar`` / ``wind`` by substring hint, else None."""
    c = str(carrier or "").lower()
    if any(h in c for h in _WIND_HINTS):
        return "wind"
    if any(h in c for h in _SOLAR_HINTS):
        return "solar"
    return None


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # reject NaN


def _coord(gen: dict[str, Any], buses: dict[str, dict[str, Any]]) -> tuple[float | None, float | None]:
    """Resolve a generator's (lat, lon): its own x/y, else its bus's x/y."""
    x, y = _num(gen.get("x")), _num(gen.get("y"))
    if x is not None and y is not None:
        return y, x
    bus = buses.get(str(gen.get("bus")))
    if bus:
        bx, by = _num(bus.get("x")), _num(bus.get("y"))
        if bx is not None and by is not None:
            return by, bx
    return None, None


def point_key(lat: float, lon: float) -> str:
    """Grid-cell key for deduplicating fetches (matches the cache grid)."""
    return f"{snap(lat)},{snap(lon)}"


def resolve_targets(
    model: dict[str, list[dict[str, Any]]],
    solar_carriers: list[str] | None = None,
    wind_carriers: list[str] | None = None,
) -> tuple[list[tuple[str, str, float, float]], list[str]]:
    """Renewable generators to attach + those skipped for want of a coordinate.

    Returns ``([(gen_name, kind, lat, lon)], [skipped_gen_name])``. Explicit
    ``solar_carriers`` / ``wind_carriers`` override the substring classifier.
    """
    gens = model.get("generators") or []
    buses = {str(b.get("name")): b for b in (model.get("buses") or [])}
    solar_set = {str(c).lower() for c in (solar_carriers or [])}
    wind_set = {str(c).lower() for c in (wind_carriers or [])}

    targets: list[tuple[str, str, float, float]] = []
    skipped: list[str] = []
    for g in gens:
        name = str(g.get("name") or "")
        if not name:
            continue
        carrier = str(g.get("carrier") or "")
        cl = carrier.lower()
        kind = "solar" if cl in solar_set else "wind" if cl in wind_set else classify(carrier)
        if kind is None:
            continue
        lat, lon = _coord(g, buses)
        if lat is None or lon is None:
            skipped.append(name)
            continue
        targets.append((name, kind, lat, lon))
    return targets, skipped


def build_profile_rows(
    targets: list[tuple[str, str, float, float]],
    point_by_key: dict[str, dict[str, Any]],
    performance_ratio: float = 0.9,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Assemble ``generators-p_max_pu`` rows attaching each target to its point.

    ``point_by_key`` maps :func:`point_key` → ``{"time", "ghi", "wind_ms"}``.
    Returns ``(rows, snapshots, attached_gen_names)``.
    """
    series: dict[str, list[float]] = {}
    times: list[str] = []
    for name, kind, lat, lon in targets:
        pt = point_by_key.get(point_key(lat, lon))
        if not pt:
            continue
        if not times and pt.get("time"):
            times = list(pt["time"])
        cf = solar_cf(pt.get("ghi") or [], performance_ratio) if kind == "solar" else wind_cf(pt.get("wind_ms") or [])
        if cf:
            series[name] = cf

    snapshots = [str(t).replace("T", " ") for t in times]
    rows: list[dict[str, Any]] = []
    for i, snap_label in enumerate(snapshots):
        row: dict[str, Any] = {"snapshot": snap_label}
        for name, cf in series.items():
            if i < len(cf):
                row[name] = round(cf[i], 4)
        rows.append(row)
    return rows, snapshots, list(series)


def merge_profile_rows(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge attached ``new`` p_max_pu rows into the session's ``existing`` rows,
    unioned by snapshot (new columns win). The browser has no server-side series,
    so the transform returns the COMPLETE sheet for a clean delete-all + re-add.
    """
    by_snap: dict[str, dict[str, Any]] = {}
    for r in [*existing, *new]:
        s = r.get("snapshot")
        if s is None:
            continue
        bucket = by_snap.setdefault(str(s), {"snapshot": str(s)})
        bucket.update({k: v for k, v in r.items() if k != "snapshot"})
    return [by_snap[s] for s in sorted(by_snap)]
