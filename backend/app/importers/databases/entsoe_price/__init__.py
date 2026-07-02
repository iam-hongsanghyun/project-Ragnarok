"""ENTSO-E Transparency — national day-ahead electricity price (BYOK).

Day-ahead Prices [12.1.D] from the ENTSO-E Transparency RESTful API: the hourly
day-ahead clearing price of a European bidding zone. This is the *price* half of
the hourly load & price pair — the demand half ships as ``entsoe_load``. It lands
one ``electricity_price`` sheet keyed by snapshot (currency/MWh), for retrospective
settlement / PPA-valuation analytics against real spot prices.

Request shape:

    documentType = A44   (Day-ahead prices)
    in_Domain / out_Domain = <EIC>   (same bidding zone for a price series)
    periodStart / periodEnd = yyyyMMddHHmm   (UTC)

The response is a ``Publication_MarketDocument``; each Period's Points carry a
``price.amount`` (not ``quantity``). Sub-hourly zones are averaged to the hourly
grid, matching ``entsoe_load``. Reuses the shared ENTSO-E EIC map + XML helpers.

Requires the same free ``entsoe_key`` token as the other ENTSO-E datasets.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
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
from ..entsoe_load import (
    ENTSOE_SOURCE_ID,
    ENTSOE_SOURCE_LABEL,
    _EIC_BY_ISO,
    _children,
    _first_reason_text,
    _local,
    _parse_dt,
    _resolution_minutes,
    _to_period,
)

_API_URL = "https://web-api.tp.entsoe.eu/api"


def _parse_price_xml(xml_text: str) -> list[tuple[datetime, float]]:
    """Extract ``(timestamp_utc, price)`` points from a Publication_MarketDocument.

    Raises ``RuntimeError`` with the reason text on an Acknowledgement document.
    """
    root = ET.fromstring(xml_text)
    if _local(root.tag) == "Acknowledgement_MarketDocument":
        raise RuntimeError(_first_reason_text(root) or "ENTSO-E returned no data for that range")

    points: list[tuple[datetime, float]] = []
    for ts in (e for e in root.iter() if _local(e.tag) == "TimeSeries"):
        for period in _children(ts, "Period"):
            start: datetime | None = None
            res_min = 60
            interval = _children(period, "timeInterval")
            if interval:
                starts = _children(interval[0], "start")
                if starts:
                    start = _parse_dt(starts[0].text)
            resolutions = _children(period, "resolution")
            if resolutions:
                res_min = _resolution_minutes(resolutions[0].text)
            if start is None:
                continue
            for pt in _children(period, "Point"):
                pos_el = _children(pt, "position")
                amt_el = _children(pt, "price.amount")
                if not pos_el or not amt_el:
                    continue
                try:
                    pos = int(pos_el[0].text or "")
                    amt = float(amt_el[0].text or "")
                except (TypeError, ValueError):
                    continue
                points.append((start + timedelta(minutes=res_min * (pos - 1)), amt))
    return points


def _aggregate_hourly(points: list[tuple[datetime, float]]) -> list[tuple[str, float]]:
    """Average sub-hourly prices onto the hourly grid (``YYYY-MM-DD HH:00``)."""
    buckets: dict[str, list[float]] = {}
    for t, price in points:
        key = t.strftime("%Y-%m-%d %H:00")
        buckets.setdefault(key, [0.0, 0.0])
        buckets[key][0] += price
        buckets[key][1] += 1
    return [(k, buckets[k][0] / buckets[k][1]) for k in sorted(buckets) if buckets[k][1] > 0]


META = DatabaseMeta(
    id="entsoe_price",
    name="ENTSO-E — national day-ahead electricity price",
    short_name="Day-ahead price",
    source_id=ENTSOE_SOURCE_ID,
    source_label=ENTSOE_SOURCE_LABEL,
    category="prices",
    subcategory="Hourly profiles",
    license="ENTSO-E Transparency (free, attribution)",
    homepage="https://transparency.entsoe.eu/",
    version_hint="Transparency RESTful API",
    description=(
        "National hourly day-ahead electricity price for a European bidding zone "
        "(Day-ahead Prices, 12.1.D). Pick the country and window; lands an "
        "electricity_price sheet keyed by snapshot (currency/MWh, UTC; sub-hourly "
        "zones averaged to hourly) for retrospective settlement / PPA valuation "
        "against real spot prices. Needs the same free ENTSO-E API token."
    ),
    targets=["electricity_price"],
    country_coverage=sorted(_EIC_BY_ISO.keys()),
    requires_secrets=["entsoe_key"],
    filters=[
        Filter(id="date_from", label="From", kind="date", default="2023-01-01",
               min="2015-01-01", max="2025-12-31",
               description="Start of the hourly window (inclusive, UTC)."),
        Filter(id="date_to", label="To", kind="date", default="2023-01-07",
               min="2015-01-01", max="2025-12-31",
               description="End of the hourly window (inclusive, UTC). ENTSO-E caps "
                           "a single request at one year."),
    ],
)


class EntsoePrice:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        token = ctx.require_secret("entsoe_key")
        mapped = _EIC_BY_ISO.get(region.country_iso)
        if not mapped:
            raise RuntimeError(
                f"ENTSO-E: no bidding-zone EIC mapped for {region.country_iso}. "
                f"Covered: {', '.join(sorted(_EIC_BY_ISO))}."
            )
        eic, zone_name = mapped
        date_from = str(filters.get("date_from") or "2023-01-01")
        date_to = str(filters.get("date_to") or "2023-01-07")
        params = {
            "securityToken": token,
            "documentType": "A44",
            "in_Domain": eic,
            "out_Domain": eic,
            "periodStart": _to_period(date_from, end=False),
            "periodEnd": _to_period(date_to, end=True),
        }
        try:
            xml_text = await ctx.http.get_text(_API_URL, params=params)
        except RuntimeError as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg:
                raise PermissionError(
                    "ENTSO-E rejected the API token. Check 'entsoe_key' in "
                    "Settings → API keys and that API access is enabled."
                ) from None
            raise RuntimeError(
                f"ENTSO-E day-ahead price request failed ({msg}). The range may "
                f"have no published price for this zone."
            ) from None

        hourly = _aggregate_hourly(_parse_price_xml(xml_text))
        return FetchResult(
            META.id, region, dict(filters),
            {"iso": region.country_iso, "eic": eic, "zone_name": zone_name,
             "hourly": hourly, "date_from": date_from, "date_to": date_to},
        )

    def preview(self, result: FetchResult) -> PreviewSummary:
        hourly = result.payload["hourly"]
        vals = [p for _, p in hourly]
        counts: dict[str, int] = {"hours": len(hourly)}
        if vals:
            counts["mean_price"] = int(round(sum(vals) / len(vals)))
            counts["peak_price"] = int(round(max(vals)))
        span = f"{hourly[0][0]} → {hourly[-1][0]}" if hourly else (
            f"{result.payload['date_from']} → {result.payload['date_to']}"
        )
        return PreviewSummary(
            counts=counts,
            samples={"hours": [{"snapshot": s, "price": round(p, 2)} for s, p in hourly[:24]]},
            notes=[f"{result.payload['zone_name']} ({result.payload['eic']}): "
                   f"{len(hourly)} hourly day-ahead prices {span} (UTC)."],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        hourly = result.payload["hourly"]
        iso = result.payload["iso"]
        frag = WorkbookFragment()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if hourly:
            frag.sheets["electricity_price"] = [
                {"snapshot": snap, "price": round(price, 4), "zone": iso}
                for snap, price in hourly
            ]
            frag.snapshots = [snap for snap, _ in hourly]
        row_counts = {s: len(r) for s, r in frag.sheets.items()}
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            ts, json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return EntsoePrice()
