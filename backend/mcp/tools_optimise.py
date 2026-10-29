"""Optimisation, statistics and network-operation tools on PyPSA 1.4 (P19-P39).

Registered on the shared ``mcp`` from :mod:`backend.mcp.server` (one import line at
the end of that file); thin wrappers over the REST API via :class:`RagnarokClient`.

Solve options themselves (``solverName``, ``transmissionLosses``,
``linearizedUnitCommitment``, ``committableBigM``, ``cycleBasisMethod``,
``computeInfeasibilities``, ``modelKwargs``, ``riskPreference``,
``iterativeExpansion``, ``twoStage``, ``nonLinearPowerFlowAfterOptimise``,
``powerFlowConfig.{xTol,useSeed,distributeSlack,slackWeights,skipPre}``,
``securityConstrainedConfig.branchOutages``, ``mgaConfig.{directions,dimensions,
maxParallel,minMax}``, ``contingencyConfig.{snapshot,branchOutages}``) are keys of
``submit_solve``'s ``options``; ``describe_optimise_options`` lists them.

Tools: describe_optimise_options, export_lp, consistency_check, network_analysis,
get_statistics, temporal_cluster, slice_model, merge_models, cluster_network_hac,
set_carrier_growth_limit.
"""
from __future__ import annotations

from typing import Any

from .catalogue import declare_areas
from .server import _EXPORT_ANN, _MUT, _RO, _needs_confirm, _preview, get_client, mcp


@mcp.tool(
    annotations=_RO,
    description="Installed solvers (capability flags) and every n.optimize / study option key accepted in submit_solve's options: transmissionLosses, linearizedUnitCommitment, committableBigM, cycleBasisMethod, computeInfeasibilities, riskPreference (CVaR), iterativeExpansion, twoStage, nonLinearPowerFlowAfterOptimise, SCLOPF branchOutages, MGA directions, powerFlowConfig extras.",
)
async def describe_optimise_options() -> Any:
    return await get_client().optimise_options()


@mcp.tool(
    annotations=_EXPORT_ANN,
    description="Write the working model's LP (or .mps) file WITHOUT solving, for inspection or an external solver. options may carry the same model-building keys as submit_solve (transmissionLosses, linearizedUnitCommitment ...). Returns path, bytes, variable and constraint counts.",
)
async def export_lp(file_name: str = "model.lp", scenario: dict[str, Any] | None = None, options: dict[str, Any] | None = None) -> Any:
    return await get_client().export_lp(file_name, scenario, options)


@mcp.tool(
    annotations=_RO,
    description="Run PyPSA's n.consistency_check on the working model (no solve): returns errors (strict failures such as maintenance/phase-shift/scenario-invariant violations) and every warning. strict=['all'] makes all checks errors; check_dtypes adds dtype checks. Run before submit_solve.",
)
async def consistency_check(strict: list[str] | None = None, check_dtypes: bool = False, options: dict[str, Any] | None = None) -> Any:
    return await get_client().consistency_check(strict, check_dtypes, options)


@mcp.tool(
    annotations=_RO,
    description="Grid-analysis outputs of the topology (no solve): include any of subnetworks (slack bus/generator), ptdf, bodf, cycles, adjacency, incidence. cycle_basis_method bfs-refined|paton. Matrices larger than max_branches are omitted.",
)
async def network_analysis(include: list[str] | None = None, cycle_basis_method: str = "bfs-refined", max_branches: int = 250) -> Any:
    return await get_client().network_analysis(include, cycle_basis_method, max_branches)


@mcp.tool(
    annotations=_RO,
    description="One PyPSA n.statistics metric on a stored run with PyPSA's own parameters. metric: energy_balance|supply|withdrawal|curtailment|capacity_factor|optimal_capacity|installed_capacity|expanded_capacity|capex|opex|installed_capex|expanded_capex|overnight_cost|fom|system_cost|revenue|market_value|prices|transmission. groupby e.g. ['bus_carrier','carrier'] (also bus, name, location, country, unit); bus_carrier filters; aggregate_time 'sum'|'mean'|false (false = time series, downsampled); at_port evaluates multi-port Links/Processes per port.",
)
async def get_statistics(
    run_name: str,
    metric: str = "energy_balance",
    groupby: list[str] | None = None,
    bus_carrier: list[str] | None = None,
    aggregate_time: str | bool = "sum",
    at_port: bool = False,
    nice_names: bool = False,
    drop_zero: bool = True,
    components: list[str] | None = None,
    carrier: list[str] | None = None,
) -> Any:
    return await get_client().statistics_query(
        run_name, metric, groupby=groupby, busCarrier=bus_carrier, aggregateTime=aggregate_time,
        atPort=at_port, niceNames=nice_names, dropZero=drop_zero, components=components, carrier=carrier,
    )


async def _apply(resp: dict[str, Any]) -> dict[str, Any]:
    await get_client().save_model(resp["model"])
    return {"status": "applied", "before": resp.get("before"), "after": resp.get("after")}


@mcp.tool(
    annotations=_MUT,
    description="Reduce the number of snapshots (representative days, resampling, downsampling) to speed up a run, with PyPSA's native temporal clustering and replace the working model. method: resample (offset like '3h' or '1D', optional drop_leap_day, aggregation_rules), downsample (stride >= 2) or segment (num_segments contiguous TSAM segments via tsam 4.1.1, installed in the backend; solver names the MIP solver tsam uses, default highs). Snapshot weightings keep annual energy and cost correct. This is the VISIBLE way to change the resolution (the run option snapshotWeight > 1 is refused): resample writes the reduced snapshots, the weightings and block-mean series into the workbook; downsample is PyPSA's point sampling (every stride-th snapshot, weight x stride). Applied on confirm.",
)
async def temporal_cluster(
    method: str = "resample",
    offset: str | None = None,
    stride: int | None = None,
    num_segments: int | None = None,
    drop_leap_day: bool = False,
    aggregation_rules: dict[str, str] | None = None,
    solver: str | None = None,
    confirm: bool = False,
) -> Any:
    args = {"method": method, "offset": offset, "stride": stride, "numSegments": num_segments,
            "dropLeapDay": drop_leap_day, "aggregationRules": aggregation_rules, "solver": solver}
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"Temporal clustering ({method}) of the working model.", args)
    return await _apply(await get_client().temporal_cluster(**{k: v for k, v in args.items() if v is not None}))


@mcp.tool(
    annotations=_MUT,
    description="Keep only part of the model, e.g. the first week of snapshots or a subset of buses. Snapshot window (start/end: integer positions, end exclusive, or ISO labels, inclusive) and/or a bus subset (buses) of the working model via n.slice_network. Applied on confirm.",
)
async def slice_model(start: int | str | None = None, end: int | str | None = None, buses: list[str] | None = None, confirm: bool = False) -> Any:
    args = {"start": start, "end": end, "buses": buses}
    if _needs_confirm(cheap=False) and not confirm:
        return _preview("Slice the working model to a window / bus subset.", args)
    return await _apply(await get_client().slice_network(**{k: v for k, v in args.items() if v is not None}))


@mcp.tool(
    annotations=_MUT,
    description="Merge another model into the working model with n.merge: give other_run (a stored run name) OR other_session_id. Component names must be unique across the two. components_to_skip lists components to leave out. Applied on confirm.",
)
async def merge_models(other_run: str | None = None, other_session_id: str | None = None, components_to_skip: list[str] | None = None, with_time: bool = True, confirm: bool = False) -> Any:
    args = {"otherRun": other_run, "otherSessionId": other_session_id, "componentsToSkip": components_to_skip, "withTime": with_time}
    if _needs_confirm(cheap=False) and not confirm:
        return _preview("Merge another model into the working model.", args)
    return await _apply(await get_client().merge_network(**{k: v for k, v in args.items() if v is not None}))


@mcp.tool(
    annotations=_MUT,
    description="Hierarchical agglomerative (HAC) spatial clustering to n_clusters buses on numeric bus columns (features, default ['x','y']), linkage ward|complete|average|single, affinity euclidean|l1|l2|manhattan|cosine (ward needs euclidean). Returns the busmap and the line map back to the original grid. Applied on confirm.",
)
async def cluster_network_hac(
    n_clusters: int,
    features: list[str] | None = None,
    linkage: str = "ward",
    affinity: str = "euclidean",
    aggregate_components: list[str] | None = None,
    confirm: bool = False,
) -> Any:
    client = get_client()
    args = {"method": "hac", "hacFeatures": features, "hacLinkage": linkage, "hacAffinity": affinity,
            "aggregateComponents": aggregate_components}
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"HAC-cluster the network to {n_clusters} buses.", {"nClusters": n_clusters, **args})
    resp = await client.cluster_network(n_clusters, **args)
    await client.save_model(resp["model"])
    return {"status": "applied", "method": resp.get("method"), "before": resp.get("before"),
            "after": resp.get("after"), "busmap": resp.get("busmap"), "linemap": resp.get("linemap")}


@mcp.tool(
    annotations=_MUT,
    description="Set a carrier's PyPSA growth limits on the carriers sheet: max_growth (MW of NEW capacity per investment period) and/or max_relative_growth (ratio). They only bind in multi-period (pathway) runs; validate_model warns otherwise.",
)
async def set_carrier_growth_limit(carrier: str, max_growth: float | None = None, max_relative_growth: float | None = None, confirm: bool = False) -> Any:
    if max_growth is None and max_relative_growth is None:
        return {"status": "error", "detail": "Give max_growth and/or max_relative_growth."}
    edits = {"max_growth": max_growth, "max_relative_growth": max_relative_growth}
    edits = {k: v for k, v in edits.items() if v is not None}
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Set growth limits on carrier {carrier!r}.", {"carrier": carrier, **edits})
    client = get_client()
    done = []
    for attr, value in edits.items():
        req = {
            "target": "carriers", "attribute": attr, "temporal": False,
            "filters": [{"column": "name", "op": "eq", "value": carrier}],
            "edit": {"op": "set", "amount": float(value)},
        }
        done.append(await client.forge_query(True, req))
    return {"status": "applied", "carrier": carrier, "edits": edits, "results": done}


# Tool areas (see catalogue.py).
declare_areas({
    "describe_optimise_options": "run",
    "export_lp": "run",
    "consistency_check": "inspect",
    "network_analysis": "inspect",
    "get_statistics": "results",
    "temporal_cluster": "transforms",
    "slice_model": "transforms",
    "merge_models": "transforms",
    "cluster_network_hac": "transforms",
    "set_carrier_growth_limit": "policy",
})
