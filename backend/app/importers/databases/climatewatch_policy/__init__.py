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
        Filter(id="reduction_pct", label="Reduction vs baseline (%)", kind="number",
               default=100.0, min=0.0, max=100.0, step=5.0,
               description="Cut vs the baseline year. 100 = net zero (cap 0)."),
    ],
)


class ClimateWatchPolicy:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        iso = (region.country_iso or "").strip().upper()
        if not iso:
            raise RuntimeError("Climate Watch: no country selected.")
        try:
            body = await ctx.http.get_json(_API, params={"regions": iso, "source": "Climate Watch"})
        except RuntimeError as exc:
            raise RuntimeError(f"Climate Watch request failed ({exc}).") from None
        records = (body or {}).get("data") or []
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
        constant_t = round(baseline_mt * _MT_TO_T * (1.0 - reduction / 100.0), 1)
        return {
            "ok": True, "base_year_used": chosen, "baseline_mt": baseline_mt,
            "target_year": target_year, "reduction": reduction, "constant_t": constant_t,
        }

    def preview(self, result: FetchResult) -> PreviewSummary:
        cap = self._cap(result)
        if not cap["ok"]:
            return PreviewSummary(counts={}, samples={}, notes=[cap["reason"]])
        return PreviewSummary(
            counts={"global_constraints": 1, "cap_MtCO2": round(cap["constant_t"] / _MT_TO_T, 2)},
            samples={"constraint": [{"target_year": cap["target_year"], "cap_tCO2": cap["constant_t"]}]},
            notes=[
                f"{result.payload['iso']} {result.payload['sector_label']} baseline "
                f"{cap['baseline_mt']:.1f} MtCO₂ ({cap['base_year_used']}, gas {result.payload['gas']}).",
                f"Cap {cap['reduction']:.0f}% below baseline by {cap['target_year']} "
                f"→ {cap['constant_t'] / _MT_TO_T:.2f} MtCO₂.",
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
                           f"−{cap['reduction']:.0f}% by {cap['target_year']}"),
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
