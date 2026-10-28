"""``/api/demand-db/*`` - read access to the self-hosted hourly demand snapshot (D2).

  GET /api/demand-db/coverage  - manifest view: sources (measure, licence), slices, years, hashes
  GET /api/demand-db/slice     - one series for a year window (compact column arrays)

Reads only the local snapshot built by ``python -m backend.app.importers.demand_db.refresh``;
no upstream call is ever made here. Putting a slice into a model goes through the normal
importer (``POST /api/import/run`` with dataset id ``demand_db``).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..importers.demand_db import parsers, store

router = APIRouter(prefix="/api/demand-db", tags=["demand-db"])

MAX_YEARS = 12


@router.get("/coverage")
def demand_db_coverage() -> dict[str, Any]:
    """Which series / years the snapshot holds, with licences and definitions."""
    return store.coverage()


@router.get("/slice")
def demand_db_slice(
    series: str | None = Query(None, description="'<source>/<area>' key from /coverage, e.g. 'opsd/DE'"),
    country: str | None = Query(None, description="ISO-3 country; picks the best national series when 'series' is omitted"),
    year_from: int = Query(2019, ge=1990, le=2100),
    year_to: int | None = Query(None, ge=1990, le=2100),
) -> dict[str, Any]:
    """Hourly load of one series for ``year_from..year_to`` (UTC years): MW, UTC, hour-beginning."""
    y1 = year_from if year_to is None else year_to
    if y1 < year_from:
        raise HTTPException(status_code=400, detail="year_to is before year_from")
    if y1 - year_from + 1 > MAX_YEARS:
        raise HTTPException(status_code=400, detail=f"at most {MAX_YEARS} years per request")
    if not series and not country:
        raise HTTPException(status_code=400, detail="give 'series' or 'country'")
    try:
        key = store.resolve_key(series, country, year_from, y1)
        df = store.read_slice(key, year_from, y1)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    entry = store.load_manifest()["slices"][key]
    return {
        "series": key,
        "label": entry.get("label"),
        "unit": "MW",
        "timezone": "UTC",
        "timestamp_convention": "hour-beginning",
        "measure": entry.get("measure"),
        "licence": entry.get("licence"),
        "attribution": entry.get("attribution"),
        "source_urls": [r.get("url") for r in entry.get("raw_files", [])],
        "retrieved_at": entry.get("retrieved_at"),
        "year_from": year_from,
        "year_to": y1,
        "stats": parsers.summary_stats(df),
        "timestamps": [t.strftime("%Y-%m-%dT%H:00:00Z") for t in df["timestamp"]],
        "load_mw": [round(float(v), 3) for v in df["load_mw"]],
    }
