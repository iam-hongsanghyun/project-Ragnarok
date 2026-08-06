"""Perspective-based report documents assembled from stored solve runs.

A report is a *selection and framing* of the analytics payload a run already
carries — never a recomputation. Every figure in a report document is read
verbatim from ``run_store.get_run_analytics(name)["result"]`` (the payload
built at solve time by ``backend/pypsa/results``), optionally reduced by
presentation-level aggregates (sums, shares, min/mean/max over a stored
series). No physics, market, or finance quantity is derived here, which is
what keeps a report reproducible: same run, same document, byte for byte
apart from ``generatedAt``.

A *perspective* is a report spec defined as data: an audience, and an ordered
list of ``(section id, key question)`` pairs. Sections are shared builders —
adding a perspective means composing existing sections with new framing, not
writing new assembly code. Sections whose source module was not enabled for
the run render an ``unavailable`` block naming what enables them, so the
document always shows its full intended structure.

Narrative blocks are deterministic templated prose: sentences with stored
numbers formatted in. The AI authoring layer (Bifrost) writes *around* these
documents via the MCP surface; it never replaces the numbers.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from . import run_store

# Time-series chart blocks are omitted above this many points so a document
# stays printable; one hourly year (8784 h leap) is deliberately inside it.
_MAX_CHART_POINTS = 8784


# ---------------------------------------------------------------------------
# formatting helpers (presentation only)
# ---------------------------------------------------------------------------

def _fmt_num(value: Any, decimals: int = 1) -> str:
    """Format a number with thousands separators; ``—`` for missing."""
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v == int(v) and abs(v) < 1e15:
        return f"{int(v):,}"
    return f"{v:,.{decimals}f}"


def _fmt(value: Any, unit: str, decimals: int = 1) -> str:
    if value is None:
        return "—"
    return f"{_fmt_num(value, decimals)} {unit}".strip()


def _fmt_pct(fraction: Any, decimals: int = 1) -> str:
    if fraction is None:
        return "—"
    try:
        return f"{float(fraction) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def _share(part: float, whole: float) -> str:
    if not whole:
        return "—"
    return _fmt_pct(part / whole)


# ---------------------------------------------------------------------------
# block constructors
# ---------------------------------------------------------------------------

def _kpis(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "kpis", "items": items}


def _narrative(*paragraphs: str) -> dict[str, Any]:
    return {"type": "narrative", "paragraphs": [p for p in paragraphs if p]}


def _table(
    title: str, columns: list[dict[str, str]], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    return {"type": "table", "title": title, "columns": columns, "rows": rows}


def _donut(title: str, unit: str, data: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "chart", "chart": {"kind": "donut", "title": title, "unit": unit, "data": data}}


def _bars(
    title: str,
    unit: str,
    labels: list[str],
    series: list[dict[str, Any]],
    *,
    stacked: bool = False,
) -> dict[str, Any]:
    return {
        "type": "chart",
        "chart": {
            "kind": "bars",
            "title": title,
            "unit": unit,
            "labels": labels,
            "series": series,
            "stacked": stacked,
        },
    }


def _line(
    title: str,
    unit: str,
    x_labels: list[str],
    series: list[dict[str, Any]],
    *,
    area: bool = False,
    stacked: bool = False,
) -> dict[str, Any]:
    return {
        "type": "chart",
        "chart": {
            "kind": "line",
            "title": title,
            "unit": unit,
            "xLabels": x_labels,
            "series": series,
            "area": area,
            "stacked": stacked,
        },
    }


def _unavailable(reason: str, requires: str) -> dict[str, Any]:
    return {"type": "unavailable", "reason": reason, "requires": requires}


# ---------------------------------------------------------------------------
# section builders — each reads ctx["result"] and returns a list of blocks
# ---------------------------------------------------------------------------

def _section_overview(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    meta = ctx["meta"]
    scenario = ctx["scenario"]
    run_meta = result.get("runMeta") or {}
    counts = run_meta.get("componentCounts") or {}
    blocks: list[dict[str, Any]] = []
    summary = result.get("summary") or []
    if summary:
        blocks.append(_kpis([
            {"label": s.get("label", ""), "value": s.get("value", ""), "detail": s.get("detail", "")}
            for s in summary
        ]))
    window = ""
    if meta.get("snapshotStart") and meta.get("snapshotEnd"):
        window = f" over {meta['snapshotStart']} – {meta['snapshotEnd']}"
    parts = [
        (
            f"This report reads the stored solve “{meta.get('label') or ctx['runName']}”"
            f"{window}, covering {_fmt(run_meta.get('modeledHours'), 'modeled hours', 0)} across "
            f"{_fmt_num(counts.get('buses'))} buses, {_fmt_num(counts.get('generators'))} generators "
            f"and {_fmt_num(counts.get('storage_units'))} storage units."
        )
    ]
    carbon = (scenario or {}).get("carbonPrice")
    if carbon:
        parts.append(f"A carbon price of {_fmt(carbon, ctx['currency'] + '/tCO2e')} was applied.")
    blocks.append(_narrative(" ".join(parts)))
    return blocks


def _section_mix(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    mix = result.get("carrierMix") or []
    if not mix:
        return [_unavailable(
            "No generation-mix data is stored for this run.",
            "A solved run with at least one dispatching generator.",
        )]
    total = sum(float(m.get("value") or 0) for m in mix)
    top = max(mix, key=lambda m: float(m.get("value") or 0))
    blocks = [
        _donut("Energy by carrier", "MWh", mix),
        _narrative(
            f"Total generation over the modeled window is {_fmt(total, 'MWh', 0)}. "
            f"The largest contribution comes from {top.get('label')} at "
            f"{_fmt(top.get('value'), 'MWh', 0)} ({_share(float(top.get('value') or 0), total)})."
        ),
    ]
    dispatch = result.get("dispatchSeries") or []
    if dispatch and len(dispatch) <= _MAX_CHART_POINTS:
        carriers: list[str] = []
        for row in dispatch:
            for c in (row.get("values") or {}):
                if c not in carriers:
                    carriers.append(c)
        colors = {m.get("label"): m.get("color") for m in mix}
        blocks.append(_line(
            "Dispatch by carrier",
            "MW",
            [row.get("label", "") for row in dispatch],
            [
                {
                    "key": c,
                    "label": c,
                    "color": colors.get(c),
                    "values": [(row.get("values") or {}).get(c) for row in dispatch],
                }
                for c in carriers
            ],
            area=True,
            stacked=True,
        ))
    return blocks


def _generator_stat_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    stats = result.get("statistics") or {}
    return [r for r in (stats.get("rows") or []) if r.get("component") == "Generator"]


def _section_capacity(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    gen_rows = _generator_stat_rows(result)
    expansion = result.get("expansionResults") or []
    if not gen_rows and not expansion:
        return [_unavailable(
            "No capacity statistics are stored for this run.",
            "A solved run (PyPSA statistics table).",
        )]
    blocks: list[dict[str, Any]] = []
    if gen_rows:
        labels = [r.get("carrier", "") for r in gen_rows]
        installed = [(r.get("values") or {}).get("Installed Capacity") for r in gen_rows]
        optimal = [(r.get("values") or {}).get("Optimal Capacity") for r in gen_rows]
        blocks.append(_bars(
            "Installed vs optimal capacity by carrier",
            "MW",
            labels,
            [
                {"key": "installed", "label": "Installed", "values": installed},
                {"key": "optimal", "label": "Optimal", "values": optimal},
            ],
        ))
    changed = [e for e in expansion if float(e.get("delta_mw") or 0) != 0]
    if changed:
        blocks.append(_table(
            "Capacity changes chosen by the optimisation",
            [
                {"key": "name", "label": "Asset"},
                {"key": "carrier", "label": "Carrier"},
                {"key": "bus", "label": "Bus"},
                {"key": "p_nom_mw", "label": "Existing (MW)"},
                {"key": "p_nom_opt_mw", "label": "Optimal (MW)"},
                {"key": "delta_mw", "label": "Delta (MW)"},
                {"key": "capex_annual", "label": f"Annualised capex ({ctx['currency']})"},
            ],
            changed,
        ))
        added = sum(float(e.get("delta_mw") or 0) for e in changed if float(e.get("delta_mw") or 0) > 0)
        blocks.append(_narrative(
            f"The optimisation adjusts capacity on {len(changed)} extendable asset(s), "
            f"adding {_fmt(added, 'MW')} in total."
        ))
    else:
        blocks.append(_narrative(
            "No extendable asset changed capacity in this run: the existing fleet "
            "was sufficient at the modeled costs and constraints."
        ))
    return blocks


def _section_cost(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    breakdown = result.get("costBreakdown") or []
    if not breakdown:
        return [_unavailable(
            "No system-cost breakdown is stored for this run.",
            "A solved run with an objective value.",
        )]
    cur = ctx["currency"]
    total = sum(float(b.get("value") or 0) for b in breakdown)
    top = max(breakdown, key=lambda b: float(b.get("value") or 0))
    return [
        _bars(
            "System cost breakdown",
            cur,
            [b.get("label", "") for b in breakdown],
            [{"key": "cost", "label": "Cost", "values": [b.get("value") for b in breakdown]}],
        ),
        _narrative(
            f"Total system cost over the modeled window is {cur}{_fmt_num(total, 0)}. "
            f"The largest component is {str(top.get('label', '')).lower()} at "
            f"{cur}{_fmt_num(top.get('value'), 0)} ({_share(float(top.get('value') or 0), total)})."
        ),
    ]


def _section_emissions(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    breakdown = result.get("emissionsBreakdown") or {}
    by_carrier = breakdown.get("byCarrier") or []
    if not by_carrier:
        return [_unavailable(
            "No emissions breakdown is stored for this run.",
            "Emission factors on at least one carrier.",
        )]
    total_t = sum(float(r.get("emissions_tco2") or 0) for r in by_carrier)
    total_mwh = sum(float(r.get("energy_mwh") or 0) for r in by_carrier)
    intensity = (total_t * 1000 / total_mwh) if total_mwh else None
    blocks = [
        _table(
            "Emissions by carrier",
            [
                {"key": "carrier", "label": "Carrier"},
                {"key": "energy_mwh", "label": "Energy (MWh)"},
                {"key": "emissions_tco2", "label": "Emissions (tCO2e)"},
                {"key": "intensity_kg_mwh", "label": "Intensity (kg/MWh)"},
            ],
            by_carrier,
        ),
        _narrative(
            f"System emissions over the modeled window total {_fmt(total_t, 'tCO2e', 0)} "
            f"at an average intensity of {_fmt(intensity, 'kg CO2e/MWh', 0)}."
        ),
    ]
    shadow = result.get("co2Shadow") or {}
    if shadow.get("found"):
        blocks.append(_narrative(
            f"The CO2 constraint “{shadow.get('constraint_name')}” is binding with a "
            f"shadow price of {_fmt(shadow.get('shadow_price'), ctx['currency'] + '/tCO2e')} — "
            f"the marginal cost of one more tonne under the cap."
        ))
    elif shadow.get("note"):
        blocks.append(_narrative(str(shadow.get("note"))))
    series = result.get("systemEmissionsSeries") or []
    if series and len(series) <= _MAX_CHART_POINTS:
        blocks.append(_line(
            "System emissions over time",
            "tCO2e",
            [row.get("label", "") for row in series],
            [{"key": "emissions", "label": "Emissions", "values": [row.get("value") for row in series]}],
        ))
    return blocks


def _section_adequacy(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    adequacy = result.get("adequacy")
    if not adequacy:
        return [_unavailable(
            "Adequacy analysis is not stored for this run.",
            "A solved run with a load profile and at least one time-varying renewable.",
        )]
    firm = adequacy.get("firmCapacityMW")
    peak = adequacy.get("peakLoadMW")
    margin = None
    if firm is not None and peak:
        margin = (float(firm) - float(peak)) / float(peak)
    blocks = [
        _kpis([
            {"label": "Firm capacity", "value": _fmt(firm, "MW"), "detail": "dispatchable fleet"},
            {"label": "Peak load", "value": _fmt(peak, "MW"), "detail": "modeled window"},
            {"label": "LOLE", "value": _fmt(adequacy.get("lole"), "h/yr"),
             "detail": f"{_fmt_num(adequacy.get('members'))} Monte-Carlo members"},
            {"label": "EENS", "value": _fmt(adequacy.get("eens"), "MWh/yr"),
             "detail": "expected energy not served"},
        ]),
        _narrative(
            f"Firm capacity of {_fmt(firm, 'MW')} against a peak load of {_fmt(peak, 'MW')} "
            f"gives a firm margin of {_fmt_pct(margin)}. "
            f"Loss-of-load expectation is {_fmt(adequacy.get('lole'), 'hours per year')} with "
            f"{_fmt(adequacy.get('eens'), 'MWh')} of expected energy not served."
        ),
    ]
    outage = result.get("outageMc") or {}
    if outage.get("enabled"):
        lole_d = outage.get("loleDistribution") or {}
        eue_d = outage.get("eueDistribution") or {}
        blocks.append(_kpis([
            {"label": "LOLE p50", "value": _fmt(lole_d.get("p50"), "h"), "detail": "outage Monte-Carlo"},
            {"label": "LOLE p95", "value": _fmt(lole_d.get("p95"), "h"), "detail": "tail scenario"},
            {"label": "EUE mean", "value": _fmt(eue_d.get("mean"), "MWh"), "detail": "unserved energy"},
            {"label": "EUE p95", "value": _fmt(eue_d.get("p95"), "MWh"), "detail": "tail scenario"},
        ]))
    elcc = result.get("elcc") or {}
    if elcc.get("enabled") and elcc.get("byCarrier"):
        rows = elcc["byCarrier"]
        blocks.append(_bars(
            "Effective load-carrying capability by carrier",
            "% of nameplate",
            [r.get("carrier", "") for r in rows],
            [{"key": "elcc", "label": "ELCC", "values": [r.get("elccPct") for r in rows]}],
        ))
    band = adequacy.get("band") or []
    if band and len(band) <= _MAX_CHART_POINTS:
        blocks.append(_line(
            "Available capacity band vs load",
            "MW",
            [str(row.get("timestamp", "")) for row in band],
            [
                {"key": "load", "label": "Load", "values": [row.get("load") for row in band]},
                {"key": "p10", "label": "P10 available", "values": [row.get("p10") for row in band]},
                {"key": "p90", "label": "P90 available", "values": [row.get("p90") for row in band]},
            ],
        ))
    return blocks


def _section_robustness(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    near = result.get("nearOptimal")
    if not near:
        return [_unavailable(
            "Near-optimal (MGA) alternatives are not stored for this run.",
            "Enable near-optimal exploration in the solve options.",
        )]
    optimum = (near.get("optimum") or {}).get("capacityByCarrier") or {}
    ok_alts = [a for a in (near.get("alternatives") or []) if a.get("status") == "ok"]
    slack = near.get("slack")
    rows = []
    for carrier, opt_mw in optimum.items():
        values = [float((a.get("capacityByCarrier") or {}).get(carrier) or 0) for a in ok_alts]
        values.append(float(opt_mw or 0))
        rows.append({
            "carrier": carrier,
            "optimal": round(float(opt_mw or 0), 1),
            "minimum": round(min(values), 1),
            "maximum": round(max(values), 1),
        })
    flexible = [r for r in rows if r["maximum"] - r["minimum"] > 0.05]
    text = (
        f"Within {_fmt_pct(slack)} of the optimal cost, the model was asked how far each "
        f"carrier's capacity can move ({len(ok_alts)} alternative solutions). "
    )
    if flexible:
        widest = max(flexible, key=lambda r: r["maximum"] - r["minimum"])
        text += (
            f"The widest range is {widest['carrier']}: anywhere between "
            f"{_fmt(widest['minimum'], 'MW')} and {_fmt(widest['maximum'], 'MW')} remains "
            f"near-optimal, so this capacity is a genuine choice rather than a model verdict."
        )
    else:
        text += "Capacities barely move — the optimal build-out is tightly determined."
    return [
        _table(
            f"Capacity ranges within {_fmt_pct(slack)} of optimal cost",
            [
                {"key": "carrier", "label": "Carrier"},
                {"key": "minimum", "label": "Min (MW)"},
                {"key": "optimal", "label": "Optimal (MW)"},
                {"key": "maximum", "label": "Max (MW)"},
            ],
            rows,
        ),
        _narrative(text),
    ]


def _price_values(result: dict[str, Any]) -> list[float]:
    series = result.get("systemPriceSeries") or []
    return [float(row.get("value")) for row in series if row.get("value") is not None]


def _section_prices(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    cur = ctx["currency"]
    values = _price_values(result)
    formation = result.get("priceFormation") or {}
    marginal = formation.get("marginalSummary") or []
    if not values and not marginal:
        return [_unavailable(
            "No price series is stored for this run.",
            "A solved LP run (duals are unavailable for MILP unit-commitment runs).",
        )]
    blocks: list[dict[str, Any]] = []
    if values:
        mean = sum(values) / len(values)
        blocks.append(_kpis([
            {"label": "Average price", "value": _fmt(mean, cur + "/MWh"), "detail": "time-weighted, modeled window"},
            {"label": "Minimum price", "value": _fmt(min(values), cur + "/MWh"), "detail": ""},
            {"label": "Maximum price", "value": _fmt(max(values), cur + "/MWh"), "detail": ""},
        ]))
    if marginal:
        top = max(marginal, key=lambda m: float(m.get("shareOfHours") or 0))
        blocks.append(_bars(
            "Share of hours setting the price, by carrier",
            "% of hours",
            [m.get("carrier", "") for m in marginal],
            [{
                "key": "share",
                "label": "Share of hours",
                "values": [round(float(m.get("shareOfHours") or 0) * 100, 1) for m in marginal],
            }],
        ))
        blocks.append(_narrative(
            f"{top.get('carrier')} is the marginal (price-setting) technology in "
            f"{_fmt_pct(top.get('shareOfHours'))} of hours, at an average price of "
            f"{_fmt(top.get('avgPrice'), cur + '/MWh')} when it sets the price."
        ))
    series = result.get("systemPriceSeries") or []
    if series and len(series) <= _MAX_CHART_POINTS:
        blocks.append(_line(
            "System price over time",
            cur + "/MWh",
            [row.get("label", "") for row in series],
            [{"key": "price", "label": "Price", "values": [row.get("value") for row in series]}],
        ))
    return blocks


def _section_economics(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    econ = result.get("generatorEconomics") or {}
    by_carrier = econ.get("byCarrier") or []
    if not by_carrier:
        return [_unavailable(
            "Generator economics are not stored for this run.",
            "A solved run with a price series.",
        )]
    cur = econ.get("currency") or ctx["currency"]
    system = econ.get("system") or {}
    return [
        _table(
            "Generator economics by carrier",
            [
                {"key": "carrier", "label": "Carrier"},
                {"key": "capacityMw", "label": "Capacity (MW)"},
                {"key": "energyMwh", "label": "Energy (MWh)"},
                {"key": "revenue", "label": f"Revenue ({cur})"},
                {"key": "grossMargin", "label": f"Gross margin ({cur})"},
                {"key": "capturePrice", "label": f"Capture price ({cur}/MWh)"},
                {"key": "recoveryPct", "label": "Fixed-cost recovery (%)"},
            ],
            by_carrier,
        ),
        _narrative(
            f"Across the fleet, market revenue of {cur}{_fmt_num(system.get('revenue'), 0)} against "
            f"variable cost of {cur}{_fmt_num(system.get('variableCost'), 0)} leaves a gross margin of "
            f"{cur}{_fmt_num(system.get('grossMargin'), 0)}. "
            f"{_fmt_num(system.get('generatorsRecovered'))} of "
            f"{_fmt_num(system.get('generatorsModeled'))} modeled generators fully recover their "
            f"fixed costs from energy-market revenue in this window."
        ),
    ]


def _section_finance(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    finance = result.get("companyFinance")
    if not finance or not finance.get("companies"):
        return [_unavailable(
            "Company finance is not stored for this run.",
            "An owner column on generators in the workbook (company attribution).",
        )]
    cur = finance.get("currency") or ctx["currency"]
    rows = finance["companies"]
    best = max(rows, key=lambda r: float(r.get("npv") or 0))
    return [
        _table(
            "Company finance",
            [
                {"key": "company", "label": "Company"},
                {"key": "overnightCapex", "label": f"Overnight capex ({cur})"},
                {"key": "annualMargin", "label": f"Annual margin ({cur})"},
                {"key": "npv", "label": f"NPV ({cur})"},
                {"key": "irr", "label": "IRR"},
                {"key": "paybackYears", "label": "Payback (yr)"},
                {"key": "dscr", "label": "DSCR"},
            ],
            rows,
        ),
        _narrative(
            f"Valuations discount each company's annual margin at "
            f"{_fmt_pct(finance.get('discountRate'))} over the asset horizon. "
            f"The strongest position is {best.get('company')} with an NPV of "
            f"{cur}{_fmt_num(best.get('npv'), 0)}."
        ),
    ]


def _section_merchant(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    merchant = result.get("merchant")
    if not merchant:
        return [_unavailable(
            "Merchant analysis is not stored for this run.",
            "A merchant owner selected in the solve options.",
        )]
    cur = merchant.get("currency") or ctx["currency"]
    totals = merchant.get("totals") or {}
    stats = merchant.get("priceStats") or {}
    return [
        _kpis([
            {"label": "Owner", "value": str(merchant.get("owner", "—")), "detail": "merchant portfolio"},
            {"label": "Energy sold", "value": _fmt(totals.get("energyMWh"), "MWh", 0), "detail": ""},
            {"label": "Revenue", "value": cur + _fmt_num(totals.get("revenue"), 0),
             "detail": f"priced at {merchant.get('priceSource', 'spot')}"},
            {"label": "Profit", "value": cur + _fmt_num(totals.get("profit"), 0),
             "detail": "after operating cost and capex"},
        ]),
        _table(
            "Merchant assets",
            [
                {"key": "name", "label": "Asset"},
                {"key": "carrier", "label": "Carrier"},
                {"key": "capacityMW", "label": "Capacity (MW)"},
                {"key": "energyMWh", "label": "Energy (MWh)"},
                {"key": "revenue", "label": f"Revenue ({cur})"},
                {"key": "capturePrice", "label": f"Capture price ({cur}/MWh)"},
                {"key": "profit", "label": f"Profit ({cur})"},
            ],
            merchant.get("assets") or [],
        ),
        _narrative(
            f"The portfolio sells into prices averaging {_fmt(stats.get('mean'), cur + '/MWh')} "
            f"(range {_fmt(stats.get('min'), cur + '/MWh')} to {_fmt(stats.get('max'), cur + '/MWh')}). "
            f"Capture prices below the market average indicate cannibalisation risk for "
            f"variable-output assets."
        ),
    ]


def _section_ppa(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    ppa = result.get("ppa")
    if not ppa:
        return [_unavailable(
            "PPA settlement is not stored for this run.",
            "Enable the PPA contract (ppaConfig) in the solve options.",
        )]
    cur = ppa.get("currency") or ctx["currency"]
    buyer_net = float(ppa.get("buyerNet") or 0)
    direction = (
        "the buyer paid above spot for certainty (a hedging premium)"
        if buyer_net < 0
        else "the contract settled in the buyer's favour against spot"
    )
    return [
        _kpis([
            {"label": "Strike price", "value": _fmt(ppa.get("strikePrice"), cur + "/MWh"),
             "detail": f"{ppa.get('volumeType', '')} volume"},
            {"label": "Contracted energy", "value": _fmt(ppa.get("energyMWh"), "MWh", 0), "detail": ""},
            {"label": "Average spot", "value": _fmt(ppa.get("avgSpotPrice"), cur + "/MWh"),
             "detail": "over delivery hours"},
            {"label": "Buyer net", "value": cur + _fmt_num(buyer_net, 0),
             "detail": "settlement vs spot"},
        ]),
        _narrative(
            f"At a strike of {_fmt(ppa.get('strikePrice'), cur + '/MWh')} against an average "
            f"captured spot of {_fmt(ppa.get('avgSpotPrice'), cur + '/MWh')}, "
            f"{direction}: buyer net {cur}{_fmt_num(buyer_net, 0)}, seller net "
            f"{cur}{_fmt_num(ppa.get('sellerNet'), 0)} on "
            f"{_fmt(ppa.get('energyMWh'), 'MWh', 0)} of contracted energy."
        ),
    ]


def _section_ppa_shapes(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    explorer = result.get("ppaExplorer")
    if not explorer or not explorer.get("shapes"):
        return [_unavailable(
            "PPA shape comparison is not stored for this run.",
            "Enable the PPA contract (ppaConfig) in the solve options.",
        )]
    cur = explorer.get("currency") or ctx["currency"]
    shapes = explorer["shapes"]
    best = shapes[0]  # builder sorts by capture (avgSpotPrice) descending
    return [
        _table(
            f"Contract shapes at a {_fmt(explorer.get('strikePrice'), cur + '/MWh')} strike",
            [
                {"key": "shape", "label": "Shape"},
                {"key": "energyMWh", "label": "Energy (MWh)"},
                {"key": "avgSpotPrice", "label": f"Avg captured spot ({cur}/MWh)"},
                {"key": "buyerNet", "label": f"Buyer net ({cur})"},
                {"key": "sellerNet", "label": f"Seller net ({cur})"},
            ],
            shapes,
        ),
        _narrative(
            f"Of the shapes compared, “{best.get('shape')}” captures the highest average "
            f"spot value ({_fmt(best.get('avgSpotPrice'), cur + '/MWh')}) — the shape premium a "
            f"buyer should expect to be priced into the strike."
        ),
    ]


def _section_balance(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = ctx["result"]
    balance = result.get("energyBalance") or {}
    carriers = balance.get("carriers") or []
    if not carriers:
        return [_unavailable(
            "Energy balance is not stored for this run.",
            "A solved run (energy balance by bus carrier).",
        )]
    blocks: list[dict[str, Any]] = []
    for entry in carriers:
        sources = entry.get("sources") or []
        sinks = entry.get("sinks") or []
        blocks.append(_table(
            f"Energy balance — {entry.get('carrier', '')} "
            f"({_fmt(entry.get('supplyMWh'), 'MWh', 0)} supplied)",
            [
                {"key": "label", "label": "Source / sink"},
                {"key": "kind", "label": "Kind"},
                {"key": "energyMWh", "label": "Energy (MWh)"},
            ],
            [dict(s, energyMWh=s.get("energyMWh")) for s in sources]
            + [dict(s, energyMWh=-abs(float(s.get("energyMWh") or 0))) for s in sinks],
        ))
    return blocks


_SECTION_BUILDERS: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]] = {
    "overview": _section_overview,
    "mix": _section_mix,
    "capacity": _section_capacity,
    "cost": _section_cost,
    "emissions": _section_emissions,
    "adequacy": _section_adequacy,
    "robustness": _section_robustness,
    "prices": _section_prices,
    "economics": _section_economics,
    "finance": _section_finance,
    "merchant": _section_merchant,
    "ppa": _section_ppa,
    "ppa-shapes": _section_ppa_shapes,
    "balance": _section_balance,
}

_SECTION_TITLES: dict[str, str] = {
    "overview": "Executive overview",
    "mix": "Generation mix",
    "capacity": "Capacity and expansion",
    "cost": "System cost",
    "emissions": "Emissions",
    "adequacy": "Resource adequacy",
    "robustness": "Robustness of the build-out",
    "prices": "Price formation",
    "economics": "Generator economics",
    "finance": "Company finance",
    "merchant": "Merchant portfolio",
    "ppa": "PPA settlement",
    "ppa-shapes": "PPA contract shapes",
    "balance": "Energy balance",
}


# ---------------------------------------------------------------------------
# perspective specs — pure data; a perspective is a framing over shared sections
# ---------------------------------------------------------------------------

PERSPECTIVES: dict[str, dict[str, Any]] = {
    "policy-maker": {
        "label": "Policy maker",
        "audience": "Ministry, regulator, market-design authority",
        "description": "Affordability, adequacy and the emissions trajectory of the scenario, "
                       "with the robustness of its build-out.",
        "sections": [
            ("overview", "What does this scenario deliver, at a glance?"),
            ("mix", "Where does the energy come from?"),
            ("capacity", "What gets built, and what stays?"),
            ("cost", "What does the system cost, and where does the money go?"),
            ("emissions", "Is the system on the emissions trajectory?"),
            ("adequacy", "Does the system keep the lights on?"),
            ("robustness", "Which parts of the build-out are choices, and which are verdicts?"),
        ],
    },
    "investor": {
        "label": "Investor / developer",
        "audience": "IPP, project developer, equity investor",
        "description": "Where the market rewards capacity: prices, capture rates, cost recovery "
                       "and the technologies the optimisation chooses to build.",
        "sections": [
            ("overview", "What kind of market does this scenario describe?"),
            ("prices", "What do prices look like, and who sets them?"),
            ("economics", "Do generators recover their costs?"),
            ("capacity", "Where does the model want new capacity?"),
            ("merchant", "How does a merchant portfolio perform in this market?"),
            ("finance", "What are the company-level returns?"),
            ("robustness", "How sensitive is the investment case to near-optimal alternatives?"),
        ],
    },
    "ppa-buyer": {
        "label": "PPA buyer",
        "audience": "Corporate offtaker, procurement of clean energy",
        "description": "What a PPA is worth in this market: settlement against spot, the cost "
                       "of contract shape, and the emissions story behind the contract.",
        "sections": [
            ("overview", "What market is this contract signed into?"),
            ("prices", "What is the spot price a PPA hedges against?"),
            ("ppa", "How does the contract settle against spot?"),
            ("ppa-shapes", "What does the delivery shape cost?"),
            ("emissions", "What is the carbon intensity behind the contract?"),
        ],
    },
    "lender": {
        "label": "Lender",
        "audience": "Project finance, credit committee",
        "description": "Downside orientation: revenue stability, coverage metrics and tail risk "
                       "in the scenario's market.",
        "sections": [
            ("overview", "What scenario is the credit assessed against?"),
            ("finance", "What are the coverage and payback metrics?"),
            ("merchant", "How exposed is revenue to merchant prices?"),
            ("prices", "How volatile are the prices behind the revenue line?"),
            ("adequacy", "What does system stress look like in the tail?"),
            ("robustness", "Could a near-optimal system leave this asset stranded?"),
        ],
    },
    "procurement": {
        "label": "Procurement",
        "audience": "Utility or corporate procurement team",
        "description": "What to buy and when: the supply picture, prices, the capacity the "
                       "system adds, and the adequacy backdrop for contracting decisions.",
        "sections": [
            ("overview", "What supply picture is procurement buying into?"),
            ("balance", "Where does delivered energy actually come from?"),
            ("prices", "What price environment will contracts settle against?"),
            ("capacity", "What new capacity is coming?"),
            ("cost", "What drives the cost that ends up in tariffs?"),
            ("adequacy", "Is there enough firm capacity behind the contracts?"),
        ],
    },
}


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def list_perspectives() -> list[dict[str, Any]]:
    """Return the available report perspectives with their section outlines."""
    return [
        {
            "id": pid,
            "label": spec["label"],
            "audience": spec["audience"],
            "description": spec["description"],
            "sections": [
                {"id": sid, "title": _SECTION_TITLES[sid], "keyQuestion": question}
                for sid, question in spec["sections"]
            ],
        }
        for pid, spec in PERSPECTIVES.items()
    ]


def _resolve_run_name(name: str) -> str | None:
    """Resolve ``latest`` to the newest stored run; pass real names through."""
    if name == "latest" and not run_store.run_exists(name):
        runs = run_store.list_runs()
        return str(runs[0]["name"]) if runs else None
    return name


def _build_caveats(ctx: dict[str, Any]) -> list[str]:
    result = ctx["result"]
    options = ctx["options"]
    run_meta = result.get("runMeta") or {}
    caveats = [
        (
            "Every figure is read from the stored solve payload of this run; nothing is "
            "recomputed at report time. Re-solving with different options changes the report."
        ),
    ]
    hours = run_meta.get("modeledHours")
    if hours is not None and float(hours) < 8760:
        caveats.append(
            f"The run models {_fmt(hours, 'hours', 0)}, not a full year; totals reflect the "
            f"modeled window and its snapshot weighting."
        )
    if run_meta.get("sampling"):
        caveats.append("Snapshot sampling was active; series shown are the sampled snapshots.")
    if options.get("enableLoadShedding"):
        caveats.append(
            f"Load shedding was enabled at {_fmt(options.get('loadSheddingCost'), ctx['currency'] + '/MWh', 0)}; "
            f"prices in shedding hours reflect that cost, not ordinary dispatch."
        )
    if (ctx["scenario"] or {}).get("carbonPrice"):
        caveats.append(
            f"A carbon price of {_fmt(ctx['scenario'].get('carbonPrice'), ctx['currency'] + '/tCO2e')} "
            f"is embedded in dispatch costs and prices."
        )
    caveats.append(
        "Model results are scenario outcomes under stated assumptions, not forecasts; "
        "read ranges and comparisons, not point estimates."
    )
    return caveats


def build_report(run_name: str, perspective: str) -> dict[str, Any] | None:
    """Assemble the report document for a stored run and a perspective.

    Args:
        run_name: Stored run name, or ``latest`` for the newest run.
        perspective: A key of :data:`PERSPECTIVES`.

    Returns:
        The report document dict, or ``None`` when the run does not exist.

    Raises:
        ValueError: If ``perspective`` is unknown.
    """
    spec = PERSPECTIVES.get(perspective)
    if spec is None:
        known = ", ".join(sorted(PERSPECTIVES))
        raise ValueError(f"Unknown perspective {perspective!r}. Known: {known}.")
    resolved = _resolve_run_name(run_name)
    if resolved is None:
        return None
    analytics = run_store.get_run_analytics(resolved)
    if analytics is None:
        return None
    result = analytics.get("result") or {}
    options = analytics.get("options") or {}
    ctx: dict[str, Any] = {
        "runName": resolved,
        "result": result,
        "options": options,
        "scenario": analytics.get("scenario") or {},
        "meta": analytics,
        "currency": str(options.get("currencySymbol") or "$"),
    }
    sections = []
    for sid, key_question in spec["sections"]:
        blocks = _SECTION_BUILDERS[sid](ctx)
        if not blocks:
            continue
        sections.append({
            "id": sid,
            "title": _SECTION_TITLES[sid],
            "keyQuestion": key_question,
            "blocks": blocks,
        })
    label = analytics.get("label") or resolved
    window = ""
    if analytics.get("snapshotStart") and analytics.get("snapshotEnd"):
        window = f"{analytics['snapshotStart']} – {analytics['snapshotEnd']}"
    return {
        "runName": resolved,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "perspective": perspective,
        "perspectiveLabel": spec["label"],
        "audience": spec["audience"],
        "title": str(label),
        "subtitle": " · ".join(p for p in (spec["label"] + " briefing", window) if p),
        "currency": ctx["currency"],
        "sections": sections,
        "caveats": _build_caveats(ctx),
        "provenance": {
            "runName": resolved,
            "savedAt": analytics.get("savedAt"),
            "origin": analytics.get("origin"),
            "filename": analytics.get("filename"),
            "note": "Assembled from the stored run analytics payload; deterministic given the run.",
        },
    }
