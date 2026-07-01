"""On-disk cache for Open-Meteo point fetches (D1 caching slice).

The ERA5 historical archive is immutable, so a fetch keyed by (rounded
coordinate, date range, variables) can be cached indefinitely — turning a
full-year × many-generator attach from hundreds of network round-trips into a
one-time cost. Coordinates are snapped to a 0.1° grid (~11 km; ERA5's native
resolution is ~0.25°) so nearby generators share a cache entry and an API call.

The cache directory is ``RAGNAROK_WEATHER_CACHE`` (default
``backend/data/cache/openmeteo/``). All filesystem access is best-effort: a
missing / unwritable / corrupt cache silently degrades to a live fetch, never an
error.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

# backend/data/cache/openmeteo — parents[4] is the backend/ root.
_DEFAULT_DIR = Path(__file__).resolve().parents[4] / "data" / "cache" / "openmeteo"

# Coordinate snap grid (degrees). 0.1° ≈ 11 km; ERA5 is ~0.25° native.
GRID_DEG = 0.1


def snap(coord: float) -> float:
    """Snap a lat/lon to the cache grid so nearby points reuse one entry."""
    return round(round(float(coord) / GRID_DEG) * GRID_DEG, 4)


def _dir() -> Path:
    return Path(os.environ.get("RAGNAROK_WEATHER_CACHE", str(_DEFAULT_DIR)))


def cache_key(lat: float, lon: float, date_from: str, date_to: str, variables: str) -> str:
    raw = f"{snap(lat)}|{snap(lon)}|{date_from}|{date_to}|{variables}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def get(key: str) -> dict[str, Any] | None:
    try:
        p = _dir() / f"{key}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a broken cache must never break a fetch
        return None
    return None


def put(key: str, value: dict[str, Any]) -> None:
    try:
        d = _dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{key}.json").write_text(json.dumps(value), encoding="utf-8")
    except Exception:  # noqa: BLE001 — caching is best-effort
        pass
