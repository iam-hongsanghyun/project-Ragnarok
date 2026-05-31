"""Overpass query builder + HTTP client.

The Overpass endpoint is rate-limited (typical public mirrors return 429 /
504 under load); we wrap the call with exponential backoff and surface a
clear error to the caller after a small number of retries.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from shapely.geometry import Polygon, MultiPolygon
from shapely.geometry.base import BaseGeometry

_log = logging.getLogger(__name__)

_DEFAULT_URL = "https://overpass-api.de/api/interpreter"
_DEFAULT_TIMEOUT = 180  # seconds (server-side)
_DEFAULT_RETRY = 3


def overpass_url() -> str:
    return os.environ.get("RAGNAROK_OVERPASS_URL", _DEFAULT_URL)


def _polygon_rings(geom: BaseGeometry) -> list[list[tuple[float, float]]]:
    """Return exterior rings of a (Multi)Polygon as ``[[(lat, lon), …], …]``."""
    rings: list[list[tuple[float, float]]] = []
    if isinstance(geom, Polygon):
        polys: Iterable[Polygon] = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    else:
        raise TypeError(f"Unsupported geometry type for Overpass: {type(geom).__name__}")
    for p in polys:
        # Overpass expects "lat lon" pairs.
        coords = [(float(y), float(x)) for x, y in p.exterior.coords]
        if len(coords) >= 3:
            rings.append(coords)
    return rings


def _poly_filter(geom: BaseGeometry) -> str:
    """Build an Overpass ``poly:"lat lon …"`` clause from a (Multi)Polygon.

    Overpass only accepts a single polygon per filter, so for MultiPolygon we
    take the largest ring (good-enough for country shapes; sliver islands
    that fall outside it are filtered by point-in-polygon afterwards anyway).
    """
    rings = _polygon_rings(geom)
    if not rings:
        raise ValueError("region polygon has no exterior ring")
    best = max(rings, key=len)
    return " ".join(f"{lat} {lon}" for lat, lon in best)


def build_query(
    geom: BaseGeometry,
    *,
    include_cables: bool,
    include_dc: bool,
    min_voltage_v: int,
    timeout: int = _DEFAULT_TIMEOUT,
) -> str:
    """Return the Overpass-QL string for the given filters."""
    poly = _poly_filter(geom)
    # Tag-presence filter (``["voltage"]`` alone) is enough — voltage normalisation
    # and the user's min_voltage threshold are re-applied client-side after parse.
    voltage_filter = '["voltage"]'
    # HVDC opt-out: dropping lines where ``frequency`` is explicitly "0".
    dc_clause = "" if include_dc else '["frequency"!="0"]'
    lines = [
        f'way["power"="line"]{voltage_filter}{dc_clause}(poly:"{poly}");',
    ]
    if include_cables:
        lines.append(
            f'way["power"="cable"]{voltage_filter}{dc_clause}(poly:"{poly}");'
        )
    lines.append(f'node["power"="substation"](poly:"{poly}");')
    lines.append(f'way["power"="substation"](poly:"{poly}");')
    body = "".join(lines)
    return (
        f"[out:json][timeout:{timeout}];"
        f"({body});"
        "out body geom;"
    )


# ── HTTP ─────────────────────────────────────────────────────────────────────


class OverpassError(RuntimeError):
    """Raised when Overpass returns an error or is unreachable."""


def post_query(
    query: str,
    *,
    url: str | None = None,
    retries: int = _DEFAULT_RETRY,
    sleep: float = 2.0,
) -> dict[str, Any]:
    """POST a query to Overpass, retrying on 429 / 504."""
    target = url or overpass_url()
    data = urllib.parse.urlencode({"data": query}).encode()
    last_exc: Exception | None = None
    headers = {
        # Overpass main mirror returns 406 to requests without a User-Agent
        # header (default urllib UA is blocked). Identify ourselves so the
        # operator can contact us if a query misbehaves.
        "User-Agent": os.environ.get(
            "RAGNAROK_OVERPASS_UA", "Ragnarok/0.1 (+https://github.com/PyPSA/PyPSA)"
        ),
        "Accept": "application/json",
    }
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                target, data=data, method="POST", headers=headers
            )
            with urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT + 60) as resp:
                body = resp.read()
            return json.loads(body)
        except urllib.error.HTTPError as exc:  # noqa: PERF203
            last_exc = exc
            if exc.code in (429, 502, 503, 504) and attempt < retries:
                _log.warning(
                    "Overpass %s on attempt %d/%d — sleeping %.1fs",
                    exc.code,
                    attempt,
                    retries,
                    sleep * attempt,
                )
                time.sleep(sleep * attempt)
                continue
            raise OverpassError(f"Overpass HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(sleep * attempt)
                continue
            raise OverpassError(f"Overpass unreachable: {exc.reason}") from exc
    if last_exc is not None:
        raise OverpassError(str(last_exc))
    raise OverpassError("Overpass request failed for an unknown reason")
