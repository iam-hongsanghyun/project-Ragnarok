"""Server-side working-model store — the backend's single source of truth.

The frontend used to hold the entire workbook (every component row plus all
8760-snapshot time-series) in browser memory. This module moves that authority
to the backend so the frontend can stay a thin terminal: it imports a model
once, then fetches only what is on screen — a *page* of static rows
(:func:`get_sheet_page`) or a *windowed, downsampled* slice of a time-series
(:func:`get_series_window`).

Storage layout (per session, under ``backend/data/session/<session_id>/``)::

    meta.json                 # sheet inventory, snapshot range, component counts
    static/<sheet>.json       # component sheets (buses, generators, …) + snapshots
    series/<sheet>.parquet    # time-series sheets (generators-p_max_pu, loads-p_set, …)
    controls.json             # run controls bound to the model (no rolling-horizon)

**Why two formats.** Time-series sheets are wide and tall (assets × 8760), so
they live in **Parquet** — columnar, compressed, and readable one column-subset
and one row-window at a time. Static sheets are small and edited cell-by-cell,
so they live in **JSON** (trivial partial slice and rewrite, no Arrow type
coercion on heterogeneous/None-heavy columns). JSON-for-control, Parquet-for-
series is the format split the project agreed on; Arrow-over-the-wire is a
later step.

A "session" is keyed by ``session_id`` (default ``"default"``). Today the app is
single-user on one machine, so one session is enough — but every function takes
``session_id`` so a remote, multi-session deployment is a configuration change,
not a rewrite.

Every public reader is defensive: a missing/cleared session returns ``None``
rather than raising, so a thin client can probe state cheaply.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from . import timeseries
from .config import load_system_defaults

logger = logging.getLogger("pypsa_gui.session_store")

# ``__file__`` is ``backend/app/session_store.py`` → ``parents[2]`` is the repo
# root, mirroring run_store.RUNS_DIR.
_REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_DIR = _REPO_ROOT / "backend" / "data" / "session"

# session_id is used as a directory name — guard against path traversal exactly
# like run_store guards run names.
_ID_GUARD = re.compile(r"^[A-Za-z0-9._\-]+$")
_SHEET_GUARD = re.compile(r"^[A-Za-z0-9._\- ]+$")

# Known PyPSA component sheets we report counts for in meta.
_COMPONENT_SHEETS = (
    "buses",
    "generators",
    "loads",
    "lines",
    "links",
    "transformers",
    "stores",
    "storage_units",
    "carriers",
)


# ── config ────────────────────────────────────────────────────────────────────

def _session_cfg() -> dict[str, Any]:
    cfg = load_system_defaults().get("session", {})
    return cfg if isinstance(cfg, dict) else {}


def default_max_points() -> int:
    return int(_session_cfg().get("max_chart_points_default", 800))


def default_window_hours() -> int:
    return int(_session_cfg().get("chart_window_hours_default", 168))


def default_page_size() -> int:
    return int(_session_cfg().get("sheet_page_default", 200))


# ── path helpers ────────────────────────────────────────────────────────────────

def _is_safe_id(session_id: str) -> bool:
    return bool(session_id) and ".." not in session_id and bool(_ID_GUARD.match(session_id))


def _is_safe_sheet(name: str) -> bool:
    return bool(name) and "/" not in name and "\\" not in name and ".." not in name and bool(
        _SHEET_GUARD.match(name)
    )


def _session_dir(session_id: str) -> Path:
    return SESSION_DIR / session_id


def _meta_path(session_id: str) -> Path:
    return _session_dir(session_id) / "meta.json"


def _static_path(session_id: str, sheet: str) -> Path:
    return _session_dir(session_id) / "static" / f"{sheet}.json"


def _series_path(session_id: str, sheet: str) -> Path:
    return _session_dir(session_id) / "series" / f"{sheet}.parquet"


def _controls_path(session_id: str) -> Path:
    return _session_dir(session_id) / "controls.json"


# ── sheet classification ────────────────────────────────────────────────────────

def is_series_sheet(name: str, rows: list[dict[str, Any]] | None = None) -> bool:
    """Return True when ``name`` is a PyPSA time-series sheet.

    The PyPSA convention is ``<component>-<attribute>`` (e.g. ``generators-p_max_pu``,
    ``loads-p_set``). The ``snapshots`` sheet is the time *axis*, not a series, and
    is stored as static. ``rows`` is accepted for symmetry but the name is decisive.
    """
    if name == "snapshots":
        return False
    return "-" in name


# ── save / ingest ────────────────────────────────────────────────────────────────

def _snapshot_labels(model: dict[str, list[dict[str, Any]]]) -> list[str]:
    snaps = model.get("snapshots")
    if not isinstance(snaps, list):
        return []
    out: list[str] = []
    for row in snaps:
        if isinstance(row, dict):
            out.append(str(row.get("snapshot") or row.get("name") or row.get("datetime") or ""))
    return out


def _scenario_year_from_labels(labels: list[str]) -> int | None:
    if not labels:
        return None
    head = labels[0]
    return int(head[:4]) if len(head) >= 4 and head[:4].isdigit() else None


def save_model(
    session_id: str,
    model: dict[str, list[dict[str, Any]]],
    *,
    filename: str = "",
    scenario_name: str = "",
) -> dict[str, Any]:
    """Persist a full model into the session, replacing any current one.

    Static sheets are written as JSON, time-series sheets as Parquet. Returns the
    lightweight ``meta`` (the only thing the frontend keeps in memory).
    """
    if not _is_safe_id(session_id):
        raise ValueError(f"Unsafe session id: {session_id!r}")

    # Replace wholesale: a new import clears the previous working model.
    clear(session_id)
    base = _session_dir(session_id)
    (base / "static").mkdir(parents=True, exist_ok=True)
    (base / "series").mkdir(parents=True, exist_ok=True)

    sheets_meta: list[dict[str, Any]] = []
    for name, rows in model.items():
        if not isinstance(rows, list):
            continue
        columns = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
        if is_series_sheet(name, rows):
            df = pd.DataFrame(rows)
            df.to_parquet(_series_path(session_id, name), index=False)
            kind = "series"
        else:
            _static_path(session_id, name).write_text(
                json.dumps(rows, ensure_ascii=False), encoding="utf-8"
            )
            kind = "static"
        sheets_meta.append(
            {"name": name, "kind": kind, "rowCount": len(rows), "columns": columns}
        )

    labels = _snapshot_labels(model)
    component_counts = {
        sheet: len(model[sheet])
        for sheet in _COMPONENT_SHEETS
        if isinstance(model.get(sheet), list)
    }
    meta = {
        "sessionId": session_id,
        "filename": filename,
        "scenarioName": scenario_name,
        "savedAt": datetime.now(timezone.utc).isoformat(),
        "sheets": sheets_meta,
        "snapshotCount": len(labels),
        "snapshotStart": labels[0] if labels else None,
        "snapshotEnd": labels[-1] if labels else None,
        "scenarioYear": _scenario_year_from_labels(labels),
        "componentCounts": component_counts,
    }
    _meta_path(session_id).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    logger.info(
        "Session %s: stored %d sheets, %d snapshots", session_id, len(sheets_meta), len(labels)
    )
    return meta


# ── read: meta ─────────────────────────────────────────────────────────────────

def get_meta(session_id: str) -> dict[str, Any] | None:
    """Return the session meta, or ``None`` if no model is loaded."""
    if not _is_safe_id(session_id):
        return None
    path = _meta_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read session meta for %s", session_id)
        return None


def _sheet_meta(session_id: str, sheet: str) -> dict[str, Any] | None:
    meta = get_meta(session_id)
    if not meta:
        return None
    for entry in meta.get("sheets", []):
        if isinstance(entry, dict) and entry.get("name") == sheet:
            return entry
    return None


# ── read: static page ──────────────────────────────────────────────────────────

def get_sheet_page(
    session_id: str, sheet: str, offset: int = 0, limit: int | None = None
) -> dict[str, Any] | None:
    """Return one page of a sheet's rows.

    Works for both static and series sheets (series are paged by snapshot row).
    Returns ``{name, kind, total, offset, limit, columns, rows}`` or ``None`` if
    the sheet is absent.
    """
    if not _is_safe_id(session_id) or not _is_safe_sheet(sheet):
        return None
    entry = _sheet_meta(session_id, sheet)
    if entry is None:
        return None
    offset = max(0, int(offset))
    limit = default_page_size() if limit is None else max(0, int(limit))

    kind = entry.get("kind")
    if kind == "series":
        path = _series_path(session_id, sheet)
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        total = len(df)
        page = df.iloc[offset : offset + limit]
        columns = [str(c) for c in df.columns]
        rows = timeseries.df_to_records(page)
    else:
        path = _static_path(session_id, sheet)
        if not path.exists():
            return None
        all_rows = json.loads(path.read_text(encoding="utf-8"))
        total = len(all_rows)
        rows = all_rows[offset : offset + limit]
        columns = list(rows[0].keys()) if rows else list(entry.get("columns", []))

    return {
        "name": sheet,
        "kind": kind,
        "total": total,
        "offset": offset,
        "limit": limit,
        "columns": columns,
        "rows": rows,
    }


# ── read: series window (downsampled) ────────────────────────────────────────────

def get_series_window(
    session_id: str,
    sheet: str,
    *,
    start: int = 0,
    end: int | None = None,
    columns: list[str] | None = None,
    max_points: int | None = None,
    agg: timeseries.Agg = "mean",
) -> dict[str, Any] | None:
    """Return a windowed, downsampled slice of a time-series sheet.

    The window is the row range ``[start, end)`` (rows are aligned 1:1 with
    snapshots, so these are snapshot indices). If the window has more than
    ``max_points`` rows it is reduced to ``max_points`` contiguous buckets using
    ``agg`` (see :func:`timeseries.downsample`). ``columns`` selects a subset of
    asset columns (the index column is always included).

    Returns ``{name, indexCol, total, window:{start,end}, returned, agg,
    columns, rows}`` or ``None`` if the sheet is absent / not a series.
    """
    if not _is_safe_id(session_id) or not _is_safe_sheet(sheet):
        return None
    entry = _sheet_meta(session_id, sheet)
    if entry is None or entry.get("kind") != "series":
        return None
    path = _series_path(session_id, sheet)
    if not path.exists():
        return None
    max_points = default_max_points() if max_points is None else max_points

    all_columns = [str(c) for c in entry.get("columns", [])] or _parquet_columns(path)
    index_col = timeseries.series_index_col(all_columns)

    # Column pushdown: read only the index + requested asset columns.
    read_cols: list[str] | None
    if columns:
        wanted = [c for c in columns if c in all_columns and c != index_col]
        read_cols = [index_col] + wanted if index_col in all_columns else wanted
    else:
        read_cols = None
    df = pd.read_parquet(path, columns=read_cols)

    window = timeseries.slice_and_reduce(
        df, start=start, end=end, max_points=max_points, agg=agg, index_col=index_col
    )
    return {"name": sheet, **window}


# ── read: full model (for the run/solve path) ────────────────────────────────────

def load_full_model(session_id: str) -> dict[str, list[dict[str, Any]]] | None:
    """Reconstruct the complete ``{sheet: rows}`` model from disk.

    Used by the run/queue path so a solve consumes the session model the user
    built — no giant payload travels from the browser. ``None`` if no session.
    """
    meta = get_meta(session_id)
    if meta is None:
        return None
    model: dict[str, list[dict[str, Any]]] = {}
    for entry in meta.get("sheets", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name"))
        if entry.get("kind") == "series":
            path = _series_path(session_id, name)
            if path.exists():
                model[name] = timeseries.df_to_records(pd.read_parquet(path))
        else:
            path = _static_path(session_id, name)
            if path.exists():
                model[name] = json.loads(path.read_text(encoding="utf-8"))
    return model


# ── controls (model-bound run settings; NO rolling-horizon) ───────────────────────

def save_controls(session_id: str, controls: dict[str, Any]) -> None:
    """Persist model-bound run controls (carbon, window, constraints, …).

    Rolling-horizon config is intentionally NOT persisted here — it resets on
    reload/import per the product rule. Callers must strip it before saving.
    """
    if not _is_safe_id(session_id):
        return
    _session_dir(session_id).mkdir(parents=True, exist_ok=True)
    _controls_path(session_id).write_text(
        json.dumps(controls, ensure_ascii=False), encoding="utf-8"
    )


def get_controls(session_id: str) -> dict[str, Any] | None:
    if not _is_safe_id(session_id):
        return None
    path = _controls_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read session controls for %s", session_id)
        return None


# ── write-path: edit a sheet in place ─────────────────────────────────────────────

def patch_sheet(session_id: str, sheet: str, ops: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Apply edit operations to a sheet and persist them (backend = source of truth).

    Supported ops (applied in order)::

        {"op": "set",        "row": <int>, "column": <str>, "value": <any>}
        {"op": "addRow",     "values": {<col>: <val>, ...}, "index"?: <int>}  # append if no index
        {"op": "deleteRows", "rows": [<int>, ...]}

    Works on static (JSON) and series (Parquet) sheets. Returns the updated sheet
    descriptor ``{name, kind, total, columns}`` and refreshes the session meta's
    row count, or ``None`` if the session/sheet is absent.
    """
    if not _is_safe_id(session_id) or not _is_safe_sheet(sheet):
        return None
    entry = _sheet_meta(session_id, sheet)
    if entry is None:
        return None
    kind = entry.get("kind")

    if kind == "series":
        path = _series_path(session_id, sheet)
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        rows = timeseries.df_to_records(df)
    else:
        path = _static_path(session_id, sheet)
        if not path.exists():
            return None
        rows = json.loads(path.read_text(encoding="utf-8"))

    rows = _apply_ops(rows, ops)

    if kind == "series":
        pd.DataFrame(rows).to_parquet(_series_path(session_id, sheet), index=False)
    else:
        _static_path(session_id, sheet).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    columns = list(rows[0].keys()) if rows else list(entry.get("columns", []))
    _update_sheet_meta(session_id, sheet, row_count=len(rows), columns=columns)
    return {"name": sheet, "kind": kind, "total": len(rows), "columns": columns}


def _apply_ops(rows: list[dict[str, Any]], ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply edit ops to a list of row dicts in order (pure; returns a new list)."""
    out = [dict(r) for r in rows]
    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        if kind == "set":
            i = op.get("row")
            col = op.get("column")
            if isinstance(i, int) and 0 <= i < len(out) and isinstance(col, str):
                out[i][col] = op.get("value")
        elif kind == "addRow":
            values = op.get("values") if isinstance(op.get("values"), dict) else {}
            at = op.get("index")
            if isinstance(at, int) and 0 <= at <= len(out):
                out.insert(at, dict(values))
            else:
                out.append(dict(values))
        elif kind == "deleteRows":
            drop = {i for i in (op.get("rows") or []) if isinstance(i, int)}
            out = [r for idx, r in enumerate(out) if idx not in drop]
    return out


def _update_sheet_meta(session_id: str, sheet: str, *, row_count: int, columns: list[str]) -> None:
    """Refresh a sheet's rowCount/columns in the session meta after an edit."""
    meta = get_meta(session_id)
    if not meta:
        return
    for entry in meta.get("sheets", []):
        if isinstance(entry, dict) and entry.get("name") == sheet:
            entry["rowCount"] = row_count
            entry["columns"] = columns
            break
    # Keep snapshot count in step when the snapshots sheet is edited.
    if sheet == "snapshots":
        meta["snapshotCount"] = row_count
    _meta_path(session_id).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


# ── clear ───────────────────────────────────────────────────────────────────────

def clear(session_id: str) -> bool:
    """Delete the session's working model from disk. Returns True if anything was removed."""
    if not _is_safe_id(session_id):
        return False
    base = _session_dir(session_id)
    existed = base.exists()
    shutil.rmtree(base, ignore_errors=True)
    if existed:
        logger.info("Session %s cleared", session_id)
    return existed


def has_model(session_id: str) -> bool:
    return get_meta(session_id) is not None


# ── internal ──────────────────────────────────────────────────────────────────────

def _parquet_columns(path: Path) -> list[str]:
    import pyarrow.parquet as pq

    return [str(c) for c in pq.read_schema(path).names]
