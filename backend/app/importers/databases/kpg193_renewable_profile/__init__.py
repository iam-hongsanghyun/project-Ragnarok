"""KPG193 — hourly per-bus renewable availability (generators-p_max_pu).

One of the four KPG193 datasets (siblings: ``kpg193`` [network],
``kpg193_renewable_capacity``, ``kpg193_demand_profile``). Reads the daily
``profile/renewables/renewables_<d>.csv`` files (PV / wind / hydro
capacity factors) for the selected window and emits a
``generators-p_max_pu`` time series.

A series is only attached to a generator that exists — so this importer
also reads the renewables_capacity CSVs (the chosen year) to learn which
``gen_<carrier>_<bus>`` generators the network actually has, and emits
p_max_pu only for those. Pair with the KPG193 renewable-capacity dataset.

Shared parsing / discovery helpers live in the ``kpg193`` package.
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
    PROFILE_DAYS_FILTER,
    PROFILE_START_FILTER,
    RENEWABLE_YEAR_FILTER,
    VERSION_FILTER,
    _build_renewable_generators,
    _build_renewable_profile,
    _capacity_paths,
    _fetch_profile_texts,
    _parse_renewable_csv,
    _profile_renewables_path,
    _raw_url,
    _resolve_profile_window,
    _resolve_renewable_year,
    _resolve_version_dir,
)

META = DatabaseMeta(
    id="kpg193_renewable_profile",
    name="KPG193 — hourly renewable availability (per bus)",
    short_name="Renewable profile",
    source_id=KPG193_SOURCE_ID,
    source_label=KPG193_SOURCE_LABEL,
    depends_on=["kpg193_renewable_capacity"],
    category="generation",
    subcategory="Hourly profiles",
    license="See agm-center/kpg-testgrid (academic / research use)",
    homepage="https://github.com/agm-center/kpg-testgrid",
    version_hint="latest (discovered)",
    description=(
        "Hourly per-bus PV / wind / hydro capacity factors, from the "
        "profile/renewables daily CSVs. Lands as a generators-p_max_pu (0-1) "
        "time series driving the renewable generators (gen_<carrier>_<bus>) — "
        "only generators that exist for the chosen capacity year get a series. "
        "Choose the start date and number of days."
    ),
    targets=["generators-p_max_pu"],
    available=True,
    country_coverage=["KOR"],
    requires_secrets=[],
    filters=[VERSION_FILTER, RENEWABLE_YEAR_FILTER, PROFILE_START_FILTER,
             PROFILE_DAYS_FILTER],
)


async def _fetch_optional(ctx: ImportContext, path: str) -> str | None:
    try:
        return await ctx.http.get_text(_raw_url(path))
    except Exception:
        return None


class Kpg193RenewableProfile:
    meta = META

    async def fetch(
        self, region: Region, filters: dict[str, Any], ctx: ImportContext
    ) -> FetchResult:
        vd = await _resolve_version_dir(ctx, filters)
        version_dir = vd["version_dir"]
        year = await _resolve_renewable_year(ctx, version_dir, filters)

        # Learn which renewable generators exist (so we only emit p_max_pu
        # columns the network will actually have).
        caps = _capacity_paths(version_dir, year)
        renewables: list[dict[str, Any]] = []
        for carrier, key in (("solar", "solar_path"), ("wind", "wind_path"),
                             ("hydro", "hydro_path")):
            text = await _fetch_optional(ctx, caps[key])
            if text:
                renewables.extend(_parse_renewable_csv(text, carrier))
        existing_gen_names = {
            g["name"] for g in _build_renewable_generators(renewables)
        }

        window = _resolve_profile_window(filters)
        paths = [_profile_renewables_path(version_dir, d) for d in window]
        texts = await _fetch_profile_texts(ctx, paths)
        p_max_pu_rows, snapshots = _build_renewable_profile(
            window, texts, existing_gen_names
        )

        sheets: dict[str, list[dict[str, Any]]] = {}
        if any(len(r) > 1 for r in p_max_pu_rows):
            sheets["generators-p_max_pu"] = p_max_pu_rows

        renewable_series = max((len(r) - 1 for r in p_max_pu_rows), default=0)
        payload = {
            "version_tag": vd["version_tag"],
            "renewable_year": year,
            "sheets": sheets,
            "snapshots": snapshots,
            "counts": {"snapshots": len(snapshots),
                       "renewable_series": renewable_series},
        }
        return FetchResult(META.id, region, dict(filters), payload)

    def preview(self, result: FetchResult) -> PreviewSummary:
        counts = result.payload["counts"]
        snaps = result.payload["snapshots"]
        span = f"{snaps[0]} → {snaps[-1]}" if snaps else "—"
        note = (
            f"KPG193 {result.payload['version_tag']} renewable profile "
            f"({result.payload['renewable_year']} fleet): "
            f"{counts['snapshots']} hourly snapshots ({span}), "
            f"{counts['renewable_series']} generator series."
        )
        return PreviewSummary(
            counts=counts,
            samples={"hours": [
                {"snapshot": r["snapshot"],
                 "gen_solar_1": r.get("gen_solar_1"),
                 "gen_wind_1": r.get("gen_wind_1")}
                for r in result.payload["sheets"].get("generators-p_max_pu", [])[:24]
            ]},
            notes=[note],
        )

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment:
        sheets = result.payload["sheets"]
        frag = WorkbookFragment()
        frag.sheets = sheets
        snapshots = result.payload.get("snapshots") or []
        if snapshots:
            frag.snapshots = list(snapshots)
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
    return Kpg193RenewableProfile()
