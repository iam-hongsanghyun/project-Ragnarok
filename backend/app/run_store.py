"""Persistent server-side store for completed optimisation runs.

Every successful solve is persisted automatically: the solve worker hands the
finished bundle to :func:`store_run`, which writes ONE SQLite file to
``backend/data/runs``:

* ``<name>.db`` — the meta link (History sidecar), the input-model SNAPSHOT
  (a run must stay reproducible after the live session is edited), and the
  result. Analytics (:func:`get_run_analytics`), model pages
  (:func:`run_model_sheet_page`) and chart windows (:func:`run_series_window`)
  are all served by SQL queries from it, so nothing is loaded whole.

The bundle JSON and the Excel workbook are DERIVED on demand — only when the
user explicitly exports (:func:`run_to_xlsx` / :func:`run_to_package`) — and
never stored. Runs saved by older versions (JSON bundle + meta sidecar +
analytics/Parquet split) migrate into their ``.db`` on first access.

Every public function is defensive — a storage failure is logged and never
propagates into the solve (a failed store must not fail an otherwise good run).
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
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

# A run name is ``{scenario}_{timestamp}`` (e.g. ``이런젠장_2026-06-07T14-30-00``).
# DENYLIST sanitisation: only filesystem-unsafe characters are replaced, so
# non-Latin scenario names (한글, 日本語, …) survive into the run name instead of
# being stripped away. The guard rejects path separators, traversal, control
# characters and anything unprintable — not non-ASCII letters.
_NAME_BAD = re.compile(r"[\\/\x00-\x1f]")
_LABEL_SANITISE = re.compile(r"[\\/:*?\"<>|\x00-\x1f\s]+")
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




# Legacy (pre-SQLite) artefact paths — only referenced by the migrate-on-read
# cleanup in `_legacy_run_paths`; new runs never create these.
def _analytics_path(name: str) -> Path:
    return RUNS_DIR / f"{name}.analytics.json"


def _series_dir(name: str) -> Path:
    return RUNS_DIR / f"{name}.series"


def _is_safe_name(name: str) -> bool:
    """Return True when ``name`` is safe to use as a filesystem stem.

    Guards every name-taking endpoint (get/delete/xlsx) against path traversal:
    rejects empty/overlong strings, ``/`` ``\\`` ``..``, leading dots/spaces and
    control characters. Non-ASCII letters (Korean scenario names etc.) are fine.
    """
    if not name or len(name) > 200 or ".." in name:
        return False
    if name.startswith((".", " ")) or name.endswith(" "):
        return False
    return not _NAME_BAD.search(name)


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


# ── Per-run SQLite storage (one <name>.db per run; zero scattered files) ──────
# A run is ONE SQLite file: the meta link, the input-model SNAPSHOT (a run must
# stay reproducible after the live session is edited), and the result. The
# analytics view and charts are served by SQL queries from it; the bundle JSON
# and Excel are DERIVED on demand (export), never stored. Legacy JSON/Parquet
# runs migrate into their .db on first access.


def _db_path(name: str) -> Path:
    return RUNS_DIR / f"{name}.db"


def _connect(name: str) -> sqlite3.Connection:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path(name)))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _kv_get(conn: Any, key: str) -> Any | None:
    try:
        row = conn.execute("SELECT v FROM _kv WHERE k = ?", (key,)).fetchone()
    except Exception:  # noqa: BLE001 — missing table on a corrupt/partial db
        return None
    return json.loads(row[0]) if row else None


def _kv_set(conn: Any, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO _kv(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (key, json.dumps(value, ensure_ascii=False, default=str)),
    )


def _insert_rows(conn: Any, table: str, rows: list[dict[str, Any]]) -> None:
    conn.execute(f"CREATE TABLE {table} (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT)")
    conn.executemany(
        f"INSERT INTO {table}(d) VALUES(?)",
        [(json.dumps(r, ensure_ascii=False, default=str),) for r in rows if isinstance(r, dict)],
    )


def _build_run_db(name: str, bundle: dict[str, Any], meta: dict[str, Any]) -> None:
    """Write the run as one ``<name>.db``: head + model tables + result tables.

    Layout: ``_kv`` holds ``meta`` (the History sidecar), ``head`` (bundle minus
    model/series), ``analytics`` (the light analytics bundle), and two name→table
    maps; ``m_<i>`` tables hold the input-model snapshot one JSON row per sheet
    row; ``o_<i>`` tables hold each output time-series one JSON row per snapshot.
    """
    result = bundle.get("result") if isinstance(bundle.get("result"), dict) else {}
    outputs = result.get("outputs") if isinstance(result.get("outputs"), dict) else {}
    series = outputs.get("series") if isinstance(outputs.get("series"), dict) else {}
    model = bundle.get("model") if isinstance(bundle.get("model"), dict) else {}

    head = {k: v for k, v in bundle.items() if k not in ("model", "result")}
    light_result = {k: v for k, v in result.items() if k != "outputs"}
    light_result["outputs"] = {
        **{k: v for k, v in outputs.items() if k != "series"},
        "seriesSheets": sorted(str(s) for s in series),
    }

    _db_path(name).unlink(missing_ok=True)
    with _connect(name) as conn:
        conn.execute("CREATE TABLE _kv (k TEXT PRIMARY KEY, v TEXT)")
        model_tables: dict[str, str] = {}
        for i, (sheet, rows) in enumerate(model.items()):
            if isinstance(rows, list):
                tbl = f"m_{i}"
                _insert_rows(conn, tbl, rows)
                model_tables[str(sheet)] = tbl
        series_tables: dict[str, str] = {}
        for i, (sheet, rows) in enumerate(series.items()):
            if isinstance(rows, list):
                tbl = f"o_{i}"
                _insert_rows(conn, tbl, rows)
                series_tables[str(sheet)] = tbl
        _kv_set(conn, "head", head)
        _kv_set(conn, "result_light", light_result)
        _kv_set(conn, "model_tables", model_tables)
        _kv_set(conn, "series_tables", series_tables)
        _kv_set(conn, "analytics", _light_analytics(bundle))
        _kv_set(conn, "meta", meta)
        conn.commit()


def _read_table(conn: Any, table: str) -> list[dict[str, Any]]:
    return [json.loads(r[0]) for r in conn.execute(f"SELECT d FROM {table} ORDER BY __row")]


def _legacy_run_paths(name: str) -> list[Path]:
    return [
        RUNS_DIR / f"{name}.json",
        RUNS_DIR / f"{name}.meta.json",
        _analytics_path(name),
        RUNS_DIR / f"{name}.xlsx",
        _series_dir(name),
    ]


def _ensure_run_migrated(name: str) -> None:
    """One-time migration of a legacy JSON/Parquet run → ``<name>.db``.

    Build-before-delete: the db is committed first, so a crash mid-migration
    leaves the legacy files intact for a retry.
    """
    if not _is_safe_name(name) or _db_path(name).exists():
        return
    legacy = RUNS_DIR / f"{name}.json"
    if not legacy.exists():
        return
    try:
        bundle = json.loads(legacy.read_text(encoding="utf-8"))
        meta_path = RUNS_DIR / f"{name}.meta.json"
        meta = (
            json.loads(meta_path.read_text(encoding="utf-8"))
            if meta_path.exists()
            else build_run_meta(name, bundle, legacy.stat().st_size)
        )
        _build_run_db(name, bundle, meta)
        import shutil

        for path in _legacy_run_paths(name):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        logger.info("Migrated legacy run %s → %s.db", name, name)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to migrate legacy run %s", name)


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

        # ONE SQLite file per run — the meta link + the input-model snapshot +
        # the result, queryable (paged sheets, windowed series, analytics) so
        # nothing is ever loaded whole. The bundle JSON and Excel are DERIVED on
        # demand (export only); no other artefact is written.
        meta = build_run_meta(name, bundle, 0)
        _build_run_db(name, bundle, meta)
        size_bytes = _db_path(name).stat().st_size
        meta["sizeBytes"] = size_bytes
        with _connect(name) as conn:
            _kv_set(conn, "meta", meta)
            conn.commit()

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
        seen: set[str] = set()
        for path in RUNS_DIR.glob("*.db"):
            try:
                with _connect(path.stem) as conn:
                    meta = _kv_get(conn, "meta")
                if isinstance(meta, dict) and meta.get("name"):
                    meta["xlsxReady"] = True  # the workbook is always derivable
                    runs.append(meta)
                    seen.add(str(meta["name"]))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping unreadable run db: %s", path.name)
        # Legacy runs not yet migrated (they upgrade to .db on first access).
        for path in RUNS_DIR.glob("*.meta.json"):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
                name = str(meta.get("name", ""))
                if name and name not in seen:
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
    """Reassemble the FULL bundle for ``name`` from its db (export/rerun path).

    This loads everything (model snapshot + all output series) — use the
    granular readers (:func:`get_run_analytics`, :func:`run_series_window`,
    :func:`run_model_sheet_page`) for anything interactive.
    ``None`` if missing/unsafe.
    """
    if not _is_safe_name(name):
        logger.warning("Rejected unsafe run name: %r", name)
        return None
    _ensure_run_migrated(name)
    if not _db_path(name).exists():
        return None
    try:
        with _connect(name) as conn:
            head = _kv_get(conn, "head") or {}
            result = _kv_get(conn, "result_light") or {}
            model_tables = _kv_get(conn, "model_tables") or {}
            series_tables = _kv_get(conn, "series_tables") or {}
            model = {sheet: _read_table(conn, tbl) for sheet, tbl in model_tables.items()}
            series = {sheet: _read_table(conn, tbl) for sheet, tbl in series_tables.items()}
        outputs = result.get("outputs") if isinstance(result.get("outputs"), dict) else {}
        outputs = {k: v for k, v in outputs.items() if k != "seriesSheets"}
        outputs["series"] = series
        result["outputs"] = outputs
        return {**head, "model": model, "result": result}
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read backend run %s", name)
        return None


def get_run_analytics(name: str) -> dict[str, Any] | None:
    """Return the lightweight analytics bundle (no input model, no output series).

    This is what "View Result" loads first — one small ``_kv`` read from the
    run's db, so it renders instantly. ``None`` if the run is missing/unsafe.
    """
    if not _is_safe_name(name):
        return None
    _ensure_run_migrated(name)
    if not _db_path(name).exists():
        return None
    try:
        with _connect(name) as conn:
            analytics = _kv_get(conn, "analytics")
        if isinstance(analytics, dict):
            return analytics
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read analytics for run %s", name)
    # Fallback: derive on the fly from the full bundle (corrupt analytics key).
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

    A SQL window read from the run's db (``LIMIT/OFFSET`` over the per-snapshot
    rows) — only the requested window is loaded, then reduced server-side.
    ``None`` if the run/sheet is absent.
    """
    if not _is_safe_name(name):
        return None
    _ensure_run_migrated(name)
    if not _db_path(name).exists():
        return None
    mp = max_points if max_points is not None else 800
    if agg not in timeseries.VALID_AGG:
        agg = "mean"

    with _connect(name) as conn:
        tbl = (_kv_get(conn, "series_tables") or {}).get(sheet)
        if tbl is None:
            return None
        total = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        start = max(0, int(start))
        end = total if end is None else min(total, int(end))
        if end < start:
            end = start
        cur = conn.execute(f"SELECT d FROM {tbl} ORDER BY __row LIMIT ? OFFSET ?", (end - start, start))
        win_rows = [json.loads(r[0]) for r in cur.fetchall()]

    all_columns = list(win_rows[0].keys()) if win_rows else []
    index_col = timeseries.series_index_col([str(c) for c in all_columns])
    if columns:
        keep = ([index_col] if index_col in all_columns else []) + [
            c for c in columns if c in all_columns and c != index_col
        ]
        win_rows = [{k: row.get(k) for k in keep} for row in win_rows]
    reduced = timeseries.downsample(pd.DataFrame(win_rows), max(1, int(mp)), agg, index_col)  # type: ignore[arg-type]
    return {
        "name": sheet,
        "indexCol": index_col,
        "total": total,
        "window": {"start": start, "end": end},
        "returned": len(reduced),
        "agg": agg,
        "columns": [str(c) for c in reduced.columns],
        "rows": timeseries.df_to_records(reduced),
    }


def run_model_sheet_page(
    name: str, sheet: str, offset: int = 0, limit: int = 200
) -> dict[str, Any] | None:
    """Return one page of a stored run's INPUT model sheet (for re-edit/import).

    A ``LIMIT/OFFSET`` page over the model-snapshot table in the run's db —
    the whole sheet is never loaded. ``None`` if missing/unsafe.
    """
    if not _is_safe_name(name):
        return None
    _ensure_run_migrated(name)
    if not _db_path(name).exists():
        return None
    offset = max(0, int(offset))
    limit = max(0, int(limit))
    with _connect(name) as conn:
        tbl = (_kv_get(conn, "model_tables") or {}).get(sheet)
        if tbl is None:
            return None
        total = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        cur = conn.execute(f"SELECT d FROM {tbl} ORDER BY __row LIMIT ? OFFSET ?", (limit, offset))
        page = [json.loads(r[0]) for r in cur.fetchall()]
    columns = list(page[0].keys()) if page and isinstance(page[0], dict) else []
    return {
        "name": sheet,
        "total": total,
        "offset": offset,
        "limit": limit,
        "columns": columns,
        "rows": page,
    }


def delete_run(name: str) -> bool:
    """Delete the run's db (and any legacy artefacts) for ``name``.

    Returns True if at least one file was removed, False otherwise (including
    an unsafe name or a non-existent run).
    """
    if not _is_safe_name(name):
        logger.warning("Rejected unsafe run name for delete: %r", name)
        return False
    removed = False
    try:
        import shutil

        for path in (_db_path(name), *_legacy_run_paths(name)):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed = True
            elif path.exists():
                path.unlink()
                removed = True
        # WAL sidecars left behind by an open connection.
        for suffix in ("-wal", "-shm"):
            side = RUNS_DIR / f"{name}.db{suffix}"
            if side.exists():
                side.unlink()
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
    checkboxes (see :func:`project_workbook.bundle_to_workbook`). ``None`` if
    the run is missing."""
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
    """Return a Ragnarok Project ``.zip`` for ``name`` — three DERIVED files.

    Everything is derived on demand from the run's db (nothing is pre-built):

    * ``<name>.json``       — the lossless bundle (model + scenario + result),
    * ``<name>.meta.json``  — the lightweight meta (History/Comparison),
    * ``<name>.xlsx``       — the human-readable workbook.

    ``None`` if the run does not exist.
    """
    if not _is_safe_name(name):
        return None
    bundle = get_run(name)
    if bundle is None:
        return None

    meta: dict[str, Any] | None = None
    try:
        with _connect(name) as conn:
            meta = _kv_get(conn, "meta")
    except Exception:  # noqa: BLE001
        pass
    if not isinstance(meta, dict):
        meta = build_run_meta(name, bundle, 0)
    meta_bytes = json.dumps(meta).encode("utf-8")
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
