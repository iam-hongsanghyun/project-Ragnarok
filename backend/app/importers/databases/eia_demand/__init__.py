"""EIA hourly electricity demand (US) — the BYOK exemplar.

US balancing-authority hourly demand from the EIA v2 API (Form-930).
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
from datetime import datetime, timezone
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

# A pragmatic subset of the larger US balancing authorities. The full list
# is ~60; these cover most of the load. (Respondent codes per EIA-930.)
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
        "Hourly electricity demand by US balancing authority from the EIA "
        "v2 API. Lands as one Load row plus an hourly loads-p_set series. "
        "Needs a free EIA API key (Settings → API keys)."
    ),
    targets=["loads"],
    country_coverage=["USA"],
    requires_secrets=["eia_key"],
    filters=[
        Filter(
            id="balancing_authority", label="Balancing authority", kind="select",
            default="PJM",
            options=[{"value": code, "label": f"{code} — {name}"}
                     for code, name in _BALANCING_AUTHORITIES],
            description="Which US balancing authority's hourly demand to pull.",
        ),
        Filter(id="date_from", label="From", kind="date", default="2023-01-01",
               min="2015-07-01", max="2025-12-31",
               description="Start of the hourly window (inclusive)."),
        Filter(id="date_to", label="To", kind="date", default="2023-01-07",
               min="2015-07-01", max="2025-12-31",
               description="End of the hourly window (inclusive). Keep it short — hourly data is large."),
    ],
)


class EiaDemand:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        # BYOK: this raises PermissionError (→ HTTP 400 with an actionable
        # message) when the user hasn't entered their key.
        api_key = ctx.require_secret("eia_key")
        ba = str(filters.get("balancing_authority") or "PJM")
        date_from = str(filters.get("date_from") or "2023-01-01")
        date_to = str(filters.get("date_to") or "2023-01-07")
        params = {
            "api_key": api_key,
            "frequency": "hourly",
            "data[0]": "value",
            "facets[type][]": "D",            # D = demand
            "facets[respondent][]": ba,
            "start": f"{date_from}T00",
            "end": f"{date_to}T23",
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": 5000,
        }
        body = await ctx.http.get_json(_API_URL, params=params)
        rows = (((body or {}).get("response") or {}).get("data")) or []
        return FetchResult(META.id, region, dict(filters),
                           {"ba": ba, "rows": rows, "date_from": date_from, "date_to": date_to})

    def preview(self, result: FetchResult) -> PreviewSummary:
        rows = result.payload["rows"]
        ba = result.payload["ba"]
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
            notes=[f"{ba}: {len(rows)} hourly points "
                   f"{result.payload['date_from']} → {result.payload['date_to']}."],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        rows = result.payload["rows"]
        ba = result.payload["ba"]
        frag = WorkbookFragment()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        load_name = _slug(f"{ba}_demand", "load")

        snapshots: list[str] = []
        p_set_rows: list[dict[str, Any]] = []
        for r in rows:
            period = r.get("period")  # e.g. "2023-01-01T00"
            value = r.get("value")
            if period is None or value in (None, ""):
                continue
            snap = str(period).replace("T", " ") + ":00"  # → "YYYY-MM-DD HH:00"
            snapshots.append(snap)
            p_set_rows.append({"snapshot": snap, load_name: float(value)})

        if p_set_rows:
            frag.sheets["loads"] = [{
                "name": load_name, "carrier": "AC", "country": "USA",
                "source": "EIA Form-930", "balancing_authority": ba,
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
