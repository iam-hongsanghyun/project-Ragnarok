"""World Bank annual electricity consumption → workbook Load row.

Port of the browser module. Pulls EG.USE.ELEC.KH.PC (kWh/capita) ×
SP.POP.TOTL (population) from the World Bank Open Data API, derives an
average MW for the chosen year, and preserves the full multi-year
history as extra columns. No API key.
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

_API_BASE = "https://api.worldbank.org/v2"
_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def _slug(raw: str | None, fallback: str = "load") -> str:
    if not raw:
        return fallback
    s = _NAME_RE.sub("_", str(raw).strip()).strip("_")
    return s or fallback


META = DatabaseMeta(
    id="worldbank_demand",
    name="World Bank — annual electricity consumption",
    short_name="World Bank",
    category="demand",
    subcategory="Annual aggregates",
    license="CC-BY 4.0",
    homepage="https://data.worldbank.org/indicator/EG.USE.ELEC.KH.PC",
    version_hint="live",
    description=(
        "Annual electricity consumption per country from the World Bank "
        "Open Data API (EG.USE.ELEC.KH.PC × SP.POP.TOTL). Lands as one "
        "Load row at the selected year's average power (MW); multi-year "
        "history preserved as columns."
    ),
    targets=["loads"],
    country_coverage="global",
    filters=[
        Filter(
            id="year", label="Year", kind="number", default=2014,
            min=1971, max=2024, step=1,
            description="World Bank data lags 2-3 years; older years are most complete.",
        ),
        Filter(
            id="load_name", label="Load name", kind="select",
            default="national_load",
            options=[
                {"value": "national_load", "label": "national_load"},
                {"value": "system_load", "label": "system_load"},
                {"value": "demand", "label": "demand"},
            ],
            description="Suffixed with the country ISO so multi-country runs don't collide.",
        ),
    ],
)


async def _fetch_indicator(http: Any, iso3: str, indicator: str) -> dict[int, float]:
    url = f"{_API_BASE}/country/{iso3.upper()}/indicator/{indicator}"
    body = await http.get_json(url, params={"format": "json", "per_page": 200})
    if not isinstance(body, list) or len(body) < 2 or not isinstance(body[1], list):
        return {}
    out: dict[int, float] = {}
    for entry in body[1]:
        value, year = entry.get("value"), entry.get("date")
        if value is None or year is None:
            continue
        try:
            out[int(year)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _annual_avg_mw(kwh_pc: dict[int, float], pop: dict[int, float], year: int) -> float | None:
    k, p = kwh_pc.get(year), pop.get(year)
    if k is None or p is None or p <= 0:
        return None
    return k * p / 8760.0 / 1000.0  # kWh → MWh → MW


class WorldBankDemand:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        notes: list[str] = []
        try:
            kwh = await _fetch_indicator(ctx.http, region.country_iso, "EG.USE.ELEC.KH.PC")
            pop = await _fetch_indicator(ctx.http, region.country_iso, "SP.POP.TOTL")
        except Exception as exc:  # noqa: BLE001
            return FetchResult(META.id, region, dict(filters), {"kwh": {}, "pop": {}},
                               notes=[f"World Bank fetch failed: {exc}"])
        if not kwh:
            notes.append(f"No EG.USE.ELEC.KH.PC data for {region.country_iso}.")
        return FetchResult(META.id, region, dict(filters), {"kwh": kwh, "pop": pop}, notes=notes)

    def _latest_year(self, kwh: dict[int, float], pop: dict[int, float]) -> int:
        overlap = set(kwh) & set(pop)
        return max(overlap) if overlap else datetime.now(timezone.utc).year - 3

    def preview(self, result: FetchResult) -> PreviewSummary:
        kwh = result.payload["kwh"]
        pop = result.payload["pop"]
        if not kwh:
            return PreviewSummary(counts={"loads": 0}, notes=result.notes or ["No annual demand data available."])
        year = int(result.filters.get("year") or self._latest_year(kwh, pop))
        years = sorted(set(kwh) & set(pop))
        history = [
            {
                "year": y,
                "kwh_per_capita": round(kwh[y], 1),
                "population": int(pop.get(y, 0)),
                "annual_avg_mw": (round(v, 1) if (v := _annual_avg_mw(kwh, pop, y)) is not None else None),
            }
            for y in years[-15:]
        ]
        mw = _annual_avg_mw(kwh, pop, year)
        counts: dict[str, int] = {"loads": 1 if mw else 0}
        if mw is not None:
            counts[f"annual_avg_mw_{year}"] = int(round(mw))
        note = (f"{year}: {round(mw, 1)} MW average load" if mw is not None
                else f"No data for {year} (latest = {years[-1] if years else 'n/a'})")
        return PreviewSummary(counts=counts, samples={"history": history}, notes=[note])

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        kwh = result.payload["kwh"]
        pop = result.payload["pop"]
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        frag = WorkbookFragment()

        def prov(rows: dict[str, int]) -> Provenance:
            return Provenance(
                META.id, result.region.country_iso, result.region.country_name,
                json.dumps(result.filters, sort_keys=True, default=str),
                json.dumps(options.__dict__, sort_keys=True, default=str),
                ts, json.dumps(rows, sort_keys=True),
            )

        if not kwh:
            frag.provenance = prov({"loads": 0})
            return frag
        requested = int(result.filters.get("year") or self._latest_year(kwh, pop))
        chosen = requested
        mw = _annual_avg_mw(kwh, pop, requested)
        if mw is None:
            years = sorted(set(kwh) & set(pop))
            if years:
                chosen = years[-1]
                mw = _annual_avg_mw(kwh, pop, chosen)
        if mw is None:
            frag.provenance = prov({"loads": 0})
            return frag
        base = str(result.filters.get("load_name") or "national_load")
        row: dict[str, Any] = {
            "name": _slug(f"{base}_{result.region.country_iso}", "load"),
            "p_set": round(mw, 4),
            "country": result.region.country_iso,
            "source": "World Bank",
            "year": chosen,
        }
        for y in sorted(set(kwh) | set(pop)):
            if (k := kwh.get(y)) is not None:
                row[f"kwh_per_capita_{y}"] = round(k, 4)
            if (p := pop.get(y)) is not None:
                row[f"population_{y}"] = int(p)
            if (m := _annual_avg_mw(kwh, pop, y)) is not None:
                row[f"annual_avg_mw_{y}"] = round(m, 4)
        frag.sheets["loads"] = [row]
        frag.provenance = prov({"loads": 1, "year": chosen})
        return frag


def build() -> Database:
    return WorldBankDemand()
