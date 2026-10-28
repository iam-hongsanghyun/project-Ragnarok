"""Server-side results the web UI used to compute only in the browser (WA7).

* ``GET /api/results/compare``       cross-run comparison matrix data
* ``GET /api/runs/{name}/kpis``      the KPI strip (nine headline metrics)
* ``GET /api/runs/{name}/companies`` company comparison (F1 + F2 + P&L joined)
* ``GET /api/runs/{name}/assets``    per-asset details (list, or full series for named assets)
* ``GET /api/runs/{name}/metrics``   chart metrics of a per-asset focus (the chart card's options)
* ``GET /api/runs/{name}/period/{period}``  the result payload of ONE investment period of a pathway run

``kpis``, ``companies``, ``assets`` and ``metrics`` all take ``period`` (a pathway
run's investment period); omitted = the whole horizon. KPIs and companies read the
period payload, assets and metrics slice the stored series to the period.

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
_PERIOD_CACHE: dict[tuple[str, float, int, str], dict[str, Any]] = {}
_PERIOD_CACHE_SIZE = 8  # derived period payloads (each re-extraction takes about a second)

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


def _period_result(name: str, period: int, currency: str | None = None) -> dict[str, Any]:
    """The result payload of one investment period of stored pathway run ``name``.

    Rebuilds the run's network from its stored model and outputs and extracts
    the payload from the period's slice of ``n.statistics`` (see
    :func:`backend.pypsa.results.derive_outputs.period_view_network`), so a
    period view uses the same definitions as the whole-horizon payload: inactive
    assets masked, money x the period's objective weight, energy summed.

    The result is the stored run's own payload with the period-specific blocks
    replaced; ``pathway`` keeps every period (the selector needs them) with
    ``selectedPeriod`` set, and ``outputs`` is dropped (the series are read
    windowed from ``/api/runs/{name}/series/{sheet}``).

    Raises:
        HTTPException: 404 missing run; 400 not a pathway run / unknown period.
    """
    from ...pypsa.results.derive_outputs import derive_results_from_outputs

    bundle = _bundle(name)
    path = run_store._db_path(name)
    stamp = path.stat().st_mtime if path.exists() else 0.0
    key = (name, stamp, int(period), currency or "")
    hit = _PERIOD_CACHE.get(key)
    if hit is not None:
        return hit
    stored = bundle.get("result") or {}
    pathway = stored.get("pathway") or {}
    periods = [int(p) for p in (pathway.get("periods") or [])]
    if not pathway.get("enabled") or not periods:
        raise HTTPException(status_code=400, detail="Run is not a multi-period (pathway) run.")
    if int(period) not in periods:
        raise HTTPException(status_code=400, detail=f"Period {period} is not one of {periods}.")
    options = dict(bundle.get("options") or {})
    if currency:
        options["currencySymbol"] = currency
    try:
        derived = derive_results_from_outputs(
            bundle.get("model") or {}, stored.get("outputs") or {}, bundle.get("scenario") or {},
            options, period=int(period),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    derived.pop("outputs", None)
    derived["pathway"] = {**pathway, "selectedPeriod": int(period)}
    derived["runMeta"] = {
        **(derived.get("runMeta") or {}),
        "planningMode": "pathway",
        "investmentPeriods": periods,
    }
    while len(_PERIOD_CACHE) >= _PERIOD_CACHE_SIZE:
        _PERIOD_CACHE.pop(next(iter(_PERIOD_CACHE)))
    _PERIOD_CACHE[key] = derived
    return derived


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
def get_run_kpis(name: str, currency: str = "$", period: int | None = None) -> dict[str, Any]:
    """The nine KPI-strip metrics for a stored run (one investment period with ``period``)."""
    analytics = _analytics(name)
    model_static = analytics.get("modelStatic") or {}
    result = _period_result(name, period, currency) if period is not None else (analytics.get("result") or {})

    def load_fallback() -> list[float]:
        # Only reached when the summary has no 'Peak demand' (rare): derive the
        # system load from the per-bus nets of the full run.
        bundle = run_store.get_run(name)
        if bundle is None:
            return []
        buses = rd.derive_asset_details(
            bundle.get("model") or {}, (bundle.get("result") or {}).get("outputs"), currency,
            rd.number_value((result.get("runMeta") or {}).get("snapshotWeight")) or 1.0,
            (result.get("runMeta") or {}).get("sampling"), kinds=["buses"], period=period,
        )["buses"]
        return rd.system_load_series(buses)

    kpis = rd.compute_kpis(
        result, model_static.get("carriers") or [], rd._storage_carriers(model_static), currency, load_fallback,
    )
    return {"run": name, "period": period, "kpis": kpis}


@router.get("/api/runs/{name}/companies")
def get_run_companies(name: str, sort_by: str | None = None, period: int | None = None) -> dict[str, Any]:
    """Company comparison: capacity / energy / revenue / emissions / NPV / IRR / net margin per owner."""
    result = _period_result(name, period) if period is not None else (_analytics(name).get("result") or {})
    out = rd.compare_companies(result, sort_by)
    return {"run": name, "period": period, "items": out["companies"], "total": len(out["companies"]), **{k: out[k] for k in ("currency", "sortedBy", "metrics")}}


@router.get("/api/runs/{name}/period/{period}")
def get_run_period(
    name: str,
    period: int,
    currency: str | None = None,
    fields: str | None = Query(None, description="Comma-separated top-level `result` keys to return; default all."),
) -> dict[str, Any]:
    """The full result payload of one investment period of a pathway run.

    Same shape as ``result`` in ``GET /api/runs/{name}/analytics`` (summary, carrier
    mix, dispatch / price / emissions series, cost breakdown, expansion, emissions
    breakdown, generator economics, companies, ...) but evaluated on the period's
    slice of the run. ``pathway`` lists every period with ``selectedPeriod`` set;
    ``outputs`` is omitted. ``fields`` narrows ``result`` to the named top-level keys
    (the per-snapshot series are the bulk of the payload). 400 when the run is
    single-period, ``period`` is not one of its investment periods, or a field is
    not a ``result`` key.
    """
    _analytics(name)  # 404 before any work
    result = _period_result(name, period, currency)
    wanted = _csv(fields)
    if wanted:
        unknown = [f for f in wanted if f not in result]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown fields {unknown}. Options: {sorted(result)}.")
        result = {k: result[k] for k in wanted}
    return {"run": name, "period": period, "result": result}


@router.get("/api/runs/{name}/assets")
def get_run_assets(
    name: str,
    kind: str | None = Query(None, description=f"One of {list(rd.ASSET_KINDS)}; default all."),
    names: str | None = Query(None, description="Comma-separated asset names; with these, full series are returned."),
    series: bool = Query(False, description="Include the per-snapshot series (always on when `names` is given)."),
    period: int | None = Query(None, description="Pathway investment period; default all rows."),
    end: int | None = Query(None, ge=1, description="Derive from only the first `end` snapshots (of the period)."),
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
    outputs = result.get("outputs")
    if end is not None and outputs and outputs.get("series"):
        # Same windowing as /metrics: keep the period, then the first `end` snapshots.
        outputs = {**outputs, "series": {
            k: v[:end] for k, v in rd.filter_series_by_period(outputs["series"], period).items()
        }}
        period = None
    details = rd.derive_asset_details(
        bundle.get("model") or {}, outputs, currency,
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


def _series_rows(name: str, sheet: str, period: int | None) -> tuple[list[str], list[dict[str, Any]], str]:
    """``(columns, rows, index_col)`` of one stored output sheet, one period when given."""
    from .. import timeseries

    outputs = (_bundle(name).get("result") or {}).get("outputs") or {}
    rows = rd.filter_series_by_period({sheet: (outputs.get("series") or {}).get(sheet) or []}, period)[sheet]
    columns = [str(c) for c in (rows[0].keys() if rows else [])]
    return columns, rows, timeseries.series_index_col(columns) if columns else "snapshot"


def _system_load_values(name: str, period: int | None) -> list[float]:
    """Per-snapshot system load (sum over the ``loads-p`` columns) of a stored run, one period when given."""
    from ...pypsa.results.derived_series import METRIC_SHEET, derive_series

    columns, rows, index_col = _series_rows(name, METRIC_SHEET["load"], period)
    if not rows:
        return []
    return list(derive_series(columns, rows, index_col, metric="load", carriers={})["series"][0]["values"])


@router.get("/api/runs/{name}/analysis/{topic}")
def get_run_analysis(
    name: str,
    topic: str,
    period: int | None = Query(None, description="Pathway investment period; default the whole horizon."),
    currency: str = "$",
    source: str = Query("load", description="duration-curve: 'price' or 'load'."),
    base_year: int = Query(2030, alias="baseYear", description="transition-risk: first year of the trajectory."),
    years: int = Query(20, ge=1, le=100, description="transition-risk: horizon length in years."),
    base_price: float = Query(50.0, ge=0, alias="basePrice", description="transition-risk: carbon price in the base year (currency/tCO2)."),
    escalation_pct: float = Query(5.0, ge=0, alias="escalationPct", description="transition-risk: annual carbon-price escalation (%/yr)."),
    stranded_threshold: float = Query(0.0, alias="strandedThreshold", description="transition-risk: net margin at or below this (currency/yr) is stranded."),
    demand_growth_pct: float = Query(0.0, alias="demandGrowthPct", description="transition-risk: annual demand growth (%/yr)."),
    fuel_growth_pct: float = Query(0.0, alias="fuelGrowthPct", description="transition-risk: annual fuel-price change (%/yr)."),
) -> dict[str, Any]:
    """Card analytics the browser used to compute from result series (P28), by ``topic``.

    * ``load-analysis``       system peak / energy / load factor / coincidence + per-bus shares.
    * ``carrier-performance`` the Carrier performance table with totals.
    * ``transition-risk``     the company net-margin trajectory under a rising carbon price.
    * ``duration-curve``      ``source`` (price | load) ranked descending, per snapshot of the period.
    * ``setpoint-duals``      which ramp-limit / set-point constraints bind, when, at what shadow price.
    * ``totals``              sums over result rows (expansion, emissions, companies, merit order,
                              stochastic expectation, maintenance hours).

    ``period`` selects one investment period of a pathway run for every topic.
    """
    if topic not in rd.ANALYSIS_TOPICS:
        raise HTTPException(status_code=400, detail=f"Unknown topic {topic!r}. Options: {list(rd.ANALYSIS_TOPICS)}.")
    if topic == "duration-curve":
        if source not in ("price", "load"):
            raise HTTPException(status_code=400, detail="source must be 'price' or 'load'.")
        stored = _analytics(name).get("result") or {}
        if source == "price":
            # The same series the system price chart plots (the load-weighted system price), so the
            # curve and the chart agree; a pathway period reads that period's payload.
            result = _period_result(name, period, currency) if period is not None else stored
            values = [rd._num(p.get("value")) for p in result.get("systemPriceSeries") or []]
        else:
            values = _system_load_values(name, period)
        values = rd.duration_curve(values, drop_non_positive=source == "load")
        return {"run": name, "topic": topic, "period": period, "source": source, "values": values, "total": len(values)}
    analytics = _analytics(name)
    if topic == "setpoint-duals":
        stored = _bundle(name).get("result") or {}
        series = rd.filter_series_by_period(
            {k: v for k, v in ((stored.get("outputs") or {}).get("series") or {}).items() if rd._DUAL_SHEET.match(k)}, period,
        )
        body = rd.setpoint_duals(series, rd.number_value((stored.get("runMeta") or {}).get("snapshotWeight")) or 1.0)
        return {"run": name, "topic": topic, "period": period, **body}
    result = _period_result(name, period, currency) if period is not None else (analytics.get("result") or {})
    if topic == "load-analysis":
        bundle = _bundle(name)
        stored = bundle.get("result") or {}
        meta = stored.get("runMeta") or {}
        details = rd.derive_asset_details(
            bundle.get("model") or {}, stored.get("outputs"), currency,
            rd.number_value(meta.get("snapshotWeight")) or 1.0, meta.get("sampling"), kinds=["buses"], period=period,
        )["buses"]
        body = rd.load_analysis(details, rd.number_value(meta.get("snapshotWeight")) or 1.0)
    elif topic == "carrier-performance":
        body = rd.carrier_performance(
            result, analytics.get("modelStatic"), ((analytics.get("result") or {}).get("outputs") or {}).get("static"), period,
        )
    elif topic == "transition-risk":
        statement = result.get("companyStatement")
        if not statement:
            raise HTTPException(status_code=404, detail="This run has no company P&L (needs owner tags and an LP run).")
        body = rd.transition_risk(
            statement, base_year=base_year, years=years, base_price=base_price, escalation_pct=escalation_pct,
            stranded_threshold=stranded_threshold, demand_growth_pct=demand_growth_pct, fuel_growth_pct=fuel_growth_pct,
        )
    else:
        peak = None
        if result.get("meritOrder"):
            loads = rd.duration_curve(_system_load_values(name, period), drop_non_positive=True)
            peak = loads[0] if loads else None
        body = rd.result_totals(result, peak)
    return {"run": name, "topic": topic, "period": period, **body}
