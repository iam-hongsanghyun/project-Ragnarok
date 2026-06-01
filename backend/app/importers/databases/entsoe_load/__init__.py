"""ENTSO-E Transparency — national hourly electricity demand (BYOK).

Actual Total Load [6.1.A] from the ENTSO-E Transparency RESTful API: the
hourly electricity demand of a European bidding zone / national control
area. This is Ragnarok's national-level hourly demand source — one Load
row plus an hourly ``loads-p_set`` series per country.

Request shape (documented in the Transparency API guide):

    documentType        = A65   (System total load)
    processType         = A16   (Realised)
    outBiddingZone_Domain = <EIC>   (the country's bidding zone)
    periodStart / periodEnd = yyyyMMddHHmm   (UTC)

The response is an XML ``GL_MarketDocument``. We read every Period's
Points, timestamp each from the period's ``timeInterval`` start +
``resolution`` × (position − 1), and aggregate to an hourly mean — so
PT15M / PT30M zones collapse onto the same hourly grid as PT60M zones.
Times are UTC.

Requires a free per-user API token (``entsoe_key``): register on the
Transparency Platform, request API access (one email), then generate a
token in your account settings. Stored browser-side, shipped in the
request body, used for this one request, never persisted or logged.
"""
from __future__ import annotations

import json
import re
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

_API_URL = "https://web-api.tp.entsoe.eu/api"
_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")

# ISO-3166-1 alpha-3 → ENTSO-E EIC code for Actual Total Load. These are the
# national bidding zone / control-area domains used by the Transparency
# platform (the same codes the `entsoe-py` client uses). Multi-zone countries
# are mapped to their primary national zone; Germany uses the DE-LU zone.
_EIC_BY_ISO: dict[str, tuple[str, str]] = {
    "ALB": ("10YAL-KESH-----5", "Albania"),
    "AUT": ("10YAT-APG------L", "Austria"),
    "BEL": ("10YBE----------2", "Belgium"),
    "BGR": ("10YCA-BULGARIA-R", "Bulgaria"),
    "HRV": ("10YHR-HEP------M", "Croatia"),
    "CZE": ("10YCZ-CEPS-----N", "Czechia"),
    "DNK": ("10Y1001A1001A65H", "Denmark"),
    "EST": ("10Y1001A1001A39I", "Estonia"),
    "FIN": ("10YFI-1--------U", "Finland"),
    "FRA": ("10YFR-RTE------C", "France"),
    "DEU": ("10Y1001A1001A82H", "Germany (DE-LU)"),
    "GRC": ("10YGR-HTSO-----Y", "Greece"),
    "HUN": ("10YHU-MAVIR----U", "Hungary"),
    "IRL": ("10YIE-1001A00010", "Ireland"),
    "ITA": ("10YIT-GRTN-----B", "Italy"),
    "LVA": ("10YLV-1001A00074", "Latvia"),
    "LTU": ("10YLT-1001A0008Q", "Lithuania"),
    "LUX": ("10YLU-CEGEDEL-NQ", "Luxembourg"),
    "NLD": ("10YNL----------L", "Netherlands"),
    "NOR": ("10YNO-0--------C", "Norway"),
    "POL": ("10YPL-AREA-----S", "Poland"),
    "PRT": ("10YPT-REN------W", "Portugal"),
    "ROU": ("10YRO-TEL------P", "Romania"),
    "SVK": ("10YSK-SEPS-----K", "Slovakia"),
    "SVN": ("10YSI-ELES-----O", "Slovenia"),
    "ESP": ("10YES-REE------0", "Spain"),
    "SWE": ("10YSE-1--------K", "Sweden"),
    "CHE": ("10YCH-SWISSGRIDZ", "Switzerland"),
    "GBR": ("10YGB----------A", "Great Britain"),
}


def _slug(raw: str | None, fallback: str = "load") -> str:
    if not raw:
        return fallback
    s = _NAME_RE.sub("_", str(raw).strip()).strip("_")
    return s or fallback


def _local(tag: str) -> str:
    """Local name of a namespaced XML tag (``{ns}Point`` → ``Point``)."""
    return tag.rsplit("}", 1)[-1]


def _children(parent: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in parent if _local(c.tag) == name]


def _to_period(date_str: str, *, end: bool) -> str:
    """ISO date → ``yyyyMMddHHmm`` UTC. ``end`` advances one day so the last
    day is included (ENTSO-E's periodEnd is the exclusive upper bound)."""
    d = date.fromisoformat(date_str)
    if end:
        d = d + timedelta(days=1)
    return d.strftime("%Y%m%d") + "0000"


def _resolution_minutes(text: str | None) -> int:
    """Parse an ISO-8601 duration (``PT60M`` / ``PT15M`` / ``PT1H``) to minutes."""
    if not text:
        return 60
    m = re.search(r"PT(?:(\d+)H)?(?:(\d+)M)?", text)
    if not m:
        return 60
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    total = hours * 60 + minutes
    return total or 60


def _parse_dt(text: str | None) -> datetime | None:
    """Parse an ENTSO-E UTC timestamp like ``2023-01-01T00:00Z``."""
    if not text:
        return None
    s = text.strip().replace("Z", "").replace("z", "")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _first_reason_text(root: ET.Element) -> str:
    for e in root.iter():
        if _local(e.tag) == "Reason":
            for c in e:
                if _local(c.tag) == "text":
                    return (c.text or "").strip()
    return ""


def _parse_load_xml(xml_text: str) -> list[tuple[datetime, float]]:
    """Extract ``(timestamp_utc, MW)`` points from a GL_MarketDocument.

    Raises ``RuntimeError`` with the reason text if the platform returned an
    ``Acknowledgement_MarketDocument`` (e.g. "No matching data found").
    """
    root = ET.fromstring(xml_text)
    if _local(root.tag) == "Acknowledgement_MarketDocument":
        reason = _first_reason_text(root)
        raise RuntimeError(reason or "ENTSO-E returned no data for that range")

    points: list[tuple[datetime, float]] = []
    series = [e for e in root.iter() if _local(e.tag) == "TimeSeries"]
    for ts in series:
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
                qty_el = _children(pt, "quantity")
                if not pos_el or not qty_el:
                    continue
                try:
                    pos = int(pos_el[0].text or "")
                    qty = float(qty_el[0].text or "")
                except (TypeError, ValueError):
                    continue
                t = start + timedelta(minutes=res_min * (pos - 1))
                points.append((t, qty))
    return points


def _aggregate_hourly(points: list[tuple[datetime, float]]) -> list[tuple[str, float]]:
    """Average sub-hourly points onto an hourly grid. Snapshots are
    ``YYYY-MM-DD HH:00`` (fixed-width → lexical sort == chronological)."""
    buckets: dict[str, list[float]] = {}
    for t, mw in points:
        key = t.strftime("%Y-%m-%d %H:00")
        buckets.setdefault(key, [0.0, 0.0])
        buckets[key][0] += mw
        buckets[key][1] += 1
    return [
        (key, buckets[key][0] / buckets[key][1])
        for key in sorted(buckets)
        if buckets[key][1] > 0
    ]


META = DatabaseMeta(
    id="entsoe_load",
    name="ENTSO-E — national hourly electricity demand (Actual Total Load)",
    short_name="ENTSO-E load",
    category="demand",
    subcategory="Hourly profiles",
    license="ENTSO-E Transparency (free, attribution)",
    homepage="https://transparency.entsoe.eu/",
    version_hint="Transparency RESTful API",
    description=(
        "National hourly electricity demand for a European country from the "
        "ENTSO-E Transparency Platform (Actual Total Load, 6.1.A). The country "
        "you pick on the map selects the bidding zone; choose the date window. "
        "Lands as one Load row plus an hourly loads-p_set series (UTC; "
        "sub-hourly zones are averaged to hourly). Needs a free ENTSO-E API "
        "token (Settings → API keys)."
    ),
    targets=["loads", "loads-p_set"],
    country_coverage=sorted(_EIC_BY_ISO.keys()),
    requires_secrets=["entsoe_key"],
    filters=[
        Filter(id="date_from", label="From", kind="date", default="2023-01-01",
               min="2015-01-01", max="2025-12-31",
               description="Start of the hourly window (inclusive, UTC)."),
        Filter(id="date_to", label="To", kind="date", default="2023-01-07",
               min="2015-01-01", max="2025-12-31",
               description="End of the hourly window (inclusive, UTC). Keep it "
                           "short — hourly load is large; ENTSO-E caps a single "
                           "request at one year."),
    ],
)


class EntsoeLoad:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        # BYOK: raises PermissionError (→ HTTP 400) when the user has no token.
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
            "documentType": "A65",
            "processType": "A16",
            "outBiddingZone_Domain": eic,
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
                    "Settings → API keys and that API access is enabled for "
                    "your account."
                ) from None
            raise RuntimeError(
                f"ENTSO-E request failed ({msg}). The range may have no "
                f"published load, or the token may lack access."
            ) from None

        points = _parse_load_xml(xml_text)
        hourly = _aggregate_hourly(points)
        return FetchResult(
            META.id, region, dict(filters),
            {"iso": region.country_iso, "eic": eic, "zone_name": zone_name,
             "hourly": hourly, "date_from": date_from, "date_to": date_to},
        )

    def preview(self, result: FetchResult) -> PreviewSummary:
        hourly = result.payload["hourly"]
        zone_name = result.payload["zone_name"]
        eic = result.payload["eic"]
        vals = [mw for _, mw in hourly]
        counts: dict[str, int] = {"loads": 1 if hourly else 0, "hours": len(hourly)}
        if vals:
            counts["peak_mw"] = int(round(max(vals)))
            counts["mean_mw"] = int(round(sum(vals) / len(vals)))
        span = f"{hourly[0][0]} → {hourly[-1][0]}" if hourly else (
            f"{result.payload['date_from']} → {result.payload['date_to']}"
        )
        return PreviewSummary(
            counts=counts,
            samples={"hours": [
                {"snapshot": snap, "mw": round(mw, 1)}
                for snap, mw in hourly[:24]
            ]},
            notes=[f"{zone_name} ({eic}): {len(hourly)} hourly points {span} (UTC)."],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        hourly = result.payload["hourly"]
        iso = result.payload["iso"]
        eic = result.payload["eic"]
        zone_name = result.payload["zone_name"]
        frag = WorkbookFragment()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        load_name = _slug(f"{iso}_demand", "load")

        snapshots = [snap for snap, _ in hourly]
        p_set_rows = [{"snapshot": snap, load_name: mw} for snap, mw in hourly]

        if p_set_rows:
            frag.sheets["loads"] = [{
                "name": load_name, "carrier": "AC", "country": iso,
                "source": "ENTSO-E Transparency (Actual Total Load)",
                "bidding_zone": eic, "zone_name": zone_name,
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
    return EntsoeLoad()
