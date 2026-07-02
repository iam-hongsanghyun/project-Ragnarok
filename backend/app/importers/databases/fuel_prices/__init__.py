"""Fuel & commodity prices → carrier marginal cost.

Turns a fuel-price snapshot (the numbers a user reads off a futures screen or a
market report) into per-carrier **thermal** fuel costs on the ``carriers`` sheet,
doing the unit conversion so users stop hand-typing €/MWh from $/MMBtu, $/tonne
and $/bbl. Each enabled fuel lands as one carrier row with ``marginal_cost``
(currency/MWh thermal) plus the raw price / unit / conversion for provenance; a
carbon price (currency/tCO₂) is carried through for the run's carbon setting.

Not a network fetch — the prices are user inputs (the TODO's "user's own futures
snapshot" source), converted deterministically. To get €/MWh **electric** at a
generator, divide the thermal cost by that generator's efficiency (Ragnarok's M3
convention already treats fuel + carbon on the primary-energy basis).

Conversions (thermal energy content, documented constants):
    gas      $/MMBtu × 3.41214 MMBtu/MWh
    coal     $/tonne ÷ 6.978 MWh/tonne   (hard coal, 25.12 GJ/t)
    oil      $/bbl   ÷ 1.699 MWh/bbl     (6.117 GJ/bbl)
    biomass  $/tonne ÷ 4.900 MWh/tonne   (wood pellets, 17.6 GJ/t)
    uranium  entered directly as currency/MWh thermal
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

MMBTU_PER_MWH = 3.412142
# MWh(thermal) per physical unit of each fuel.
_MWH_TH_PER_UNIT = {
    "coal": 6.978,     # tonne, hard coal 25.12 GJ/t
    "oil": 1.699,      # barrel, 6.117 GJ/bbl
    "biomass": 4.900,  # tonne, wood pellets 17.6 GJ/t
}

# (filter id, carrier name, raw unit, converter → currency/MWh thermal)
_FUELS: list[tuple[str, str, str, Any]] = [
    ("gas_price", "gas", "$/MMBtu", lambda p: p * MMBTU_PER_MWH),
    ("coal_price", "coal", "$/tonne", lambda p: p / _MWH_TH_PER_UNIT["coal"]),
    ("oil_price", "oil", "$/bbl", lambda p: p / _MWH_TH_PER_UNIT["oil"]),
    ("biomass_price", "biomass", "$/tonne", lambda p: p / _MWH_TH_PER_UNIT["biomass"]),
    ("uranium_cost", "nuclear", "$/MWh_th", lambda p: p),
]


def convert_fuel_prices(filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure: filter values → carrier rows with thermal ``marginal_cost``.

    A fuel is included only when its price is a positive number.
    """
    rows: list[dict[str, Any]] = []
    for fid, carrier, unit, conv in _FUELS:
        try:
            raw = float(filters.get(fid))
        except (TypeError, ValueError):
            continue
        if raw <= 0:
            continue
        rows.append({
            "name": carrier,
            "marginal_cost": round(float(conv(raw)), 4),
            "fuel_cost_basis": "thermal (currency/MWh_th)",
            "raw_price": raw,
            "raw_unit": unit,
            "source": "Fuel price snapshot",
        })
    return rows


META = DatabaseMeta(
    id="fuel_prices",
    name="Fuel & commodity prices → carrier marginal cost",
    short_name="Fuel prices",
    source_id="fuel_prices",
    source_label="Fuel price snapshot",
    category="prices",
    subcategory="Fuel & carbon",
    license="User input",
    homepage="",
    version_hint="snapshot",
    description=(
        "Enter current or forward fuel prices in their native units (gas $/MMBtu, "
        "coal & biomass $/tonne, oil $/bbl, nuclear directly in $/MWh thermal). "
        "They're converted to per-MWh thermal fuel costs and land on the carriers "
        "sheet as marginal_cost, so you stop hand-typing €/MWh. A carbon price "
        "(currency/tCO₂) is carried through for the run's carbon setting. Divide "
        "the thermal cost by a plant's efficiency for its €/MWh electric."
    ),
    targets=["carriers"],
    country_coverage="global",  # prices aren't country-specific here
    requires_secrets=[],
    filters=[
        Filter(id="gas_price", label="Natural gas", kind="number", default=10.0,
               min=0, step=0.5, unit="$/MMBtu", description="Henry-Hub-style gas price."),
        Filter(id="coal_price", label="Coal", kind="number", default=120.0,
               min=0, step=5, unit="$/tonne", description="Hard-coal price ($/tonne)."),
        Filter(id="oil_price", label="Oil", kind="number", default=85.0,
               min=0, step=5, unit="$/bbl", description="Crude oil price ($/barrel)."),
        Filter(id="biomass_price", label="Biomass", kind="number", default=150.0,
               min=0, step=5, unit="$/tonne", description="Wood-pellet price ($/tonne)."),
        Filter(id="uranium_cost", label="Nuclear fuel", kind="number", default=6.0,
               min=0, step=0.5, unit="$/MWh_th", description="Nuclear fuel cost, entered directly."),
        Filter(id="carbon_price", label="Carbon price", kind="number", default=0.0,
               min=0, step=5, unit="$/tCO₂",
               description="Carried through for the run's carbon setting (informational here)."),
    ],
)


class FuelPrices:
    meta = META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        # No network — the snapshot is user input; convert deterministically.
        carriers = convert_fuel_prices(filters)
        try:
            carbon = float(filters.get("carbon_price") or 0.0)
        except (TypeError, ValueError):
            carbon = 0.0
        return FetchResult(META.id, region, dict(filters),
                           {"carriers": carriers, "carbon_price": carbon})

    def preview(self, result: FetchResult) -> PreviewSummary:
        carriers = result.payload["carriers"]
        carbon = result.payload["carbon_price"]
        notes = [
            f"{c['name']}: {c['raw_price']} {c['raw_unit']} → {c['marginal_cost']} /MWh thermal"
            for c in carriers
        ]
        if carbon > 0:
            notes.append(f"Carbon price {carbon} /tCO₂ (set it as the run carbon price).")
        if not carriers:
            notes.append("No fuel prices entered — set at least one to a positive value.")
        return PreviewSummary(
            counts={"carriers": len(carriers)},
            samples={"carriers": carriers},
            notes=notes,
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        frag = WorkbookFragment()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        carriers = result.payload["carriers"]
        if carriers:
            frag.sheets["carriers"] = carriers
        row_counts = {s: len(r) for s, r in frag.sheets.items()}
        frag.provenance = Provenance(
            META.id, result.region.country_iso, result.region.country_name,
            json.dumps(result.filters, sort_keys=True, default=str),
            json.dumps(options.__dict__, sort_keys=True, default=str),
            ts, json.dumps(row_counts, sort_keys=True),
        )
        return frag


def build() -> Database:
    return FuelPrices()
