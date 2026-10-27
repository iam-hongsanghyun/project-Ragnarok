"""Results tools added with the P28/P29/RB10/P39 result-accounting work.

Registered on the shared ``mcp`` object from :mod:`backend.mcp.server` (one import
line at the end of that file). Thin wrappers over the REST API via
:class:`RagnarokClient`; the maths lives in ``backend/app/run_collection.py``.

Read-only:

* ``compare_run_statistics`` - native ``n.statistics`` metrics for 2-5 stored runs, evaluated
  in one ``pypsa.NetworkCollection`` (``GET /api/results/compare?topics=statistics``).
* ``get_metric_options`` - chart-ready metrics (rows + series + colours) of one per-asset
  focus of a stored run (``GET /api/runs/{name}/metrics``).

The other changes of that work need no new tool: the PyPSA-basis emissions
(``emissionsBreakdown.totalTco2`` / ``byStorage``), the Process rows of
``generatorEconomics`` and the ``metricDefinitions`` block travel inside the run
analytics that ``get_run_analytics`` already returns.
"""

from __future__ import annotations

from typing import Any

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
