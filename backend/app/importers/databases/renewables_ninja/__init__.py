"""Renewables.ninja — validated wind/solar capacity factors (BYOK).

renewables.ninja serves hourly, bias-corrected wind & solar capacity factors for
any coordinate (Pfenninger & Staffell's MERRA-2 / ERA5 model). It's the
validated complement to the first-order Open-Meteo/PVGIS/NASA conversions.

Two requests per fetch (PV + wind) at the region centroid, each with
``capacity=1`` so ``electricity`` is the capacity factor (0–1). Auth is an
``Authorization: Token <key>`` header (BYOK — ``renewables_ninja_key``).

Licence + rate limits: the ninja terms forbid **redistribution / bulk caching**
of the series, so — unlike the keyless weather sources — this NEVER touches the
on-disk weather cache; every fetch goes live under the user's own token (free
tier: 6 requests/min, 50/hour). Get a token at renewables.ninja → Profile.
"""
from __future__ import annotations

import asyncio
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

_PV_URL = "https://www.renewables.ninja/api/data/pv"
_WIND_URL = "https://www.renewables.ninja/api/data/wind"
_SECRET = "renewables_ninja_key"
_TECHS = [{"value": "solar", "label": "Solar PV"}, {"value": "wind", "label": "Wind"}]


def _iso(region: Region) -> str:
    return (region.country_iso or "REG").strip().upper() or "REG"


def _techs(filters: dict[str, Any]) -> list[str]:
    raw = filters.get("technologies")
    if isinstance(raw, str):
        raw = [raw]
    picked = [t for t in (raw or ["solar", "wind"]) if t in ("solar", "wind")]
    return picked or ["solar", "wind"]


def _series(body: Any) -> list[tuple[str, float]]:
    """Parse a ninja ``format=json`` body → sorted ``[(snapshot, cf)]``.

    ``data`` maps a timestamp to ``{"electricity": <cf>}`` (capacity=1 → the
    value is the capacity factor). Timestamps are ``YYYY-MM-DD HH:MM``.
    """
    data = (body or {}).get("data") or {}
    out: list[tuple[str, float]] = []
    for ts, rec in data.items():
        val = rec.get("electricity") if isinstance(rec, dict) else rec
        if val is None:
            continue
        try:
            out.append((str(ts)[:16].replace("T", " "), float(val)))
        except (TypeError, ValueError):
            continue
    out.sort()
    return out


META = DatabaseMeta(
    id="renewables_ninja",
    name="Renewables.ninja — validated wind & solar capacity factors (BYOK)",
    short_name="Renewables.ninja",
    source_id="renewables_ninja",
    source_label="Renewables.ninja (BYOK)",
    category="generation",
    subcategory="Hourly profiles",
    license="Renewables.ninja (CC-BY-NC; no redistribution / bulk caching)",
    homepage="https://www.renewables.ninja/",
    version_hint="ninja API (MERRA-2 / ERA5)",
    description=(
        "Validated, bias-corrected hourly wind & solar capacity factors for the "
        "region centroid from renewables.ninja (Pfenninger & Staffell). The "
        "validated complement to the keyless Open-Meteo/PVGIS/NASA profiles. "
        "Lands a bus + solar/wind generator(s) with p_max_pu. Needs a free "
        "renewables.ninja token (Settings → API keys); fetched live per request "
        "(the licence forbids caching)."
    ),
    targets=["carriers", "buses", "generators", "generators-p_max_pu"],
    country_coverage="global",
    requires_secrets=[_SECRET],
    filters=[
        Filter(id="date_from", label="From", kind="date", default="2019-01-01",
               description="Window start. MERRA-2 covers 2000–2019 (ERA5 to ~2023); a "
                           "single request must stay within one calendar year."),
        Filter(id="date_to", label="To", kind="date", default="2019-01-31",
               description="Window end (same calendar year as From)."),
        Filter(id="technologies", label="Technologies", kind="multiselect",
               default=["solar", "wind"], options=_TECHS),
        Filter(id="dataset", label="Reanalysis", kind="select", default="merra2",
               options=[{"value": "merra2", "label": "MERRA-2 (2000–2019)"},
                        {"value": "era5", "label": "ERA5 (2000–2023)"}]),
        Filter(id="capacity_mw", label="Capacity per generator (MW)", kind="number",
               default=100.0, min=0.0, step=10.0, unit="MW"),
    ],
)


class RenewablesNinja:
    meta = META

    async def _fetch_cf(self, ctx: ImportContext, url: str, params: dict[str, Any]) -> list[tuple[str, float]]:
        token = ctx.require_secret(_SECRET)
        try:
            body = await ctx.http.get_json(url, params=params, headers={"Authorization": f"Token {token}"})
        except RuntimeError as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg:
                raise PermissionError(
                    f"Renewables.ninja rejected the token. Check '{_SECRET}' in "
                    f"Settings → API keys."
                ) from None
            if "429" in msg:
                raise RuntimeError(
                    "Renewables.ninja rate limit hit (free tier: 6/min, 50/hour). "
                    "Wait a minute and retry."
                ) from None
            raise RuntimeError(f"Renewables.ninja request failed ({msg}).") from None
        return _series(body)

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        c = region.polygon.centroid
        lat, lon = round(float(c.y), 4), round(float(c.x), 4)
        date_from = str(filters.get("date_from") or "2019-01-01")
        date_to = str(filters.get("date_to") or "2019-01-31")
        dataset = str(filters.get("dataset") or "merra2")
        techs = _techs(filters)
        common = {"lat": lat, "lon": lon, "date_from": date_from, "date_to": date_to,
                  "dataset": dataset, "capacity": 1, "format": "json", "metadata": "false", "header": "false"}

        tasks = {}
        if "solar" in techs:
            tasks["solar"] = self._fetch_cf(ctx, _PV_URL, {**common, "system_loss": 0.1, "tracking": 0, "tilt": 35, "azim": 180})
        if "wind" in techs:
            tasks["wind"] = self._fetch_cf(ctx, _WIND_URL, {**common, "height": 100, "turbine": "Vestas V90 2000"})
        results = await asyncio.gather(*tasks.values())
        cf_by_tech = dict(zip(tasks.keys(), results))
        return FetchResult(META.id, region, dict(filters),
                           {"iso": _iso(region), "lat": lat, "lon": lon, "cf": cf_by_tech})

    def preview(self, result: FetchResult) -> PreviewSummary:
        cf = result.payload["cf"]
        hours = max((len(s) for s in cf.values()), default=0)
        notes = [f"Centroid ({result.payload['lat']}, {result.payload['lon']}): {hours} hourly points."]
        for tech, series in cf.items():
            if series:
                notes.append(f"{tech} mean CF ≈ {sum(v for _, v in series) / len(series):.2f}.")
        return PreviewSummary(
            counts={"generators": len([t for t, s in cf.items() if s]), "hours": hours},
            samples={"site": [{"lat": result.payload["lat"], "lon": result.payload["lon"]}]},
            notes=notes,
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        cf: dict[str, list[tuple[str, float]]] = result.payload["cf"]
        iso = result.payload["iso"]
        lat, lon = result.payload["lat"], result.payload["lon"]
        capacity = max(0.0, float(result.filters.get("capacity_mw") or 100.0))
        bus = f"re_ninja_{iso}"

        snaps = sorted({s for series in cf.values() for s, _ in series})
        gen_rows: list[dict] = []
        cf_by_gen: dict[str, dict[str, float]] = {}
        carriers = [{"name": "AC"}]
        for tech, series in cf.items():
            if not series:
                continue
            name = f"{tech}_ninja_{iso}"
            cf_by_gen[name] = {s: max(0.0, min(1.0, v)) for s, v in series}
            gen_rows.append({"name": name, "bus": bus, "carrier": tech,
                             "p_nom": capacity, "marginal_cost": 0.0, "x": lon, "y": lat})
            carriers.append({"name": tech, "co2_emissions": 0.0})

        frag = WorkbookFragment()
        if gen_rows and snaps:
            frag.sheets["carriers"] = carriers
            frag.sheets["buses"] = [{"name": bus, "carrier": "AC", "x": lon, "y": lat}]
            frag.sheets["generators"] = gen_rows
            frag.sheets["generators-p_max_pu"] = [
                {"snapshot": s, **{n: round(cf_by_gen[n][s], 4) for n in cf_by_gen if s in cf_by_gen[n]}}
                for s in snaps
            ]
            frag.snapshots = snaps
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps({s: len(r) for s, r in frag.sheets.items()}, sort_keys=True),
        )
        return frag


def build() -> Database:
    return RenewablesNinja()
