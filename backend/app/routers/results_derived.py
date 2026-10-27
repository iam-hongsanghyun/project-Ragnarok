"""Server-side results the web UI used to compute only in the browser (WA7).

* ``GET /api/results/compare``       cross-run comparison matrix data
* ``GET /api/runs/{name}/kpis``      the KPI strip (nine headline metrics)
* ``GET /api/runs/{name}/companies`` company comparison (F1 + F2 + P&L joined)
* ``GET /api/runs/{name}/assets``    per-asset details (list, or full series for named assets)
* ``GET /api/runs/{name}/metrics``   chart metrics of a per-asset focus (the chart card's options)

The maths lives in :mod:`backend.app.results_derived` (a port of the TS the
cards still use); these routes only load the stored run and call it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .. import results_derived as rd
from .. import run_collection
from .. import run_store

router = APIRouter(tags=["results-derived"])

_BUNDLE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_BUNDLE_CACHE_SIZE = 2  # whole runs held in memory; a dashboard's cards share one load

MAX_COMPARE_RUNS = 5  # the matrix's column cap (ComparisonPane MAX_SCENARIOS)


def _analytics(name: str) -> dict[str, Any]:
    analytics = run_store.get_run_analytics(name)
    if analytics is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    return analytics


def _bundle(name: str) -> dict[str, Any]:
    """The full stored run, re-read only when its db file changed (every chart card asks)."""
    path = run_store._db_path(name) if run_store._is_safe_name(name) else None
    stamp = path.stat().st_mtime if path is not None and path.exists() else None
    hit = _BUNDLE_CACHE.get(name)
    if stamp is not None and hit is not None and hit[0] == stamp:
        return hit[1]
    bundle = run_store.get_run(name)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    if stamp is not None:
        _BUNDLE_CACHE.pop(name, None)
        while len(_BUNDLE_CACHE) >= _BUNDLE_CACHE_SIZE:
            _BUNDLE_CACHE.pop(next(iter(_BUNDLE_CACHE)))
        _BUNDLE_CACHE[name] = (stamp, bundle)
    return bundle


def _csv(raw: str | None) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


@router.get("/api/results/compare")
def compare_runs(
    runs: str = Query(..., description="Comma-separated run names (2 to 5)."),
    topics: str | None = Query(None, description=f"Comma-separated subset of {list(rd.COMPARISON_TOPICS)}; default kpi,generation-mix."),
    metrics: str | None = Query(None, description=f"For topic 'statistics': comma-separated subset of {list(run_collection.COMPARISON_METRICS)}; default {list(run_collection.DEFAULT_METRICS)}."),
    groupby: str = Query("carrier", description="For topic 'statistics': PyPSA grouper (carrier, bus_carrier, bus, ...)."),
) -> dict[str, Any]:
    """Side-by-side comparison data for stored runs (the Analytics -> Comparison matrix).

    The ``statistics`` topic (P39) adds ``item["statistics"]`` per run, evaluated by
    one ``NetworkCollection.statistics`` call over the rebuilt networks - PyPSA's own
    metric definitions side by side. The response shape of every other topic is
    unchanged.
    """
    names = _csv(runs)
    if not 2 <= len(names) <= MAX_COMPARE_RUNS:
        raise HTTPException(status_code=400, detail=f"Give 2 to {MAX_COMPARE_RUNS} run names.")
    chosen = _csv(topics) or ["kpi", "generation-mix"]
    unknown = [t for t in chosen if t not in rd.COMPARISON_TOPICS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown topics {unknown}. Options: {list(rd.COMPARISON_TOPICS)}.")
    items = [rd.run_comparison_entry(n, _analytics(n), chosen) for n in names]
    out: dict[str, Any] = {"items": items, "total": len(items), "topics": chosen}
    if "statistics" in chosen:
        bundles = {}
        for n in names:
            bundle = run_store.get_run(n)
            if bundle is None:
                raise HTTPException(status_code=404, detail=f"Stored run {n!r} not found.")
            bundles[n] = bundle
        try:
            stats = run_collection.collection_statistics(bundles, _csv(metrics) or None, groupby)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for item in items:
            item["statistics"] = stats["runs"].get(item["name"], {})
        out["statistics"] = {k: stats[k] for k in ("mode", "metrics", "groupby", "units")}
    return out


@router.get("/api/runs/{name}/kpis")
def get_run_kpis(name: str, currency: str = "$") -> dict[str, Any]:
    """The nine KPI-strip metrics for a stored run."""
    analytics = _analytics(name)
    result = analytics.get("result") or {}
    model_static = analytics.get("modelStatic") or {}

    def load_fallback() -> list[float]:
        # Only reached when the summary has no 'Peak demand' (rare): derive the
        # system load from the per-bus nets of the full run.
        bundle = run_store.get_run(name)
        if bundle is None:
            return []
        buses = rd.derive_asset_details(
            bundle.get("model") or {}, (bundle.get("result") or {}).get("outputs"), currency,
            rd.number_value((result.get("runMeta") or {}).get("snapshotWeight")) or 1.0,
            (result.get("runMeta") or {}).get("sampling"), kinds=["buses"],
        )["buses"]
        return rd.system_load_series(buses)

    kpis = rd.compute_kpis(
        result, model_static.get("carriers") or [], rd._storage_carriers(model_static), currency, load_fallback,
    )
    return {"run": name, "kpis": kpis}


@router.get("/api/runs/{name}/companies")
def get_run_companies(name: str, sort_by: str | None = None) -> dict[str, Any]:
    """Company comparison: capacity / energy / revenue / emissions / NPV / IRR / net margin per owner."""
    out = rd.compare_companies(_analytics(name).get("result") or {}, sort_by)
    return {"run": name, "items": out["companies"], "total": len(out["companies"]), **{k: out[k] for k in ("currency", "sortedBy", "metrics")}}


@router.get("/api/runs/{name}/assets")
def get_run_assets(
    name: str,
    kind: str | None = Query(None, description=f"One of {list(rd.ASSET_KINDS)}; default all."),
    names: str | None = Query(None, description="Comma-separated asset names; with these, full series are returned."),
    series: bool = Query(False, description="Include the per-snapshot series (always on when `names` is given)."),
    period: int | None = None,
    currency: str = "$",
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
) -> dict[str, Any]:
    """Per-asset details of a stored run: summaries by default, series for named assets."""
    if kind is not None and kind not in rd.ASSET_KINDS:
        raise HTTPException(status_code=400, detail=f"Unknown kind {kind!r}. Options: {list(rd.ASSET_KINDS)}.")
    wanted = set(_csv(names)) or None
    bundle = _bundle(name)
    result = bundle.get("result") or {}
    meta = result.get("runMeta") or {}
    details = rd.derive_asset_details(
        bundle.get("model") or {}, result.get("outputs"), currency,
        rd.number_value(meta.get("snapshotWeight")) or 1.0, meta.get("sampling"),
        kinds=[kind] if kind else None, names=wanted, period=period,
    )
    with_series = series or wanted is not None
    items: list[dict[str, Any]] = []
    for k, group in details.items():
        for asset_name, detail in group.items():
            row = {"kind": k, **detail}
            if not with_series:
                row = {key: v for key, v in row.items() if not key.endswith("Series")}
            items.append(row)
    total = len(items)
    return {"run": name, "items": items[offset : offset + limit], "total": total, "offset": offset, "limit": limit}


@router.get("/api/runs/{name}/metrics")
def get_run_metrics(
    name: str,
    focus: str = Query(..., description=f"Asset type: one of {list(rd.FOCUS_KINDS)}."),
    keys: str | None = Query(None, description="Comma-separated asset names; one = that asset, none = every asset of the type."),
    group_by: str = Query("carrier", alias="groupBy", description=f"Multi-generator grouping, one of {list(rd.GROUP_BYS)}."),
    bus_filter: str | None = Query(None, alias="busFilter", description="Narrow generators / storage units / stores to these buses."),
    carrier_filter: str | None = Query(None, alias="carrierFilter", description="Narrow generators to these carriers."),
    period: int | None = Query(None, description="Pathway investment period; default all rows."),
    end: int | None = Query(None, ge=1, description="Return only the first `end` snapshots (of the period)."),
    currency: str = "$",
) -> dict[str, Any]:
    """Chart-ready metrics (rows + series + colours) of a per-asset focus of a stored run.

    The server twin of ``useMetricOptions`` for ``focus != system``: the browser plots
    ``items`` instead of hydrating output series and deriving them. Only the sheets
    the focus reads are touched, and only the first ``end`` snapshots are derived.
    """
    if focus not in rd.FOCUS_KINDS:
        raise HTTPException(status_code=400, detail=f"Unknown focus {focus!r}. Options: {list(rd.FOCUS_KINDS)}.")
    if group_by not in rd.GROUP_BYS:
        raise HTTPException(status_code=400, detail=f"Unknown groupBy {group_by!r}. Options: {list(rd.GROUP_BYS)}.")
    asset_keys = _csv(keys)
    bundle = _bundle(name)
    model = bundle.get("model") or {}
    result = bundle.get("result") or {}
    meta = result.get("runMeta") or {}
    outputs = result.get("outputs") or {}
    series = rd.filter_series_by_period(
        {k: v for k, v in (outputs.get("series") or {}).items() if k in rd.FOCUS_SHEETS[focus]}, period,
    )
    if end is not None:
        series = {k: v[:end] for k, v in series.items()}
    weight = rd.number_value(meta.get("snapshotWeight")) or 1.0
    sliced = {**outputs, "series": series}
    wanted: set[str] | None = set(asset_keys) if asset_keys else None

    def derive(kind: str, names: set[str] | None) -> dict[str, Any]:
        return rd.derive_asset_details(model, sliced, currency, weight, meta.get("sampling"), kinds=[kind], names=names)

    details = derive(rd.FOCUS_KINDS[focus], wanted)
    if focus == "bus" and len(asset_keys) != 1:
        # Several buses also chart the generators attached to them.
        attached = {rd.string_value(g.get("name")) for g in model.get("generators") or []
                    if wanted is None or rd.string_value(g.get("bus")) in wanted}
        details["generators"] = derive("generators", attached)["generators"]
    items = rd.build_metric_options(
        details, model, focus, asset_keys, group_by, currency, _csv(bus_filter), _csv(carrier_filter),
    )
    return {"run": name, "focus": focus, "items": items, "total": len(items)}
