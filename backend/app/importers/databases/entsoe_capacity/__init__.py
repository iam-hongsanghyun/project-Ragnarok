"""ENTSO-E Transparency — installed generation capacity per type (BYOK).

Installed Generation Capacity Aggregated [14.1.A] from the ENTSO-E
Transparency RESTful API (documentType A68, processType A33). Returns the
national installed capacity (MW) per production type for a chosen year.

This is a dataset of the ``entsoe`` source (sibling of the national-load
dataset). It lands as one aggregate PyPSA Generator per carrier
(``gen_<iso>_<carrier>``) sitting on the source's national bus — so it
depends on the national-load dataset, which emits that bus. Fetch them
together (the batch auto-includes the dependency) for a one-bus national
model with demand + installed capacity.

Requires the same free ``entsoe_key`` token as the load dataset.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
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
from ..entsoe_load import (
    ENTSOE_SOURCE_ID,
    ENTSOE_SOURCE_LABEL,
    PSRTYPE_CARRIER,
    _API_URL,
    _EIC_BY_ISO,
    _children,
    _first_reason_text,
    _local,
    _slug,
    national_bus_name,
)

_DEFAULT_YEAR = "2023"


def _parse_capacity_xml(xml_text: str) -> dict[str, float]:
    """Extract ``{psrType: MW}`` from an A68 GL_MarketDocument.

    Each TimeSeries carries one ``MktPSRType/psrType`` and one Period whose
    single Point quantity is the installed capacity (MW). Raises with the
    reason text on an Acknowledgement (e.g. "No matching data found").
    """
    root = ET.fromstring(xml_text)
    if _local(root.tag) == "Acknowledgement_MarketDocument":
        reason = _first_reason_text(root)
        raise RuntimeError(reason or "ENTSO-E returned no capacity for that year")

    out: dict[str, float] = {}
    for ts in (e for e in root.iter() if _local(e.tag) == "TimeSeries"):
        psr = ""
        for el in ts.iter():
            if _local(el.tag) == "psrType":
                psr = (el.text or "").strip()
                break
        if not psr:
            continue
        qty: float | None = None
        for period in _children(ts, "Period"):
            for pt in _children(period, "Point"):
                q_el = _children(pt, "quantity")
                if q_el:
                    try:
                        qty = float(q_el[0].text or "")
                    except (TypeError, ValueError):
                        qty = None
                    break
            if qty is not None:
                break
        if qty is not None:
            out[psr] = out.get(psr, 0.0) + qty
    return out


META = DatabaseMeta(
    id="entsoe_capacity",
    name="ENTSO-E — installed generation capacity per type",
    short_name="Installed capacity",
    source_id=ENTSOE_SOURCE_ID,
    source_label=ENTSOE_SOURCE_LABEL,
    depends_on=["entsoe_load"],
    category="generation",
    subcategory="Capacity",
    license="ENTSO-E Transparency (free, attribution)",
    homepage="https://transparency.entsoe.eu/",
    version_hint="Transparency RESTful API",
    description=(
        "National installed generation capacity per production type (14.1.A, "
        "A68) for a European country. Lands as one aggregate Generator per "
        "carrier (gen_<iso>_<carrier>) on the source's national bus. Pair with "
        "the national-load dataset (auto-included) for a one-bus national "
        "model. Needs a free ENTSO-E API token (Settings → API keys)."
    ),
    targets=["generators", "carriers"],
    country_coverage=sorted(_EIC_BY_ISO.keys()),
    requires_secrets=["entsoe_key"],
    filters=[
        Filter(
            id="capacity_year", label="Capacity year", kind="select",
            default=_DEFAULT_YEAR,
            options=[{"value": str(y), "label": str(y)} for y in range(2015, 2026)],
            description="Reference year for the installed-capacity snapshot.",
        ),
    ],
)


class EntsoeCapacity:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        token = ctx.require_secret("entsoe_key")
        mapped = _EIC_BY_ISO.get(region.country_iso)
        if not mapped:
            raise RuntimeError(
                f"ENTSO-E: no domain EIC mapped for {region.country_iso}. "
                f"Covered: {', '.join(sorted(_EIC_BY_ISO))}."
            )
        eic, zone_name = mapped
        year = str(filters.get("capacity_year") or _DEFAULT_YEAR)
        try:
            y = int(year)
        except ValueError:
            y = int(_DEFAULT_YEAR)
        params = {
            "securityToken": token,
            "documentType": "A68",
            "processType": "A33",
            "in_Domain": eic,
            "periodStart": f"{y}01010000",
            "periodEnd": f"{y + 1}01010000",
        }
        try:
            xml_text = await ctx.http.get_text(_API_URL, params=params)
        except RuntimeError as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg:
                raise PermissionError(
                    "ENTSO-E rejected the API token. Check 'entsoe_key' in "
                    "Settings → API keys and that API access is enabled."
                ) from None
            raise RuntimeError(
                f"ENTSO-E capacity request failed ({msg}). The year may have no "
                f"published capacity, or the token may lack access."
            ) from None

        by_psr = _parse_capacity_xml(xml_text)
        return FetchResult(
            META.id, region, dict(filters),
            {"iso": region.country_iso, "eic": eic, "zone_name": zone_name,
             "year": y, "by_psr": by_psr},
        )

    def _generators(self, result: FetchResult) -> list[dict[str, Any]]:
        iso = result.payload["iso"]
        bus = national_bus_name(iso)
        out: list[dict[str, Any]] = []
        for psr, mw in result.payload["by_psr"].items():
            if not (mw and mw > 0):
                continue
            carrier = PSRTYPE_CARRIER.get(psr, psr)
            out.append({
                "name": _slug(f"gen_{iso}_{carrier}", f"gen_{iso}_{psr}"),
                "bus": bus,
                "carrier": carrier,
                "control": "PV",
                "p_nom": mw,
                "p_min_pu": 0,
                "p_max_pu": 1,
                "source": f"ENTSO-E A68 ({result.payload['year']})",
            })
        return out

    def preview(self, result: FetchResult) -> PreviewSummary:
        gens = self._generators(result)
        counts: dict[str, int] = {"generators": len(gens)}
        for g in gens:
            counts[f"carrier:{g['carrier']}"] = int(round(float(g["p_nom"])))
        total = int(round(sum(float(g["p_nom"]) for g in gens)))
        note = (
            f"{result.payload['zone_name']} ({result.payload['eic']}): "
            f"{len(gens)} carriers, {total} MW installed "
            f"({result.payload['year']})."
        )
        return PreviewSummary(
            counts=counts,
            samples={"generators": [
                {"name": g["name"], "carrier": g["carrier"], "p_nom": g["p_nom"]}
                for g in gens
            ]},
            notes=[note],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        gens = self._generators(result)
        frag = WorkbookFragment()
        if gens:
            frag.sheets["generators"] = gens
            frag.sheets["carriers"] = [
                {"name": c} for c in sorted({g["carrier"] for g in gens})
            ]
        row_counts = {s: len(r) for s, r in frag.sheets.items()}
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps({"year": result.payload["year"]}, sort_keys=True, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return EntsoeCapacity()
