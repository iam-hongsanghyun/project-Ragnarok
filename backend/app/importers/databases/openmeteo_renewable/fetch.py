"""Shared Open-Meteo point fetch — one cached call → ready-to-convert arrays.

Used by both the region-based importer (``__init__.py``) and the attach-to-fleet
transform, so the caching, unit handling, and GHI-fallback live in one place.
Returns ``{"time": [...], "ghi": [W/m²], "wind_ms": [m/s]}`` for a single point.
"""
from __future__ import annotations

from typing import Any

from . import cache
from .conversion import combined_ghi

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# GHI components (shortwave is occasionally null for recent dates → fall back to
# direct+diffuse) plus 100 m (hub-height) wind speed.
HOURLY_VARS = "shortwave_radiation,direct_radiation,diffuse_radiation,wind_speed_100m"


async def fetch_point(
    http: Any, lat: float, lon: float, date_from: str, date_to: str
) -> dict[str, Any]:
    """Fetch one point's hourly GHI + hub-height wind, cached on disk.

    Coordinates snap to the cache grid before the request so the cached data
    matches its key and nearby generators share a call. ``http`` is an
    ``AsyncClientWrapper`` (``get_json``).
    """
    glat, glon = cache.snap(lat), cache.snap(lon)
    key = cache.cache_key(glat, glon, date_from, date_to, HOURLY_VARS)
    hit = cache.get(key)
    if hit is not None:
        return hit

    params = {
        "latitude": glat,
        "longitude": glon,
        "start_date": date_from,
        "end_date": date_to,
        "hourly": HOURLY_VARS,
        "wind_speed_unit": "ms",  # API defaults to km/h
        "timezone": "UTC",
    }
    body = await http.get_json(ARCHIVE_URL, params=params)
    hourly = (body or {}).get("hourly") or {}
    result = {
        "time": list(hourly.get("time") or []),
        "ghi": combined_ghi(
            hourly.get("shortwave_radiation"),
            hourly.get("direct_radiation"),
            hourly.get("diffuse_radiation"),
        ),
        "wind_ms": list(hourly.get("wind_speed_100m") or []),
    }
    cache.put(key, result)
    return result
