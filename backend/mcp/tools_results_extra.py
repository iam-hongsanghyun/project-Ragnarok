"""Results tools added with the P28/P29/RB10/P39 result-accounting work.

Registered on the shared ``mcp`` object from :mod:`backend.mcp.server` (one import
line at the end of that file). Thin wrappers over the REST API via
:class:`RagnarokClient`; the maths lives in ``backend/app/run_collection.py``.

Read-only:

* ``compare_run_statistics`` - native ``n.statistics`` metrics for 2-5 stored runs, evaluated
  in one ``pypsa.NetworkCollection`` (``GET /api/results/compare?topics=statistics``).
* ``get_metric_options`` - chart-ready metrics (rows + series + colours) of one per-asset
  focus of a stored run (``GET /api/runs/{name}/metrics``).
* ``get_run_analysis`` - the Analytics-card metrics the browser no longer computes: load factor /
  coincidence / per-bus shares, carrier performance, transition risk, duration curves and totals
  (``GET /api/runs/{name}/analysis/{topic}``).
* ``get_period_results`` - the result payload of ONE investment period of a pathway run, from
  that period's slice of ``n.statistics`` (``GET /api/runs/{name}/period/{period}``).
  ``get_kpis``, ``compare_companies``, ``get_asset_details`` and ``get_metric_options`` take the
  same ``period`` argument.

The other changes of that work need no new tool: the PyPSA-basis emissions
(``emissionsBreakdown.totalTco2`` / ``byStorage``), the Process rows of
``generatorEconomics`` and the ``metricDefinitions`` block travel inside the run
analytics that ``get_run_analytics`` already returns.
"""

from __future__ import annotations

from typing import Any

from .catalogue import declare_areas
from .server import _RO, get_client, mcp


@mcp.tool(
    annotations=_RO,
    description=(
        "PyPSA-native statistics side by side for 2-5 stored runs, evaluated in ONE pypsa.NetworkCollection "
        "(n.statistics with PyPSA's own definitions, no hand-rolled maths). 'metrics' picks from "
        "optimal_capacity (MW), installed_capacity (MW), supply (MWh), withdrawal (MWh), curtailment (MWh; "
        "PyPSA's max(p_max_pu*p_nom_opt - p, 0), so a dispatchable unit running below nameplate shows headroom), "
        "capex (currency/yr), opex, revenue, capacity_factor; default optimal_capacity, supply, capex, opex. "
        "'groupby' is a PyPSA grouper (carrier, bus_carrier, bus, ...; default carrier). Returns one block per run "
        "of {component, carrier, value} rows plus the units and whether the collection ('collection') or a "
        "per-network fallback was used. For the KPI / mix / cost matrix use compare_runs."
    ),
)
async def compare_run_statistics(
    run_names: list[str],
    metrics: list[str] | None = None,
    groupby: str = "carrier",
) -> Any:
    return await get_client()._get(
        "/api/results/compare",
        {
            "runs": ",".join(run_names),
            "topics": "statistics",
            "metrics": ",".join(metrics) if metrics else None,
            "groupby": groupby,
        },
    )


@mcp.tool(
    annotations=_RO,
    description=(
        "Chart-ready metrics of one per-asset focus of a stored run - what the Analytics chart card offers: "
        "rows, series and colours per metric option. 'focus' is the asset type (generator, bus, storageUnit, store, "
        "branch, process or shuntImpedance; an unknown value returns the list of valid ones). 'keys' narrows to named assets "
        "(one = that asset's own metrics, none = every asset of the type); 'group_by' (carrier or asset) groups a multi-generator "
        "view (carrier by default); 'bus_filter' / 'carrier_filter' narrow it; 'period' picks a pathway "
        "investment period; 'end' returns only the first N snapshots. Returns {run, focus, items, total}."
    ),
)
async def get_metric_options(
    run_name: str,
    focus: str,
    keys: list[str] | None = None,
    group_by: str | None = None,
    bus_filter: list[str] | None = None,
    carrier_filter: list[str] | None = None,
    period: int | None = None,
    end: int | None = None,
    currency: str | None = None,
) -> Any:
    return await get_client().get_metric_options(
        run_name,
        focus,
        keys=",".join(keys) if keys else None,
        groupBy=group_by,
        busFilter=",".join(bus_filter) if bus_filter else None,
        carrierFilter=",".join(carrier_filter) if carrier_filter else None,
        period=period,
        end=end,
        currency=currency,
    )


#: The compact sections ``get_period_results`` returns unless ``fields`` names others - the
#: per-snapshot series are the bulk of a payload and rarely what an agent wants for one period.
_PERIOD_DEFAULT_FIELDS = (
    "summary", "carrierMix", "costBreakdown", "emissionsBreakdown", "expansionResults",
    "generatorEconomics", "companies", "pathway", "runMeta", "metricDefinitions",
)


@mcp.tool(
    annotations=_RO,
    description=(
        "The result payload of ONE investment period of a stored pathway (multi-period) run, extracted from that "
        "period's slice of n.statistics: assets outside their build/lifetime window are masked, money (fuel, carbon, "
        "capex, revenue) is weighted by the period's objective weight, energy is summed, emissions carry the years "
        "weight. Same shape as the analytics 'result'. By default returns the compact sections (summary, carrierMix, "
        "costBreakdown, emissionsBreakdown, expansionResults, generatorEconomics, companies, pathway, runMeta, "
        "metricDefinitions); 'fields' names other top-level keys (e.g. dispatchSeries, systemPriceSeries, "
        "companyFinance, companyStatement) - the series are large. Errors when the run is single-period or 'period' "
        "is not one of its investment periods (the message lists them). Returns {run, period, result}."
    ),
)
async def get_period_results(
    run_name: str,
    period: int,
    fields: list[str] | None = None,
    currency: str | None = None,
) -> Any:
    return await get_client().get_run_period(
        run_name, period, fields=",".join(fields or _PERIOD_DEFAULT_FIELDS), currency=currency,
    )


@mcp.tool(
    annotations=_RO,
    description=(
        "Analytics-card metrics of a stored run, computed on the server (the UI cards show the same numbers). "
        "'topic' is one of: load-analysis (system peak MW, energy MWh, load factor = mean/peak, coincidence = system peak / "
        "sum of bus peaks, per-bus peak / energy / load factor / share), carrier-performance (per carrier: generator count, "
        "nameplate MW, generated MW, energy MWh, shares, capacity factor from n.statistics.capacity_factor, curtailment MWh, plus "
        "totals), transition-risk (each company's net margin year by year while the carbon price rises; set base_year, years, "
        "base_price, escalation_pct, stranded_threshold, demand_growth_pct, fuel_growth_pct; returns stranded year and margin at "
        "risk per company plus a summary), duration-curve (system 'source' price or load, ranked descending; load drops "
        "non-positive snapshots) and totals (sums over result rows: capacity expansion, emissions, company NPV and owner "
        "emissions, merit-order MW, stochastic expectation, maintenance hours). 'period' picks a pathway investment period; "
        "omitted = the whole horizon. An unknown topic returns the valid ones. Mean nodal price per bus is "
        "get_asset_details(kind='buses') field averageSmp."
    ),
)
async def get_run_analysis(
    run_name: str,
    topic: str,
    period: int | None = None,
    source: str | None = None,
    base_year: int | None = None,
    years: int | None = None,
    base_price: float | None = None,
    escalation_pct: float | None = None,
    stranded_threshold: float | None = None,
    demand_growth_pct: float | None = None,
    fuel_growth_pct: float | None = None,
    currency: str | None = None,
) -> Any:
    return await get_client().get_run_analysis(
        run_name, topic, period=period, source=source, baseYear=base_year, years=years, basePrice=base_price,
        escalationPct=escalation_pct, strandedThreshold=stranded_threshold, demandGrowthPct=demand_growth_pct,
        fuelGrowthPct=fuel_growth_pct, currency=currency,
    )


_TOTALS_GROUPS = ("generators", "buses", "processes")
_TOTALS_CAP = 50


@mcp.tool(
    annotations=_RO,
    description=(
        "Weighted per-asset totals of a stored run, read from PyPSA's own n.statistics under the run's snapshot weightings (so a sampled or clustered run is weighted correctly): "
        "group 'generators' = per generator energyMwh, operatingCost (marginal cost plus the carbon term), carbonCost, emissionsTco2, curtailmentMwh; 'buses' = loadMwh, generationMwh, averagePrice (load-weighted), carrierMwh; "
        "'processes' = throughputMwh, operatingCost. Also modeledHours (sum of the weights). sort_by names a field to rank by (descending); only the top `limit` assets (default 50) are returned, "
        "with a truncation notice that says how many were left out. The per-snapshot weights are omitted unless include_weights=true. period picks a pathway investment period."
    ),
)
async def get_run_totals(
    run_name: str, group: str = "generators", sort_by: str | None = None, limit: int = _TOTALS_CAP,
    period: int | None = None, include_weights: bool = False,
) -> Any:
    from urllib.parse import quote

    if group not in _TOTALS_GROUPS:
        return {"error": f'unknown group "{group}"; valid: {", ".join(_TOTALS_GROUPS)}.'}
    res = await get_client()._get(f"/api/runs/{quote(run_name, safe='')}/derived", {"period": period})
    assets: dict[str, dict[str, Any]] = res.get(group) or {}
    fields = sorted({k for v in assets.values() for k, x in v.items() if isinstance(x, (int, float))})
    if sort_by is not None and sort_by not in fields:
        return {"error": f'unknown sort_by "{sort_by}" for {group}; valid: {", ".join(fields) or "none (no assets)"}.'}
    key = sort_by or (fields[0] if fields else None)
    names = sorted(assets, key=(lambda n: -float(assets[n].get(key) or 0.0)) if key else None)  # type: ignore[arg-type]
    shown = names[: max(1, int(limit))]
    out: dict[str, Any] = {
        "run": res.get("run", run_name), "period": res.get("period"), "group": group, "modeledHours": res.get("modeledHours"),
        "sortedBy": key, "total": len(names), "returned": len(shown), "items": {n: assets[n] for n in shown},
    }
    if len(shown) < len(names):
        out["truncated"] = f"Showing the top {len(shown)} of {len(names)} {group} by {key}; raise limit or pick another group."
    if include_weights:
        out["weights"] = res.get("weights")
    else:
        out["weightsHint"] = f"Per-snapshot weights ({len(res.get('weights') or [])} values) omitted; call with include_weights=true to get them."
    return out


# Tool areas (see catalogue.py).
declare_areas({
    "get_run_totals": "results",
    "compare_run_statistics": "results",
    "get_metric_options": "results",
    "get_period_results": "results",
    "get_run_analysis": "results",
})
