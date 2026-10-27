"""Server-side results the web UI used to compute only in the browser (WA7).

* ``GET /api/results/compare``       cross-run comparison matrix data
* ``GET /api/runs/{name}/kpis``      the KPI strip (nine headline metrics)
* ``GET /api/runs/{name}/companies`` company comparison (F1 + F2 + P&L joined)
* ``GET /api/runs/{name}/assets``    per-asset details (list, or full series for named assets)

The maths lives in :mod:`backend.app.results_derived` (a port of the TS the
cards still use); these routes only load the stored run and call it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .. import results_derived as rd
from .. import run_store

router = APIRouter(tags=["results-derived"])

MAX_COMPARE_RUNS = 5  # the matrix's column cap (ComparisonPane MAX_SCENARIOS)


def _analytics(name: str) -> dict[str, Any]:
    analytics = run_store.get_run_analytics(name)
    if analytics is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    return analytics


def _csv(raw: str | None) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


@router.get("/api/results/compare")
def compare_runs(
    runs: str = Query(..., description="Comma-separated run names (2 to 5)."),
    topics: str | None = Query(None, description=f"Comma-separated subset of {list(rd.COMPARISON_TOPICS)}; default kpi,generation-mix."),
) -> dict[str, Any]:
    """Side-by-side comparison data for stored runs (the Analytics -> Comparison matrix)."""
    names = _csv(runs)
    if not 2 <= len(names) <= MAX_COMPARE_RUNS:
        raise HTTPException(status_code=400, detail=f"Give 2 to {MAX_COMPARE_RUNS} run names.")
    chosen = _csv(topics) or ["kpi", "generation-mix"]
    unknown = [t for t in chosen if t not in rd.COMPARISON_TOPICS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown topics {unknown}. Options: {list(rd.COMPARISON_TOPICS)}.")
    items = [rd.run_comparison_entry(n, _analytics(n), chosen) for n in names]
    return {"items": items, "total": len(items), "topics": chosen}


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
    bundle = run_store.get_run(name)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
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
