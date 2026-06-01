"""KPG193 — hourly per-bus demand profile (loads-p_set / loads-q_set).

One of the four KPG193 datasets (siblings: ``kpg193`` [network],
``kpg193_renewable_capacity``, ``kpg193_renewable_profile``). Reads the
daily ``profile/demand/daily_demand_<d>.csv`` files for the selected
window and emits the hourly time series for the per-bus loads — pair it
with the KPG193 network dataset (whose loads, ``load_<bus>``, these
columns drive).

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
    VERSION_FILTER,
    _build_load_profile,
    _fetch_profile_texts,
    _profile_demand_path,
    _resolve_profile_window,
    _resolve_version_dir,
)

META = DatabaseMeta(
    id="kpg193_demand_profile",
    name="KPG193 — hourly demand profile (per bus)",
    short_name="Demand profile",
    source_id=KPG193_SOURCE_ID,
    source_label=KPG193_SOURCE_LABEL,
    depends_on=["kpg193_network"],
    category="demand",
    subcategory="Hourly profiles",
    license="See agm-center/kpg-testgrid (academic / research use)",
    homepage="https://github.com/agm-center/kpg-testgrid",
    version_hint="latest (discovered)",
    description=(
        "Hourly per-bus electricity demand, from the profile/demand daily "
        "CSVs. Lands as loads-p_set (active, MW) and loads-q_set (reactive, "
        "MVAr) time series, one column per bus load (load_<bus>), driving the "
        "network's loads. Choose the start date and number of days."
    ),
    targets=["loads-p_set", "loads-q_set"],
    available=True,
    country_coverage=["KOR"],
    requires_secrets=[],
    filters=[VERSION_FILTER, PROFILE_START_FILTER, PROFILE_DAYS_FILTER],
)


class Kpg193DemandProfile:
    meta = META

    async def fetch(
        self, region: Region, filters: dict[str, Any], ctx: ImportContext
    ) -> FetchResult:
        vd = await _resolve_version_dir(ctx, filters)
        window = _resolve_profile_window(filters)
        paths = [_profile_demand_path(vd["version_dir"], d) for d in window]
        texts = await _fetch_profile_texts(ctx, paths)
        p_set_rows, q_set_rows, snapshots = _build_load_profile(window, texts)

        sheets: dict[str, list[dict[str, Any]]] = {}
        if p_set_rows:
            sheets["loads-p_set"] = p_set_rows
        if any(len(r) > 1 for r in q_set_rows):
            sheets["loads-q_set"] = q_set_rows

        load_series = max((len(r) - 1 for r in p_set_rows), default=0)
        payload = {
            "version_tag": vd["version_tag"],
            "sheets": sheets,
            "snapshots": snapshots,
            "counts": {"snapshots": len(snapshots), "load_series": load_series},
        }
        return FetchResult(META.id, region, dict(filters), payload)

    def preview(self, result: FetchResult) -> PreviewSummary:
        counts = result.payload["counts"]
        snaps = result.payload["snapshots"]
        span = f"{snaps[0]} → {snaps[-1]}" if snaps else "—"
        note = (
            f"KPG193 {result.payload['version_tag']} demand: "
            f"{counts['snapshots']} hourly snapshots ({span}), "
            f"{counts['load_series']} bus-load series."
        )
        return PreviewSummary(
            counts=counts,
            samples={"hours": [
                {"snapshot": r["snapshot"],
                 "load_1": r.get("load_1"), "load_2": r.get("load_2")}
                for r in result.payload["sheets"].get("loads-p_set", [])[:24]
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
            json.dumps({"version": result.payload["version_tag"]},
                       sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return Kpg193DemandProfile()
