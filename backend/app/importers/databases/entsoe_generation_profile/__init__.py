"""ENTSO-E Transparency — measured hourly renewable profiles (BYOK).

The empirical complement to the weather-modelled renewable importers
(Open-Meteo / PVGIS / NASA POWER): instead of deriving capacity factors from
reanalysis irradiance/wind, this reads the *actual* hourly generation a country
recorded and divides it by installed capacity to get a real, observed
``p_max_pu`` per variable-renewable carrier.

Two ENTSO-E requests, same free ``entsoe_key`` token as the sibling datasets:

    documentType = A75, processType = A16, in_Domain = <EIC>   (16.1.B&C —
        Actual Generation per Production Type, hourly)
    documentType = A68, processType = A33, in_Domain = <EIC>   (14.1.A —
        Installed Capacity per Production Type, for the same year)

Capacity factor = clip(hourly_generation / installed_capacity, 0, 1). When a
carrier has generation but no published capacity we fall back to normalising by
its own window peak (a shape, not an absolute CF) and say so in the preview.

Lands one aggregate Generator per variable-renewable carrier
(``gen_<iso>_<carrier>``, matching the installed-capacity dataset so the two
attach cleanly) on the shared national bus, plus its ``generators-p_max_pu``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import xml.etree.ElementTree as ET

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
from ..entsoe_capacity import _parse_capacity_xml
from ..entsoe_load import (
    ENTSOE_SOURCE_ID,
    ENTSOE_SOURCE_LABEL,
    PSRTYPE_CARRIER,
    _aggregate_hourly,
    _API_URL,
    _children,
    _EIC_BY_ISO,
    _first_reason_text,
    _local,
    _parse_dt,
    _resolution_minutes,
    _slug,
    _to_period,
    national_bus_name,
    national_bus_row,
)

# Variable-renewable production types that have a meaningful availability profile.
_VRE_PSRTYPES = ("B16", "B18", "B19", "B11")  # solar, offwind, onwind, hydro RoR


def _parse_generation_xml(xml_text: str) -> dict[str, list[tuple[datetime, float]]]:
    """Extract ``{psrType: [(timestamp_utc, MW)]}`` from an A75 GL_MarketDocument.

    Each TimeSeries carries one ``MktPSRType/psrType`` and Period/Points like the
    load document. Series reporting *consumption* (an ``outBiddingZone_Domain``,
    e.g. pumped-storage charging) are skipped — we want generation only.
    """
    root = ET.fromstring(xml_text)
    if _local(root.tag) == "Acknowledgement_MarketDocument":
        raise RuntimeError(_first_reason_text(root) or "ENTSO-E returned no generation for that range")

    out: dict[str, list[tuple[datetime, float]]] = {}
    for ts in (e for e in root.iter() if _local(e.tag) == "TimeSeries"):
        if _children(ts, "outBiddingZone_Domain.mRID"):
            continue  # consumption leg of a storage type — not generation
        psr = ""
        for el in ts.iter():
            if _local(el.tag) == "psrType":
                psr = (el.text or "").strip()
                break
        if not psr:
            continue
        bucket = out.setdefault(psr, [])
        for period in _children(ts, "Period"):
            start = None
            res_min = 60
            interval = _children(period, "timeInterval")
            if interval:
                starts = _children(interval[0], "start")
                if starts:
                    start = _parse_dt(starts[0].text)
            resolutions = _children(period, "resolution")
            if resolutions:
                res_min = _resolution_minutes(resolutions[0].text)
            if start is None:
                continue
            for pt in _children(period, "Point"):
                pos_el = _children(pt, "position")
                qty_el = _children(pt, "quantity")
                if not pos_el or not qty_el:
                    continue
                try:
                    pos = int(pos_el[0].text or "")
                    qty = float(qty_el[0].text or "")
                except (TypeError, ValueError):
                    continue
                bucket.append((start + timedelta(minutes=res_min * (pos - 1)), qty))
    return out


META = DatabaseMeta(
    id="entsoe_generation_profile",
    name="ENTSO-E — measured hourly renewable profiles (Actual Generation ÷ capacity)",
    short_name="Measured profiles",
    source_id=ENTSOE_SOURCE_ID,
    source_label=ENTSOE_SOURCE_LABEL,
    depends_on=["entsoe_load"],
    category="generation",
    subcategory="Hourly profiles",
    license="ENTSO-E Transparency (free, attribution)",
    homepage="https://transparency.entsoe.eu/",
    version_hint="Transparency RESTful API",
    description=(
        "Real observed hourly wind/solar capacity factors for a European country "
        "— actual generation per production type (16.1.B&C, A75) divided by "
        "installed capacity (14.1.A, A68). The empirical complement to the "
        "weather-modelled Open-Meteo/PVGIS/NASA profiles. Lands one aggregate "
        "renewable generator per carrier on the national bus + its "
        "generators-p_max_pu. Needs a free ENTSO-E API token (Settings → API keys)."
    ),
    targets=["buses", "carriers", "generators", "generators-p_max_pu"],
    country_coverage=sorted(_EIC_BY_ISO.keys()),
    requires_secrets=["entsoe_key"],
    filters=[
        Filter(id="date_from", label="From", kind="date", default="2023-01-01",
               min="2015-01-01", max="2025-12-31",
               description="Start of the hourly window (inclusive, UTC)."),
        Filter(id="date_to", label="To", kind="date", default="2023-01-07",
               min="2015-01-01", max="2025-12-31",
               description="End of the hourly window (inclusive, UTC). Keep it short — "
                           "hourly generation is large; ENTSO-E caps a request at one year."),
    ],
)


class EntsoeGenerationProfile:
    meta = META

    async def _get(self, ctx: ImportContext, params: dict[str, str], what: str) -> str:
        try:
            return await ctx.http.get_text(_API_URL, params=params)
        except RuntimeError as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg:
                raise PermissionError(
                    "ENTSO-E rejected the API token. Check 'entsoe_key' in "
                    "Settings → API keys and that API access is enabled."
                ) from None
            raise RuntimeError(f"ENTSO-E {what} request failed ({msg}).") from None

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        token = ctx.require_secret("entsoe_key")
        mapped = _EIC_BY_ISO.get(region.country_iso)
        if not mapped:
            raise RuntimeError(
                f"ENTSO-E: no domain EIC mapped for {region.country_iso}. "
                f"Covered: {', '.join(sorted(_EIC_BY_ISO))}."
            )
        eic, zone_name = mapped
        date_from = str(filters.get("date_from") or "2023-01-01")
        date_to = str(filters.get("date_to") or "2023-01-07")
        year = int(date_from[:4])

        gen_xml = await self._get(ctx, {
            "securityToken": token, "documentType": "A75", "processType": "A16",
            "in_Domain": eic,
            "periodStart": _to_period(date_from, end=False),
            "periodEnd": _to_period(date_to, end=True),
        }, "generation")
        # Installed capacity for the same year normalises generation → CF. A
        # missing/failed capacity call degrades to peak-normalisation per carrier.
        capacity: dict[str, float] = {}
        try:
            cap_xml = await self._get(ctx, {
                "securityToken": token, "documentType": "A68", "processType": "A33",
                "in_Domain": eic,
                "periodStart": f"{year}01010000", "periodEnd": f"{year + 1}01010000",
            }, "capacity")
            capacity = _parse_capacity_xml(cap_xml)
        except (RuntimeError, PermissionError):
            capacity = {}

        raw = _parse_generation_xml(gen_xml)
        gen_hourly = {
            psr: _aggregate_hourly(pts)
            for psr, pts in raw.items()
            if psr in _VRE_PSRTYPES and pts
        }
        return FetchResult(
            META.id, region, dict(filters),
            {"iso": region.country_iso, "eic": eic, "zone_name": zone_name,
             "date_from": date_from, "date_to": date_to,
             "gen_hourly": gen_hourly, "capacity": capacity},
        )

    def _profiles(self, result: FetchResult) -> tuple[list[dict], list[str], list[dict], list[str]]:
        """Return (generator rows, snapshots, p_max_pu rows, notes)."""
        iso = result.payload["iso"]
        bus = national_bus_name(iso)
        capacity = result.payload["capacity"]
        gen_hourly: dict[str, list[tuple[str, float]]] = result.payload["gen_hourly"]

        snapshots: list[str] = sorted({s for series in gen_hourly.values() for s, _ in series})
        cf_by_gen: dict[str, dict[str, float]] = {}
        gen_rows: list[dict] = []
        notes: list[str] = []
        for psr, series in gen_hourly.items():
            carrier = PSRTYPE_CARRIER.get(psr, psr)
            cap = float(capacity.get(psr) or 0.0)
            peak = max((mw for _, mw in series), default=0.0)
            denom = cap if cap > 0 else peak
            if denom <= 0:
                continue
            name = _slug(f"gen_{iso}_{carrier}", f"gen_{iso}_{psr}")
            cf_by_gen[name] = {s: max(0.0, min(1.0, mw / denom)) for s, mw in series}
            gen_rows.append({
                "name": name, "bus": bus, "carrier": carrier,
                "p_nom": round(denom, 3), "p_min_pu": 0, "p_max_pu": 1,
                "source": f"ENTSO-E A75/A68 ({result.payload['date_from']}→{result.payload['date_to']})",
            })
            basis = "installed capacity" if cap > 0 else "window peak (no A68 capacity)"
            mean_cf = sum(cf_by_gen[name].values()) / len(cf_by_gen[name]) if cf_by_gen[name] else 0.0
            notes.append(f"{carrier}: mean CF ≈ {mean_cf:.2f} (÷ {basis}).")

        p_max_pu_rows: list[dict] = []
        for snap in snapshots:
            row: dict[str, Any] = {"snapshot": snap}
            for name, cf in cf_by_gen.items():
                if snap in cf:
                    row[name] = round(cf[snap], 4)
            p_max_pu_rows.append(row)
        return gen_rows, snapshots, p_max_pu_rows, notes

    def preview(self, result: FetchResult) -> PreviewSummary:
        gen_rows, snapshots, _rows, notes = self._profiles(result)
        head = (
            f"{result.payload['zone_name']} ({result.payload['eic']}): "
            f"{len(gen_rows)} renewable carrier(s), {len(snapshots)} hourly points (UTC)."
        )
        return PreviewSummary(
            counts={"generators": len(gen_rows), "hours": len(snapshots)},
            samples={"generators": [{"name": g["name"], "carrier": g["carrier"], "p_nom": g["p_nom"]} for g in gen_rows]},
            notes=[head, *notes],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        gen_rows, snapshots, p_max_pu_rows, _notes = self._profiles(result)
        frag = WorkbookFragment()
        if gen_rows and snapshots:
            frag.sheets["carriers"] = [{"name": "AC"}] + [
                {"name": c} for c in sorted({g["carrier"] for g in gen_rows})
            ]
            frag.sheets["buses"] = [national_bus_row(result.region)]
            frag.sheets["generators"] = gen_rows
            frag.sheets["generators-p_max_pu"] = p_max_pu_rows
            frag.snapshots = snapshots
        row_counts = {s: len(r) for s, r in frag.sheets.items()}
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return EntsoeGenerationProfile()
