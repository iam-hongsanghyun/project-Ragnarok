"""Source health checks (D1) — is each upstream reachable right now?

One cheap probe URL per source (an API root or a stable endpoint that answers
without heavy work). A source is **reachable** when the probe answers with any
status below 500 — 401/403 mean "up, needs a key", which is healthy for a BYOK
source. Timeouts / connection errors / 5xx mean unreachable.

``GET /api/import/health`` runs every probe concurrently (bounded timeout) and
returns per-source ``{ok, status, latencyMs, checkedAt}`` — the Data view can
grey out sources whose upstream is down instead of failing on fetch.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx

_TIMEOUT_S = 6.0

# source_id → cheap probe URL. Roots/docs endpoints chosen to answer fast
# without auth-side effects; BYOK APIs return 401/403 (= reachable).
HEALTH_PROBES: dict[str, str] = {
    "osm": "https://overpass-api.de/api/status",
    "wri_gppd": "https://raw.githubusercontent.com/wri/global-power-plant-database/master/README.md",
    "worldbank": "https://api.worldbank.org/v2/country/KOR?format=json",
    "kpg193": "https://api.github.com/repos/kepco-research/KPG193",
    "eia": "https://api.eia.gov/v2/",
    "entsoe": "https://web-api.tp.entsoe.eu/api",
    "openelectricity": "https://api.openelectricity.org.au/v4/networks",
    "elexon": "https://data.elexon.co.uk/bmrs/api/v1/health",
    "renewables_ninja": "https://www.renewables.ninja/api/",
    "climatewatch": "https://www.climatewatchdata.org/api/v1/data/historical_emissions?page=1",
    "open_meteo": "https://archive-api.open-meteo.com/v1/archive",
    "pvgis": "https://re.jrc.ec.europa.eu/api/v5_2/seriescalc",
    "nasa_power": "https://power.larc.nasa.gov/api/temporal/hourly/point",
    "ember": "https://api.ember-energy.org/v1/options",
}


async def _probe(client: httpx.AsyncClient, source_id: str, url: str) -> tuple[str, dict[str, Any]]:
    started = time.perf_counter()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        resp = await client.get(url, follow_redirects=True)
        latency = round((time.perf_counter() - started) * 1000.0, 1)
        return source_id, {
            "ok": resp.status_code < 500,
            "status": resp.status_code,
            "latencyMs": latency,
            "checkedAt": checked_at,
        }
    except Exception as exc:  # noqa: BLE001 — every failure mode = unreachable
        latency = round((time.perf_counter() - started) * 1000.0, 1)
        return source_id, {
            "ok": False,
            "status": None,
            "error": type(exc).__name__,
            "latencyMs": latency,
            "checkedAt": checked_at,
        }


async def check_sources(source_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Probe the given sources (default: all known) concurrently."""
    targets = {
        sid: url for sid, url in HEALTH_PROBES.items()
        if source_ids is None or sid in source_ids
    }
    if not targets:
        return {}
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        results = await asyncio.gather(
            *(_probe(client, sid, url) for sid, url in targets.items())
        )
    return dict(results)
