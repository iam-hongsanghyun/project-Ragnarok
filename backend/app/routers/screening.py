"""``/api/screening/*`` — statistical pre-screen of solar and wind sites and regions.

Datasets (uploaded per-site or per-region CF / MW series + a site / region table) live
server-side per session under ``<data root>/screening_datasets/`` (see
``screening/datasets.py``; the old ``siting_datasets/`` folder is migrated on first touch), not in
the model sheets, and survive reload. Every statistic is computed here
(``screening/correlation.py``); the browser only draws what comes back.

Level. The statistic routes (correlation, lagged, profiles, metrics, optimise, cluster)
take ``level: "site" | "region"``. At ``region`` the series analysed are region series -
aggregated from the sites of a site dataset (``weighting`` equal | capacity | custom,
``byTechnology``, ``technology``) or the series of a region dataset - and the response
shapes are those of the site level, with region names where site names were
(``sites`` lists regions, ``distance`` is between centroids).

  POST   /validate                 multipart  validation report, nothing stored
  POST   /datasets                 multipart  validate + store (gap policy interpolate | drop)
  GET    /datasets                 list ``{items, total}``
  GET    /datasets/{id}            one dataset: sites + validation report
  DELETE /datasets/{id}
  POST   /correlation              matrix (Pearson / Spearman) on a basis, vs-distance pairs, vs a reference
  POST   /lagged                   lagged cross-correlation of one site against others
  POST   /profiles                 diurnal / monthly / seasonal profiles + a down-sampled series
  POST   /metrics                  complementarity metrics of a weighted portfolio + duration curve
  POST   /optimise                 min-variance / max-mean portfolio (+ efficient frontier)
  POST   /cluster                  hierarchical clustering on 1 - correlation
  POST   /regions                  the region series in use: members, weights, centroid, polygon
  POST   /regions/structure        within- vs between-region correlation, site vs own / other regions
  POST   /promote                  preview or apply: selected sites -> generators + p_max_pu

Sizes are capped: matrices for at most ``MAX_MATRIX_SITES`` sites, chart series
down-sampled to ``MAX_CHART_POINTS``.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from .. import fragment_merge, model_store, run_store
from ..screening import correlation as corr
from ..screening import datasets as ds
from ..screening.promote import build_promotion

router = APIRouter(prefix="/api/screening", tags=["screening"])

#: Most sites in one correlation / cluster / metrics request (matrix payload = n^2 floats).
MAX_MATRIX_SITES = int(os.environ.get("RAGNAROK_SITING_MAX_MATRIX_SITES", "60"))
#: Most points of a chart series returned.
MAX_CHART_POINTS = int(os.environ.get("RAGNAROK_SITING_MAX_CHART_POINTS", "500"))
#: Most sites in a region-structure request (only per-region summaries are returned, so more than a matrix).
MAX_STRUCTURE_SITES = int(os.environ.get("RAGNAROK_SITING_MAX_STRUCTURE_SITES", "400"))
#: Longest lag searched (hours).
MAX_LAG_HOURS = int(os.environ.get("RAGNAROK_SITING_MAX_LAG_HOURS", "336"))


# ── helpers ───────────────────────────────────────────────────────────────────


def _clean(obj: Any) -> Any:
    """Recursively turn NaN / inf into ``None`` and numpy scalars into Python numbers (JSON-safe)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _clean(obj.tolist())
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def _bad(status: int, exc: Exception) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


def _dataset(session_id: str, dataset_id: str, kind: str | None = "sites") -> tuple[dict[str, Any], pd.DataFrame]:
    try:
        meta = ds.get_meta(session_id, dataset_id)
        series = ds.load_series(session_id, dataset_id) if meta else None
    except ds.DatasetError as exc:
        raise _bad(400, exc) from exc
    if meta is None or series is None:
        raise HTTPException(404, f"Dataset {dataset_id!r} not found.")
    if kind and meta.get("kind") != kind:
        raise HTTPException(422, f"Dataset {dataset_id!r} is a {meta.get('kind')} dataset, expected {kind}.")
    return meta, series


def _regions_of(meta: dict[str, Any], series: pd.DataFrame, req: ScreenBase) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
    """Region series + info rows of a dataset: aggregated from its sites, or its own region series."""
    if meta.get("kind") == "regions":
        rows = [{
            "name": r["name"], "region": r["name"], "technology": r.get("technology") or "all", "nSites": None, "members": None,
            "capacityMw": r.get("capacityMw"), "lat": r.get("lat"), "lon": r.get("lon"), "geometry": r.get("geometry"),
            "meanCf": float(series[r["name"]].mean()),
        } for r in meta.get("regions", []) if r["name"] in series.columns]
        return series[[r["name"] for r in rows]], rows, []
    try:
        frame, rows, unassigned = corr.aggregate_regions(
            series, meta["sites"], weighting=req.weighting, weights=req.siteWeights, by_technology=req.byTechnology,
            technology=req.technology,
        )
    except ValueError as exc:
        raise _bad(422, exc) from exc
    return frame, rows, unassigned


def _load(req: ScreenBase) -> tuple[dict[str, Any], pd.DataFrame]:
    """The dataset of a request at its level: sites as stored, or a region view of it.

    The region view is a pseudo dataset (``kind`` ``sites``) whose ``sites`` are the region rows
    (``name, region, technology, lat, lon, meanCf, ...``) and whose series has one column per
    region, so the site routes run on it unchanged.
    """
    if req.level == "site":
        return _dataset(req.sessionId, req.datasetId)
    if req.level != "region":
        raise HTTPException(422, "level must be 'site' or 'region'.")
    meta, series = _dataset(req.sessionId, req.datasetId, kind=None)
    if meta.get("kind") not in ("sites", "regions"):
        raise HTTPException(422, f"Dataset {req.datasetId!r} is a {meta.get('kind')} dataset; regions come from a site or region dataset.")
    frame, rows, _ = _regions_of(meta, series, req)
    return {**meta, "kind": "sites", "sites": rows, "level": "region"}, frame


class ScreenBase(BaseModel):
    """Selection + analysis basis shared by the statistic routes."""

    sessionId: str = "default"
    datasetId: str
    sites: list[str] | None = Field(None, description="Sites to include; default all (at most MAX_MATRIX_SITES).")
    basis: str = Field("daily", description=f"One of {list(corr.BASES)}.")
    rule: str | None = Field(None, description="pandas offset alias for basis 'custom' (e.g. '6h', '2W', 'QS').")
    seasonMap: dict[str, str] | None = Field(None, description="Custom month (1-12) -> season label for basis 'seasonal'.")
    start: str | None = Field(None, description="First timestamp kept (ISO date or datetime, analysis clock).")
    end: str | None = Field(None, description="Last timestamp kept; a bare date keeps the whole day.")
    months: list[int] | None = Field(None, description="Keep only these calendar months (1-12).")
    utcOffsetHours: float = Field(0.0, description="Analysis clock = UTC + this many hours (diurnal shapes follow local time).")
    method: str = Field("pearson", description="pearson | spearman")
    anomaly: bool = Field(False, description="Correlate hourly anomalies (diurnal + seasonal cycle removed).")
    anomalyStandardise: bool = Field(False, description="Divide anomalies by their (month, hour) standard deviation.")
    level: str = Field("site", description="site | region: analyse sites, or region series (aggregated from sites, or a region dataset).")
    weighting: str = Field("equal", description=f"Aggregation weights of sites into regions, one of {list(corr.WEIGHTINGS)}.")
    siteWeights: dict[str, float] | None = Field(None, description="{site: weight} for weighting 'custom'.")
    byTechnology: bool = Field(False, description="One region series per (region, technology).")
    technology: str | None = Field(None, description="Aggregate only sites of this technology.")


def _season_map(req: ScreenBase) -> dict[int, str] | None:
    if not req.seasonMap:
        return None
    try:
        out = {int(k): str(v) for k, v in req.seasonMap.items()}
    except ValueError as exc:
        raise HTTPException(422, "seasonMap keys must be month numbers 1-12.") from exc
    if any(not 1 <= m <= 12 for m in out):
        raise HTTPException(422, "seasonMap keys must be month numbers 1-12.")
    return out


def _select(meta: dict[str, Any], series: pd.DataFrame, sites: list[str] | None) -> pd.DataFrame:
    """Columns chosen by name (all of the dataset by default), at most ``MAX_MATRIX_SITES``."""
    names = [s["name"] for s in meta.get("sites", [])] if meta.get("kind") == "sites" else list(series.columns)
    chosen = sites if sites else names
    unknown = [s for s in chosen if s not in series.columns]
    if unknown:
        raise HTTPException(422, f"Unknown site(s): {unknown[:8]}.")
    if len(chosen) > MAX_MATRIX_SITES:
        raise HTTPException(422, f"{len(chosen)} sites selected; at most {MAX_MATRIX_SITES} per request - narrow the selection.")
    return series[list(dict.fromkeys(chosen))]


def _pipeline(frame: pd.DataFrame, req: ScreenBase, *, resample: bool = True, allow_anomaly: bool = True) -> pd.DataFrame:
    """Window -> anomalies -> basis, in that order (the same for sites and the reference)."""
    out = corr.filter_window(frame, req.start, req.end, req.months, req.utcOffsetHours)
    if len(out) == 0:
        raise HTTPException(422, "No data in the chosen date range / months.")
    if req.anomaly and allow_anomaly:
        if req.basis in ("diurnal", "month_hour") and resample:
            raise HTTPException(422, "Anomalies remove the cycle that the diurnal / month-hour basis shows; pick another basis.")
        out = corr.anomalies(out, standardise=req.anomalyStandardise)
    if resample:
        try:
            out = corr.resample_basis(out, req.basis, rule=req.rule, season_map=_season_map(req))
        except ValueError as exc:
            raise _bad(422, exc) from exc
    return out


def _hourly(meta: dict[str, Any], series: pd.DataFrame, req: ScreenBase) -> pd.DataFrame:
    frame = _select(meta, series, req.sites)
    return _pipeline(frame, req, resample=False, allow_anomaly=False)


# ── datasets ──────────────────────────────────────────────────────────────────


async def _build_from_form(
    file: UploadFile, sites_file: UploadFile | None, sites_json: str | None, layout: str,
    timezone_name: str, gap_policy: str, max_interp_steps: int | None, kind: str, default_unit: str,
    reference_unit: str, geojson_file: UploadFile | None = None, geojson_text: str | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any], str]:
    data = await file.read()
    if len(data) > ds.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File is {len(data) / 1e6:.0f} MB; the limit is {ds.MAX_UPLOAD_BYTES / 1e6:.0f} MB.")
    series_df = ds.read_table(data, file.filename or "")
    sites_df: pd.DataFrame | None = None
    geojson: Any = None
    if kind == "regions":
        if geojson_file is not None and (geojson_file.filename or ""):
            geojson = (await geojson_file.read()).decode("utf-8", errors="replace")
        elif geojson_text:
            geojson = geojson_text
    if kind in ("sites", "regions"):
        if sites_file is not None and (sites_file.filename or ""):
            sites_df = ds.read_table(await sites_file.read(), sites_file.filename or "")
        elif sites_json:
            try:
                parsed = json.loads(sites_json)
                sites_df = pd.DataFrame(parsed)
            except (ValueError, TypeError) as exc:
                raise ds.DatasetError(f"sitesJson is not a JSON list of {'region' if kind == 'regions' else 'site'} objects: {exc}") from exc
            if kind == "regions" and "geometry" in sites_df.columns:  # nested objects: keep them as JSON text
                sites_df["geometry"] = sites_df["geometry"].map(lambda g: json.dumps(g) if isinstance(g, dict) else g)
    grid, sites, report = ds.build_dataset(
        series_df, layout=layout, sites_df=sites_df, timezone_name=timezone_name, gap_policy=gap_policy,
        max_interp_steps=max_interp_steps, kind=kind, default_unit=default_unit, reference_unit=reference_unit,
        geojson=geojson,
    )
    return grid, sites, report, file.filename or ""


@router.post("/validate")
async def validate_upload(
    file: UploadFile,
    sitesFile: UploadFile | None = None,
    sitesJson: str | None = Form(None),
    layout: str = Form("wide"),
    timezone: str = Form("UTC"),
    gapPolicy: str = Form("interpolate"),
    maxInterpSteps: int | None = Form(None),
    kind: str = Form("sites"),
    defaultUnit: str = Form("cf"),
    unit: str = Form("MW"),
    geojsonFile: UploadFile | None = None,
    geojson: str | None = Form(None),
) -> dict[str, Any]:
    """Validate an upload and report timestamps, duplicates, gaps, time zone and units. Stores nothing.

    ``kind`` is ``sites`` (series + site table), ``regions`` (series per region + a region table in
    ``sitesFile`` / ``sitesJson``, optional ``geojsonFile`` / ``geojson`` polygons) or ``reference``.
    """
    try:
        grid, sites, report, _ = await _build_from_form(
            file, sitesFile, sitesJson, layout, timezone, gapPolicy, maxInterpSteps, kind, defaultUnit, unit,
            geojsonFile, geojson,
        )
    except ds.DatasetError as exc:
        return _clean({"ok": False, "message": str(exc), "report": exc.report or {"errors": [str(exc)], "warnings": []}})
    return _clean({"ok": True, "message": "Valid.", "report": report, "siteCount": len(sites) if kind != "reference" else 1,
                   "rows": len(grid)})


@router.post("/datasets")
async def upload_dataset(
    file: UploadFile,
    sitesFile: UploadFile | None = None,
    sitesJson: str | None = Form(None),
    sessionId: str = Form("default"),
    name: str = Form(""),
    layout: str = Form("wide"),
    timezone: str = Form("UTC"),
    gapPolicy: str = Form("interpolate"),
    maxInterpSteps: int | None = Form(None),
    kind: str = Form("sites"),
    referenceKind: str = Form("load"),
    defaultUnit: str = Form("cf"),
    unit: str = Form("MW"),
    geojsonFile: UploadFile | None = None,
    geojson: str | None = Form(None),
) -> dict[str, Any]:
    """Validate and store a dataset (a site set, a region set, or one reference load / price series)."""
    try:
        grid, sites, report, filename = await _build_from_form(
            file, sitesFile, sitesJson, layout, timezone, gapPolicy, maxInterpSteps, kind, defaultUnit, unit,
            geojsonFile, geojson,
        )
        meta = ds.store_dataset(
            sessionId, name, grid, sites, report, kind=kind, timezone_name=timezone, layout=layout, filename=filename,
            reference_kind=referenceKind if kind == "reference" else None, unit=unit if kind == "reference" else "cf",
        )
    except ds.DatasetError as exc:
        raise HTTPException(422, detail={"message": str(exc), "report": _clean(exc.report)}) from exc
    return _clean(meta)


@router.get("/datasets")
def list_datasets(
    sessionId: str = "default",
    kind: str | None = Query(None, description="sites | reference"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The session's datasets, newest first: ``{items, total}``."""
    try:
        rows = ds.list_datasets(sessionId, kind)
    except ds.DatasetError as exc:
        raise _bad(400, exc) from exc
    return {"items": rows[offset: offset + limit], "total": len(rows)}


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, sessionId: str = "default") -> dict[str, Any]:
    """One dataset's meta: sites (with mean CF), step, window and the validation report."""
    meta, _ = _dataset(sessionId, dataset_id, kind=None)
    return _clean(meta)


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, sessionId: str = "default") -> dict[str, Any]:
    """Delete a dataset (series + meta)."""
    try:
        return {"deleted": ds.delete_dataset(sessionId, dataset_id)}
    except ds.DatasetError as exc:
        raise _bad(400, exc) from exc


# ── reference series ──────────────────────────────────────────────────────────


class ReferenceSpec(BaseModel):
    """A series the sites are correlated with."""

    type: str = Field(..., description="load (the model's total load) | price (a run's system price) | dataset (uploaded reference)")
    run: str | None = Field(None, description="Run name for type 'price'.")
    datasetId: str | None = Field(None, description="Reference dataset id for type 'dataset'.")
    modelUtcOffsetHours: float = Field(0.0, description="Model / run snapshot labels are UTC + this (local time).")
    align: str = Field("exact", description="exact: same timestamps | calendar: match month-day-hour across years.")


def _numeric_sum(rows: list[dict[str, Any]], index_col: str, skip: tuple[str, ...] = ()) -> pd.Series:
    labels = [r.get(index_col) for r in rows]
    vals = []
    for r in rows:
        total = 0.0
        for k, v in r.items():
            if k == index_col or k in skip or v in (None, ""):
                continue
            try:
                total += float(v)
            except (TypeError, ValueError):
                continue
        vals.append(total)
    return pd.Series(vals, index=pd.to_datetime([str(x).replace("T", " ") for x in labels], errors="coerce"), dtype=float)


def _load_reference(session_id: str, spec: ReferenceSpec, dataset_index: pd.DatetimeIndex) -> tuple[pd.Series, str]:
    """The reference as a UTC-indexed series plus a label."""
    if spec.type == "dataset":
        if not spec.datasetId:
            raise HTTPException(422, "reference.datasetId is required for type 'dataset'.")
        meta, frame = _dataset(session_id, spec.datasetId, kind="reference")
        ref = frame.iloc[:, 0]
        label = f"{meta.get('name')} ({meta.get('unit')})"
        offset = 0.0
    elif spec.type == "load":
        model = model_store.load_full_model(session_id)
        rows = (model or {}).get("loads-p_set") or []
        if not rows:
            raise HTTPException(422, "The working model has no loads-p_set series; upload a load as a reference dataset instead.")
        ref = _numeric_sum(rows, "snapshot")
        label, offset = "Model load (MW)", spec.modelUtcOffsetHours
    elif spec.type == "price":
        if not spec.run:
            raise HTTPException(422, "reference.run is required for type 'price'.")
        from ...pypsa.results.derived_series import derive_series

        window = run_store.run_series_window(spec.run, "buses-marginal_price", max_points=10_000_000)
        if window is None:
            raise HTTPException(404, f"Run {spec.run!r} has no buses-marginal_price series.")
        derived = derive_series(window["columns"], window["rows"], window["indexCol"], metric="system_price", carriers={})
        ref = pd.Series(derived["series"][0]["values"],
                        index=pd.to_datetime([str(x).replace("T", " ") for x in derived["labels"]], errors="coerce"), dtype=float)
        label, offset = f"System price of run {spec.run}", spec.modelUtcOffsetHours
    else:
        raise HTTPException(422, "reference.type must be load, price or dataset.")
    ref = ref[ref.index.notna()]
    ref = ref.groupby(level=0).mean().sort_index()
    if offset:
        ref.index = ref.index - pd.Timedelta(hours=float(offset))
    if spec.align == "calendar":
        keys = {(t.month, t.day, t.hour): t for t in dataset_index[::-1]}
        mapped = [keys.get((t.month, t.day, t.hour)) for t in ref.index]
        ref = ref[[m is not None for m in mapped]]
        ref.index = pd.DatetimeIndex([m for m in mapped if m is not None])
        ref = ref.groupby(level=0).mean().sort_index()
    elif spec.align != "exact":
        raise HTTPException(422, "reference.align must be exact or calendar.")
    return ref, label


# ── correlation ───────────────────────────────────────────────────────────────


class CorrelationRequest(ScreenBase):
    reference: ReferenceSpec | None = None


@router.post("/correlation")
def correlation(req: CorrelationRequest) -> dict[str, Any]:
    """Site-by-site (or region-by-region) correlation on the chosen basis, correlation-vs-distance pairs and optional reference correlation."""
    meta, series = _load(req)
    frame = _select(meta, series, req.sites)
    if frame.shape[1] < 2:
        raise HTTPException(422, "Select at least two sites.")
    data = _pipeline(frame, req)
    try:
        matrix = corr.correlation_matrix(data, req.method)
    except ValueError as exc:
        raise _bad(422, exc) from exc
    by_name = {s["name"]: s for s in meta["sites"]}
    names = list(matrix.columns)
    located = [n for n in names if by_name[n].get("lat") is not None and by_name[n].get("lon") is not None]
    pairs = corr.correlation_vs_distance(
        matrix.loc[located, located], [by_name[n]["lat"] for n in located], [by_name[n]["lon"] for n in located]
    )
    warnings: list[str] = []
    if len(data) < 8:
        warnings.append(f"Only {len(data)} observations on this basis; correlations are unreliable.")
    out: dict[str, Any] = {
        "datasetId": req.datasetId, "level": req.level, "basis": req.basis, "method": req.method, "anomaly": req.anomaly,
        "nObs": len(data), "sites": names, "matrix": matrix.to_numpy().tolist(),
        "distance": pairs.to_dict("records"), "reference": None, "warnings": warnings,
    }
    if req.reference is not None:
        ref, label = _load_reference(req.sessionId, req.reference, series.index)
        ref_frame = _pipeline(ref.to_frame("reference"), req)
        rc = corr.reference_correlation(data, ref_frame["reference"], req.method)
        overlap = len(data.index.intersection(ref_frame.index))
        if overlap < 3:
            warnings.append(
                f"The reference overlaps the dataset in only {overlap} observation(s) on this basis; "
                "choose align 'calendar' if it covers a different year."
            )
        out["reference"] = {"label": label, "nOverlap": overlap, "correlations": {k: v for k, v in rc.items()}}
    return _clean(out)


class LaggedRequest(ScreenBase):
    site: str
    others: list[str] | None = None
    maxLagHours: int = Field(48, ge=1)


@router.post("/lagged")
def lagged(req: LaggedRequest) -> dict[str, Any]:
    """Lagged cross-correlation of ``site`` against each other site, lags -N..N hours (hourly data)."""
    if req.maxLagHours > MAX_LAG_HOURS:
        raise HTTPException(422, f"maxLagHours is at most {MAX_LAG_HOURS}.")
    meta, series = _load(req)
    chosen = list(dict.fromkeys([req.site] + (req.others or [n["name"] for n in meta["sites"]])))
    frame = _hourly(meta, series, req.model_copy(update={"sites": chosen}))
    step_h = float(meta.get("stepMinutes") or 60.0) / 60.0
    grid = frame.asfreq(pd.Timedelta(hours=step_h))
    lag_steps = max(1, round(req.maxLagHours / step_h))
    result: dict[str, list[float]] = {}
    best: dict[str, dict[str, float | None]] = {}
    lags_h: list[float] = []
    for other in chosen[1:]:
        lags, r = corr.lagged_cross_correlation(grid[req.site].to_numpy(), grid[other].to_numpy(), lag_steps)
        lags_h = [float(k) * step_h for k in lags]
        result[other] = r.tolist()
        if np.isfinite(r).any():
            j = int(np.nanargmax(r))
            best[other] = {"lagHours": lags_h[j], "r": float(r[j])}
        else:
            best[other] = {"lagHours": None, "r": None}
    return _clean({"site": req.site, "lagsHours": lags_h, "series": result, "best": best, "stepHours": step_h})


class ProfilesRequest(ScreenBase):
    includeSeries: bool = True


@router.post("/profiles")
def profiles(req: ProfilesRequest) -> dict[str, Any]:
    """Diurnal (24 h), monthly (12) and seasonal mean-CF profiles per site, plus a down-sampled series."""
    meta, series = _load(req)
    hourly = _hourly(meta, series, req)
    diurnal = corr.resample_basis(hourly, "diurnal")
    monthly = hourly.groupby(hourly.index.month).mean()
    seasonal = corr.resample_basis(hourly, "seasonal", season_map=_season_map(req))
    smap = _season_map(req) or corr.DEFAULT_SEASONS
    season_labels = list(dict.fromkeys(smap.values()))
    seasonal_mean = seasonal.groupby(seasonal.index.str.split(" ").str[1]).mean()
    seasonal_mean = seasonal_mean.reindex([s for s in season_labels if s in seasonal_mean.index])
    out: dict[str, Any] = {
        "sites": list(hourly.columns),
        "diurnal": {"hours": [int(h) for h in diurnal.index], "series": {c: diurnal[c].tolist() for c in diurnal.columns}},
        "monthly": {"months": [int(m) for m in monthly.index], "series": {c: monthly[c].tolist() for c in monthly.columns}},
        "seasonal": {"labels": list(seasonal_mean.index), "series": {c: seasonal_mean[c].tolist() for c in seasonal_mean.columns}},
        "nObs": len(hourly),
    }
    if req.includeSeries:
        small = corr.downsample_mean(hourly, MAX_CHART_POINTS)
        out["timeseries"] = {"timestamps": corr.index_labels(small.index), "series": {c: small[c].tolist() for c in small.columns},
                             "downsampledFrom": len(hourly)}
    return _clean(out)


# ── portfolio ─────────────────────────────────────────────────────────────────


class MetricsRequest(ScreenBase):
    weights: dict[str, float] = Field(..., description="{site: weight}; normalised to sum 1.")
    lowThreshold: float = Field(0.05, ge=0, le=1, description="CF below which an hour is low output.")
    worstN: int = Field(100, ge=1, description="N for the worst-hours loss.")
    durationPoints: int = Field(200, ge=10, le=MAX_CHART_POINTS)


def _metrics_payload(hourly: pd.DataFrame, weights: dict[str, float], low: float, worst_n: int, n_points: int) -> dict[str, Any]:
    try:
        out = corr.portfolio_metrics(hourly, weights, low_threshold=low, worst_n=worst_n)
    except ValueError as exc:
        raise _bad(422, exc) from exc
    names = list(out["weights"])
    w = np.array([out["weights"][n] for n in names])
    out["durationCurve"] = {
        "portfolio": corr.duration_curve(corr.portfolio_series(hourly[names], w), n_points),
        "sites": {n: corr.duration_curve(hourly[n], n_points) for n in names},
    }
    return out


@router.post("/metrics")
def metrics(req: MetricsRequest) -> dict[str, Any]:
    """Complementarity metrics of a weighted portfolio (hourly series, date window honoured)."""
    meta, series = _load(req)
    sites = [s for s, w in req.weights.items() if w > 0] or list(req.weights)
    hourly = _hourly(meta, series, req.model_copy(update={"sites": sites}))
    return _clean(_metrics_payload(hourly, req.weights, req.lowThreshold, req.worstN, req.durationPoints))


class OptimiseRequest(MetricsRequest):
    weights: dict[str, float] = Field(default_factory=dict)  # type: ignore[assignment]
    objective: str = Field("min_variance", description="min_variance | max_mean")
    targetMeanCf: float | None = Field(None, description="Minimum mean CF for min_variance.")
    varianceCap: float | None = Field(None, description="Maximum variance (CF^2) for max_mean.")
    maxWeight: float = Field(1.0, gt=0, le=1)
    regionCaps: dict[str, float] | None = Field(None, description="{region: max total weight}; regions come from the site table.")
    frontierPoints: int = Field(12, ge=0, le=40)


@router.post("/optimise")
def optimise(req: OptimiseRequest) -> dict[str, Any]:
    """Long-only portfolio over the selected sites (weights >= 0, sum 1), plus its metrics and the efficient frontier."""
    meta, series = _load(req)
    hourly = _hourly(meta, series, req)
    if hourly.shape[1] < 2:
        raise HTTPException(422, "Select at least two sites to optimise.")
    regions = {s["name"]: s.get("region") or "" for s in meta["sites"]}
    try:
        res = corr.optimise_portfolio(
            hourly, objective=req.objective, target_mean=req.targetMeanCf, variance_cap=req.varianceCap,  # type: ignore[arg-type]
            max_weight=req.maxWeight, regions=regions, region_caps=req.regionCaps, frontier_points=req.frontierPoints,
        )
    except ValueError as exc:
        raise _bad(422, exc) from exc
    weights = {k: v for k, v in res["weights"].items() if v > 1e-6}
    res["metrics"] = _metrics_payload(hourly, weights, req.lowThreshold, req.worstN, req.durationPoints)
    return _clean(res)


class ClusterRequest(ScreenBase):
    k: int | None = Field(None, ge=1, description="Number of clusters (give k or threshold).")
    threshold: float | None = Field(None, ge=0, description="Cut height on 1 - r.")
    linkage: str = "average"


@router.post("/cluster")
def cluster(req: ClusterRequest) -> dict[str, Any]:
    """Hierarchical clustering of sites on 1 - correlation: dendrogram order, labels, linkage."""
    if req.k is None and req.threshold is None:
        req = req.model_copy(update={"k": 3})
    meta, series = _load(req)
    frame = _select(meta, series, req.sites)
    if frame.shape[1] < 2:
        raise HTTPException(422, "Select at least two sites.")
    data = _pipeline(frame, req)
    try:
        matrix = corr.correlation_matrix(data, req.method)
        res = corr.cluster_sites(matrix, k=req.k, threshold=req.threshold, method=req.linkage)
    except ValueError as exc:
        raise _bad(422, exc) from exc
    res.update({"basis": req.basis, "method": req.method, "nObs": len(data)})
    return _clean(res)


# ── regions ───────────────────────────────────────────────────────────────────


def _region_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: r.get(k) for k in ("name", "region", "technology", "nSites", "members", "capacityMw", "lat", "lon", "geometry", "meanCf")}
            for r in rows]


@router.post("/regions")
def regions(req: ScreenBase) -> dict[str, Any]:
    """The region series in use: for each region its members and normalised weights (aggregated from sites),
    installed capacity, centroid (weighted mean of the sites, or the uploaded centroid / polygon centroid),
    the polygon when one was uploaded, and the mean CF. ``req.sites`` narrows to named regions.
    """
    meta, series = _dataset(req.sessionId, req.datasetId, kind=None)
    if meta.get("kind") not in ("sites", "regions"):
        raise HTTPException(422, f"Dataset {req.datasetId!r} is a {meta.get('kind')} dataset; regions come from a site or region dataset.")
    _, rows, unassigned = _regions_of(meta, series, req)
    if req.sites:
        rows = [r for r in rows if r["name"] in set(req.sites)]
    warnings = [f"{len(unassigned)} site(s) have no region label and are left out: {unassigned[:8]}."] if unassigned else []
    return _clean({
        "datasetId": req.datasetId, "source": "regions" if meta.get("kind") == "regions" else "sites",
        "weighting": req.weighting if meta.get("kind") == "sites" else None, "byTechnology": req.byTechnology,
        "regions": _region_payload(rows), "unassigned": unassigned, "warnings": warnings,
    })


class StructureRequest(ScreenBase):
    regions: list[str] | None = Field(None, description="Keep only sites of these regions (labels of the site table).")


@router.post("/regions/structure")
def region_structure(req: StructureRequest) -> dict[str, Any]:
    """Does spreading across regions buy diversification? Within- vs between-region correlation, and where each site sits.

    Needs a site dataset. ``within``: the distribution of pairwise site correlations inside each region;
    ``between``: across each region pair (with ``aggregateR``, the correlation of the two aggregated
    region series); ``summary``: pooled means and the gain ``withinMean - betweenMean``;
    ``siteVsRegion``: each site against its own region (leave-one-out) and every other region, the sites
    that behave like another region listed in ``behavesLike``. Sites: at most ``MAX_STRUCTURE_SITES``.
    """
    meta, series = _dataset(req.sessionId, req.datasetId, kind="sites")
    rows = [s for s in meta["sites"] if (not req.sites or s["name"] in set(req.sites)) and (not req.regions or s.get("region") in set(req.regions))]
    if len(rows) > MAX_STRUCTURE_SITES:
        raise HTTPException(422, f"{len(rows)} sites selected; at most {MAX_STRUCTURE_SITES} per request - narrow by region.")
    unknown = [n for n in (req.sites or []) if n not in series.columns]
    if unknown:
        raise HTTPException(422, f"Unknown site(s): {unknown[:8]}.")
    if not rows:
        raise HTTPException(422, "No site matches the selection.")
    sub = series[[s["name"] for s in rows]]
    try:
        rframe, rinfo, unassigned = corr.aggregate_regions(
            sub, rows, weighting=req.weighting, weights=req.siteWeights, by_technology=req.byTechnology, technology=req.technology)
    except ValueError as exc:
        raise _bad(422, exc) from exc
    group_of = {m["site"]: r["name"] for r in rinfo for m in r["members"]}
    weight_of = {m["site"]: m["weight"] for r in rinfo for m in r["members"]}
    if len(rinfo) < 2:
        raise HTTPException(422, "Need at least two regions to compare; check the region labels of the site table.")
    sdata = _pipeline(sub[list(group_of)], req)
    try:
        matrix = corr.correlation_matrix(sdata, req.method)
        rmatrix = corr.correlation_matrix(_pipeline(rframe, req), req.method)
        out = corr.within_between_correlation(matrix, group_of)
        sv = corr.site_region_correlation(sdata, group_of, weight_of, req.method)
    except ValueError as exc:
        raise _bad(422, exc) from exc
    for b in out["between"]:
        b["aggregateR"] = rmatrix.loc[b["a"], b["b"]]
    warnings = [f"{len(unassigned)} site(s) have no region label and are left out: {unassigned[:8]}."] if unassigned else []
    if req.anomaly and req.anomalyStandardise:
        warnings.append("Standardised anomalies are not linear in the sites, so the own-region (leave-one-out) correlation is approximate.")
    if len(sdata) < 8:
        warnings.append(f"Only {len(sdata)} observations on this basis; correlations are unreliable.")
    return _clean({
        "datasetId": req.datasetId, "level": "region", "basis": req.basis, "method": req.method, "anomaly": req.anomaly,
        "nObs": len(sdata), "nSites": len(group_of), "groups": [r["name"] for r in rinfo], **out, "siteVsRegion": sv,
        "warnings": warnings,
    })


# ── promote ───────────────────────────────────────────────────────────────────


class PromoteRequest(BaseModel):
    sessionId: str = "default"
    datasetId: str
    sites: list[str]
    utcOffset: int = Field(0, description="Hours from UTC to the model's clock.")
    pNomMw: dict[str, float] | None = None
    extendable: bool = False
    capitalCost: dict[str, float] = Field(default_factory=dict, description="OVERNIGHT currency/MW per technology (extendable only), written as overnight_cost.")
    discountRate: float | None = Field(None, description="Written as discount_rate on extendable sites (PyPSA annuitises overnight_cost with it). Required when extendable.")
    marginalCost: float = 0.0
    busOverrides: dict[str, str] | None = None
    buses: list[dict[str, Any]] | None = Field(None, description="Override of the model's buses (name, x, y); default the session's.")
    targetSnapshots: list[str] | None = Field(None, description="Override of the model's snapshot labels; default the session's.")
    apply: bool = Field(False, description="Merge into the session model (MCP / API); the GUI merges the returned fragment itself.")
    force: bool = Field(False, description="Apply even when the alignment report is not ok.")
    includeFragment: bool = Field(True, description="Return the fragment (large: sites x snapshots).")


@router.post("/promote")
def promote(req: PromoteRequest) -> dict[str, Any]:
    """Preview (default) or apply: selected sites become generators with ``p_max_pu`` aligned to the model's snapshots.

    The fragment goes through the single merge path (``fragment_merge.merge_fragment``): rows are
    appended with name dedupe, snapshots unioned, ``generators-p_max_pu`` widened.
    """
    meta, series = _dataset(req.sessionId, req.datasetId)
    model = model_store.load_full_model(req.sessionId, static_only=True) or {}
    snaps = req.targetSnapshots
    if snaps is None:
        snaps = [str(r.get("snapshot")) for r in model.get("snapshots", []) if r.get("snapshot")]
    buses = req.buses if req.buses is not None else model.get("buses", [])
    existing = {str(g.get("name")) for g in model.get("generators", [])}
    try:
        fragment, report = build_promotion(
            series, meta["sites"], req.sites, step_minutes=meta.get("stepMinutes"), target_snapshots=snaps, buses=buses,
            existing_generators=existing, utc_offset=req.utcOffset, p_nom_mw=req.pNomMw, extendable=req.extendable,
            capital_cost=req.capitalCost, marginal_cost=req.marginalCost, bus_overrides=req.busOverrides, dataset_id=req.datasetId,
            discount_rate=req.discountRate,
        )
    except ValueError as exc:
        raise _bad(422, exc) from exc
    frag_json = fragment.to_json()
    out: dict[str, Any] = {
        "applied": False,
        "report": report,
        "counts": {name: len(rows) for name, rows in fragment.sheets.items()},
        "generators": [g["name"] for g in fragment.sheets["generators"]],
    }
    if req.apply:
        if not report["ok"] and not req.force:
            raise HTTPException(409, detail={"message": "Profiles do not align with the model's snapshots; pass force to apply anyway.", "report": _clean(report)})
        base = model_store.load_full_model(req.sessionId) or {}
        merged = fragment_merge.merge_fragment(base, frag_json)
        out["meta"] = model_store.resave_model(req.sessionId, merged)
        out["applied"] = True
    if req.includeFragment:
        out["fragment"] = frag_json
    return _clean(out)
