"""Elexon Insights (Great Britain) — hourly demand & renewable profiles.

Great Britain left ENTSO-E's real-time reporting after Brexit, so its
authoritative hourly data comes from Elexon's keyless BMRS "Insights" API
(``data.elexon.co.uk``). Two datasets share the source:

  • demand — Initial National Demand Outturn (INDO, MW) → a Load + loads-p_set.
  • renewable profiles — actual generation per fuel type (MW), peak-normalised
    into ``generators-p_max_pu`` for solar / onshore wind / offshore wind.

Half-hourly settlement periods are averaged onto an hourly grid; timestamps are
UTC. No API key required.
"""
from __future__ import annotations

import json
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

_API = "https://data.elexon.co.uk/bmrs/api/v1"
_SOURCE_ID = "elexon"
_SOURCE_LABEL = "Elexon — Great Britain (BMRS)"

# Elexon psrType → PyPSA carrier, for the variable renewables we profile.
_VRE_PSRTYPE = {"Solar": "solar", "Wind Onshore": "onwind", "Wind Offshore": "offwind"}

_DATE_FILTERS = [
    Filter(id="date_from", label="From", kind="date", default="2024-01-01",
           description="Start of the hourly window (inclusive, UTC)."),
    Filter(id="date_to", label="To", kind="date", default="2024-01-07",
           description="End of the hourly window (inclusive, UTC). Keep it short — "
                       "half-hourly settlement data is large."),
]


def _win(filters: dict[str, Any]) -> tuple[str, str]:
    return (str(filters.get("date_from") or "2024-01-01"), str(filters.get("date_to") or "2024-01-07"))


def _snap(iso: str) -> str:
    """ISO UTC stamp → ``YYYY-MM-DD HH:00`` (the settlement half-hour's hour)."""
    s = str(iso)
    return f"{s[0:10]} {s[11:13]}:00" if len(s) >= 13 else s


def _hourly_mean(pairs: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Average (usually two) half-hourly points onto the hourly grid, sorted."""
    buckets: dict[str, list[float]] = {}
    for iso, val in pairs:
        buckets.setdefault(_snap(iso), []).append(val)
    return [(k, sum(v) / len(v)) for k, v in sorted(buckets.items()) if v]


def _gb_bus(region: Region) -> dict[str, Any]:
    try:
        c = region.polygon.centroid
        x, y = float(c.x), float(c.y)
    except Exception:
        x, y = -1.5, 53.0
    return {"name": "GBR", "x": x, "y": y, "carrier": "AC", "country": "GBR", "source": "Elexon BMRS"}


async def _get(ctx: ImportContext, path: str, params: dict[str, str], what: str) -> Any:
    try:
        return await ctx.http.get_json(f"{_API}{path}", params={**params, "format": "json"})
    except RuntimeError as exc:
        raise RuntimeError(f"Elexon {what} request failed ({exc}).") from None


# ── Demand dataset ────────────────────────────────────────────────────────────
_DEMAND_META = DatabaseMeta(
    id="elexon_demand",
    name="Elexon — GB hourly demand (National Demand Outturn)",
    short_name="GB demand",
    source_id=_SOURCE_ID, source_label=_SOURCE_LABEL,
    category="demand", subcategory="Hourly profiles",
    license="Elexon Insights (free, open)",
    homepage="https://bmrs.elexon.co.uk/",
    version_hint="Elexon BMRS Insights API v1",
    description=(
        "Great Britain's hourly electricity demand (Initial National Demand "
        "Outturn) from Elexon's keyless BMRS API. Lands one GB bus + a Load + "
        "hourly loads-p_set (UTC; half-hourly periods averaged to hourly)."
    ),
    targets=["buses", "loads", "loads-p_set", "carriers"],
    country_coverage=["GBR"], requires_secrets=[],
    filters=list(_DATE_FILTERS),
)


class ElexonDemand:
    meta = _DEMAND_META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        df, dt = _win(filters)
        body = await _get(ctx, "/demand/outturn",
                          {"settlementDateFrom": df, "settlementDateTo": dt}, "demand")
        pairs: list[tuple[str, float]] = []
        for row in (body or {}).get("data") or []:
            t = row.get("startTime")
            mw = row.get("initialDemandOutturn")
            if t is not None and mw is not None:
                try:
                    pairs.append((str(t), float(mw)))
                except (TypeError, ValueError):
                    continue
        return FetchResult(_DEMAND_META.id, region, dict(filters), {"hourly": _hourly_mean(pairs)})

    def preview(self, result: FetchResult) -> PreviewSummary:
        hourly = result.payload["hourly"]
        vals = [v for _, v in hourly]
        counts = {"loads": 1 if hourly else 0, "hours": len(hourly)}
        if vals:
            counts["peak_mw"] = int(round(max(vals)))
            counts["mean_mw"] = int(round(sum(vals) / len(vals)))
        return PreviewSummary(
            counts=counts,
            samples={"hours": [{"snapshot": s, "mw": round(v, 1)} for s, v in hourly[:24]]},
            notes=[f"Great Britain: {len(hourly)} hourly demand points (UTC)."],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        hourly = result.payload["hourly"]
        frag = WorkbookFragment()
        if hourly:
            frag.sheets["carriers"] = [{"name": "AC"}]
            frag.sheets["buses"] = [_gb_bus(result.region)]
            frag.sheets["loads"] = [{"name": "GBR_demand", "bus": "GBR", "carrier": "AC",
                                     "country": "GBR", "source": "Elexon INDO"}]
            frag.sheets["loads-p_set"] = [{"snapshot": s, "GBR_demand": v} for s, v in hourly]
            frag.snapshots = [s for s, _ in hourly]
        frag.provenance = _prov(_DEMAND_META.id, result, options, frag)
        return frag


# ── Renewable-profiles dataset ────────────────────────────────────────────────
_GEN_META = DatabaseMeta(
    id="elexon_renewable",
    name="Elexon — GB measured renewable profiles",
    short_name="GB renewable profiles",
    source_id=_SOURCE_ID, source_label=_SOURCE_LABEL,
    depends_on=["elexon_demand"],
    category="generation", subcategory="Hourly profiles",
    license="Elexon Insights (free, open)",
    homepage="https://bmrs.elexon.co.uk/",
    version_hint="Elexon BMRS Insights API v1",
    description=(
        "Measured hourly solar & wind (on/offshore) capacity-factor profiles for "
        "Great Britain — actual generation per fuel type, peak-normalised into "
        "generators-p_max_pu on the GB bus. Keyless (Elexon BMRS)."
    ),
    targets=["buses", "carriers", "generators", "generators-p_max_pu"],
    country_coverage=["GBR"], requires_secrets=[],
    filters=list(_DATE_FILTERS),
)


class ElexonRenewable:
    meta = _GEN_META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        df, dt = _win(filters)
        # per-type takes an ISO datetime range; +1 day so the last day is included.
        to_excl = (date.fromisoformat(dt) + timedelta(days=1)).isoformat()
        body = await _get(ctx, "/generation/actual/per-type",
                          {"from": f"{df}T00:00Z", "to": f"{to_excl}T00:00Z"}, "generation")
        by_carrier: dict[str, list[tuple[str, float]]] = {}
        for period in (body or {}).get("data") or []:
            t = period.get("startTime")
            if t is None:
                continue
            for item in period.get("data") or []:
                carrier = _VRE_PSRTYPE.get(str(item.get("psrType")))
                if not carrier:
                    continue
                try:
                    by_carrier.setdefault(carrier, []).append((str(t), float(item.get("quantity"))))
                except (TypeError, ValueError):
                    continue
        gen = {c: _hourly_mean(pairs) for c, pairs in by_carrier.items()}
        return FetchResult(_GEN_META.id, region, dict(filters), {"gen": gen})

    def _profiles(self, result: FetchResult) -> tuple[list[dict], list[str], list[dict], list[str]]:
        gen: dict[str, list[tuple[str, float]]] = result.payload["gen"]
        snaps = sorted({s for series in gen.values() for s, _ in series})
        gen_rows: list[dict] = []
        cf_by_gen: dict[str, dict[str, float]] = {}
        notes: list[str] = []
        for carrier, series in gen.items():
            peak = max((v for _, v in series), default=0.0)
            if peak <= 0:
                continue
            name = f"GBR_{carrier}"
            cf_by_gen[name] = {s: max(0.0, min(1.0, v / peak)) for s, v in series}
            gen_rows.append({"name": name, "bus": "GBR", "carrier": carrier,
                             "p_nom": round(peak, 3), "p_min_pu": 0, "p_max_pu": 1,
                             "source": "Elexon (measured generation, peak-normalised)"})
            mean = sum(cf_by_gen[name].values()) / len(cf_by_gen[name]) if cf_by_gen[name] else 0.0
            notes.append(f"{carrier}: mean CF ≈ {mean:.2f} (÷ window peak).")
        rows = [
            {"snapshot": s, **{n: round(cf[s], 4) for n, cf in cf_by_gen.items() if s in cf}}
            for s in snaps
        ]
        return gen_rows, snaps, rows, notes

    def preview(self, result: FetchResult) -> PreviewSummary:
        gen_rows, snaps, _rows, notes = self._profiles(result)
        return PreviewSummary(
            counts={"generators": len(gen_rows), "hours": len(snaps)},
            samples={"generators": [{"name": g["name"], "carrier": g["carrier"]} for g in gen_rows]},
            notes=[f"Great Britain: {len(gen_rows)} renewable carrier(s), {len(snaps)} hours (UTC).", *notes],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        gen_rows, snaps, rows, _notes = self._profiles(result)
        frag = WorkbookFragment()
        if gen_rows and snaps:
            frag.sheets["carriers"] = [{"name": "AC"}] + [{"name": c} for c in sorted({g["carrier"] for g in gen_rows})]
            frag.sheets["buses"] = [_gb_bus(result.region)]
            frag.sheets["generators"] = gen_rows
            frag.sheets["generators-p_max_pu"] = rows
            frag.snapshots = snaps
        frag.provenance = _prov(_GEN_META.id, result, options, frag)
        return frag


def _prov(db_id: str, result: FetchResult, options: ConvertOptions, frag: WorkbookFragment) -> Provenance:
    return Provenance(
        db_id, result.region.country_iso, result.region.country_name,
        json.dumps(result.filters, sort_keys=True, default=str),
        json.dumps(options.__dict__, sort_keys=True, default=str),
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        json.dumps({s: len(r) for s, r in frag.sheets.items()}, sort_keys=True),
    )


def build() -> Database:
    return ElexonDemand()


def build_renewable() -> Database:
    return ElexonRenewable()
