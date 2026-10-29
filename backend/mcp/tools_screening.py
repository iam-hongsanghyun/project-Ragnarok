"""Screening module tools — statistical pre-screen of solar / wind sites and regions on historical series.

Registered on the shared ``mcp`` object from :mod:`backend.mcp.server` (one import line at the
end of that file). Thin wrappers over ``/api/screening/*`` via :class:`RagnarokClient`;
nothing here imports ``backend.app``. Every route has a tool. The tool names keep their
original ``siting_`` prefix (the module was a Siting step first) so existing agent prompts keep working.

Datasets (per-site or per-region CF or MW series + a site / region table) are stored server-side per
session, not as model sheets. The analysis tools only read them; promotion is the only tool that
touches the model. Region level: pass ``level='region'`` to the statistic tools (regions aggregated
from a site dataset, or the series of a region dataset), or use the two region tools.

Read-only (``_RO``):
  list_siting_datasets, get_siting_dataset, validate_siting_dataset, siting_correlation,
  siting_lagged_correlation, siting_profiles, siting_portfolio_metrics,
  siting_optimise_portfolio, siting_cluster_sites, siting_region_series, siting_region_structure
Gated by ``confirm`` (mutating):
  upload_siting_dataset (stores a dataset), delete_siting_dataset (removes one),
  promote_siting_sites (adds generators + p_max_pu to the working model).
"""

from __future__ import annotations

from typing import Any

from .catalogue import declare_areas
from .server import _MUT, _RO, _needs_confirm, _preview, get_client, mcp

_MAX_LIST = 200  # most per-pair / per-lag values echoed back inline


def _opts(**kw: Any) -> dict[str, Any]:
    """Drop ``None`` so the backend defaults apply."""
    return {k: v for k, v in kw.items() if v is not None}


def _json(obj: Any) -> str | None:
    import json

    return None if obj is None else json.dumps(obj)


def _sites_bytes(sites_csv: str | None, sites: list[dict[str, Any]] | None) -> bytes | None:
    if sites_csv:
        return sites_csv.encode("utf-8")
    if sites:
        import csv
        import io
        import json

        cols = list(dict.fromkeys(k for row in sites for k in row))
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols)
        writer.writeheader()
        writer.writerows([{k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in sites])
        return buf.getvalue().encode("utf-8")
    return None


_LEVEL_HELP = (
    "level: 'site' (default) or 'region' - at region level the series are regions (aggregated from the sites of "
    "a site dataset by weighting equal | capacity | custom [site_weights {site: w}], optionally by_technology, or "
    "only one technology; or the series of a region dataset) and `sites` / the weights name regions."
)


def _level_opts(level: str, weighting: str, site_weights: dict[str, float] | None, by_technology: bool,
                technology: str | None) -> dict[str, Any]:
    if level == "site":
        return {}
    return _opts(level=level, weighting=weighting, siteWeights=site_weights, byTechnology=by_technology or None,
                 technology=technology)


_BASIS_HELP = (
    "basis: hourly (raw) | daily | weekly | monthly | seasonal (season-year means; season_map = "
    "{'12':'DJF',...} for custom months) | diurnal (24 hour-of-day means) | month_hour | custom "
    "(any pandas offset alias in rule, e.g. '6h', '2W', 'QS'). start/end filter the date range, "
    "months keeps calendar months only, utc_offset_hours shifts the clock (diurnal shape in local time)."
)


@mcp.tool(
    annotations=_RO,
    description=(
        "List the siting-screening datasets stored for this session (uploaded per-site capacity-factor series + "
        "site table, or reference load / price series): id, name, kind, site count, step, window, warnings. "
        "Use the id with every siting_* tool. kind='sites' or 'reference' filters."
    ),
)
async def list_siting_datasets(kind: str | None = None) -> Any:
    return await get_client().screening_list(kind)


@mcp.tool(
    annotations=_RO,
    description=(
        "One siting-screening dataset: its sites (name, lat, lon, technology, region, unit, mean CF), step, window "
        "and the full validation report (timestamps, duplicates, gaps, time zone, units)."
    ),
)
async def get_siting_dataset(dataset_id: str) -> Any:
    return await get_client().screening_get(dataset_id)


@mcp.tool(
    annotations=_RO,
    description=(
        "Validate an upload WITHOUT storing it. series_csv is the CSV text of the series: layout 'wide' = a timestamp "
        "column + one column per site; 'long' = columns site, timestamp, value. The site table is sites_csv (CSV text) "
        "or sites (list of objects) with name, lat, lon, technology (solar|wind|other), optional region, unit "
        "(cf | mw) and capacity_mw (needed for mw). timezone is an IANA name (default UTC; offsets in the timestamps "
        "win). Reports unparseable timestamps, duplicates (averaged), gaps per site (interpolate up to "
        "max_interp_steps, else drop), and unit sanity (capacity factor must lie in 0-1). Returns ok + the report. "
        "kind='regions' validates a region-level series (one column per region: a national or zonal CF) with "
        "regions_csv / regions = rows name, optional lat, lon (centroid), technology, unit, capacity_mw and an optional "
        "geometry (GeoJSON polygon); geojson = a FeatureCollection whose properties.name is the region name."
    ),
)
async def validate_siting_dataset(
    series_csv: str,
    sites_csv: str | None = None,
    sites: list[dict[str, Any]] | None = None,
    layout: str = "wide",
    timezone: str = "UTC",
    gap_policy: str = "interpolate",
    max_interp_steps: int | None = None,
    kind: str = "sites",
    default_unit: str = "cf",
    regions_csv: str | None = None,
    regions: list[dict[str, Any]] | None = None,
    geojson: dict[str, Any] | None = None,
) -> Any:
    return await get_client().screening_upload(
        series_csv.encode("utf-8"), "series.csv", sites=_sites_bytes(regions_csv or sites_csv, regions or sites),
        sites_name="sites.csv", validate_only=True,
        form=_opts(layout=layout, timezone=timezone, gapPolicy=gap_policy, maxInterpSteps=max_interp_steps, kind=kind,
                   defaultUnit=default_unit, geojson=_json(geojson)),
    )


@mcp.tool(
    annotations=_MUT,
    description=(
        "Store a siting-screening dataset server-side for this session (survives reload; NOT model sheets). Same inputs "
        "as validate_siting_dataset plus name; kind='reference' stores ONE load or price series (reference_kind "
        "'load'|'price', unit label) to correlate sites against. Without confirm=true the upload is only validated and "
        "the report returned as a preview; with confirm it is stored and the dataset (id, sites, report) returned. "
        "kind='regions' stores a region-level dataset (regions_csv / regions / geojson as in validate_siting_dataset)."
    ),
)
async def upload_siting_dataset(
    series_csv: str,
    name: str,
    sites_csv: str | None = None,
    sites: list[dict[str, Any]] | None = None,
    layout: str = "wide",
    timezone: str = "UTC",
    gap_policy: str = "interpolate",
    max_interp_steps: int | None = None,
    kind: str = "sites",
    reference_kind: str = "load",
    unit: str = "MW",
    default_unit: str = "cf",
    regions_csv: str | None = None,
    regions: list[dict[str, Any]] | None = None,
    geojson: dict[str, Any] | None = None,
    confirm: bool = False,
) -> Any:
    client = get_client()
    form = _opts(layout=layout, timezone=timezone, gapPolicy=gap_policy, maxInterpSteps=max_interp_steps, kind=kind,
                 defaultUnit=default_unit, unit=unit, name=name, referenceKind=reference_kind, geojson=_json(geojson))
    sites_data = _sites_bytes(regions_csv or sites_csv, regions or sites)
    if _needs_confirm(cheap=False) and not confirm:
        verdict = await client.screening_upload(series_csv.encode("utf-8"), "series.csv", sites=sites_data,
                                                sites_name="sites.csv", validate_only=True, form=form)
        return _preview(
            f"Store siting dataset {name!r} ({kind}) for this session." if verdict.get("ok")
            else f"Dataset {name!r} does NOT validate and would be rejected: {verdict.get('message')}",
            {"name": name, "kind": kind, "validation": verdict},
        )
    return await client.screening_upload(series_csv.encode("utf-8"), "series.csv", sites=sites_data,
                                         sites_name="sites.csv", validate_only=False, form=form)


@mcp.tool(
    annotations=_MUT,
    description=(
        "Delete a stored siting-screening dataset (series + site table). The working model is untouched; generators "
        "already promoted from it stay. Applied on confirm."
    ),
)
async def delete_siting_dataset(dataset_id: str, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"Delete siting dataset {dataset_id!r}.", {"dataset_id": dataset_id})
    return await get_client().screening_delete(dataset_id)


@mcp.tool(
    annotations=_RO,
    description=(
        "Which wind or solar sites are correlated or complementary: site-by-site correlation matrix (Pearson or Spearman) of a screening dataset on a chosen basis, plus every "
        "site pair's distance (haversine km) vs correlation, plus optional correlation with a reference. "
        + _BASIS_HELP
        + " anomaly=true correlates hourly anomalies (month-hour cycle removed) so two solar sites do not look alike "
        "only because the sun rises (not with diurnal/month_hour bases). reference: {'type':'load'} (model load), "
        "{'type':'price','run':name} (a run's system price) or {'type':'dataset','datasetId':id}; add "
        "'align':'calendar' when the reference is another year and 'modelUtcOffsetHours' for local-time model labels. "
        "At most 60 sites. NaN correlations (constant series) come back null."
        + " " + _LEVEL_HELP
    ),
)
async def siting_correlation(
    dataset_id: str,
    sites: list[str] | None = None,
    basis: str = "daily",
    method: str = "pearson",
    rule: str | None = None,
    season_map: dict[str, str] | None = None,
    start: str | None = None,
    end: str | None = None,
    months: list[int] | None = None,
    utc_offset_hours: float = 0.0,
    anomaly: bool = False,
    anomaly_standardise: bool = False,
    reference: dict[str, Any] | None = None,
    level: str = "site",
    weighting: str = "equal",
    site_weights: dict[str, float] | None = None,
    by_technology: bool = False,
    technology: str | None = None,
) -> Any:
    out = await get_client().screening_post("correlation", _opts(
        **_level_opts(level, weighting, site_weights, by_technology, technology), datasetId=dataset_id, sites=sites, basis=basis, method=method, rule=rule, seasonMap=season_map, start=start,
        end=end, months=months, utcOffsetHours=utc_offset_hours, anomaly=anomaly, anomalyStandardise=anomaly_standardise,
        reference=reference))
    if len(out.get("distance", [])) > _MAX_LIST:
        total = len(out["distance"])
        out["distance"] = out["distance"][:_MAX_LIST]
        out["distanceTruncated"] = {"returned": _MAX_LIST, "total": total}
    return out


@mcp.tool(
    annotations=_RO,
    description=(
        "Lagged cross-correlation of one site against others, lags -N..+N hours (weather fronts moving between "
        "sites). A positive best lag means the other site repeats what `site` did that many hours earlier. Hourly "
        "series; start/end/months/utc_offset_hours as in siting_correlation. max_lag_hours up to 336. Returns the "
        "full r(lag) per other site and the best lag + r."
        + " " + _LEVEL_HELP
    ),
)
async def siting_lagged_correlation(
    dataset_id: str,
    site: str,
    others: list[str] | None = None,
    max_lag_hours: int = 48,
    start: str | None = None,
    end: str | None = None,
    months: list[int] | None = None,
    utc_offset_hours: float = 0.0,
    level: str = "site",
    weighting: str = "equal",
    site_weights: dict[str, float] | None = None,
    by_technology: bool = False,
    technology: str | None = None,
) -> Any:
    return await get_client().screening_post("lagged", _opts(
        **_level_opts(level, weighting, site_weights, by_technology, technology), datasetId=dataset_id, site=site, others=others, maxLagHours=max_lag_hours, start=start, end=end,
        months=months, utcOffsetHours=utc_offset_hours))


@mcp.tool(
    annotations=_RO,
    description=(
        "Mean-CF profiles per site: diurnal (24 hour-of-day values), monthly (12) and seasonal (DJF/MAM/JJA/SON or "
        "season_map), optionally a down-sampled time series (max 500 points; off by default here). Hourly basis; "
        "start/end/months/utc_offset_hours as in siting_correlation."
        + " " + _LEVEL_HELP
    ),
)
async def siting_profiles(
    dataset_id: str,
    sites: list[str] | None = None,
    season_map: dict[str, str] | None = None,
    start: str | None = None,
    end: str | None = None,
    months: list[int] | None = None,
    utc_offset_hours: float = 0.0,
    include_series: bool = False,
    level: str = "site",
    weighting: str = "equal",
    site_weights: dict[str, float] | None = None,
    by_technology: bool = False,
    technology: str | None = None,
) -> Any:
    return await get_client().screening_post("profiles", _opts(
        **_level_opts(level, weighting, site_weights, by_technology, technology), datasetId=dataset_id, sites=sites, seasonMap=season_map, start=start, end=end, months=months,
        utcOffsetHours=utc_offset_hours, includeSeries=include_series))


@mcp.tool(
    annotations=_RO,
    description=(
        "How complementary are wind and solar sites: complementarity metrics of a weighted portfolio of sites (weights {site: w}, normalised to sum 1): mean CF, "
        "std, coefficient of variation, P10/P50/P90 output (exceedance: P90 is exceeded 90 % of hours), share of "
        "hours below low_threshold, ramp std / max, diversification ratio, loss of output in the worst N hours, "
        "per-site rows, coincident-low-output probability per pair (with the independent expectation), ramp "
        "correlation matrix, and the combined output duration curve (200 points). Hourly series."
        + " " + _LEVEL_HELP
    ),
)
async def siting_portfolio_metrics(
    dataset_id: str,
    weights: dict[str, float],
    low_threshold: float = 0.05,
    worst_n: int = 100,
    start: str | None = None,
    end: str | None = None,
    months: list[int] | None = None,
    utc_offset_hours: float = 0.0,
    level: str = "site",
    weighting: str = "equal",
    site_weights: dict[str, float] | None = None,
    by_technology: bool = False,
    technology: str | None = None,
) -> Any:
    return await get_client().screening_post("metrics", _opts(
        **_level_opts(level, weighting, site_weights, by_technology, technology), datasetId=dataset_id, weights=weights, lowThreshold=low_threshold, worstN=worst_n, start=start, end=end,
        months=months, utcOffsetHours=utc_offset_hours))


@mcp.tool(
    annotations=_RO,
    description=(
        "Choose the best mix of complementary wind / solar sites: long-only portfolio optimiser over the chosen sites (weights >= 0, sum 1). objective 'min_variance' "
        "(optionally at least target_mean_cf) or 'max_mean' (needs variance_cap in CF^2). max_weight caps one site; "
        "region_caps {region: max total weight} uses the regions of the site table. Infeasible targets / caps return "
        "an error stating the reachable value. Returns weights, mean CF, std, the full metrics of the result and an "
        "efficient frontier (frontier_points)."
        + " " + _LEVEL_HELP
    ),
)
async def siting_optimise_portfolio(
    dataset_id: str,
    sites: list[str] | None = None,
    objective: str = "min_variance",
    target_mean_cf: float | None = None,
    variance_cap: float | None = None,
    max_weight: float = 1.0,
    region_caps: dict[str, float] | None = None,
    frontier_points: int = 12,
    low_threshold: float = 0.05,
    worst_n: int = 100,
    start: str | None = None,
    end: str | None = None,
    months: list[int] | None = None,
    utc_offset_hours: float = 0.0,
    level: str = "site",
    weighting: str = "equal",
    site_weights: dict[str, float] | None = None,
    by_technology: bool = False,
    technology: str | None = None,
) -> Any:
    return await get_client().screening_post("optimise", _opts(
        **_level_opts(level, weighting, site_weights, by_technology, technology), datasetId=dataset_id, sites=sites, objective=objective, targetMeanCf=target_mean_cf, varianceCap=variance_cap,
        maxWeight=max_weight, regionCaps=region_caps, frontierPoints=frontier_points, lowThreshold=low_threshold,
        worstN=worst_n, start=start, end=end, months=months, utcOffsetHours=utc_offset_hours))


@mcp.tool(
    annotations=_RO,
    description=(
        "Hierarchical clustering of sites on 1 - correlation (linkage average|complete|single|ward). Give k "
        "(number of clusters, default 3) or threshold (cut height on 1 - r). Returns the dendrogram leaf order, the "
        "cluster of each site and the linkage merges. "
        + _BASIS_HELP
        + " " + _LEVEL_HELP
    ),
)
async def siting_cluster_sites(
    dataset_id: str,
    sites: list[str] | None = None,
    k: int | None = None,
    threshold: float | None = None,
    linkage: str = "average",
    basis: str = "daily",
    method: str = "pearson",
    rule: str | None = None,
    season_map: dict[str, str] | None = None,
    start: str | None = None,
    end: str | None = None,
    months: list[int] | None = None,
    utc_offset_hours: float = 0.0,
    anomaly: bool = False,
    level: str = "site",
    weighting: str = "equal",
    site_weights: dict[str, float] | None = None,
    by_technology: bool = False,
    technology: str | None = None,
) -> Any:
    return await get_client().screening_post("cluster", _opts(
        **_level_opts(level, weighting, site_weights, by_technology, technology), datasetId=dataset_id, sites=sites, k=k, threshold=threshold, linkage=linkage, basis=basis, method=method,
        rule=rule, seasonMap=season_map, start=start, end=end, months=months, utcOffsetHours=utc_offset_hours,
        anomaly=anomaly))


@mcp.tool(
    annotations=_RO,
    description=(
        "The region series in use at region level: each region's members and normalised weights (when aggregated "
        "from a site dataset: CF_region = sum(w_i CF_i) / sum(w_i), weighting equal | capacity | custom with "
        "site_weights {site: w}), installed capacity, centroid, polygon (if uploaded) and mean CF; also works on a "
        "region dataset (uploaded region-level series). by_technology=true gives one series per region and "
        "technology, technology='solar'|'wind'|'other' aggregates only that technology. regions narrows to names."
    ),
)
async def siting_region_series(
    dataset_id: str,
    regions: list[str] | None = None,
    weighting: str = "equal",
    site_weights: dict[str, float] | None = None,
    by_technology: bool = False,
    technology: str | None = None,
) -> Any:
    return await get_client().screening_post("regions", _opts(
        datasetId=dataset_id, sites=regions, weighting=weighting, siteWeights=site_weights,
        byTechnology=by_technology or None, technology=technology))


@mcp.tool(
    annotations=_RO,
    description=(
        "Does spreading capacity across regions buy diversification? On a site dataset: the distribution (n, mean, "
        "median, std, min, q1, q3, max) of pairwise site correlations WITHIN each region and ACROSS each region pair "
        "(with aggregateR, the correlation of the two aggregated region series), pooled within / between means and "
        "the gain within - between; and for each site its correlation with its own region (leave-one-out) and every "
        "other region, listing the sites that behave more like another region (behavesLike). Weights as in "
        "siting_region_series; regions keeps only sites of these regions; sites narrows the sites (at most 400). "
        + _BASIS_HELP
        + " anomaly=true uses hourly anomalies."
    ),
)
async def siting_region_structure(
    dataset_id: str,
    sites: list[str] | None = None,
    regions: list[str] | None = None,
    weighting: str = "equal",
    site_weights: dict[str, float] | None = None,
    by_technology: bool = False,
    technology: str | None = None,
    basis: str = "daily",
    method: str = "pearson",
    rule: str | None = None,
    season_map: dict[str, str] | None = None,
    start: str | None = None,
    end: str | None = None,
    months: list[int] | None = None,
    utc_offset_hours: float = 0.0,
    anomaly: bool = False,
    anomaly_standardise: bool = False,
) -> Any:
    return await get_client().screening_post("regions/structure", _opts(
        datasetId=dataset_id, sites=sites, regions=regions, weighting=weighting, siteWeights=site_weights,
        byTechnology=by_technology or None, technology=technology, basis=basis, method=method, rule=rule,
        seasonMap=season_map, start=start, end=end, months=months, utcOffsetHours=utc_offset_hours, anomaly=anomaly,
        anomalyStandardise=anomaly_standardise))


@mcp.tool(
    annotations=_MUT,
    description=(
        "Add screened sites to the working model as generators with p_max_pu profiles from the dataset, aligned to "
        "the model's snapshots (exact timestamp, else the same calendar hour of another year, else the hour-of-day "
        "mean) and merged through the GUI's 'Add to workbook' rules. Each site attaches to the nearest bus unless "
        "bus_overrides {site: bus}; p_nom_mw {site: MW} (default the site capacity, else 100); extendable=true makes "
        "them zero-capacity expansion candidates (p_nom_max = p_nom_mw, capital_cost_per_mw {tech: OVERNIGHT cost}, written as overnight_cost with discount_rate - pass it, e.g. 0.07). "
        "utc_offset is hours from UTC to the model clock. Without confirm=true returns the alignment report "
        "(per-site exact/calendar/unaligned counts, warnings, ok) and applies nothing; with confirm it merges, "
        "refusing (409) when the profiles do not align unless force=true."
    ),
)
async def promote_siting_sites(
    dataset_id: str,
    sites: list[str],
    utc_offset: int = 0,
    p_nom_mw: dict[str, float] | None = None,
    extendable: bool = False,
    capital_cost_per_mw: dict[str, float] | None = None,
    discount_rate: float | None = None,
    marginal_cost: float = 0.0,
    bus_overrides: dict[str, str] | None = None,
    force: bool = False,
    confirm: bool = False,
) -> Any:
    gated = _needs_confirm(cheap=False) and not confirm
    res = await get_client().screening_post("promote", _opts(
        datasetId=dataset_id, sites=sites, utcOffset=utc_offset, pNomMw=p_nom_mw, extendable=extendable,
        capitalCost=capital_cost_per_mw, discountRate=discount_rate, marginalCost=marginal_cost, busOverrides=bus_overrides, force=force,
        apply=not gated, includeFragment=False))
    if gated:
        return _preview("Add the sites to the working model as generators with p_max_pu profiles.",
                        {"dataset_id": dataset_id, "sites": sites, "report": res.get("report"),
                         "counts": res.get("counts"), "generators": res.get("generators")})
    res.pop("meta", None)
    return res


# Tool areas (see catalogue.py).
declare_areas({
    "list_siting_datasets": "siting",
    "get_siting_dataset": "siting",
    "validate_siting_dataset": "siting",
    "upload_siting_dataset": "siting",
    "delete_siting_dataset": "siting",
    "siting_correlation": "siting",
    "siting_lagged_correlation": "siting",
    "siting_profiles": "siting",
    "siting_portfolio_metrics": "siting",
    "siting_optimise_portfolio": "siting",
    "siting_cluster_sites": "siting",
    "siting_region_series": "siting",
    "siting_region_structure": "siting",
    "promote_siting_sites": "siting",
})
