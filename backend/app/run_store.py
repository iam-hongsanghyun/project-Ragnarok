"""Persistent server-side store for completed optimisation runs.

Every successful solve is persisted automatically: the solve worker hands the
finished bundle to :func:`store_run`, which writes two files to
``backend/data/runs``:

* ``<name>.json`` — the full bundle (model + scenario + options + result).
  This is the canonical form the frontend reopens via ``GET /api/runs/{name}``.
* ``<name>.meta.json`` — a lightweight sidecar listed in the History tab so
  the browser never has to download a full-year result just to enumerate runs.

Storing server-side sidesteps the browser-tab out-of-memory failure that a
full-year (8784 h) xlsx export hits client-side: the heavy bytes stay on disk
and Excel is produced on demand by :func:`run_to_xlsx`.

Every public function is defensive — a storage failure is logged and never
propagates into the solve (a failed store must not fail an otherwise good run).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from . import timeseries

logger = logging.getLogger("pypsa_gui.run_store")

# Resolve the runs directory relative to the repository root. ``__file__`` is
# ``backend/app/run_store.py`` so ``parents[2]`` is the repo root, mirroring
# the path resolution used by the test conftest and other backend modules.
_REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = _REPO_ROOT / "backend" / "data" / "runs"

# A run name is a sanitised UTC timestamp, optionally suffixed with a label:
# ``2026-06-07T14-30-00`` or ``2026-06-07T14-30-00_my-scenario``. The guard
# rejects anything with path separators or parent-directory traversal.
_NAME_GUARD = re.compile(r"^[A-Za-z0-9._\-T:]+$")
_LABEL_SANITISE = re.compile(r"[^A-Za-z0-9._-]+")
_LABEL_MAX_LEN = 40

# Stem-only file extensions stripped before a filename becomes a run label, so a
# run is never named ``...ragnarok_case.xlsx`` (which then yields a double
# ``.xlsx.xlsx`` on download). Generic default filenames carry no information —
# they're dropped so the run name stays a clean timestamp.
_LABEL_EXTENSIONS = (".xlsx", ".xls", ".nc", ".h5", ".hdf5", ".zip")
_DEFAULT_FILENAME_STEMS = {"ragnarok_case", "ragnarok_project", "ragnarok"}


def _filename_label_stem(filename: str) -> str:
    """Filename → label stem: lowercase-extension stripped; '' for generic defaults.

    ``ragnarok_case.xlsx`` → ``''`` (a meaningless default, so no label),
    ``north-sea-2030.xlsx`` → ``north-sea-2030``.
    """
    stem = filename.strip()
    lowered = stem.lower()
    for ext in _LABEL_EXTENSIONS:
        if lowered.endswith(ext):
            stem = stem[: -len(ext)]
            break
    return "" if stem.lower() in _DEFAULT_FILENAME_STEMS else stem


_SHEET_SANITISE = re.compile(r"[^A-Za-z0-9._\-]+")


def _safe_sheet_filename(sheet: str) -> str:
    """Filesystem-safe stem for a series sheet (e.g. ``generators-p``)."""
    return _SHEET_SANITISE.sub("_", sheet).strip("_") or "sheet"


def _analytics_path(name: str) -> Path:
    return RUNS_DIR / f"{name}.analytics.json"


def _series_dir(name: str) -> Path:
    return RUNS_DIR / f"{name}.series"


def _is_safe_name(name: str) -> bool:
    """Return True when ``name`` is safe to use as a filesystem stem.

    Guards every name-taking endpoint (get/delete/xlsx) against path
    traversal: rejects empty strings, anything containing ``/`` or ``..``,
    and anything not matching the allowed character class.
    """
    if not name or "/" in name or "\\" in name or ".." in name:
        return False
    return bool(_NAME_GUARD.match(name))


def _sanitise_label(label: str) -> str:
    """Collapse a free-text label into a filesystem-safe, truncated token."""
    cleaned = _LABEL_SANITISE.sub("-", label).strip("-._")
    return cleaned[:_LABEL_MAX_LEN]


def _derive_name(model: dict[str, Any], scenario: dict[str, Any], options: dict[str, Any]) -> str:
    """Build a ``scenarioname_datetime`` filesystem-safe run name.

    The scenario name leads (from ``options['runLabel']``, the scenario label, or
    the model filename with its extension stripped), followed by a UTC timestamp
    ``<YYYY-MM-DDTHH-MM-SS>`` so reruns of the same scenario never collide and
    sort chronologically within a scenario: ``north-sea-2030_2026-06-09T14-30-00``.
    A generic default filename (``ragnarok_case.xlsx`` etc.) contributes no name,
    so such a run is just the clean timestamp.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    raw_label = (
        (options.get("runLabel") if isinstance(options, dict) else None)
        or (scenario.get("label") if isinstance(scenario, dict) else None)
        or ""
    )
    if not raw_label and isinstance(options, dict) and options.get("filename"):
        raw_label = _filename_label_stem(str(options["filename"]))
    label = _sanitise_label(str(raw_label)) if raw_label else ""
    return f"{label}_{stamp}" if label else stamp


def _label_for_bundle(scenario: dict[str, Any], options: dict[str, Any], filename: str) -> str:
    """Human-facing label for the meta sidecar (falls back to the filename)."""
    if isinstance(options, dict) and options.get("runLabel"):
        return str(options["runLabel"])
    if isinstance(scenario, dict) and scenario.get("label"):
        return str(scenario["label"])
    return _filename_label_stem(filename) or "Run"


def _total_demand_mwh(model: dict[str, Any]) -> float | None:
    """Annual energy demand (MWh) = sum of every cell in the loads-p_set sheet.

    Falls back to static ``loads.p_set`` × modelled hours when there is no load
    time-series. ``None`` when no load data is present.
    """
    lps = model.get("loads-p_set")
    if isinstance(lps, list) and lps:
        total = 0.0
        for row in lps:
            if not isinstance(row, dict):
                continue
            for key, value in row.items():
                if key in ("snapshot", "period", "name", "datetime"):
                    continue
                try:
                    total += float(value)
                except (TypeError, ValueError):
                    continue
        return total
    loads = model.get("loads")
    if isinstance(loads, list) and loads:
        peak = 0.0
        for row in loads:
            try:
                peak += float(row.get("p_set"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
        return peak if peak else None
    return None


def _scenario_year(model: dict[str, Any], snapshot_start: int) -> int | None:
    """Calendar year of the run's first snapshot (window-aware)."""
    snaps = model.get("snapshots")
    if not isinstance(snaps, list) or not snaps:
        return None
    idx = snapshot_start if isinstance(snapshot_start, int) and 0 <= snapshot_start < len(snaps) else 0
    row = snaps[idx] if isinstance(snaps[idx], dict) else {}
    raw = str(row.get("snapshot") or row.get("name") or row.get("datetime") or "")
    return int(raw[:4]) if len(raw) >= 4 and raw[:4].isdigit() else None


def _nonstandard_tags(scenario: dict[str, Any], options: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Short chips for any non-default / notable run settings."""
    tags: list[str] = []
    cp = scenario.get("carbonPrice")
    if isinstance(cp, (int, float)) and cp:
        tags.append(f"carbon {cp:g}")
    if options.get("forceLp"):
        tags.append("force-LP")
    if options.get("enableLoadShedding"):
        tags.append("load-shed")
    solver = options.get("solverType")
    if solver and solver != "auto":
        tags.append(f"solver:{solver}")
    pathway = result.get("pathway") if isinstance(result, dict) else None
    if isinstance(pathway, dict) and pathway.get("enabled"):
        tags.append("pathway")
    if isinstance(options.get("stochasticConfig"), dict) and options["stochasticConfig"].get("enabled"):
        tags.append("stochastic")
    if isinstance(options.get("securityConstrainedConfig"), dict) and options["securityConstrainedConfig"].get("enabled"):
        tags.append("N-1")
    constraints = scenario.get("constraints")
    if isinstance(constraints, list):
        enabled = sum(1 for c in constraints if isinstance(c, dict) and c.get("enabled"))
        if enabled:
            tags.append(f"{enabled} constraint{'s' if enabled != 1 else ''}")
    return tags


def build_run_meta(name: str, bundle: dict[str, Any], size_bytes: int = 0) -> dict[str, Any]:
    """Compute the lightweight meta sidecar from a run bundle.

    Shared by :func:`store_run` (persisted alongside the bundle) and the project
    export path (so an exported package's ``.meta.json`` matches a stored run's).
    Carries only the small fields History + Analytics→Comparison read — never a
    time series.
    """
    scenario = bundle.get("scenario") or {}
    options = bundle.get("options") or {}
    result = bundle.get("result") or {}
    model = bundle.get("model") or {}

    run_meta = result.get("runMeta") if isinstance(result, dict) else None
    component_counts = (run_meta.get("componentCounts", {}) if isinstance(run_meta, dict) else {}) or {}

    summary = result.get("summary") if isinstance(result, dict) else None
    summary = summary if isinstance(summary, list) else []

    carrier_mix = result.get("carrierMix") if isinstance(result, dict) else None
    carrier_mix = carrier_mix if isinstance(carrier_mix, list) else []

    pathway_src = result.get("pathway") if isinstance(result, dict) else None
    pathway_meta: dict[str, Any] | None = None
    if isinstance(pathway_src, dict):
        pathway_meta = {
            "enabled": pathway_src.get("enabled"),
            "periods": pathway_src.get("periods"),
            "selectedPeriod": pathway_src.get("selectedPeriod"),
            "summaries": pathway_src.get("summaries"),
        }

    rolling_src = result.get("rolling") if isinstance(result, dict) else None
    rolling_meta: dict[str, Any] | None = None
    if isinstance(rolling_src, dict):
        rolling_meta = {
            "enabled": rolling_src.get("enabled"),
            "horizonSnapshots": rolling_src.get("horizonSnapshots"),
            "overlapSnapshots": rolling_src.get("overlapSnapshots"),
            "windowCount": rolling_src.get("windowCount"),
        }

    scenario_label = (
        (scenario.get("label") if isinstance(scenario, dict) else None)
        or (options.get("scenarioLabel") if isinstance(options, dict) else None)
        or None
    )
    filename = str(options.get("filename") or bundle.get("filename") or "")

    return {
        "name": name,
        "savedAt": bundle.get("savedAt"),
        "label": bundle.get("label") or _label_for_bundle(scenario, options, filename),
        "filename": filename,
        "snapshotStart": options.get("snapshotStart"),
        "snapshotEnd": options.get("snapshotEnd"),
        "snapshotWeight": options.get("snapshotWeight"),
        "componentCounts": component_counts,
        "kpis": summary[:4],
        "sizeBytes": size_bytes,
        "summary": summary,
        "carrierMix": carrier_mix,
        "pathway": pathway_meta,
        "rolling": rolling_meta,
        "scenarioLabel": scenario_label,
        # History-card display fields (see HistoryView): scenario name, the
        # snapshot year, the effective resolution (hours/snapshot), rolling
        # batch count, total annual demand, and any non-standard settings.
        "scenarioYear": _scenario_year(model, options.get("snapshotStart") or 0),
        "resolutionHours": options.get("snapshotWeight"),
        "windowCount": rolling_meta.get("windowCount") if rolling_meta else None,
        "totalDemandMwh": _total_demand_mwh(model),
        "tags": _nonstandard_tags(scenario, options, result),
    }


def _is_series_sheet(name: str) -> bool:
    """A PyPSA time-series sheet is ``<component>-<attribute>``; ``snapshots`` is
    the time axis (static). Mirrors session_store.is_series_sheet."""
    return name != "snapshots" and "-" in name


def _model_static(model: Any) -> dict[str, Any]:
    """Topology-only view of a model: every static sheet, none of the heavy input
    time-series. Small enough to ship with the light analytics bundle so the
    network map renders on View without downloading the full model."""
    if not isinstance(model, dict):
        return {}
    return {name: rows for name, rows in model.items() if not _is_series_sheet(str(name))}


def _generator_energy_fallback(result: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-generator dispatched energy from the per-snapshot series (older runs).

    New runs carry ``result['generatorEnergy']`` (computed server-side at solve
    time); runs stored before that field existed are summed here from
    ``generatorDispatchSeries`` so the "Dispatch by unit" donut still has its
    small aggregate after the heavy series is stripped from the light view.
    """
    rows = result.get("generatorDispatchSeries")
    if not isinstance(rows, list) or not rows:
        return []
    totals: dict[str, float] = {}
    for row in rows:
        values = row.get("values") if isinstance(row, dict) else None
        if isinstance(values, dict):
            for key, value in values.items():
                try:
                    totals[str(key)] = totals.get(str(key), 0.0) + float(value)
                except (TypeError, ValueError):
                    continue
    weight = bundle.get("snapshotWeight") or (bundle.get("options") or {}).get("snapshotWeight") or 1.0
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        weight = 1.0
    carrier_map: dict[str, str] = {}
    gens = (bundle.get("model") or {}).get("generators")
    if isinstance(gens, list):
        for g in gens:
            if isinstance(g, dict) and g.get("name") is not None:
                carrier_map[str(g["name"])] = str(g.get("carrier", ""))
    out = [
        {"name": k, "value": v * weight, "carrier": carrier_map.get(k, "")}
        for k, v in totals.items()
        if v > 0.0
    ]
    out.sort(key=lambda row: row["value"], reverse=True)
    return out


def _light_analytics(bundle: dict[str, Any]) -> dict[str, Any]:
    """Build the lightweight analytics bundle.

    Drops the heavy input model and per-component output series, plus the heavy
    per-snapshot ``generatorDispatchSeries`` (tens of MB). Keeps topology (for the
    map), the small result aggregates, the carrier-level dispatch series, and a
    compact per-generator energy aggregate (``generatorEnergy``) for the
    "Dispatch by unit" donut. The stripped series stay in the canonical bundle
    (used by Import) and are served windowed on demand.
    """
    result = bundle.get("result")
    outputs = result.get("outputs") if isinstance(result, dict) else None
    series = outputs.get("series") if isinstance(outputs, dict) else None
    light_outputs = dict(outputs) if isinstance(outputs, dict) else {}
    light_outputs["series"] = None
    light_outputs["seriesSheets"] = sorted(series) if isinstance(series, dict) else []
    analytics = {k: v for k, v in bundle.items() if k != "model"}
    if isinstance(result, dict):
        light_result = {**result, "outputs": light_outputs}
        if not light_result.get("generatorEnergy"):
            light_result["generatorEnergy"] = _generator_energy_fallback(result, bundle)
        # The dominant payload (tens of MB) — only needed for the per-unit
        # time-series view, which fetches it windowed on demand.
        light_result["generatorDispatchSeries"] = None
        analytics["result"] = light_result
    analytics["modelStatic"] = _model_static(bundle.get("model"))
    analytics["hasModel"] = isinstance(bundle.get("model"), dict)
    return analytics


def _write_results_split(name: str, bundle: dict[str, Any]) -> None:
    """Write the granular artefacts the thin client reads instead of the bundle.

    The full ``<name>.json`` bundle stays the lossless source of truth, but
    "View Result" used to download it whole — model + every output time-series —
    which froze the tab. So we additionally write:

    * ``<name>.analytics.json`` — the bundle minus the heavy input ``model`` and
      minus the output ``result.outputs.series`` (replaced by a ``seriesSheets``
      name list). Small; the analytics view loads this first and renders at once.
    * ``<name>.series/<sheet>.parquet`` — one Parquet per output time-series
      sheet, read back windowed + downsampled via :func:`run_series_window`.
    """
    result = bundle.get("result")
    if not isinstance(result, dict):
        return
    outputs = result.get("outputs")
    series = outputs.get("series") if isinstance(outputs, dict) else None

    _analytics_path(name).write_text(json.dumps(_light_analytics(bundle)), encoding="utf-8")

    if isinstance(series, dict) and series:
        sdir = _series_dir(name)
        sdir.mkdir(parents=True, exist_ok=True)
        for sheet, rows in series.items():
            if isinstance(rows, list) and rows:
                pd.DataFrame(rows).to_parquet(
                    sdir / f"{_safe_sheet_filename(str(sheet))}.parquet", index=False
                )


def store_run(
    model: dict[str, Any],
    scenario: dict[str, Any],
    options: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any] | None:
    """Persist a finished run as a JSON bundle plus a lightweight meta sidecar.

    Args:
        model: The in-memory workbook submitted for the run (``{sheet: rows[]}``).
        scenario: The scenario blob submitted for the run.
        options: The run options dict (carries snapshot window + an optional
            ``runLabel`` / ``filename``).
        result: The solver result dict returned by ``backend.run(...)``.

    Returns:
        The meta dict that was written to disk, or ``None`` if storage failed
        (the failure is logged — it never raises into the solve).
    """
    try:
        options = options or {}
        scenario = scenario or {}
        RUNS_DIR.mkdir(parents=True, exist_ok=True)

        name = _derive_name(model, scenario, options)
        saved_at = datetime.now(timezone.utc).isoformat()
        filename = str(options.get("filename") or "")
        label = _label_for_bundle(scenario, options, filename)

        bundle = {
            "savedAt": saved_at,
            "label": label,
            "filename": filename,
            "snapshotStart": options.get("snapshotStart"),
            "snapshotEnd": options.get("snapshotEnd"),
            "snapshotWeight": options.get("snapshotWeight"),
            "model": model,
            "scenario": scenario,
            "options": options,
            "result": result,
        }

        bundle_path = RUNS_DIR / f"{name}.json"
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        size_bytes = bundle_path.stat().st_size

        meta = build_run_meta(name, bundle, size_bytes)
        (RUNS_DIR / f"{name}.meta.json").write_text(json.dumps(meta), encoding="utf-8")

        # Granular artefacts for the thin client (analytics.json + series parquet).
        # Non-fatal: the canonical bundle above already holds everything.
        try:
            _write_results_split(name, bundle)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write results split for run %s", name)

        # NO xlsx is written here. Excel is a derived export artefact, built ONLY
        # when the user explicitly downloads/exports it (GET /api/runs/{name}/xlsx
        # and /package both build on demand from this bundle). Ragnarok keeps SQL/
        # JSON as the source of truth and never auto-creates workbooks.

        logger.info("Stored run %s (%d bytes)", name, size_bytes)
        return meta
    except Exception:  # noqa: BLE001 — storage must never fail the solve
        logger.exception("Failed to store run in backend")
        return None


def list_runs() -> list[dict[str, Any]]:
    """Return every stored run's meta sidecar, newest first.

    Missing or corrupt sidecar files are skipped with a warning so one bad
    file never breaks the History listing.
    """
    runs: list[dict[str, Any]] = []
    try:
        if not RUNS_DIR.exists():
            return runs
        for path in RUNS_DIR.glob("*.meta.json"):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
                # Excel is never pre-built — it's derived on demand from the
                # canonical bundle when the user downloads/exports. So any stored
                # run can always produce a workbook; flag it ready unconditionally.
                name = str(meta.get("name", ""))
                meta["xlsxReady"] = bool(name)
                runs.append(meta)
            except Exception:  # noqa: BLE001
                logger.warning("Skipping unreadable run meta: %s", path.name)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to list backend runs")
        return runs
    runs.sort(key=lambda m: str(m.get("savedAt", "")), reverse=True)
    return runs


def get_run(name: str) -> dict[str, Any] | None:
    """Return the full bundle for ``name``, or ``None`` if missing/unsafe."""
    if not _is_safe_name(name):
        logger.warning("Rejected unsafe run name: %r", name)
        return None
    try:
        path = RUNS_DIR / f"{name}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read backend run %s", name)
        return None


def get_run_analytics(name: str) -> dict[str, Any] | None:
    """Return the lightweight analytics bundle (no input model, no output series).

    This is what "View Result" loads first — small enough to render instantly.
    Falls back to deriving it from the full bundle for runs stored before the
    results-split existed. ``None`` if the run is missing/unsafe.
    """
    if not _is_safe_name(name):
        return None
    path = _analytics_path(name)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to read analytics for run %s", name)
    # Fallback: derive on the fly from the canonical bundle (older runs).
    bundle = get_run(name)
    if bundle is None:
        return None
    return _light_analytics(bundle)


def run_series_window(
    name: str,
    sheet: str,
    *,
    start: int = 0,
    end: int | None = None,
    columns: list[str] | None = None,
    max_points: int | None = None,
    agg: str = "mean",
) -> dict[str, Any] | None:
    """Return a windowed, downsampled slice of a stored run's output series.

    Reads the per-sheet Parquet written by :func:`_write_results_split`; for
    older runs without it, falls back to the series embedded in the bundle.
    ``None`` if the run/sheet is absent.
    """
    if not _is_safe_name(name):
        return None
    mp = max_points if max_points is not None else 800

    path = _series_dir(name) / f"{_safe_sheet_filename(sheet)}.parquet"
    if path.exists():
        df = _read_series_with_columns(path, columns)
        index_col = timeseries.series_index_col([str(c) for c in df.columns])
    else:
        bundle = get_run(name)
        series = (((bundle or {}).get("result") or {}).get("outputs") or {}).get("series")
        rows = series.get(sheet) if isinstance(series, dict) else None
        if not isinstance(rows, list) or not rows:
            return None
        df = pd.DataFrame(rows)
        index_col = timeseries.series_index_col([str(c) for c in df.columns])
        if columns:
            keep = [index_col] + [c for c in columns if c in df.columns and c != index_col]
            df = df[[c for c in keep if c in df.columns]]
    window = timeseries.slice_and_reduce(
        df, start=start, end=end, max_points=mp, agg=agg, index_col=index_col
    )
    return {"name": sheet, **window}


def run_model_sheet_page(
    name: str, sheet: str, offset: int = 0, limit: int = 200
) -> dict[str, Any] | None:
    """Return one page of a stored run's INPUT model sheet (for re-edit/import).

    Reads from the canonical bundle's ``model``. ``None`` if missing/unsafe.
    """
    if not _is_safe_name(name):
        return None
    bundle = get_run(name)
    model = bundle.get("model") if isinstance(bundle, dict) else None
    rows = model.get(sheet) if isinstance(model, dict) else None
    if not isinstance(rows, list):
        return None
    offset = max(0, int(offset))
    limit = max(0, int(limit))
    page = rows[offset : offset + limit]
    columns = list(page[0].keys()) if page and isinstance(page[0], dict) else []
    return {
        "name": sheet,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "columns": columns,
        "rows": page,
    }


def _read_series_with_columns(path: Path, columns: list[str] | None) -> pd.DataFrame:
    """Read a series parquet, pushing down a column subset (index col kept)."""
    if not columns:
        return pd.read_parquet(path)
    import pyarrow.parquet as pq

    available = [str(c) for c in pq.read_schema(path).names]
    index_col = timeseries.series_index_col(available)
    wanted = [c for c in columns if c in available and c != index_col]
    read_cols = ([index_col] + wanted) if index_col in available else wanted
    return pd.read_parquet(path, columns=read_cols or None)


def delete_run(name: str) -> bool:
    """Delete the bundle, meta sidecar, analytics, series dir and xlsx for ``name``.

    Returns True if at least one file was removed, False otherwise (including
    an unsafe name or a non-existent run).
    """
    if not _is_safe_name(name):
        logger.warning("Rejected unsafe run name for delete: %r", name)
        return False
    removed = False
    try:
        for suffix in (".json", ".meta.json", ".xlsx", ".analytics.json"):
            path = RUNS_DIR / f"{name}{suffix}"
            if path.exists():
                path.unlink()
                removed = True
        sdir = _series_dir(name)
        if sdir.exists():
            import shutil

            shutil.rmtree(sdir, ignore_errors=True)
            removed = True
    except Exception:  # noqa: BLE001
        logger.exception("Failed to delete backend run %s", name)
        return removed
    return removed


def xlsx_path(name: str) -> Path | None:
    """Path to a pre-built xlsx for ``name`` if one exists (and ``name`` is safe).

    Runs no longer pre-build workbooks (Excel is export-only), but runs stored
    by older versions may still have one on disk — a FULL export can stream it.
    """
    if not _is_safe_name(name):
        return None
    path = RUNS_DIR / f"{name}.xlsx"
    return path if path.exists() else None


def run_to_xlsx(
    name: str,
    *,
    include_meta: bool = True,
    include_model: bool = True,
    include_result: bool = True,
) -> bytes | None:
    """Build the run's export workbook ON DEMAND from the canonical bundle.

    The ``include_*`` flags mirror the Export dialog's Metadata/Model/Result
    checkboxes (see :func:`project_workbook.bundle_to_workbook`). A legacy
    pre-built file is reused only for a FULL export. ``None`` if the run is
    missing."""
    if include_meta and include_model and include_result:
        pre = xlsx_path(name)
        if pre is not None:
            try:
                return pre.read_bytes()
            except Exception:  # noqa: BLE001
                logger.exception("Failed to read pre-built xlsx for %s", name)
    bundle = get_run(name)
    if bundle is None:
        return None
    try:
        from . import project_workbook

        return project_workbook.bundle_to_workbook(
            bundle,
            include_meta=include_meta,
            include_model=include_model,
            include_result=include_result,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to build xlsx for backend run %s", name)
        return None


def run_to_package(name: str) -> bytes | None:
    """Return a Ragnarok Project ``.zip`` for ``name`` — ALL THREE files.

    Bundles the three on-disk artefacts so the export is complete:

    * ``<name>.json``       — the canonical bundle (lossless source of truth),
    * ``<name>.meta.json``  — the lightweight meta sidecar (History/Comparison),
    * ``<name>.xlsx``       — the human-readable workbook.

    ``None`` if the run does not exist. The xlsx is built on demand if its
    pre-built file is somehow missing, so the package is always complete.
    """
    if not _is_safe_name(name):
        return None
    bundle = get_run(name)
    if bundle is None:
        return None

    meta_path = RUNS_DIR / f"{name}.meta.json"
    meta_bytes = meta_path.read_bytes() if meta_path.exists() else None
    xlsx_bytes = run_to_xlsx(name)

    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}.json", json.dumps(bundle))
        if meta_bytes is not None:
            zf.writestr(f"{name}.meta.json", meta_bytes)
        if xlsx_bytes is not None:
            zf.writestr(f"{name}.xlsx", xlsx_bytes)
    return buffer.getvalue()
