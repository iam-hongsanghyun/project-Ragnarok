"""World Bank annual electricity consumption → workbook Load row.

Self-contained module. No imports from a shared convert/ package. Slug /
dedupe / provenance helpers inlined. The Load row carries the requested
year's average MW as ``p_set`` plus **every year** of the underlying
indicators (`kwh_per_capita_*`, `population_*`, `annual_avg_mw_*`) as
extra columns — so the user has the full history right next to the value
used in the model, without a follow-up fetch.

Optional PyPSA attributes (`sign`, `carrier`, `p_set` time-series cols, …)
are **not** populated when the upstream is silent — PyPSA's component
defaults apply at solve time.

No API key; the World Bank Open Data API is public.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ...protocol import (
    ConvertOptions,
    DatabaseMeta,
    FetchResult,
    PreviewSummary,
    Provenance,
    Region,
    WorkbookFragment,
)

_log = logging.getLogger(__name__)


def _api_base() -> str:
    return os.environ.get("RAGNAROK_WORLDBANK_URL", "https://api.worldbank.org/v2")


def _http_get_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": os.environ.get(
                "RAGNAROK_WORLDBANK_UA",
                "Ragnarok/0.1 (+https://github.com/PyPSA/PyPSA)",
            ),
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _fetch_indicator(country_iso3: str, indicator: str) -> dict[int, float]:
    """Return ``{year: value}`` for the indicator, dropping null years."""
    base = _api_base()
    url = (
        f"{base}/country/{country_iso3.upper()}/indicator/{indicator}"
        f"?format=json&per_page=200"
    )
    body = _http_get_json(url)
    # Response is [metadata, data]; we want the data array.
    if not isinstance(body, list) or len(body) < 2 or not isinstance(body[1], list):
        return {}
    out: dict[int, float] = {}
    for entry in body[1]:
        value = entry.get("value")
        year = entry.get("date")
        if value is None or year is None:
            continue
        try:
            out[int(year)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


# ── Slug helper (inlined) ────────────────────────────────────────────────────

_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def _slug(raw: str | None, fallback: str = "load") -> str:
    if not raw:
        return fallback
    s = _NAME_RE.sub("_", str(raw).strip()).strip("_")
    return s or fallback


# ── Series ──────────────────────────────────────────────────────────────────


@dataclass
class _Series:
    kwh_per_capita: dict[int, float]
    population: dict[int, float]

    def annual_avg_mw(self, year: int) -> float | None:
        kwh_pc = self.kwh_per_capita.get(year)
        pop = self.population.get(year)
        if kwh_pc is None or pop is None or pop <= 0:
            return None
        total_kwh = kwh_pc * pop
        return total_kwh / 8760.0 / 1000.0  # kWh → MWh → MW


def _latest_year(series: _Series) -> int:
    overlap = set(series.kwh_per_capita) & set(series.population)
    return max(overlap) if overlap else datetime.now(timezone.utc).year - 3


# ── Database implementation ──────────────────────────────────────────────────


@dataclass
class WorldBankDemandImporter:
    meta: DatabaseMeta

    def fetch(self, region: Region, filters: dict[str, Any]) -> FetchResult:
        notes: list[str] = []
        try:
            kwh_pc = _fetch_indicator(region.country_iso, "EG.USE.ELEC.KH.PC")
            pop = _fetch_indicator(region.country_iso, "SP.POP.TOTL")
        except Exception as exc:  # noqa: BLE001
            return FetchResult(
                database_id=self.meta.id,
                region=region,
                filters=dict(filters),
                payload={"series": None},
                notes=[f"World Bank fetch failed: {exc}"],
            )
        series = _Series(kwh_per_capita=kwh_pc, population=pop)
        if not kwh_pc:
            notes.append(
                f"No EG.USE.ELEC.KH.PC data for {region.country_iso}. "
                "World Bank coverage stops in 2014 for some countries."
            )
        return FetchResult(
            database_id=self.meta.id,
            region=region,
            filters=dict(filters),
            payload={"series": series},
            notes=notes,
        )

    def preview(self, result: FetchResult) -> PreviewSummary:
        series: _Series | None = result.payload.get("series")
        if series is None or not series.kwh_per_capita:
            return PreviewSummary(
                counts={"loads": 0},
                samples={},
                notes=result.notes or ["No annual demand data available."],
            )
        year = int(result.filters.get("year") or _latest_year(series))
        annual_mw = series.annual_avg_mw(year)
        years_available = sorted(set(series.kwh_per_capita) & set(series.population))
        samples = {
            "history": [
                {
                    "year": y,
                    "kwh_per_capita": round(series.kwh_per_capita[y], 1),
                    "population": int(series.population.get(y, 0)),
                    "annual_avg_mw": (
                        round(series.annual_avg_mw(y), 1)
                        if series.annual_avg_mw(y) is not None
                        else None
                    ),
                }
                for y in years_available[-15:]
            ]
        }
        counts: dict[str, int] = {"loads": 1 if annual_mw else 0}
        if annual_mw is not None:
            counts[f"annual_avg_mw_{year}"] = int(round(annual_mw))
        return PreviewSummary(
            counts=counts,
            samples=samples,
            notes=[
                (
                    f"{year}: {round(annual_mw, 1)} MW average load"
                    if annual_mw is not None
                    else f"No data for {year} (latest = {years_available[-1] if years_available else 'n/a'})"
                ),
            ],
            overlay={},
        )

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment:
        fragment = WorkbookFragment()
        series: _Series | None = result.payload.get("series")
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if series is None or not series.kwh_per_capita:
            fragment.provenance = self._provenance(result, options, ts, {"loads": 0})
            return fragment

        requested_year = int(result.filters.get("year") or _latest_year(series))
        annual_mw = series.annual_avg_mw(requested_year)
        chosen_year = requested_year
        if annual_mw is None:
            # Fall back to the most recent year with data.
            years = sorted(set(series.kwh_per_capita) & set(series.population))
            if years:
                chosen_year = years[-1]
                annual_mw = series.annual_avg_mw(chosen_year)
        if annual_mw is None:
            fragment.provenance = self._provenance(result, options, ts, {"loads": 0})
            return fragment

        base_name = str(result.filters.get("load_name") or "national_load")
        full_name = _slug(
            f"{base_name}_{result.region.country_iso}", fallback="load"
        )
        load_row: dict[str, Any] = {
            "name": full_name,
            # bus, carrier, sign INTENTIONALLY UNSET — PyPSA defaults apply
            # at solve time. The user reconciles `bus` via T3 later.
            "p_set": round(annual_mw, 4),
            "country": result.region.country_iso,
            "source": "World Bank",
            "year": chosen_year,
        }
        # Preserve the full multi-year history as extra columns. No upstream
        # value is silently dropped.
        for y in sorted(set(series.kwh_per_capita) | set(series.population)):
            kwh = series.kwh_per_capita.get(y)
            pop = series.population.get(y)
            mw = series.annual_avg_mw(y)
            if kwh is not None:
                load_row[f"kwh_per_capita_{y}"] = round(kwh, 4)
            if pop is not None:
                load_row[f"population_{y}"] = int(pop)
            if mw is not None:
                load_row[f"annual_avg_mw_{y}"] = round(mw, 4)
        fragment.sheets["loads"] = [load_row]
        fragment.provenance = self._provenance(
            result, options, ts, {"loads": 1, "year": chosen_year}
        )
        return fragment

    def _provenance(
        self,
        result: FetchResult,
        options: ConvertOptions,
        timestamp: str,
        row_counts: dict[str, int],
    ) -> Provenance:
        return Provenance(
            database_id=self.meta.id,
            country_iso=result.region.country_iso,
            country_name=result.region.country_name,
            filters_json=json.dumps(result.filters, sort_keys=True, default=str),
            convert_options_json=json.dumps(options.__dict__, sort_keys=True, default=str),
            fetch_timestamp=timestamp,
            row_counts_json=json.dumps(row_counts, sort_keys=True),
        )
