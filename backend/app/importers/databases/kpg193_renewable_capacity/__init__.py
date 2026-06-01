"""KPG193 — per-bus renewable nameplate capacity (PV / wind / hydro).

One of the four KPG193 datasets (see the sibling packages ``kpg193``
[network], ``kpg193_demand_profile``, ``kpg193_renewable_profile``).
This one reads the ``renewables_capacity/{solar,wind,hydro}_generators_
<year>.csv`` files and emits PyPSA Generator rows — the renewable fleet
that pairs with the thermal fleet in the network dataset.

Shared parsing / discovery helpers live in the ``kpg193`` package and are
reused here so the four datasets stay byte-for-byte consistent.
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
    PreviewSummary,
    Provenance,
    Region,
    WorkbookFragment,
)
from ..kpg193 import (
    KPG193_SOURCE_ID,
    KPG193_SOURCE_LABEL,
    RENEWABLE_YEAR_FILTER,
    VERSION_FILTER,
    _build_renewable_generators,
    _capacity_paths,
    _parse_renewable_csv,
    _raw_url,
    _resolve_renewable_year,
    _resolve_version_dir,
)

META = DatabaseMeta(
    id="kpg193_renewable_capacity",
    name="KPG193 — renewable capacity (per bus)",
    short_name="Renewable capacity",
    source_id=KPG193_SOURCE_ID,
    source_label=KPG193_SOURCE_LABEL,
    depends_on=["kpg193_network"],
    category="generation",
    subcategory="Renewable capacity",
    license="See agm-center/kpg-testgrid (academic / research use)",
    homepage="https://github.com/agm-center/kpg-testgrid",
    version_hint="latest (discovered)",
    description=(
        "Per-bus solar / wind / hydro nameplate capacity, from the "
        "renewables_capacity CSVs. Emits PyPSA Generator rows "
        "(gen_<carrier>_<bus>) on the network's buses, alongside the thermal "
        "fleet. Pick the capacity year; versions and years are discovered from "
        "the repo."
    ),
    targets=["generators", "carriers"],
    available=True,
    country_coverage=["KOR"],
    requires_secrets=[],
    filters=[VERSION_FILTER, RENEWABLE_YEAR_FILTER],
)


async def _fetch_optional(ctx: ImportContext, path: str) -> str | None:
    """Renewable CSV may be absent for a (version, carrier) tuple."""
    try:
        return await ctx.http.get_text(_raw_url(path))
    except Exception:
        return None


class Kpg193RenewableCapacity:
    meta = META

    async def fetch(
        self, region: Region, filters: dict[str, Any], ctx: ImportContext
    ) -> FetchResult:
        vd = await _resolve_version_dir(ctx, filters)
        version_dir = vd["version_dir"]
        year = await _resolve_renewable_year(ctx, version_dir, filters)
        caps = _capacity_paths(version_dir, year)

        renewables: list[dict[str, Any]] = []
        for carrier, key in (("solar", "solar_path"), ("wind", "wind_path"),
                             ("hydro", "hydro_path")):
            text = await _fetch_optional(ctx, caps[key])
            if text:
                renewables.extend(_parse_renewable_csv(text, carrier))

        generators = _build_renewable_generators(renewables)
        carriers_present = sorted(
            {g["carrier"] for g in generators if g.get("carrier")}
        )
        carriers = [{"name": name} for name in carriers_present]

        sheets: dict[str, list[dict[str, Any]]] = {
            "carriers": carriers,
            "generators": generators,
        }
        by_carrier: dict[str, int] = {}
        for g in generators:
            by_carrier[g["carrier"]] = by_carrier.get(g["carrier"], 0) + 1
        payload = {
            "version_tag": vd["version_tag"],
            "renewable_year": year,
            "sheets": sheets,
            "counts": {"generators": len(generators), **{
                f"carrier:{c}": n for c, n in by_carrier.items()
            }},
        }
        return FetchResult(META.id, region, dict(filters), payload)

    def preview(self, result: FetchResult) -> PreviewSummary:
        counts = result.payload["counts"]
        gens = result.payload["sheets"].get("generators", [])
        note = (
            f"KPG193 {result.payload['version_tag']} renewables "
            f"{result.payload['renewable_year']}: {counts['generators']} "
            f"generators across {len([k for k in counts if k.startswith('carrier:')])} "
            f"carriers."
        )
        return PreviewSummary(
            counts=counts,
            samples={"generators": [
                {"name": g.get("name"), "bus": g.get("bus"),
                 "carrier": g.get("carrier"), "p_nom": g.get("p_nom")}
                for g in gens[:10]
            ]},
            notes=[note],
        )

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment:
        sheets = result.payload["sheets"]
        frag = WorkbookFragment()
        frag.sheets = sheets
        row_counts = {k: len(v) for k, v in sheets.items()}
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps({"version": result.payload["version_tag"],
                        "renewable_year": result.payload["renewable_year"]},
                       sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return Kpg193RenewableCapacity()
