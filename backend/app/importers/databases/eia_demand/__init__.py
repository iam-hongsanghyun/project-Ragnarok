"""EIA hourly electricity demand (US) — the BYOK exemplar.

US hourly demand from the EIA v2 API (Form-930 / Hourly Electric Grid
Monitor). The data is collected per balancing authority (sub-national
operational regions, not states); EIA also publishes 13 regional
aggregates and a US48 national total. The ``respondent`` filter lets the
user pick the granularity — national, region, or balancing authority —
and ``date_from`` / ``date_to`` set the window.

Requires a free per-user API key (``eia_key``): the user enters it in
Settings → API keys, the frontend ships it in the request body, and we
use it here for this one request via ``ctx.require_secret('eia_key')`` —
never persisted, never logged.

This is the reference implementation of the BYOK pattern: every future
key-gated source follows the same shape. Coverage is USA only.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ...context import ImportContext
from ...protocol import (
    ConvertOptions,
    Database,
    DatabaseMeta,
    FetchResult,
    Filter,
    PreviewSummary,
    Provenance,
    Region,
    WorkbookFragment,
)

_API_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")

# EIA-930 collects hourly demand per *balancing authority* (sub-national
# operational regions — not states). The same region-data `respondent` facet
# also serves EIA's aggregates: a single US48 national total and 13 regional
# rollups. We expose all three granularities so the user picks how coarse the
# series should be. (Codes per the EIA Hourly Electric Grid Monitor.)
_NATIONAL: list[tuple[str, str]] = [
    ("US48", "Lower 48 states"),
]
_REGIONS: list[tuple[str, str]] = [
    ("CAL", "California"),
    ("CAR", "Carolinas"),
    ("CENT", "Central"),
    ("FLA", "Florida"),
    ("MIDA", "Mid-Atlantic"),
    ("MIDW", "Midwest"),
    ("NE", "New England"),
    ("NW", "Northwest"),
    ("NY", "New York"),
    ("SE", "Southeast"),
    ("SW", "Southwest"),
    ("TEN", "Tennessee"),
    ("TEX", "Texas"),
]
# A pragmatic subset of the ~65 balancing authorities — these carry most of
# the load. The respondent codes are the full list's identifiers.
_BALANCING_AUTHORITIES: list[tuple[str, str]] = [
    ("PJM", "PJM Interconnection"),
    ("MISO", "Midcontinent ISO"),
    ("CISO", "California ISO"),
    ("ERCO", "ERCOT (Texas)"),
    ("SWPP", "Southwest Power Pool"),
    ("NYIS", "New York ISO"),
    ("ISNE", "ISO New England"),
    ("FPL", "Florida Power & Light"),
    ("SOCO", "Southern Company"),
    ("TVA", "Tennessee Valley Authority"),
    ("DUK", "Duke Energy Carolinas"),
    ("BPAT", "Bonneville Power Administration"),
]

# code → (granularity level, full name) for labels, preview, and provenance.
_RESPONDENT_INFO: dict[str, tuple[str, str]] = {
    **{c: ("national", n) for c, n in _NATIONAL},
    **{c: ("region", n) for c, n in _REGIONS},
    **{c: ("balancing authority", n) for c, n in _BALANCING_AUTHORITIES},
}


def _respondent_options() -> list[dict[str, str]]:
    """Build the single granularity-aware select: national, then regions,
    then balancing authorities — each labelled with its level."""
    out: list[dict[str, str]] = []
    for code, name in _NATIONAL:
        out.append({"value": code, "label": f"{code} — {name} (national)"})
    for code, name in _REGIONS:
        out.append({"value": code, "label": f"{code} — {name} (region)"})
    for code, name in _BALANCING_AUTHORITIES:
        out.append({"value": code, "label": f"{code} — {name} (balancing authority)"})
    return out


def _slug(raw: str | None, fallback: str = "load") -> str:
    if not raw:
        return fallback
    s = _NAME_RE.sub("_", str(raw).strip()).strip("_")
    return s or fallback


META = DatabaseMeta(
    id="eia_demand",
    name="EIA — US hourly electricity demand (Form-930)",
    short_name="EIA demand",
    category="demand",
    subcategory="Hourly profiles",
    license="Public domain (US EIA)",
    homepage="https://www.eia.gov/opendata/",
    version_hint="v2 API",
    description=(
        "Hourly US electricity demand from the EIA Hourly Electric Grid "
        "Monitor (Form-930) v2 API. Choose the granularity — national (US48), "
        "one of the 13 regional aggregates, or an individual balancing "
        "authority — and the date window. Lands as one Load row plus an hourly "
        "loads-p_set series. Needs a free EIA API key (Settings → API keys)."
    ),
    targets=["buses", "loads", "loads-p_set", "carriers"],
    country_coverage=["USA"],
    requires_secrets=["eia_key"],
    filters=[
        Filter(
            id="respondent", label="Granularity / coverage area", kind="select",
            default="US48",
            options=_respondent_options(),
            description=(
                "Which EIA-930 demand series to pull. The data is collected per "
                "balancing authority (sub-national operational regions, not "
                "states); EIA also publishes 13 regional aggregates and a US48 "
                "national total. Pick the granularity: national, region, or "
                "balancing authority."
            ),
        ),
        Filter(id="date_from", label="From", kind="date", default="2023-01-01",
               min="2015-07-01", max="2025-12-31",
               description="Start of the hourly window (inclusive)."),
        Filter(id="date_to", label="To", kind="date", default="2023-01-07",
               min="2015-07-01", max="2025-12-31",
               description="End of the hourly window (inclusive). Keep it short — hourly data is large."),
    ],
)


# RI4: EIA ``period`` is HOUR-ENDING, in UTC. Evidence (checked 2026-10-28):
#  * https://api.eia.gov/v2/electricity/rto/region-data (route metadata, EIA API v2): frequency "hourly"
#    = "One data point for each hour in UTC time." (``YYYY-MM-DD"T"HH24``); source "Form EIA-930".
#  * EIA-930 bulk files (https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/, EIA930_BALANCE_*.csv)
#    label every hour "Local Time at End of Hour" / "UTC Time at End of Hour".
#  * The same value appears under the same instant in both: AECI demand 2495 MW is the bulk row with
#    "UTC Time at End of Hour = 01/01/2023 7:00:00 AM" and the API row ``period = 2023-01-01T07``.
# So ``period = T07`` covers 06:00-07:00 UTC. PyPSA snapshots are interval-start labels (weight = the
# hour that follows), so every period is shifted back one hour on import.
_HOUR_ENDING_SHIFT = timedelta(hours=1)


def _hour_beginning_label(period: str) -> str:
    """EIA hour-ending UTC ``period`` (``YYYY-MM-DDTHH``) -> hour-beginning ``YYYY-MM-DD HH:00``."""
    t = datetime.strptime(str(period)[:13], "%Y-%m-%dT%H") - _HOUR_ENDING_SHIFT
    return t.strftime("%Y-%m-%d %H:00")


def _period_window(date_from: str, date_to: str) -> tuple[str, str]:
    """API ``start``/``end`` (hour-ending) that yield hour-beginning snapshots 00:00 of
    ``date_from`` .. 23:00 of ``date_to``: periods ``date_fromT01`` .. ``(date_to+1)T00``."""
    d1 = date.fromisoformat(date_to) + timedelta(days=1)
    return f"{date_from}T01", f"{d1.isoformat()}T00"


_PAGE = 5000  # EIA v2 caps ``length`` at 5000 rows per response
_MAX_PAGES = 100


async def _fetch_all_rows(ctx: ImportContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Page the EIA v2 endpoint with ``offset`` until ``response.total`` rows
    are read (a page that comes back short or empty also ends the loop when
    ``total`` is missing). A single request silently truncates at 5000 rows —
    under a year of hourly data."""
    rows: list[dict[str, Any]] = []
    total: int | None = None
    for page in range(_MAX_PAGES):
        body = await ctx.http.get_json(_API_URL, params={**params, "offset": page * _PAGE})
        resp = (body or {}).get("response") or {}
        data = resp.get("data") or []
        if total is None:
            try:
                total = int(resp.get("total"))
            except (TypeError, ValueError):
                total = None
        rows.extend(data)
        if not data:
            break
        if total is not None:
            if len(rows) >= total:
                break
        elif len(data) < _PAGE:
            break
    else:
        raise RuntimeError(f"EIA: more than {_MAX_PAGES * _PAGE} rows; narrow the date window.")
    if total is not None and len(rows) < total:
        raise RuntimeError(f"EIA returned {len(rows)} of {total} rows; retry.")
    return rows


class EiaDemand:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        # BYOK: this raises PermissionError (→ HTTP 400 with an actionable
        # message) when the user hasn't entered their key.
        api_key = ctx.require_secret("eia_key")
        # Accept the new `respondent` id; fall back to the old
        # `balancing_authority` for any stale client form state.
        respondent = str(
            filters.get("respondent")
            or filters.get("balancing_authority")
            or "US48"
        )
        date_from = str(filters.get("date_from") or "2023-01-01")
        date_to = str(filters.get("date_to") or "2023-01-07")
        start, end = _period_window(date_from, date_to)
        params = {
            "api_key": api_key,
            "frequency": "hourly",
            "data[0]": "value",
            "facets[type][]": "D",            # D = demand
            "facets[respondent][]": respondent,
            "start": start,
            "end": end,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": 5000,
        }
        rows = await _fetch_all_rows(ctx, params)
        return FetchResult(META.id, region, dict(filters),
                           {"respondent": respondent, "rows": rows,
                            "date_from": date_from, "date_to": date_to})

    def preview(self, result: FetchResult) -> PreviewSummary:
        rows = result.payload["rows"]
        respondent = result.payload["respondent"]
        level, name = _RESPONDENT_INFO.get(respondent, ("balancing authority", respondent))
        vals = [float(r["value"]) for r in rows if r.get("value") not in (None, "")]
        counts: dict[str, int] = {"loads": 1 if rows else 0, "hours": len(rows)}
        if vals:
            counts["peak_mw"] = int(round(max(vals)))
            counts["mean_mw"] = int(round(sum(vals) / len(vals)))
        return PreviewSummary(
            counts=counts,
            samples={"hours": [
                {"period": r.get("period"), "value": r.get("value")}
                for r in rows[:24]
            ]},
            notes=[f"{name} ({respondent}, {level}): {len(rows)} hourly points "
                   f"{result.payload['date_from']} → {result.payload['date_to']}."],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        rows = result.payload["rows"]
        respondent = result.payload["respondent"]
        level, name = _RESPONDENT_INFO.get(respondent, ("balancing authority", respondent))
        frag = WorkbookFragment()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        load_name = _slug(f"{respondent}_demand", "load")

        snapshots: list[str] = []
        p_set_rows: list[dict[str, Any]] = []
        for r in rows:
            period = r.get("period")  # e.g. "2023-01-01T00"
            value = r.get("value")
            if period is None or value in (None, ""):
                continue
            snap = _hour_beginning_label(period)  # hour-ending UTC → hour-beginning (RI4)
            snapshots.append(snap)
            p_set_rows.append({"snapshot": snap, load_name: float(value)})

        if p_set_rows:
            # Self-contained PyPSA model: a single national bus the load sits
            # on (PyPSA Load requires a bus). Placed at the region centroid so
            # it lands on the map.
            bus_name = _slug(respondent, "bus")
            try:
                c = result.region.polygon.centroid
                bx, by = float(c.x), float(c.y)
            except Exception:
                bx, by = "", ""
            frag.sheets["carriers"] = [{"name": "AC"}]
            frag.sheets["buses"] = [{
                "name": bus_name, "x": bx, "y": by, "carrier": "AC",
                "country": "USA", "source": "EIA Form-930",
            }]
            frag.sheets["loads"] = [{
                "name": load_name, "bus": bus_name, "carrier": "AC",
                "country": "USA", "source": "EIA Form-930",
                "respondent": respondent, "respondent_level": level,
                "respondent_name": name,
            }]
            frag.sheets["loads-p_set"] = p_set_rows
            frag.snapshots = snapshots

        row_counts = {s: len(r) for s, r in frag.sheets.items()}
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            ts, json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return EiaDemand()
