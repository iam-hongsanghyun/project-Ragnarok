"""SQLite-backed session store — per-project ``project.db`` (one file per session).

Same public API + JSON shapes as :mod:`session_store` (the endpoint contract is
unchanged), but the model lives in one SQLite file so the backend can query what
the client asks for instead of loading whole sheets:

* `get_sheet_page` → ``LIMIT ? OFFSET ?`` (no whole-sheet load)
* `get_series_window` → window rows via ``LIMIT/OFFSET`` then downsample
* `patch_sheet` → in-place edits
* `distinct_values` → ``SELECT DISTINCT json_extract(...)`` for dropdowns
  (Forge, and a plugin's on-demand filter hook)

Layout (format version 2; ``docs/project-file.md`` is the specification):

* ``_project(k, v)``  project facts, one JSON value per key (``format_version``,
  ``filename``, ``scenarioName``, ``savedAt``, snapshot summary, notices).
* ``_sheets``         the catalog: one row per sheet — name, its table, its
  ``section`` (``pypsa`` / ``ragnarok`` / ``other``), ``kind`` (static/series),
  row count and columns, in workbook order.
* ``pypsa_<i>`` / ``config_<i>`` / ``other_<i>``  one table per sheet, one row
  per sheet row as JSON (``__row INTEGER PRIMARY KEY, d TEXT``) — series too
  (one row per snapshot), which sidesteps SQLite's 2000-column limit and
  asset-name quoting.
* ``_app_state(key, value)``  every app setting, verbatim (:mod:`app_state`).

A version-1 file (one ``_kv`` table + ``sheet_<i>`` tables) is upgraded in
place on first read (:func:`_upgrade_layout`). Shared helpers (id/sheet guards,
sheet classification, snapshot parsing, op application, config defaults) are
reused from :mod:`session_store` so the two stores stay in lock-step.

Selected via ``RAGNAROK_STORE=sqlite`` (see :func:`backend.app.model_store.active`).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from . import app_state as app_state_mod
from . import session_store as ss
from . import timeseries

logger = logging.getLogger("pypsa_gui.sqlite_store")

_SAFE_COL = re.compile(r"^[A-Za-z0-9_]+$")

#: ``_project`` key holding the cost-basis migration report of a session (see :mod:`...pypsa.network.cost_basis`).
MIGRATION_KV_KEY = "cost_basis_migration"

#: Version of the ``project.db`` layout written by this module.
FORMAT_VERSION = 2

#: Meta fields stored one per ``_project`` row (``sheets`` comes from ``_sheets``).
_META_KEYS = (
    "sessionId", "filename", "scenarioName", "savedAt", "snapshotCount",
    "snapshotStart", "snapshotEnd", "scenarioYear", "componentCounts",
)

#: Table-name prefix of each section.
_PREFIX = {"pypsa": "pypsa", "ragnarok": "config", "other": "other"}

_LAYOUT_SQL = (
    "CREATE TABLE IF NOT EXISTS _project (k TEXT PRIMARY KEY, v TEXT NOT NULL)",
    (
        "CREATE TABLE IF NOT EXISTS _sheets (position INTEGER NOT NULL, name TEXT PRIMARY KEY, tbl TEXT NOT NULL UNIQUE,"
        " section TEXT NOT NULL, kind TEXT NOT NULL, row_count INTEGER NOT NULL, columns TEXT NOT NULL)"
    ),
    "CREATE TABLE IF NOT EXISTS _app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)
_migration_locks: dict[str, threading.RLock] = {}
_migration_locks_guard = threading.Lock()


def _migration_lock(session_id: str) -> threading.RLock:
    with _migration_locks_guard:
        return _migration_locks.setdefault(session_id, threading.RLock())


def _db_path(session_id: str) -> Path:
    return ss.SESSION_DIR / session_id / "project.db"


@contextmanager
def _connect(session_id: str, path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open the session db for one operation and ALWAYS close it.

    ``with sqlite3.connect(...)`` only manages the transaction — it leaves the
    connection (and its file handle) open, which is invisible on POSIX but
    breaks Windows: open db files there cannot be deleted or replaced, so
    ``clear``/``save_model`` raise PermissionError. This wrapper preserves the
    commit-on-success / rollback-on-error semantics and closes the handle.
    """
    path = path or _db_path(session_id)
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


def section_of(name: str) -> str:
    """``pypsa`` (a PyPSA component, ``<component>-<attr>`` series or ``-pw`` table, snapshots, network),
    ``ragnarok`` (a ``RAGNAROK_*`` app or module sheet) or ``other``."""
    if name.startswith("RAGNAROK_"):
        return "ragnarok"
    from ..pypsa import pypsa_schema as ps

    base = name.split("-", 1)[0]
    if name in ("snapshots", "network") or base in ps.component_sheets() or base in ps.non_component_sheets():
        return "pypsa"
    return "other"


def _create_layout(conn: sqlite3.Connection) -> None:
    for sql in _LAYOUT_SQL:
        conn.execute(sql)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _kv_get(conn: sqlite3.Connection, key: str) -> Any | None:
    """One ``_project`` value (``None`` when absent or the db has no layout yet)."""
    try:
        cur = conn.execute("SELECT v FROM _project WHERE k = ?", (key,))
    except sqlite3.OperationalError:
        return None
    row = cur.fetchone()
    return json.loads(row[0]) if row else None


def _kv_set(conn: sqlite3.Connection, key: str, value: Any) -> None:
    """Write one ``_project`` value."""
    conn.execute(
        "INSERT INTO _project(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (key, json.dumps(value, ensure_ascii=False, default=ss.json_default)),
    )


def _tables(conn: sqlite3.Connection) -> dict[str, str]:
    """Sheet name -> table name, from the ``_sheets`` catalog."""
    try:
        return {str(n): str(t) for n, t in conn.execute("SELECT name, tbl FROM _sheets")}
    except sqlite3.OperationalError:
        return {}


def _load_meta(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """The public meta dict (``_project`` facts + the ``_sheets`` catalog), ``None`` without a project."""
    try:
        facts = {str(k): json.loads(v) for k, v in conn.execute("SELECT k, v FROM _project")}
        sheets = conn.execute(
            "SELECT name, kind, row_count, columns FROM _sheets ORDER BY position"
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    if "savedAt" not in facts and not sheets:
        return None
    meta: dict[str, Any] = {key: facts.get(key) for key in _META_KEYS}
    meta["sheets"] = [
        {"name": n, "kind": k, "rowCount": int(c), "columns": json.loads(cols)} for n, k, c, cols in sheets
    ]
    return meta


def _alloc_table(name: str, tables: dict[str, str]) -> str:
    """A free table name in the sheet's section (``pypsa_<i>`` / ``config_<i>`` / ``other_<i>``)."""
    prefix = _PREFIX[section_of(name)]
    used = set(tables.values())
    n = 0
    while f"{prefix}_{n}" in used:
        n += 1
    return f"{prefix}_{n}"


def _save_meta(conn: sqlite3.Connection, meta: dict[str, Any], tables: dict[str, str]) -> None:
    """Write the meta facts into ``_project`` and rewrite the ``_sheets`` catalog from ``meta['sheets']``."""
    _create_layout(conn)
    _kv_set(conn, "format_version", FORMAT_VERSION)
    for key in _META_KEYS:
        if key in meta:
            _kv_set(conn, key, meta[key])
    conn.execute("DELETE FROM _sheets")
    position = 0
    for entry in meta.get("sheets", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name"))
        tbl = tables.get(name)
        if tbl is None:
            continue
        conn.execute(
            "INSERT INTO _sheets(position, name, tbl, section, kind, row_count, columns) VALUES(?,?,?,?,?,?,?)",
            (position, name, tbl, section_of(name), str(entry.get("kind") or "static"),
             int(entry.get("rowCount") or 0), json.dumps(entry.get("columns") or [], ensure_ascii=False)),
        )
        position += 1


def _upgrade_layout(conn: sqlite3.Connection) -> bool:
    """Upgrade a version-1 file (``_kv`` + ``sheet_<i>``) to the current layout in place. Returns whether it did.

    Each sheet's table is renamed into its section (``pypsa_<i>`` / ``config_<i>`` / ``other_<i>``); an EMPTY
    sheet that is neither PyPSA nor Ragnarok (a stray ``meta``) and tables no sheet points at are dropped; the
    ``_kv`` facts move to ``_project``; the retired ``controls`` value (run controls now live in the app state)
    is dropped with ``_kv``.
    """
    if not _has_table(conn, "_kv") or _has_table(conn, "_sheets"):
        return False

    def kv(key: str) -> Any | None:
        row = conn.execute("SELECT v FROM _kv WHERE k = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    meta = kv("meta") or {}
    old_tables: dict[str, str] = kv("tables") or {}
    _create_layout(conn)
    new_tables: dict[str, str] = {}
    kept: list[dict[str, Any]] = []
    for entry in meta.get("sheets", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name"))
        old = old_tables.get(name)
        if old is None or not _has_table(conn, old):
            continue
        if section_of(name) == "other" and int(entry.get("rowCount") or 0) == 0:
            continue  # stray empty non-model sheet
        tbl = _alloc_table(name, new_tables)
        conn.execute(f'ALTER TABLE "{old}" RENAME TO {tbl}')
        new_tables[name] = tbl
        kept.append(entry)
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'sheet\\_%' ESCAPE '\\'").fetchall():
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')
    meta["sheets"] = kept
    _save_meta(conn, meta, new_tables)
    for key, value in conn.execute("SELECT k, v FROM _kv WHERE k NOT IN ('meta', 'tables', 'controls')").fetchall():
        conn.execute("INSERT OR REPLACE INTO _project(k, v) VALUES(?, ?)", (key, value))
    conn.execute("DROP TABLE _kv")
    return True


def upgrade_file(db_path: Path) -> bool:
    """Upgrade one ``project.db`` (a session, a bundled example) to the current layout. Returns whether it changed."""
    if not db_path.exists():
        return False
    conn = sqlite3.connect(str(db_path))
    try:
        changed = _upgrade_layout(conn)
        conn.commit()
        if changed:
            conn.execute("VACUUM")
        return changed
    finally:
        conn.close()


def read_kv(db_path: Path, key: str) -> Any | None:
    """Read one ``_project`` value from an arbitrary ``project.db`` (e.g. a bundled example) — keeps example
    metadata inside the SQLite file, not a sidecar. A version-1 file is read from its ``_kv`` table."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    try:
        if _has_table(conn, "_project"):
            return _kv_get(conn, key)
        if _has_table(conn, "_kv"):
            row = conn.execute("SELECT v FROM _kv WHERE k = ?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
        return None
    finally:
        conn.close()


def write_kv(db_path: Path, key: str, value: Any) -> None:
    """Write one ``_project`` value into an arbitrary ``project.db`` (authoring helper)."""
    conn = sqlite3.connect(str(db_path))
    try:
        _upgrade_layout(conn)
        _create_layout(conn)
        _kv_set(conn, key, value)
        conn.commit()
    finally:
        conn.close()


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
    model, report = _ingest_cost_basis(model, legacy_origin=True)
    _build_db(
        session_id,
        model,
        filename=str(legacy_meta.get("filename", "")),
        scenario_name=str(legacy_meta.get("scenarioName", "")),
        migration_report=report,
    )
    # DB is committed and reads will now hit it — drop the legacy artifacts.
    for path in _legacy_artifacts(session_id):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)
    logger.info("Migrated legacy session %s → sqlite project.db (%d sheets)", session_id, len(model))


def _ensure_layout(session_id: str) -> None:
    """Upgrade a version-1 session db to the current layout, once (cheap when already current)."""
    with _migration_lock(session_id):
        try:
            with _connect(session_id) as conn:
                if _upgrade_layout(conn):
                    logger.info("Session %s: project.db reorganised to layout v%d", session_id, FORMAT_VERSION)
        except Exception:
            logger.exception("Failed to upgrade the project.db layout of %s", session_id)


def _raw_meta(session_id: str) -> dict[str, Any] | None:
    """Meta dict as stored (sheet entries are the public {name,kind,rowCount,columns})."""
    if not ss._is_safe_id(session_id):
        return None
    _ensure_migrated(session_id)
    if not _db_path(session_id).exists():
        return None
    _ensure_layout(session_id)
    _ensure_cost_basis(session_id)
    try:
        with _connect(session_id) as conn:
            return _load_meta(conn)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read sqlite meta for %s", session_id)
        return None


# ── save / ingest ─────────────────────────────────────────────────────────────

def save_model(
    session_id: str,
    model: dict[str, list[dict[str, Any]]],
    *,
    filename: str = "",
    scenario_name: str = "",
    legacy_origin: bool = False,
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Persist a full model into the session's project.db, replacing any current one.

    A model carrying no ``ragnarok_schema_version`` is stamped as current - it was written by
    something that follows PyPSA's cost semantics (an importer, a plugin, an agent). Only a
    caller that knows it holds an OLD Ragnarok workbook (``legacy_origin=True``: the browser
    opening a file, a project import) gets the one-off cost-basis migration, whose report is
    stored with the session and returned in the meta as ``costBasisMigration``.
    """
    if not ss._is_safe_id(session_id):
        raise ValueError(f"Unsafe session id: {session_id!r}")
    model, report = _ingest_cost_basis(model, legacy_origin=legacy_origin, discount_rate=discount_rate)
    # Build the replacement beside the live db and swap it in with an atomic
    # os.replace. Clearing first (as this used to) destroyed the session whenever
    # the rebuild then failed — an unserialisable cell, a full disk — leaving the
    # user with nothing. A failed build now leaves the existing session untouched.
    final = _db_path(session_id)
    # A model without its own app state (a plain PyPSA workbook, an importer, an agent) keeps the
    # session's: the project's settings are not lost because its model was replaced.
    if app_state_mod.SHEET not in model:
        previous = get_app_state(session_id)
        if previous:
            model = {**model, app_state_mod.SHEET: app_state_mod.to_rows(previous)}
    building = final.with_name(final.name + ".building")
    _discard_db_files(building)
    try:
        meta = _build_db(
            session_id, model, filename=filename, scenario_name=scenario_name, db_path=building,
            migration_report=report,
        )
    except BaseException:
        _discard_db_files(building)
        raise
    for sidecar in (final.with_name(final.name + "-wal"), final.with_name(final.name + "-shm")):
        sidecar.unlink(missing_ok=True)
    os.replace(building, final)
    _discard_db_files(building)  # stray -wal/-shm of the temp name, if any
    for path in _legacy_artifacts(session_id):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    return meta


def _discard_db_files(db_path: Path) -> None:
    """Remove a sqlite file and its WAL/SHM sidecars (no error when absent)."""
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)


def _build_db(
    session_id: str,
    model: dict[str, list[dict[str, Any]]],
    *,
    filename: str = "",
    scenario_name: str = "",
    db_path: Path | None = None,
    migration_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a fresh ``project.db`` (or ``db_path``) and populate it. Assumes no db exists there yet.

    Split out of :func:`save_model` so :func:`_ensure_migrated` can build the db
    from legacy files *without* :func:`clear` wiping those files mid-migration.
    """
    model, state = app_state_mod.split_from_model(model)
    with _connect(session_id, db_path) as conn:
        # IF NOT EXISTS: a concurrent request can recreate the db file with its own
        # layout between a clear and this rebuild — a bare CREATE would then 500.
        _create_layout(conn)
        sheets_meta: list[dict[str, Any]] = []
        tables: dict[str, str] = {}
        for name, rows in model.items():
            if not isinstance(rows, list):
                continue
            tbl = _alloc_table(name, tables)
            # DROP-then-CREATE: two near-simultaneous builds of one session (a
            # double-fired importer "send") are last-writer-wins instead of the
            # second failing on an existing table.
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
            conn.execute(f"CREATE TABLE {tbl} (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT)")
            conn.executemany(
                f"INSERT INTO {tbl}(d) VALUES(?)",
                [(json.dumps(row, ensure_ascii=False, default=ss.json_default),) for row in rows if isinstance(row, dict)],
            )
            columns = ss.columns_of_rows(rows)
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
        _save_meta(conn, meta, tables)
        if migration_report is not None:
            _kv_set(conn, MIGRATION_KV_KEY, {**migration_report, "acknowledged": False})
        if state is not None:
            _write_app_state(conn, state)
        conn.commit()
    if migration_report is not None:
        meta = {**meta, "costBasisMigration": migration_report}
    logger.info("Session %s (sqlite): stored %d sheets, %d snapshots", session_id, len(sheets_meta), len(labels))
    return meta


# ── cost-basis schema (PyPSA semantics) ───────────────────────────────────────────

def _ingest_cost_basis(
    model: dict[str, list[dict[str, Any]]],
    *,
    legacy_origin: bool,
    discount_rate: float | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any] | None]:
    """Stamp (or, for an old Ragnarok workbook, migrate) ``model``; returns ``(model, report | None)``.

    ``report`` is the migration report dict when something was converted or flagged, else ``None``.
    """
    from ..pypsa.network import cost_basis as cb

    version = cb.schema_version(model)
    if version is not None and version >= cb.CURRENT_SCHEMA_VERSION:
        return model, None
    # The workbook's OWN rate (its scenario preset / RAGNAROK_Settings sheet) wins over the app's current Settings value.
    file_rate, _source = cb.resolve_discount_rate(model, None) if legacy_origin else (None, "")
    out, report = cb.migrate_cost_basis(
        model, discount_rate=file_rate if file_rate is not None else discount_rate, pypsa_native=not legacy_origin
    )
    if not report.noteworthy:
        return out, None  # stamped; nothing worth a notice
    return out, report.as_dict()


def _read_static_sheets(conn: sqlite3.Connection, meta: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    tables = _tables(conn)
    model: dict[str, list[dict[str, Any]]] = {}
    for entry in meta.get("sheets", []):
        if not isinstance(entry, dict) or entry.get("kind") == "series":
            continue
        tbl = tables.get(str(entry.get("name")))
        if tbl is None:
            continue
        model[str(entry["name"])] = [
            json.loads(r[0]) for r in conn.execute(f"SELECT d FROM {tbl} ORDER BY __row").fetchall()
        ]
    return model


def _write_static_sheet(
    conn: sqlite3.Connection, meta: dict[str, Any], tables: dict[str, str], name: str, rows: list[dict[str, Any]]
) -> None:
    tbl = tables.get(name)
    if tbl is None:
        tbl = _alloc_table(name, tables)
        tables[name] = tbl
    conn.execute(f"CREATE TABLE IF NOT EXISTS {tbl} (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT)")
    conn.execute(f"DELETE FROM {tbl}")
    conn.executemany(
        f"INSERT INTO {tbl}(d) VALUES(?)",
        [(json.dumps(row, ensure_ascii=False, default=ss.json_default),) for row in rows if isinstance(row, dict)],
    )
    columns = ss.columns_of_rows(rows)
    entry = next((s for s in meta.get("sheets", []) if isinstance(s, dict) and s.get("name") == name), None)
    if entry is None:
        meta.setdefault("sheets", []).append({"name": name, "kind": "static", "rowCount": len(rows), "columns": columns})
    else:
        entry["rowCount"] = len(rows)
        entry["columns"] = columns


def _read_one_sheet(conn: sqlite3.Connection, meta: dict[str, Any], name: str) -> dict[str, list[dict[str, Any]]]:
    """``{name: rows}`` of one static sheet (empty when absent)."""
    tables = _tables(conn)
    tbl = tables.get(name)
    if tbl is None:
        return {}
    return {name: [json.loads(r[0]) for r in conn.execute(f"SELECT d FROM {tbl} ORDER BY __row").fetchall()]}


def _ensure_cost_basis(session_id: str) -> None:
    """Migrate a session db written before schema 2 (a bundled example, an old project.db), once.

    Cheap when the db carries ``RAGNAROK_Schema``. Otherwise the static sheets are migrated in
    place, the report is stored in ``_kv`` (shown to the user once; see :func:`get_cost_basis_migration`)
    and one journal entry (with an undo snapshot) records it.
    """
    from ..pypsa.network import cost_basis as cb

    db = _db_path(session_id)
    if not db.exists():
        return
    with _migration_lock(session_id):
        try:
            with _connect(session_id) as conn:
                meta = _load_meta(conn)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(meta, dict):
            return
        if any(isinstance(s, dict) and s.get("name") == cb.SCHEMA_SHEET for s in meta.get("sheets", [])):
            with _connect(session_id) as conn:
                current = cb.schema_version(_read_one_sheet(conn, meta, cb.SCHEMA_SHEET))
            if current is not None and current >= cb.CURRENT_SCHEMA_VERSION:
                return
        from . import journal

        with journal.migration_scope(session_id, "migrate the model to the current schema (PyPSA cost basis, annual budgets)") as scope:
            with _connect(session_id) as conn:
                meta = _load_meta(conn) or meta
                tables = _tables(conn)
                static = _read_static_sheets(conn, meta)
                migrated, report = cb.migrate_cost_basis(static, pypsa_native=False)
                before = {k: v for k, v in static.items()}
                for name, rows in migrated.items():
                    if name == cb.SCHEMA_SHEET or before.get(name) != rows:
                        _write_static_sheet(conn, meta, tables, name, rows)
                _save_meta(conn, meta, tables)
                if report.noteworthy:
                    _kv_set(conn, MIGRATION_KV_KEY, {**report.as_dict(), "acknowledged": False})
                conn.commit()
            scope["report"] = report.as_dict()
            scope["changed"] = report.noteworthy
        logger.info(
            "Session %s: schema migration (%d cost row(s), %d budget(s), %d flagged)",
            session_id, len(report.changed_rows), len(report.budgets), len(report.review),
        )


def get_cost_basis_migration(session_id: str, *, include_acknowledged: bool = False) -> dict[str, Any] | None:
    """The session's cost-basis migration report, ``None`` when there is none or it was acknowledged."""
    if not ss._is_safe_id(session_id) or not _db_path(session_id).exists():
        return None
    _ensure_cost_basis(session_id)
    with _connect(session_id) as conn:
        value = _kv_get(conn, MIGRATION_KV_KEY)
    if not isinstance(value, dict):
        return None
    if value.get("acknowledged") and not include_acknowledged:
        return None
    return value


def acknowledge_cost_basis_migration(session_id: str) -> bool:
    """Mark the migration notice as seen. Returns whether there was one to acknowledge."""
    if not ss._is_safe_id(session_id) or not _db_path(session_id).exists():
        return False
    with _connect(session_id) as conn:
        value = _kv_get(conn, MIGRATION_KV_KEY)
        if not isinstance(value, dict):
            return False
        _kv_set(conn, MIGRATION_KV_KEY, {**value, "acknowledged": True})
    return True


def merge_static_model(session_id: str, model: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """Overwrite the session's STATIC sheets from ``model``; leave series untouched.

    A ``RAGNAROK_AppState`` sheet in ``model`` replaces the project's app state instead of becoming a sheet.
    """
    if not ss._is_safe_id(session_id):
        return None
    meta = _raw_meta(session_id)
    if meta is None:
        return None
    model, state = app_state_mod.split_from_model(model)
    if state is not None:
        set_app_state(session_id, state)
    with _connect(session_id) as conn:
        tables = _tables(conn)
        existing = {s["name"]: s for s in meta.get("sheets", []) if isinstance(s, dict)}
        for name, rows in model.items():
            if not isinstance(rows, list) or ss.is_series_sheet(name):
                continue
            tbl = tables.get(name)
            if tbl is None:
                tbl = _alloc_table(name, tables)
                tables[name] = tbl
            # IF NOT EXISTS + unconditional DELETE: race-safe for new and existing
            # sheets alike (same concurrent-write class as _build_db / _kv above).
            conn.execute(f"CREATE TABLE IF NOT EXISTS {tbl} (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT)")
            conn.execute(f"DELETE FROM {tbl}")
            conn.executemany(
                f"INSERT INTO {tbl}(d) VALUES(?)",
                [(json.dumps(row, ensure_ascii=False, default=ss.json_default),) for row in rows if isinstance(row, dict)],
            )
            columns = ss.columns_of_rows(rows)
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
        _save_meta(conn, meta, tables)
        conn.commit()
    return meta


def merge_series_sheets(session_id: str, model: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """Write (replace) whole SERIES sheets of ``model`` into the session; static sheets and other series are untouched.

    The path for a sheet that reaches the server as a fragment (a backend plugin's ``contribute``): :func:`merge_static_model`
    leaves series alone, so without this a contributed temporal sheet would be dropped. The sheet is stored with
    ``kind: "series"`` so windowed reads, retargeting and the thin client treat it as temporal. Returns the meta, or ``None``
    when there is no session.
    """
    if not ss._is_safe_id(session_id):
        return None
    meta = _raw_meta(session_id)
    if meta is None:
        return None
    with _connect(session_id) as conn:
        tables = _tables(conn)
        for name, rows in model.items():
            if not isinstance(rows, list) or not ss.is_series_sheet(name) or not ss._is_safe_sheet(name):
                continue
            _write_static_sheet(conn, meta, tables, name, rows)
            for entry in meta["sheets"]:
                if isinstance(entry, dict) and entry.get("name") == name:
                    entry["kind"] = "series"
        _save_meta(conn, meta, tables)
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
        tbl = _tables(conn).get(sheet)
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
        tbl = _tables(conn).get(sheet)
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
        tables = _tables(conn)
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


# ── app state (every app setting, verbatim; see app_state.py) ─────────────────

def _write_app_state(conn: sqlite3.Connection, state: dict[str, str]) -> None:
    _create_layout(conn)
    conn.execute("DELETE FROM _app_state")
    conn.executemany(
        "INSERT INTO _app_state(key, value) VALUES(?, ?)",
        [(str(k), str(v)) for k, v in sorted(state.items())],
    )


def get_app_state(session_id: str) -> dict[str, str] | None:
    """The session project's app state ``{key: value}``; ``None`` without a project, ``{}`` when it holds none."""
    if not ss._is_safe_id(session_id) or _raw_meta(session_id) is None:
        return None
    with _connect(session_id) as conn:
        try:
            return {str(k): str(v) for k, v in conn.execute("SELECT key, value FROM _app_state ORDER BY key")}
        except sqlite3.OperationalError:
            return {}


def set_app_state(session_id: str, state: dict[str, str], *, replace: bool = True) -> dict[str, str] | None:
    """Store the app state (``replace``: the whole set; else merge these keys in). ``None`` without a project.

    A ``None`` value under ``replace=False`` removes that key.
    """
    if not ss._is_safe_id(session_id) or _raw_meta(session_id) is None:
        return None
    current = {} if replace else (get_app_state(session_id) or {})
    for key, value in state.items():
        if value is None:
            current.pop(str(key), None)
        else:
            current[str(key)] = str(value)
    with _connect(session_id) as conn:
        _write_app_state(conn, current)
        conn.commit()
    return current


# ── write-path ────────────────────────────────────────────────────────────────

def patch_sheet(session_id: str, sheet: str, ops: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not ss._is_safe_id(session_id) or not ss._is_safe_sheet(sheet):
        return None
    meta = _raw_meta(session_id)
    if meta is None:
        return None
    entry = _sheet_entry(meta, sheet)
    with _connect(session_id) as conn:
        tables = _tables(conn)
        tbl = tables.get(sheet)
        if entry is None or tbl is None:
            # Create the sheet on first write — importing a NEW series/static
            # sheet (e.g. generators-p_max_pu into a session that lacks it) must
            # not silently no-op.
            tbl = _alloc_table(sheet, tables)
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
            conn.execute(f"CREATE TABLE {tbl} (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT)")
            tables[sheet] = tbl
            entry = {
                "name": sheet,
                "kind": "series" if ss.is_series_sheet(sheet) else "static",
                "rowCount": 0, "columns": [],
            }
            meta.setdefault("sheets", []).append(entry)
            rows: list[dict[str, Any]] = []
        else:
            rows = [json.loads(r[0]) for r in conn.execute(f"SELECT d FROM {tbl} ORDER BY __row").fetchall()]
        rows = ss._apply_ops(rows, ops)
        # Rewrite the sheet's rows (correct for set/addRow/deleteRows alike).
        conn.execute(f"DELETE FROM {tbl}")
        conn.executemany(
            f"INSERT INTO {tbl}(d) VALUES(?)",
            [(json.dumps(row, ensure_ascii=False, default=ss.json_default),) for row in rows],
        )
        columns = list(rows[0].keys()) if rows else list(entry.get("columns", []))
        entry["rowCount"] = len(rows)
        entry["columns"] = columns
        if sheet == "snapshots":
            meta["snapshotCount"] = len(rows)
        _save_meta(conn, meta, tables)
        conn.commit()
    return {"name": sheet, "kind": entry.get("kind"), "total": len(rows), "columns": columns}


def transform_series(
    session_id: str, sheet: str, op: str, params: dict[str, Any]
) -> dict[str, Any] | None:
    """Apply a bulk transform (scale/shift/interpolate/…) to a series sheet (T1).

    Reads the full sheet, transforms the value columns via
    :func:`timeseries.transform_rows`, and rewrites it in one transaction — the
    same read→rewrite shape as :func:`patch_sheet`. Returns ``None`` for a
    missing/static sheet.
    """
    if not ss._is_safe_id(session_id) or not ss._is_safe_sheet(sheet):
        return None
    if op not in timeseries.VALID_TRANSFORMS:
        raise ValueError(f"unknown transform op {op!r}")
    meta = _raw_meta(session_id)
    if meta is None:
        return None
    entry = _sheet_entry(meta, sheet)
    if entry is None or entry.get("kind") != "series":
        return None
    with _connect(session_id) as conn:
        tbl = _tables(conn).get(sheet)
        if tbl is None:
            return None
        rows = [json.loads(r[0]) for r in conn.execute(f"SELECT d FROM {tbl} ORDER BY __row").fetchall()]
        index_col = timeseries.series_index_col(list(rows[0].keys()) if rows else list(entry.get("columns", [])))
        rows = timeseries.transform_rows(
            rows, index_col, op,  # type: ignore[arg-type]  (validated above)
            columns=params.get("columns"),
            value=float(params.get("value", 0.0)),
            factor=float(params.get("factor", 1.0)),
            delta=float(params.get("delta", 0.0)),
            shift=int(params.get("shift", 0)),
            wrap=bool(params.get("wrap", True)),
            min_value=params.get("minValue"),
            max_value=params.get("maxValue"),
            growth_pct=float(params.get("growthPct", 0.0)),
        )
        conn.execute(f"DELETE FROM {tbl}")
        conn.executemany(
            f"INSERT INTO {tbl}(d) VALUES(?)",
            [(json.dumps(row, ensure_ascii=False, default=ss.json_default),) for row in rows],
        )
        columns = list(rows[0].keys()) if rows else list(entry.get("columns", []))
        entry["rowCount"] = len(rows)
        entry["columns"] = columns
        _save_meta(conn, meta, _tables(conn))
        conn.commit()
    return {"name": sheet, "kind": "series", "total": len(rows), "columns": columns}


# ── distinct values (generic; Forge + a plugin's on-demand filter hook) ──────────

def distinct_values(session_id: str, sheet: str, column: str) -> list[str] | None:
    """Distinct non-empty string values of ``column`` in ``sheet`` (sorted)."""
    if not ss._is_safe_id(session_id) or not ss._is_safe_sheet(sheet) or not column:
        return None
    meta = _raw_meta(session_id)
    if meta is None or _sheet_entry(meta, sheet) is None:
        return None
    with _connect(session_id) as conn:
        tbl = _tables(conn).get(sheet)
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


# ── project files (a project.db outside the session: download, upload, build) ────

def export_file(session_id: str, dest: Path) -> dict[str, Any] | None:
    """Write a consistent copy of the session's ``project.db`` to ``dest`` (SQLite backup API, safe while the
    session is in use). Returns the meta, ``None`` without a project."""
    meta = _raw_meta(session_id)
    if meta is None:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    _discard_db_files(dest)
    src = sqlite3.connect(str(_db_path(session_id)))
    out = sqlite3.connect(str(dest))
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return meta


def validate_file(path: Path) -> dict[str, Any]:
    """Upgrade ``path`` in place to the current layout and return its meta. Raises ``ValueError`` when it is not
    a Ragnarok project file (not SQLite, or no project in it)."""
    try:
        upgrade_file(path)
        conn = sqlite3.connect(str(path))
        try:
            meta = _load_meta(conn)
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"not a Ragnarok project file (SQLite): {exc}") from exc
    if meta is None or not meta.get("sheets"):
        raise ValueError("not a Ragnarok project file: it holds no _project/_sheets (see docs/project-file.md)")
    return meta


def import_file(session_id: str, src: Path) -> dict[str, Any]:
    """Make the project file ``src`` the session's project (validated and upgraded first). Returns the meta."""
    if not ss._is_safe_id(session_id):
        raise ValueError(f"Unsafe session id: {session_id!r}")
    final = _db_path(session_id)
    final.parent.mkdir(parents=True, exist_ok=True)
    staged = final.with_name(final.name + ".incoming")
    _discard_db_files(staged)
    shutil.copyfile(src, staged)
    try:
        validate_file(staged)
    except BaseException:
        _discard_db_files(staged)
        raise
    for sidecar in (final.with_name(final.name + "-wal"), final.with_name(final.name + "-shm")):
        sidecar.unlink(missing_ok=True)
    os.replace(staged, final)
    _discard_db_files(staged)
    for path in _legacy_artifacts(session_id):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    meta = _raw_meta(session_id)
    if meta is None:
        raise ValueError("the project file could not be opened")
    return meta


def build_file(
    model: dict[str, Any],
    dest: Path,
    *,
    app_state: dict[str, str] | None = None,
    filename: str = "",
    scenario_name: str = "",
    example: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write ``model`` (``{sheet: rows}``, PyPSA units) as a project file at ``dest`` with Ragnarok's own writer.

    The model is stamped with the current cost-basis schema (its costs are taken as PyPSA semantics),
    ``app_state`` (or a ``RAGNAROK_AppState`` sheet in ``model``) becomes its settings, and ``example``
    (``{label, description, order}``) makes it listable as a bundled example. Returns the meta.
    """
    model, report = _ingest_cost_basis(dict(model), legacy_origin=False)
    if app_state is not None:
        model = {**model, app_state_mod.SHEET: app_state_mod.to_rows(app_state)}
    dest.parent.mkdir(parents=True, exist_ok=True)
    _discard_db_files(dest)
    meta = _build_db("file", model, filename=filename, scenario_name=scenario_name, db_path=dest, migration_report=report)
    conn = sqlite3.connect(str(dest))
    try:
        conn.execute("PRAGMA journal_mode=DELETE")  # one self-contained file, no -wal sidecar
        _kv_set(conn, "sessionId", "")
        if example is not None:
            _kv_set(conn, "example", example)
        conn.commit()
    finally:
        conn.close()
    meta["sessionId"] = ""
    return meta
