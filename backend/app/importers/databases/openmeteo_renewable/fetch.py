"""Shared point fetch — one cached call per (source, point) → weather arrays.

Dispatches to a source adapter in :mod:`.sources` and caches the normalised
result. Used by both the region importer and the attach-to-fleet transform, so
caching, source selection, and units live in one place. Returns
``{"time": [...], "ghi": [W/m²], "wind_ms": [m/s @100m]}``.
"""
from __future__ import annotations

from typing import Any

from . import cache
from .sources import DEFAULT_SOURCE, SOURCES


async def fetch_point(
    http: Any,
    lat: float,
    lon: float,
    date_from: str,
    date_to: str,
    source: str = DEFAULT_SOURCE,
    secret: str | None = None,
) -> dict[str, Any]:
    """Fetch one point's hourly GHI + hub-height wind from ``source``, cached.

    Coordinates snap to the cache grid so the cached data matches its key and
    nearby generators share a call. Unknown sources fall back to the default.
    """
    adapter = SOURCES.get(source) or SOURCES[DEFAULT_SOURCE]
    src_id = source if source in SOURCES else DEFAULT_SOURCE

    glat, glon = cache.snap(lat), cache.snap(lon)
    key = cache.cache_key(glat, glon, date_from, date_to, src_id)
    hit = cache.get(key)
    if hit is not None:
        return hit

    result = await adapter(http, glat, glon, date_from, date_to, secret)
    # Only cache non-empty results (a transient upstream failure shouldn't stick).
    if result.get("time"):
        cache.put(key, result)
    return result
