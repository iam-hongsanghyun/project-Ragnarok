"""Climate Watch — emissions-target snapshot → a CO₂ cap global constraint (I8).

Turns a country's climate target into a PyPSA ``global_constraints`` row so a
capacity-expansion run can be bound against an emissions path, instead of the
user hand-typing a tonnage. The **data-grounded** half — the baseline emissions
level — is fetched live from Climate Watch's keyless API (historical emissions,
CC-BY); the **policy** half (target year + % reduction vs the base year, e.g. a
net-zero pledge) is a filter, with defaults set to a net-zero-by-2050 headline.

Lands one ``primary_energy`` / ``co2_emissions`` constraint:

    constant [tCO₂] = baseline_emissions(base_year) × (1 − reduction% / 100)

Baseline is Climate Watch CO₂ for the chosen sector (Electricity/Heat by default,
so the cap matches a power-system model's scope), converted MtCO₂ → tCO₂.
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

_API = "https://www.climatewatchdata.org/api/v1/data/historical_emissions"

# Filter value → the exact Climate Watch ``sector`` label (the API ignores the
# ``sectors`` query param, so we match client-side).
_SECTORS = {
    "electricity": "Electricity/Heat",
    "energy": "Energy",
    "total": "Total excluding LULUCF",
}
_MT_TO_T = 1_000_000.0
_HOURS_PER_YEAR = 8760.0


def _pick_series(records: list[dict], sector_label: str) -> tuple[dict[int, float], str]:
    """Return ``({year: MtCO₂}, gas_used)`` for the sector, preferring CO₂ then
    falling back to All GHG."""
    for gas in ("CO2", "All GHG"):
        for r in records:
            if r.get("sector") == sector_label and r.get("gas") == gas:
                pts: dict[int, float] = {}
                for p in r.get("emissions") or []:
                    yr, val = p.get("year"), p.get("value")
                    if isinstance(yr, int) and isinstance(val, (int, float)):
                        pts[yr] = float(val)
                if pts:
                    return pts, gas
    return {}, ""


META = DatabaseMeta(
    id="climatewatch_policy",
    name="Climate Watch — emissions target → CO₂ cap",
    short_name="Emissions target",
    source_id="climatewatch",
    source_label="Climate Watch (policy)",
    category="policy",
    subcategory="Constraints",
    license="Climate Watch (CC-BY 4.0)",
    homepage="https://www.climatewatchdata.org/",
    version_hint="Climate Watch historical emissions API",
    description=(
        "Bound a run against a country's climate target: a CO₂ emission cap "
        "global constraint whose baseline is Climate Watch's historical emissions "
        "(keyless, CC-BY) and whose trajectory (target year + % reduction) you "
        "set. Defaults to net-zero by 2050 on the Electricity/Heat sector."
    ),
    targets=["global_constraints"],
    country_coverage="global",
    requires_secrets=[],
    filters=[
        Filter(id="sector", label="Sector", kind="select", default="electricity",
               options=[{"value": "electricity", "label": "Electricity & heat"},
                        {"value": "energy", "label": "Energy (all)"},
                        {"value": "total", "label": "Economy-wide (excl. LULUCF)"}],
               description="Which emissions to use as the cap baseline. Electricity/Heat "
                           "matches a power-system model's scope."),
        Filter(id="base_year", label="Baseline year", kind="number", default=2022,
               min=1990, max=2023, step=1,
               description="Year whose emissions set the baseline (nearest available is used)."),
        Filter(id="target_year", label="Target year", kind="number", default=2050,
               min=2000, max=2100, step=1,
               description="Year the cap applies to."),
        Filter(id="window_hours", label="Modelled hours", kind="number", default=8760,
               min=1, max=8784, step=1, unit="h",
               description="Hours the model's snapshots cover (sum of snapshot weightings). "
                           "The cap is an annual tonnage, so it is scaled by hours/8760; "
                           "leave 8760 only for a full-year model."),
        Filter(id="reduction_pct", label="Reduction vs baseline (%)", kind="number",
               default=100.0, min=0.0, max=100.0, step=5.0,
               description="Cut vs the baseline year. 100 = net zero (cap 0)."),
    ],
)


_PER_PAGE = 200
_MAX_PAGES = 20


async def _fetch_records(ctx: ImportContext, iso: str) -> list[dict]:
    """All historical-emissions records for ``iso``, following pagination.

    The API returns the records in pages; the sector/gas we want can sit beyond
    page 1. Follows ``meta.next_page`` (or ``meta.total_pages``) when present;
    an unpaginated body simply ends after the first request.
    """
    records: list[dict] = []
    page = 1
    for _ in range(_MAX_PAGES):
        try:
            body = await ctx.http.get_json(_API, params={
                "regions": iso, "source": "Climate Watch",
                "page": page, "per_page": _PER_PAGE,
            })
        except RuntimeError as exc:
            raise RuntimeError(f"Climate Watch request failed ({exc}).") from None
        records.extend((body or {}).get("data") or [])
        meta = (body or {}).get("meta") or {}
        pag = meta.get("pagination") if isinstance(meta.get("pagination"), dict) else meta
        nxt = pag.get("next_page")
        total_pages = pag.get("total_pages")
        if isinstance(nxt, int) and nxt > page:
            page = nxt
        elif isinstance(total_pages, int) and page < total_pages:
            page += 1
        else:
            break
    return records


class ClimateWatchPolicy:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        iso = (region.country_iso or "").strip().upper()
        if not iso:
            raise RuntimeError("Climate Watch: no country selected.")
        records = await _fetch_records(ctx, iso)
        sector_key = str(filters.get("sector") or "electricity")
        sector_label = _SECTORS.get(sector_key, _SECTORS["electricity"])
        series, gas = _pick_series(records, sector_label)
        return FetchResult(META.id, region, dict(filters),
                           {"iso": iso, "series": series, "gas": gas, "sector_label": sector_label})

    def _cap(self, result: FetchResult) -> dict[str, Any]:
        f = result.filters
        series: dict[int, float] = result.payload["series"]
        base_year = int(f.get("base_year") or 2022)
        target_year = int(f.get("target_year") or 2050)
        reduction = max(0.0, min(100.0, float(f.get("reduction_pct") if f.get("reduction_pct") is not None else 100.0)))
        if not series:
            return {"ok": False, "reason": "No CO₂ emissions published for this country/sector."}
        # Nearest available year ≤ base_year, else the closest year overall.
        years = sorted(series)
        chosen = max([y for y in years if y <= base_year], default=None) or min(years, key=lambda y: abs(y - base_year))
        baseline_mt = series[chosen]
        annual_t = baseline_mt * _MT_TO_T * (1.0 - reduction / 100.0)
        try:
            window_h = float(f.get("window_hours") if f.get("window_hours") not in (None, "") else _HOURS_PER_YEAR)
        except (TypeError, ValueError):
            window_h = _HOURS_PER_YEAR
        if not window_h > 0:
            window_h = _HOURS_PER_YEAR
        # PyPSA's primary_energy constant bounds the emissions summed over the
        # modelled (weighted) snapshots, so an annual tonnage must be pro-rated.
        constant_t = round(annual_t * window_h / _HOURS_PER_YEAR, 1)
        return {
            "ok": True, "base_year_used": chosen, "baseline_mt": baseline_mt,
            "target_year": target_year, "reduction": reduction, "constant_t": constant_t,
            "annual_t": round(annual_t, 1), "window_hours": window_h,
        }

    def preview(self, result: FetchResult) -> PreviewSummary:
        cap = self._cap(result)
        if not cap["ok"]:
            return PreviewSummary(counts={}, samples={}, notes=[cap["reason"]])
        extra: list[str] = []
        if result.payload["gas"] != "CO2":
            extra.append("WARNING: no CO₂-only series published; baseline is All GHG "
                         "(CO₂e), which overstates a CO₂ cap.")
        if cap["window_hours"] == _HOURS_PER_YEAR:
            extra.append("Cap is an annual tonnage (window = 8760 h); set 'Modelled hours' "
                         "if the model covers fewer hours.")
        return PreviewSummary(
            counts={"global_constraints": 1, "cap_MtCO2": round(cap["constant_t"] / _MT_TO_T, 2)},
            samples={"constraint": [{"target_year": cap["target_year"], "cap_tCO2": cap["constant_t"]}]},
            notes=[
                f"{result.payload['iso']} {result.payload['sector_label']} baseline "
                f"{cap['baseline_mt']:.1f} MtCO₂ ({cap['base_year_used']}, gas {result.payload['gas']}).",
                f"Cap {cap['reduction']:.0f}% below baseline by {cap['target_year']} "
                f"→ {cap['annual_t'] / _MT_TO_T:.2f} MtCO₂/yr, {cap['constant_t'] / _MT_TO_T:.4f} "
                f"MtCO₂ over {cap['window_hours']:.0f} h.",
                *extra,
            ],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        cap = self._cap(result)
        frag = WorkbookFragment()
        if cap["ok"]:
            frag.sheets["global_constraints"] = [{
                "name": f"co2_limit_{cap['target_year']}",
                "type": "primary_energy",
                "carrier_attribute": "co2_emissions",
                "sense": "<=",
                "constant": cap["constant_t"],
                "source": (f"Climate Watch {result.payload['sector_label']} baseline "
                           f"{cap['baseline_mt']:.1f} MtCO₂ ({cap['base_year_used']}), "
                           f"−{cap['reduction']:.0f}% by {cap['target_year']}; annual "
                           f"{cap['annual_t']:.0f} t scaled to {cap['window_hours']:.0f} h"
                           + ("" if result.payload["gas"] == "CO2"
                              else "; gas = All GHG (CO2e), not CO2")),
            }]
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps({s: len(r) for s, r in frag.sheets.items()}, sort_keys=True),
        )
        return frag


def build() -> Database:
    return ClimateWatchPolicy()
