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
from ..entsoe_load import (
    ENTSOE_SOURCE_ID,
    ENTSOE_SOURCE_LABEL,
    _EIC_BY_ISO,
    _children,
    _first_reason_text,
    _local,
    _period_points,
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
            # curveType A03 (omitted == unchanged) is forward-filled by the helper.
            points.extend(_period_points(ts, period, "price.amount"))
    return points


def _parse_price_currency(xml_text: str) -> str:
    """Currency of a Publication_MarketDocument (``currency_Unit.name`` of the
    first TimeSeries, e.g. ``EUR``); empty when the document omits it."""
    root = ET.fromstring(xml_text)
    for el in root.iter():
        if _local(el.tag) == "currency_Unit.name" and (el.text or "").strip():
            return (el.text or "").strip()
    return ""


# Day-ahead price bidding zones. Prices clear per *bidding zone*, which for
# DK/IT/NO/SE/IE differs from the national control-area code used by the load
# dataset (those control-area codes return no price document). Values are
# ``(zone code -> (EIC, label))``.
_DE_AT_LU = ("10Y1001A1001A63L", "DE-AT-LU")
_DE_LU = ("10Y1001A1001A82H", "DE-LU")
_PRICE_ZONES: dict[str, tuple[str, str]] = {
    "DK1": ("10YDK-1--------W", "Denmark DK1"),
    "DK2": ("10YDK-2--------M", "Denmark DK2"),
    "IT-NORD": ("10Y1001A1001A73I", "Italy North"),
    "IT-CNOR": ("10Y1001A1001A70O", "Italy Centre-North"),
    "IT-CSUD": ("10Y1001A1001A71M", "Italy Centre-South"),
    "IT-SUD": ("10Y1001A1001A788", "Italy South"),
    "IT-SICI": ("10Y1001A1001A75E", "Italy Sicily"),
    "IT-SARD": ("10Y1001A1001A74G", "Italy Sardinia"),
    "NO1": ("10YNO-1--------2", "Norway NO1"),
    "NO2": ("10YNO-2--------T", "Norway NO2"),
    "NO3": ("10YNO-3--------J", "Norway NO3"),
    "NO4": ("10YNO-4--------9", "Norway NO4"),
    "NO5": ("10Y1001A1001A48H", "Norway NO5"),
    "SE1": ("10Y1001A1001A44P", "Sweden SE1"),
    "SE2": ("10Y1001A1001A45N", "Sweden SE2"),
    "SE3": ("10Y1001A1001A46L", "Sweden SE3"),
    "SE4": ("10Y1001A1001A47J", "Sweden SE4"),
    "IE-SEM": ("10Y1001A1001A59C", "Ireland (SEM)"),
}
# Countries whose national bidding zone is a single price zone: the load map's
# EIC is right for them. Multi-zone countries default to the zone named here
# (the user can pick another via the ``zone`` filter).
_DEFAULT_ZONE_BY_ISO = {
    "DNK": "DK1", "ITA": "IT-NORD", "NOR": "NO1", "SWE": "SE3", "IRL": "IE-SEM",
}
# 2018-10-01: the DE-AT-LU zone split into DE-LU and AT (Austria then has its
# own zone; Luxembourg stays with Germany).
DE_AT_LU_SPLIT = date(2018, 10, 1)
_SPLIT_ISOS = ("DEU", "AUT", "LUX")


def _zone_options() -> list[dict[str, str]]:
    out = [{"value": "auto", "label": "Country default (auto)"}]
    out += [{"value": k, "label": f"{k} — {name}"} for k, (_e, name) in _PRICE_ZONES.items()]
    return out


def price_segments(
    iso: str, zone: str | None, date_from: str, date_to: str
) -> list[tuple[str, str, str, str]]:
    """Resolve ``(eic, zone_label, from, to)`` request segments for a window.

    ``zone`` is a ``_PRICE_ZONES`` key or ``auto``/empty. DEU/AUT/LUX split at
    ``DE_AT_LU_SPLIT``: before it Germany, Austria and Luxembourg clear in the
    joint DE-AT-LU zone, after it Germany + Luxembourg in DE-LU and Austria in
    its own zone. Raises ``RuntimeError`` for an unmapped country / zone.
    """
    z = (zone or "auto").strip()
    if z != "auto":
        if z not in _PRICE_ZONES:
            raise RuntimeError(f"ENTSO-E: unknown price zone '{z}'.")
        eic, label = _PRICE_ZONES[z]
        return [(eic, label, date_from, date_to)]
    if iso in _SPLIT_ISOS:
        after = (_EIC_BY_ISO["AUT"][0], "Austria") if iso == "AUT" else _DE_LU
        d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
        if d1 < DE_AT_LU_SPLIT:
            return [(*_DE_AT_LU, date_from, date_to)]
        if d0 >= DE_AT_LU_SPLIT:
            return [(*after, date_from, date_to)]
        last_before = (DE_AT_LU_SPLIT - timedelta(days=1)).isoformat()
        return [(*_DE_AT_LU, date_from, last_before),
                (*after, DE_AT_LU_SPLIT.isoformat(), date_to)]
    if iso in _DEFAULT_ZONE_BY_ISO:
        eic, label = _PRICE_ZONES[_DEFAULT_ZONE_BY_ISO[iso]]
        return [(eic, label, date_from, date_to)]
    mapped = _EIC_BY_ISO.get(iso)
    if not mapped:
        raise RuntimeError(
            f"ENTSO-E: no bidding-zone EIC mapped for {iso}. "
            f"Covered: {', '.join(sorted(_EIC_BY_ISO))}."
        )
    return [(mapped[0], mapped[1], date_from, date_to)]


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
        Filter(id="zone", label="Price zone", kind="select", default="auto",
               options=_zone_options(),
               description="Day-ahead prices clear per bidding zone. 'auto' uses the "
                           "country's zone (DE/LU: DE-LU from 2018-10-01, DE-AT-LU "
                           "before; AT likewise); pick an explicit zone for "
                           "DK, IT, NO, SE or IE (default DK1 / IT-NORD / NO1 / SE3 / IE-SEM)."),
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
        date_from = str(filters.get("date_from") or "2023-01-01")
        date_to = str(filters.get("date_to") or "2023-01-07")
        segments = price_segments(
            region.country_iso, str(filters.get("zone") or "auto"), date_from, date_to
        )
        points: list[tuple[datetime, float]] = []
        currencies: list[str] = []
        for eic, _label, seg_from, seg_to in segments:
            params = {
                "securityToken": token,
                "documentType": "A44",
                "in_Domain": eic,
                "out_Domain": eic,
                "periodStart": _to_period(seg_from, end=False),
                "periodEnd": _to_period(seg_to, end=True),
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
            points.extend(_parse_price_xml(xml_text))
            cur = _parse_price_currency(xml_text)
            if cur and cur not in currencies:
                currencies.append(cur)

        hourly = _aggregate_hourly(points)
        eic_label = "+".join(dict.fromkeys(e for e, *_ in segments))
        zone_name = " → ".join(dict.fromkeys(n for _e, n, *_ in segments))
        return FetchResult(
            META.id, region, dict(filters),
            {"iso": region.country_iso, "eic": eic_label, "zone_name": zone_name,
             "currency": "/".join(currencies), "hourly": hourly,
             "date_from": date_from, "date_to": date_to},
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
                   f"{len(hourly)} hourly day-ahead prices {span} (UTC), "
                   f"{result.payload.get('currency') or 'currency not reported'}/MWh."],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        hourly = result.payload["hourly"]
        iso = result.payload["iso"]
        frag = WorkbookFragment()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if hourly:
            frag.sheets["electricity_price"] = [
                {"snapshot": snap, "price": round(price, 4), "zone": iso,
                 "bidding_zone": result.payload.get("zone_name", ""),
                 "currency": result.payload.get("currency", "")}
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
