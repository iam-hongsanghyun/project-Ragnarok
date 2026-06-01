"""Country boundaries — ISO-A3 → shapely polygon, the country list for the
map search, and the raw GeoJSON the frontend renders.

Source: Natural Earth 50m Admin-0 (public domain), the same dataset the
browser importer used. Fetched once from a CORS-irrelevant raw GitHub
URL (this is server-side now) and cached: on disk under the cache dir
and in memory for the process. Bumping ``RAGNAROK_BOUNDARIES_URL`` or
deleting the cache file re-fetches.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from .protocol import Region


_DEFAULT_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector"
    "/master/geojson/ne_50m_admin_0_countries.geojson"
)

_ISO_KEYS = ("ADM0_A3", "ISO_A3_EH", "ISO_A3", "SOV_A3")
_NAME_KEYS = ("ADMIN", "NAME", "NAME_LONG", "SOVEREIGNT")


def _boundaries_url() -> str:
    return os.environ.get("RAGNAROK_BOUNDARIES_URL", _DEFAULT_URL)


def _cache_dir() -> Path:
    base = os.environ.get("RAGNAROK_CACHE_DIR")
    if base:
        return Path(base).expanduser()
    # Default under backend/data/cache/ (gitignored).
    return Path(__file__).resolve().parents[2] / "data" / "cache"


def _cache_path() -> Path:
    return _cache_dir() / "ne_50m_admin_0_countries.geojson"


async def ensure_boundaries(http: Any) -> bytes:
    """Return the boundaries GeoJSON bytes, fetching + caching on first use.

    ``http`` is the request's AsyncClientWrapper. Subsequent calls read
    the on-disk cache.
    """
    path = _cache_path()
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    data = await http.get_bytes(_boundaries_url())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _load_geojson_from_disk() -> dict[str, Any]:
    path = _cache_path()
    if not (path.exists() and path.stat().st_size > 0):
        raise RuntimeError(
            "country boundaries not cached yet; the first importer fetch "
            "downloads them. (Set RAGNAROK_BOUNDARIES_URL or pre-warm the "
            "cache if running offline.)"
        )
    return json.loads(path.read_text())


def _feature_iso(props: dict[str, Any]) -> str | None:
    for k in _ISO_KEYS:
        v = props.get(k)
        if isinstance(v, str) and v and v != "-99":
            return v.upper()
    return None


def _feature_name(props: dict[str, Any]) -> str:
    for k in _NAME_KEYS:
        v = props.get(k)
        if isinstance(v, str) and v:
            return v
    return "(unknown)"


@lru_cache(maxsize=1)
def _country_index() -> dict[str, dict[str, Any]]:
    gj = _load_geojson_from_disk()
    out: dict[str, dict[str, Any]] = {}
    for feature in gj.get("features", []):
        props = feature.get("properties") or {}
        iso = _feature_iso(props)
        if not iso:
            continue
        geom = feature.get("geometry")
        if not geom:
            continue
        try:
            polygon: BaseGeometry = shape(geom)
        except Exception:  # noqa: BLE001
            continue
        out[iso] = {
            "name": _feature_name(props),
            "polygon": polygon,
            "bbox": tuple(float(v) for v in polygon.bounds),
            "centroid": (float(polygon.centroid.x), float(polygon.centroid.y)),
        }
    if not out:
        raise RuntimeError("country boundaries produced an empty index")
    return out


def country_list() -> list[dict[str, Any]]:
    """``[{iso, name, bbox, centroid}]`` for the map search box."""
    idx = _country_index()
    return [
        {
            "iso": iso,
            "name": e["name"],
            "bbox": list(e["bbox"]),
            "centroid": list(e["centroid"]),
        }
        for iso, e in sorted(idx.items(), key=lambda kv: kv[1]["name"])
    ]


def get_region(country_iso: str) -> Region:
    iso = country_iso.strip().upper()
    entry = _country_index().get(iso)
    if entry is None:
        raise KeyError(f"unknown country ISO-A3: {country_iso!r}")
    return Region(country_iso=iso, country_name=entry["name"], polygon=entry["polygon"])


def boundaries_geojson_bytes() -> bytes:
    """Raw GeoJSON bytes for the frontend basemap layer (cached on disk)."""
    return _cache_path().read_bytes()


def reset_cache() -> None:
    _country_index.cache_clear()
