"""Ragnarok demand database - self-hosted historical hourly load (TODO D2).

Serves the snapshot built by ``python -m backend.app.importers.demand_db.refresh``: per-area
parquet slices of hourly demand (MW, UTC, hour-beginning) from Open Power System Data (EU
2015-2020), EIA Form-930 (US balancing authorities) and, where a token was configured at refresh
time, ENTSO-E. No upstream call happens here - the point is offline / rate-limit-free access.

Region / years come from the manifest (what is *actually* stored): the series select lists it,
the year bounds follow its coverage, and "auto" picks the best national series for the country
selected on the map. Output matches the other demand importers: one national bus, one Load, an
hourly ``loads-p_set`` series and the snapshot labels ``YYYY-MM-DD HH:00`` (UTC, hour-beginning).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ...context import ImportContext
from ...demand_db import catalogue, parsers, store
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

_NO_SNAPSHOT = (
    "No demand snapshot has been built yet - run "
    "`python -m backend.app.importers.demand_db.refresh` (see docs/backend.md, Demand database)."
)
_FALLBACK_COUNTRIES = ["USA", "DEU", "FRA", "GBR"]


def _slug(raw: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_") or "load"


def build_meta() -> DatabaseMeta:
    """Meta computed from the manifest on every call (cheap), so a refresh shows up without a restart."""
    slices = store.load_manifest()["slices"]
    options: list[dict[str, str]] = [{"value": "auto", "label": "Auto - best national series for the selected country"}]
    countries: set[str] = set()
    for key in sorted(slices):
        e = slices[key]
        y = e.get("years") or []
        span = f"{min(y)}-{max(y)}" if y else "n/a"
        options.append({"value": key, "label": f"{key} - {e.get('label', '')} ({span}, {e.get('source')})"})
        if e.get("iso3"):
            countries.add(e["iso3"])
    all_years = sorted({y for e in slices.values() for y in e.get("years", [])})
    lo, hi = (all_years[0], all_years[-1]) if all_years else (2015, 2020)
    default_year = 2019 if lo <= 2019 <= hi else hi
    available = bool(slices)
    return DatabaseMeta(
        id="demand_db",
        name="Ragnarok demand database - self-hosted hourly load (OPSD / EIA-930 / ENTSO-E)",
        short_name="Demand DB",
        category="demand",
        subcategory="Hourly profiles",
        license="Per series: EIA public domain; OPSD MIT + ENTSO-E reuse with attribution (see manifest)",
        homepage="https://data.open-power-system-data.org/time_series/",
        version_hint=f"snapshot {store.load_manifest().get('generated_at') or 'not built'}",
        description=(
            "Historical hourly electricity demand served from Ragnarok's own offline snapshot - no "
            "per-user API calls or keys. Series are national ENTSO-E Actual Total Load via Open "
            "Power System Data (EU, 2015 to Sep 2020), US balancing-authority demand from EIA-930, "
            "and ENTSO-E where a token was used at refresh time. All in MW, UTC, hour-beginning. "
            "Lands as a national bus + a Load + an hourly loads-p_set series. Pick the year window; "
            "short gaps are linearly interpolated (and counted in the preview)."
        ),
        targets=["buses", "loads", "loads-p_set", "carriers"],
        country_coverage=sorted(countries) if countries else _FALLBACK_COUNTRIES,
        requires_secrets=[],
        available=available,
        unavailable_reason=None if available else _NO_SNAPSHOT,
        filters=[
            Filter(id="series", label="Series", kind="select", default="auto", options=options,
                   description="source/area slice stored in the snapshot; 'auto' picks the national series for the selected country with most coverage of the years asked."),
            Filter(id="year_from", label="From year", kind="number", default=default_year, min=lo, max=hi, step=1,
                   description="First UTC calendar year (inclusive)."),
            Filter(id="year_to", label="To year", kind="number", default=default_year, min=lo, max=hi, step=1,
                   description="Last UTC calendar year (inclusive)."),
            Filter(id="fill_gaps", label="Interpolate gaps", kind="toggle", default=True,
                   description="Fill missing hours inside the window by linear interpolation so the snapshot axis is regular; edge gaps are trimmed."),
        ],
    )


def regularise(df: pd.DataFrame, fill_gaps: bool) -> tuple[pd.DataFrame, int]:
    """Put ``df`` (timestamp, load_mw) on a regular hourly grid; returns ``(frame, filled_hours)``.

    With ``fill_gaps`` interior holes are linearly interpolated in time; without it the frame is
    returned as stored (irregular). The window never grows: leading / trailing gaps are not invented.
    """
    if df.empty or not fill_gaps:
        return df[["timestamp", "load_mw"]].reset_index(drop=True), 0
    s = df.set_index("timestamp")["load_mw"].sort_index()
    grid = pd.date_range(s.index.min(), s.index.max(), freq="h", tz="UTC")
    missing = int(len(grid) - len(s))
    full = s.reindex(grid).interpolate(method="time")
    out = pd.DataFrame({"timestamp": full.index, "load_mw": full.to_numpy()})
    return out, missing


class DemandDb:
    @property
    def meta(self) -> DatabaseMeta:  # dynamic: reflects the current manifest
        return build_meta()

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        meta = self.meta
        if not meta.available:
            raise RuntimeError(meta.unavailable_reason or _NO_SNAPSHOT)
        y0 = int(filters.get("year_from") or 2019)
        y1 = int(filters.get("year_to") or y0)
        if y1 < y0:
            raise ValueError(f"year_to {y1} is before year_from {y0}")
        try:
            key = store.resolve_key(str(filters.get("series") or "auto"), region.country_iso, y0, y1)
        except KeyError as exc:
            raise RuntimeError(str(exc.args[0])) from None
        entry = store.load_manifest()["slices"][key]
        raw = await asyncio.to_thread(store.read_slice, key, y0, y1)
        if raw.empty:
            raise RuntimeError(
                f"{key} has no hours in {y0}-{y1}; stored years: {entry.get('years')} "
                f"({entry['coverage_start'][:10]} .. {entry['coverage_end'][:10]})."
            )
        fill = filters.get("fill_gaps", True)
        fill = fill if isinstance(fill, bool) else str(fill).lower() not in ("0", "false", "no")
        frame, filled = regularise(raw, fill)
        return FetchResult(
            meta.id, region, dict(filters),
            {"key": key, "entry": entry, "frame": frame, "stored_hours": int(len(raw)), "filled_hours": filled,
             "year_from": y0, "year_to": y1},
            notes=[f"{filled} gap hour(s) interpolated"] if filled else [],
        )

    def preview(self, result: FetchResult) -> PreviewSummary:
        p = result.payload
        frame: pd.DataFrame = p["frame"]
        stats = parsers.summary_stats(frame)
        counts: dict[str, int] = {"loads": 1, "hours": int(len(frame)), "filled_hours": int(p["filled_hours"])}
        if stats.get("hours"):
            counts["peak_mw"] = int(round(stats["peak_mw"]))
            counts["mean_mw"] = int(round(stats["mean_mw"]))
        e = p["entry"]
        return PreviewSummary(
            counts=counts,
            samples={"hours": [
                {"snapshot": t.strftime("%Y-%m-%d %H:00"), "value": round(float(v), 1)}
                for t, v in zip(frame["timestamp"].head(24), frame["load_mw"].head(24))
            ]},
            notes=[
                f"{e['label']} ({p['key']}): {len(frame)} hourly points {p['year_from']}-{p['year_to']}, "
                f"{stats.get('energy_twh', 0)} TWh; MW, UTC, hour-beginning. Snapshot retrieved {e.get('retrieved_at')}.",
                f"Licence: {e['licence']}. Attribution: {e['attribution']}.",
                *result.notes,
            ],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        p = result.payload
        key: str = p["key"]
        entry = p["entry"]
        frame: pd.DataFrame = p["frame"]
        source, area = store.split_key(key)
        iso = entry.get("iso3") or result.region.country_iso
        frag = WorkbookFragment()
        load_name = _slug(f"{area if source == 'eia930' else iso}_demand")
        snaps = [t.strftime("%Y-%m-%d %H:00") for t in frame["timestamp"]]
        values = [float(v) for v in frame["load_mw"]]
        if snaps:
            bus = _slug(area) if source == "eia930" else (result.region.country_iso or iso)
            try:
                c = result.region.polygon.centroid
                bx, by = float(c.x), float(c.y)
            except Exception:  # noqa: BLE001
                bx, by = "", ""
            frag.sheets["carriers"] = [{"name": "AC"}]
            frag.sheets["buses"] = [{"name": bus, "x": bx, "y": by, "carrier": "AC", "country": iso,
                                     "source": f"Ragnarok demand DB ({source})"}]
            frag.sheets["loads"] = [{
                "name": load_name, "bus": bus, "carrier": "AC", "country": iso,
                "source": f"Ragnarok demand DB / {catalogue.SOURCES[source]['label']}",
                "source_url": (entry.get("raw_files") or [{}])[0].get("url") or catalogue.SOURCES[source]["homepage"],
                "series": key, "series_label": entry.get("label", ""),
                "licence": entry.get("licence", ""),
            }]
            frag.sheets["loads-p_set"] = [{"snapshot": s, load_name: v} for s, v in zip(snaps, values)]
            frag.snapshots = snaps
        row_counts = {s: len(r) for s, r in frag.sheets.items()}
        frag.provenance = Provenance(
            "demand_db", result.region.country_iso, result.region.country_name,
            json.dumps({**result.filters, "resolved_series": key, "slice_sha256": entry.get("sha256")}, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return DemandDb()
