"""Ember — monthly electricity generation by fuel (BYOK).

Country-by-month generation per fuel from the Ember Data API
(``api.ember-energy.org``), the open (CC-BY) successor to the Ember data
explorer downloads. This is Ragnarok's **calibration** source (I7): compare a
model's carrier mix against what the country actually generated — a cheap
sanity check that catches order-of-magnitude errors — or use it as a fallback
when hourly data is unavailable.

Request shape (Ember API v1):

    GET /v1/electricity-generation/monthly
        ?entity_code=<ISO3>&is_aggregate_series=false
        &start_date=YYYY-MM&end_date=YYYY-MM&api_key=<key>

The response is JSON ``{"data": [{entity_code, date, series, generation_twh,
share_of_generation_pct, …}, …]}``. Fuel names are mapped onto Ragnarok's
carrier vocabulary. Lands as one informational ``generation_history`` sheet
(month × carrier rows, GWh + share) — reference data, not solver input.

Requires a free per-user API key (``ember_key``): register on
ember-energy.org/data/api, then paste the key in Settings → API keys.
"""
from __future__ import annotations

import json
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

_API_URL = "https://api.ember-energy.org/v1/electricity-generation/monthly"

# Ember fuel names → Ragnarok carrier vocabulary (the names the other
# importers and the analytics carrier registry use).
FUEL_CARRIER: dict[str, str] = {
    "bioenergy": "biomass",
    "coal": "coal",
    "gas": "gas",
    "hydro": "hydro",
    "nuclear": "nuclear",
    "other fossil": "oil",
    "other renewables": "other_renewable",
    "solar": "solar",
    "wind": "wind",
}


def map_fuel(series: str) -> str:
    """Ember fuel label → Ragnarok carrier (lowercased passthrough if unknown)."""
    key = str(series or "").strip().lower()
    return FUEL_CARRIER.get(key, key.replace(" ", "_") or "unknown")


def rows_from_payload(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ember API records → ``generation_history`` sheet rows (GWh, sorted)."""
    out: list[dict[str, Any]] = []
    for rec in data or []:
        date = str(rec.get("date", "")).strip()
        series = rec.get("series")
        twh = rec.get("generation_twh")
        if not date or series is None or twh is None:
            continue
        try:
            gwh = float(twh) * 1000.0
        except (TypeError, ValueError):
            continue
        row: dict[str, Any] = {
            "snapshot": date,  # YYYY-MM month key
            "carrier": map_fuel(str(series)),
            "generation_gwh": round(gwh, 3),
            "source": "Ember",
        }
        share = rec.get("share_of_generation_pct")
        try:
            if share is not None:
                row["share_pct"] = round(float(share), 3)
        except (TypeError, ValueError):
            pass
        out.append(row)
    out.sort(key=lambda r: (r["snapshot"], r["carrier"]))
    return out


META = DatabaseMeta(
    id="ember_history",
    name="Ember — monthly generation by fuel (calibration history)",
    short_name="Generation history",
    source_id="ember",
    source_label="Ember",
    category="history",
    subcategory="Calibration",
    license="CC-BY 4.0 (Ember)",
    homepage="https://ember-energy.org/data/api/",
    version_hint="Ember Data API v1",
    description=(
        "Country-by-month electricity generation per fuel from the Ember Data "
        "API — the calibration reference: compare your model's carrier mix "
        "against what the country actually generated (a cheap sanity check "
        "that catches order-of-magnitude errors). Lands one generation_history "
        "sheet (month × carrier, GWh + share). Needs a free Ember API key "
        "(Settings → API keys)."
    ),
    targets=["generation_history"],
    country_coverage="global",
    requires_secrets=["ember_key"],
    filters=[
        Filter(id="date_from", label="From (month)", kind="date", default="2023-01-01",
               min="2000-01-01", max="2025-12-31",
               description="Start month (inclusive)."),
        Filter(id="date_to", label="To (month)", kind="date", default="2023-12-31",
               min="2000-01-01", max="2025-12-31",
               description="End month (inclusive)."),
    ],
)


def _month(value: Any, fallback: str) -> str:
    s = str(value or fallback)
    return s[:7]  # YYYY-MM from an ISO date


class EmberHistory:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        api_key = ctx.require_secret("ember_key")
        date_from = _month(filters.get("date_from"), "2023-01")
        date_to = _month(filters.get("date_to"), "2023-12")
        params = {
            "entity_code": region.country_iso,
            "is_aggregate_series": "false",
            "start_date": date_from,
            "end_date": date_to,
            "api_key": api_key,
        }
        # D1 general cache: monthly aggregates are stable — 7-day TTL. The key
        # excludes the api_key (same data for every key).
        from ...cache import cache_get, cache_put

        cache_key = {"iso": region.country_iso, "from": date_from, "to": date_to}
        body = cache_get("ember", cache_key)
        if body is not None:
            rows = rows_from_payload((body or {}).get("data") or [])
            return FetchResult(META.id, region, dict(filters),
                               {"rows": rows, "date_from": date_from, "date_to": date_to})
        try:
            body = await ctx.http.get_json(_API_URL, params=params)
        except RuntimeError as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg:
                raise PermissionError(
                    "Ember rejected the API key. Check 'ember_key' in Settings → API keys "
                    "(free key at ember-energy.org/data/api)."
                ) from None
            raise RuntimeError(f"Ember request failed ({msg}).") from None
        cache_put("ember", cache_key, body, ttl_days=7)
        rows = rows_from_payload((body or {}).get("data") or [])
        return FetchResult(META.id, region, dict(filters),
                           {"rows": rows, "date_from": date_from, "date_to": date_to})

    def preview(self, result: FetchResult) -> PreviewSummary:
        rows = result.payload["rows"]
        months = sorted({r["snapshot"] for r in rows})
        carriers = sorted({r["carrier"] for r in rows})
        total_gwh = sum(r["generation_gwh"] for r in rows)
        return PreviewSummary(
            counts={"months": len(months), "carriers": len(carriers),
                    "total_gwh": int(round(total_gwh))},
            samples={"generation_history": rows[:24]},
            notes=[
                f"{result.region.country_name}: {len(rows)} month×fuel records "
                f"({months[0]} → {months[-1]}) totalling {total_gwh:,.0f} GWh."
                if rows else "No records for that range.",
            ],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        frag = WorkbookFragment()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = result.payload["rows"]
        if rows:
            frag.sheets["generation_history"] = rows
        row_counts = {s: len(r) for s, r in frag.sheets.items()}
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            ts, json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return EmberHistory()
