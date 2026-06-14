"""SQLite-backed session store — per-project ``project.db`` (one file per session).

Same public API + JSON shapes as :mod:`session_store` (the endpoint contract is
unchanged), but the model lives in one SQLite file so the backend can query what
the client asks for instead of loading whole sheets:

* `get_sheet_page` → ``LIMIT ? OFFSET ?`` (no whole-sheet load)
* `get_series_window` → window rows via ``LIMIT/OFFSET`` then downsample
* `patch_sheet` → in-place edits
* `distinct_values` → ``SELECT DISTINCT json_extract(...)`` for dropdowns
  (Forge, and a plugin's on-demand filter hook)

Rows are stored one-per-row as JSON in ``sheet_<i>(__row INTEGER PRIMARY KEY,
d TEXT)`` — this is the "wide" row-per-snapshot shape for series too (one row per
snapshot), and sidesteps SQLite's 2000-column limit + arbitrary asset-name
quoting that literal columns would require. Shared helpers (id/sheet guards,
sheet classification, snapshot parsing, op application, config defaults) are
reused from :mod:`session_store` so the two stores stay in lock-step.

Selected via ``RAGNAROK_STORE=sqlite`` (see :func:`backend.app.model_store.active`).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from . import session_store as ss
from . import timeseries

logger = logging.getLogger("pypsa_gui.sqlite_store")

_SAFE_COL = re.compile(r"^[A-Za-z0-9_]+$")


def _db_path(session_id: str) -> Path:
    return ss.SESSION_DIR / session_id / "project.db"


@contextmanager
def _connect(session_id: str) -> Iterator[sqlite3.Connection]:
    """Open the session db for one operation and ALWAYS close it.

    ``with sqlite3.connect(...)`` only manages the transaction — it leaves the
    connection (and its file handle) open, which is invisible on POSIX but
    breaks Windows: open db files there cannot be deleted or replaced, so
    ``clear``/``save_model`` raise PermissionError. This wrapper preserves the
    commit-on-success / rollback-on-error semantics and closes the handle.
    """
    path = _db_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        # Concurrent FastAPI worker threads write this db (e.g. an importer
        # plugin storing the model while the UI persists controls). Without a
        # busy timeout a second writer fails instantly with "database is
        # locked" instead of waiting for the first to finish.
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _kv_get(conn: sqlite3.Connection, key: str) -> Any | None:
    try:
        cur = conn.execute("SELECT v FROM _kv WHERE k = ?", (key,))
    except sqlite3.OperationalError:
        return None
    row = cur.fetchone()
    return json.loads(row[0]) if row else None


def _kv_set(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO _kv(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (key, json.dumps(value, ensure_ascii=False)),
    )


def _legacy_artifacts(session_id: str) -> list[Path]:
    """The legacy JSON/Parquet artifacts for a session (meta + static/ + series/ + controls)."""
    base = ss.SESSION_DIR / session_id
    return [base / "meta.json", base / "controls.json", base / "static", base / "series"]


def _ensure_migrated(session_id: str) -> None:
    """One-time, transparent migration of a legacy JSON/Parquet session → ``project.db``.

    Triggered on first read when ``project.db`` is absent but legacy files exist
    (i.e. a session created before the SQLite flip). The full legacy model is read
    into memory, written into a fresh db, then the legacy artifacts are removed so
    the session dir holds only ``project.db`` — keeping Ragnarok free of the old
    scattered-file storage. Building the db *before* deleting anything means a
    crash mid-migration leaves the legacy files intact for a retry.
    """
    if _db_path(session_id).exists():
        return
    legacy_meta = ss.get_meta(session_id)
    if legacy_meta is None:
        return  # no legacy session to migrate
    model = ss.load_full_model(session_id)
    if not model:
        return
    _build_db(
        session_id,
        model,
        filename=str(legacy_meta.get("filename", "")),
        scenario_name=str(legacy_meta.get("scenarioName", "")),
    )
    controls = ss.get_controls(session_id)
    if controls is not None:
        save_controls(session_id, controls)
    # DB is committed and reads will now hit it — drop the legacy artifacts.
    for path in _legacy_artifacts(session_id):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)
    logger.info("Migrated legacy session %s → sqlite project.db (%d sheets)", session_id, len(model))


def _raw_meta(session_id: str) -> dict[str, Any] | None:
    """Meta dict as stored (sheet entries are the public {name,kind,rowCount,columns})."""
    if not ss._is_safe_id(session_id):
        return None
    _ensure_migrated(session_id)
    if not _db_path(session_id).exists():
        return None
    try:
        with _connect(session_id) as conn:
            return _kv_get(conn, "meta")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read sqlite meta for %s", session_id)
        return None


def _tables(session_id: str) -> dict[str, str]:
    with _connect(session_id) as conn:
        return _kv_get(conn, "tables") or {}


# ── save / ingest ─────────────────────────────────────────────────────────────

def save_model(
    session_id: str,
    model: dict[str, list[dict[str, Any]]],
    *,
    filename: str = "",
    scenario_name: str = "",
) -> dict[str, Any]:
    """Persist a full model into the session's project.db, replacing any current one."""
    if not ss._is_safe_id(session_id):
        raise ValueError(f"Unsafe session id: {session_id!r}")
    clear(session_id)
    return _build_db(session_id, model, filename=filename, scenario_name=scenario_name)


def _build_db(
    session_id: str,
    model: dict[str, list[dict[str, Any]]],
    *,
    filename: str = "",
    scenario_name: str = "",
) -> dict[str, Any]:
    """Create a fresh ``project.db`` and populate it. Assumes no db exists yet.

    Split out of :func:`save_model` so :func:`_ensure_migrated` can build the db
    from legacy files *without* :func:`clear` wiping those files mid-migration.
    """
    with _connect(session_id) as conn:
        # IF NOT EXISTS: between save_model's clear() and this rebuild, a
        # concurrent request (save_controls, fired by the UI while a run is in
        # flight) can recreate the db file with its own _kv — a bare CREATE
        # then 500s every save with "table _kv already exists".
        conn.execute("CREATE TABLE IF NOT EXISTS _kv (k TEXT PRIMARY KEY, v TEXT)")
        sheets_meta: list[dict[str, Any]] = []
        tables: dict[str, str] = {}
        for i, (name, rows) in enumerate(r for r in model.items()):
            if not isinstance(rows, list):
                continue
            tbl = f"sheet_{i}"
            # DROP-then-CREATE for the same race as _kv above: two near-simultaneous
            # save_model calls on one session (a double-fire / retry of an importer
            # "send") otherwise have the second hit a bare CREATE on an existing
            # sheet_0 — which surfaces the failing SQL ("... INTEGER PRIMARY KEY ...")
            # as an error even though the first build already stored the model.
            # Drop-then-create is last-writer-wins (both builds carry the same model).
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
            conn.execute(f"CREATE TABLE {tbl} (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT)")
            conn.executemany(
                f"INSERT INTO {tbl}(d) VALUES(?)",
                [(json.dumps(row, ensure_ascii=False),) for row in rows if isinstance(row, dict)],
            )
            columns = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
            kind = "series" if ss.is_series_sheet(name, rows) else "static"
            sheets_meta.append({"name": name, "kind": kind, "rowCount": len(rows), "columns": columns})
            tables[name] = tbl

        labels = ss._snapshot_labels(model)
        meta = {
            "sessionId": session_id,
            "filename": filename,
            "scenarioName": scenario_name,
            "savedAt": datetime.now(timezone.utc).isoformat(),
            "sheets": sheets_meta,
            "snapshotCount": len(labels),
            "snapshotStart": labels[0] if labels else None,
            "snapshotEnd": labels[-1] if labels else None,
            "scenarioYear": ss._scenario_year_from_labels(labels),
            "componentCounts": {
                s: len(model[s]) for s in ss._COMPONENT_SHEETS if isinstance(model.get(s), list)
            },
        }
        _kv_set(conn, "meta", meta)
        _kv_set(conn, "tables", tables)
        conn.commit()
    logger.info("Session %s (sqlite): stored %d sheets, %d snapshots", session_id, len(sheets_meta), len(labels))
    return meta


def merge_static_model(session_id: str, model: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """Overwrite the session's STATIC sheets from ``model``; leave series untouched."""
    if not ss._is_safe_id(session_id):
        return None
    meta = _raw_meta(session_id)
    if meta is None:
        return None
    with _connect(session_id) as conn:
        tables = _kv_get(conn, "tables") or {}
        existing = {s["name"]: s for s in meta.get("sheets", []) if isinstance(s, dict)}
        for name, rows in model.items():
            if not isinstance(rows, list) or ss.is_series_sheet(name):
                continue
            tbl = tables.get(name)
            if tbl is None:
                tbl = f"sheet_{len(tables)}"
                tables[name] = tbl
            # IF NOT EXISTS + unconditional DELETE: race-safe for new and existing
            # sheets alike (same concurrent-write class as _build_db / _kv above).
            conn.execute(f"CREATE TABLE IF NOT EXISTS {tbl} (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT)")
            conn.execute(f"DELETE FROM {tbl}")
            conn.executemany(
                f"INSERT INTO {tbl}(d) VALUES(?)",
                [(json.dumps(row, ensure_ascii=False),) for row in rows if isinstance(row, dict)],
            )
            columns = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
            entry = existing.get(name)
            if entry is None:
                meta.setdefault("sheets", []).append(
                    {"name": name, "kind": "static", "rowCount": len(rows), "columns": columns}
                )
            else:
                entry["rowCount"] = len(rows)
                entry["columns"] = columns
        if isinstance(model.get("snapshots"), list):
            meta["snapshotCount"] = len(model["snapshots"])
        _kv_set(conn, "meta", meta)
        _kv_set(conn, "tables", tables)
        conn.commit()
    return meta


# ── reads ───────────────────────────────────────────────────────────────────────

def get_meta(session_id: str) -> dict[str, Any] | None:
    return _raw_meta(session_id)


def _sheet_entry(meta: dict[str, Any], sheet: str) -> dict[str, Any] | None:
    for entry in meta.get("sheets", []):
        if isinstance(entry, dict) and entry.get("name") == sheet:
            return entry
    return None


def get_sheet_page(
    session_id: str, sheet: str, offset: int = 0, limit: int | None = None
) -> dict[str, Any] | None:
    if not ss._is_safe_id(session_id) or not ss._is_safe_sheet(sheet):
        return None
    meta = _raw_meta(session_id)
    if meta is None:
        return None
    entry = _sheet_entry(meta, sheet)
    if entry is None:
        return None
    offset = max(0, int(offset))
    limit = ss.default_page_size() if limit is None else max(0, int(limit))
    with _connect(session_id) as conn:
        tbl = (_kv_get(conn, "tables") or {}).get(sheet)
        if tbl is None:
            return None
        total = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        cur = conn.execute(f"SELECT d FROM {tbl} ORDER BY __row LIMIT ? OFFSET ?", (limit, offset))
        rows = [json.loads(r[0]) for r in cur.fetchall()]
    columns = list(rows[0].keys()) if rows else list(entry.get("columns", []))
    return {
        "name": sheet, "kind": entry.get("kind"), "total": total,
        "offset": offset, "limit": limit, "columns": columns, "rows": rows,
    }


def get_series_window(
    session_id: str, sheet: str, *, start: int = 0, end: int | None = None,
    columns: list[str] | None = None, max_points: int | None = None,
    agg: timeseries.Agg = "mean",
) -> dict[str, Any] | None:
    if not ss._is_safe_id(session_id) or not ss._is_safe_sheet(sheet):
        return None
    meta = _raw_meta(session_id)
    if meta is None:
        return None
    entry = _sheet_entry(meta, sheet)
    if entry is None or entry.get("kind") != "series":
        return None
    max_points = ss.default_max_points() if max_points is None else max_points
    all_columns = [str(c) for c in entry.get("columns", [])]
    index_col = timeseries.series_index_col(all_columns)
    with _connect(session_id) as conn:
        tbl = (_kv_get(conn, "tables") or {}).get(sheet)
        if tbl is None:
            return None
        total = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        start = max(0, int(start))
        end = total if end is None else min(total, int(end))
        if end < start:
            end = start
        cur = conn.execute(
            f"SELECT d FROM {tbl} ORDER BY __row LIMIT ? OFFSET ?", (end - start, start)
        )
        win_rows = [json.loads(r[0]) for r in cur.fetchall()]
    # Column pushdown (project the window rows to index + requested assets).
    if columns:
        wanted = [c for c in columns if c in all_columns and c != index_col]
        keep = ([index_col] if index_col in all_columns else []) + wanted
        win_rows = [{k: row.get(k) for k in keep} for row in win_rows]
    df = pd.DataFrame(win_rows)
    reduced = timeseries.downsample(df, max(1, int(max_points)), agg if agg in timeseries.VALID_AGG else "mean", index_col)
    return {
        "name": sheet, "indexCol": index_col, "total": total,
        "window": {"start": start, "end": end}, "returned": len(reduced),
        "agg": agg if agg in timeseries.VALID_AGG else "mean",
        "columns": [str(c) for c in reduced.columns], "rows": timeseries.df_to_records(reduced),
    }


def load_full_model(
    session_id: str, *, static_only: bool = False
) -> dict[str, list[dict[str, Any]]] | None:
    meta = _raw_meta(session_id)
    if meta is None:
        return None
    model: dict[str, list[dict[str, Any]]] = {}
    with _connect(session_id) as conn:
        tables = _kv_get(conn, "tables") or {}
        for entry in meta.get("sheets", []):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name"))
            if entry.get("kind") == "series" and static_only:
                continue
            tbl = tables.get(name)
            if tbl is None:
                continue
            cur = conn.execute(f"SELECT d FROM {tbl} ORDER BY __row")
            model[name] = [json.loads(r[0]) for r in cur.fetchall()]
    return model


# ── controls ────────────────────────────────────────────────────────────────────

def save_controls(session_id: str, controls: dict[str, Any]) -> None:
    if not ss._is_safe_id(session_id):
        return
    with _connect(session_id) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS _kv (k TEXT PRIMARY KEY, v TEXT)")
        _kv_set(conn, "controls", controls)
        conn.commit()


def get_controls(session_id: str) -> dict[str, Any] | None:
    if not ss._is_safe_id(session_id):
        return None
    _ensure_migrated(session_id)
    if not _db_path(session_id).exists():
        return None
    with _connect(session_id) as conn:
        return _kv_get(conn, "controls")


# ── write-path ────────────────────────────────────────────────────────────────

def patch_sheet(session_id: str, sheet: str, ops: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not ss._is_safe_id(session_id) or not ss._is_safe_sheet(sheet):
        return None
    meta = _raw_meta(session_id)
    if meta is None:
        return None
    entry = _sheet_entry(meta, sheet)
    if entry is None:
        return None
    with _connect(session_id) as conn:
        tbl = (_kv_get(conn, "tables") or {}).get(sheet)
        if tbl is None:
            return None
        cur = conn.execute(f"SELECT d FROM {tbl} ORDER BY __row")
        rows = [json.loads(r[0]) for r in cur.fetchall()]
        rows = ss._apply_ops(rows, ops)
        # Rewrite the sheet's rows (correct for set/addRow/deleteRows alike).
        conn.execute(f"DELETE FROM {tbl}")
        conn.executemany(
            f"INSERT INTO {tbl}(d) VALUES(?)",
            [(json.dumps(row, ensure_ascii=False),) for row in rows],
        )
        columns = list(rows[0].keys()) if rows else list(entry.get("columns", []))
        entry["rowCount"] = len(rows)
        entry["columns"] = columns
        if sheet == "snapshots":
            meta["snapshotCount"] = len(rows)
        _kv_set(conn, "meta", meta)
        conn.commit()
    return {"name": sheet, "kind": entry.get("kind"), "total": len(rows), "columns": columns}


# ── distinct values (generic; Forge + a plugin's on-demand filter hook) ──────────

def distinct_values(session_id: str, sheet: str, column: str) -> list[str] | None:
    """Distinct non-empty string values of ``column`` in ``sheet`` (sorted)."""
    if not ss._is_safe_id(session_id) or not ss._is_safe_sheet(sheet) or not column:
        return None
    meta = _raw_meta(session_id)
    if meta is None or _sheet_entry(meta, sheet) is None:
        return None
    with _connect(session_id) as conn:
        tbl = (_kv_get(conn, "tables") or {}).get(sheet)
        if tbl is None:
            return None
        if _SAFE_COL.match(column):
            # True SQL DISTINCT (no whole-sheet load) for simple column names.
            cur = conn.execute(
                f"SELECT DISTINCT json_extract(d, '$.{column}') FROM {tbl}"
            )
            vals = [r[0] for r in cur.fetchall()]
        else:
            # Odd column name → scan rows and extract in Python (still bounded).
            cur = conn.execute(f"SELECT d FROM {tbl}")
            vals = [json.loads(r[0]).get(column) for r in cur.fetchall()]
    seen: set[str] = set()
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            seen.add(s)
    return sorted(seen)


# ── lifecycle ─────────────────────────────────────────────────────────────────

def clear(session_id: str) -> bool:
    if not ss._is_safe_id(session_id):
        return False
    base = ss.SESSION_DIR / session_id
    existed = base.exists()
    shutil.rmtree(base, ignore_errors=True)
    if existed:
        logger.info("Session %s (sqlite) cleared", session_id)
    return existed


def has_model(session_id: str) -> bool:
    return get_meta(session_id) is not None


# Re-exported for parity with session_store.
is_series_sheet = ss.is_series_sheet
