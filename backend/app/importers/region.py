"""Country boundaries loader + ISO-A3 → polygon lookup.

We need two related things:

- A GeoJSON of country polygons the frontend renders on its Leaflet map so the
  user can click a country to select it.
- A way for each database module to resolve ``country_iso`` → ``shapely``
  polygon so it can clip the upstream dataset to the user's selection.

Both come from the same Natural Earth Admin-0 dataset (public domain). The
file is cached on disk under the configured boundaries directory; if absent
on startup, it is fetched once from the configured URL.

This module owns no business logic — just file I/O, caching, and a small
country index (ISO-A3 → name) extracted on first load.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from .protocol import Region

_log = logging.getLogger(__name__)


# ── Configuration (env-backed; no hardcoded URLs in source) ──────────────────


def _boundaries_path() -> Path:
    override = os.environ.get("RAGNAROK_BOUNDARIES_PATH")
    if override:
        return Path(override).expanduser().resolve()
    # backend/data/boundaries/countries.geojson — backend root is parents[2]
    return (
        Path(__file__).resolve().parents[2]
        / "data"
        / "boundaries"
        / "countries.geojson"
    )


def _boundaries_url() -> str:
    return os.environ.get(
        "RAGNAROK_BOUNDARIES_URL",
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector"
        "/master/geojson/ne_110m_admin_0_countries.geojson",
    )


# ── Loader ───────────────────────────────────────────────────────────────────


def _ensure_local_file() -> Path:
    """Ensure the boundaries GeoJSON is on disk; download once if missing."""
    target = _boundaries_path()
    if target.exists() and target.stat().st_size > 0:
        return target
    url = _boundaries_url()
    _log.info("downloading country boundaries from %s → %s", url, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"could not fetch country boundaries from {url}: {exc}. "
            "Set RAGNAROK_BOUNDARIES_PATH to a local Natural Earth Admin-0 "
            "GeoJSON to bypass the network fetch."
        ) from exc
    target.write_bytes(data)
    return target


@lru_cache(maxsize=1)
def _load_geojson() -> dict[str, Any]:
    path = _ensure_local_file()
    with path.open() as f:
        gj: dict[str, Any] = json.load(f)
    if gj.get("type") != "FeatureCollection":
        raise RuntimeError(
            f"boundaries file at {path} is not a FeatureCollection"
        )
    return gj


# Natural Earth uses ``ADM0_A3`` for ISO-3166-1 alpha-3 and ``ADMIN`` /
# ``NAME`` for the country name. We accept either, with fallbacks, so the
# loader tolerates equivalent admin layers (e.g. ``ISO_A3`` from older
# releases).
_ISO_KEYS = ("ADM0_A3", "ISO_A3_EH", "ISO_A3", "SOV_A3")
_NAME_KEYS = ("ADMIN", "NAME", "NAME_LONG", "SOVEREIGNT")


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
    """``{ISO_A3: {name, polygon, bbox, centroid}}`` lazily computed."""
    gj = _load_geojson()
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
        except Exception as exc:  # noqa: BLE001
            _log.warning("skipping %s — bad geometry: %s", iso, exc)
            continue
        out[iso] = {
            "name": _feature_name(props),
            "polygon": polygon,
            "bbox": tuple(float(v) for v in polygon.bounds),
            "centroid": (float(polygon.centroid.x), float(polygon.centroid.y)),
        }
    if not out:
        raise RuntimeError("country boundaries file produced an empty index")
    return out


# ── Public API ───────────────────────────────────────────────────────────────


def country_list() -> list[dict[str, Any]]:
    """JSON-serialisable list of ``{iso, name, bbox, centroid}``."""
    idx = _country_index()
    return [
        {
            "iso": iso,
            "name": entry["name"],
            "bbox": list(entry["bbox"]),
            "centroid": list(entry["centroid"]),
        }
        for iso, entry in sorted(idx.items(), key=lambda kv: kv[1]["name"])
    ]


def get_region(country_iso: str) -> Region:
    iso = country_iso.strip().upper()
    entry = _country_index().get(iso)
    if entry is None:
        raise KeyError(f"unknown country ISO-A3: {country_iso!r}")
    return Region(country_iso=iso, country_name=entry["name"], polygon=entry["polygon"])


def boundaries_geojson_bytes() -> bytes:
    """Return the raw GeoJSON bytes for the frontend basemap layer."""
    path = _ensure_local_file()
    return path.read_bytes()


def reset_cache() -> None:
    """Drop in-memory caches (used by tests)."""
    _load_geojson.cache_clear()
    _country_index.cache_clear()
