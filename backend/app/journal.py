"""Session mutation journal — audit trail + per-step diff + undo (Bifrost).

Every mutation of the working model — from the GUI, the MCP server, or the
embedded agent — lands here by wrapping the five mutators of the
:mod:`backend.app.model_store` facade at startup (:func:`wrap_model_store`).
All writers call the facade by attribute access, so coverage is total without
touching the ~15 call sites. Each successful mutation:

1. captures enough *before*-state to undo it,
2. appends one entry to ``backend/data/journal/<session>/journal.jsonl``
   (append-only, monotonic ``version`` — the provenance-log pattern), and
3. publishes a ``session.version`` event so the GUI repaints live.

Entries carry the actor (``user`` / ``mcp`` / ``agent``) and originating
endpoint from :mod:`backend.app.actor_context`; multiple writes by one HTTP
request share a ``requestId`` so the timeline can group them.

Undo strategies (per entry ``kind``):

* ``patch``            — exact inverse ops computed by forward-replaying the
                          batch against the before-rows (indices shift as ops
                          apply, so a naive per-op inverse would be wrong).
* ``series-transform`` — gzip snapshot of the touched sheet, restored whole
                          (display shows per-column aggregates, never 8760 cells).
* ``model-replace``    — full session snapshot (SQLite ``backup()`` /
                          legacy dir copy), restored whole.
* ``clear``            — model snapshot, as above.
* ``revert``           — written by an undo; its own undo info is the original
                          change, so redo = undo-the-revert and falls out free.

Journal storage lives OUTSIDE the session store (which ``save_model``/``clear``
delete wholesale). Best-effort like the provenance log: a journal failure logs a
warning and never blocks the edit. NaN-vs-NaN and None-vs-NaN compare as equal
(:func:`values_equal`) so parquet/JSON round-trips don't produce phantom diffs.
"""
from __future__ import annotations

import gzip
import json
import logging
import math
import os
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import actor_context, events_bus, model_store

logger = logging.getLogger("pypsa_gui.journal")

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Inline inverse-op payloads bigger than this spill to a snapshot file.
_INLINE_UNDO_LIMIT = 32_768
# Detailed cell diffs are capped (the UI shows `truncated: true` beyond).
_DIFF_ROW_CAP = 200
_SUMMARY_COL_CAP = 50

_MAX_ENTRIES = int(os.environ.get("RAGNAROK_JOURNAL_MAX_ENTRIES", "200"))
_MAX_SNAPSHOT_BYTES = int(os.environ.get("RAGNAROK_JOURNAL_MAX_BYTES", str(1_000_000_000)))

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

# Originals kept for capture reads + undo application (never re-journaled).
_orig: dict[str, Callable[..., Any]] = {}


def _lock(session_id: str) -> threading.Lock:
    with _locks_guard:
        lk = _locks.get(session_id)
        if lk is None:
            lk = _locks[session_id] = threading.Lock()
        return lk


def _dir(session_id: str) -> Path:
    root = Path(os.environ.get("RAGNAROK_JOURNAL_DIR", str(_DATA_DIR / "journal")))
    return root / session_id


def _jsonl(session_id: str) -> Path:
    return _dir(session_id) / "journal.jsonl"


def _snapshot_dir(session_id: str, entry_id: int) -> Path:
    return _dir(session_id) / "snapshots" / str(entry_id)


# ── value comparison (NaN-safe) ─────────────────────────────────────────────────

def values_equal(a: Any, b: Any) -> bool:
    """True when two cell values are the same *for diff purposes*.

    Both-NaN counts as equal (NaN != NaN would flag every unset float), and
    ``None`` is treated as NaN's JSON twin — a parquet→JSON round trip turns
    NaN into None and must not produce a phantom whole-sheet diff.
    """
    a_nan = a is None or (isinstance(a, float) and math.isnan(a))
    b_nan = b is None or (isinstance(b, float) and math.isnan(b))
    if a_nan or b_nan:
        return a_nan and b_nan
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
            and not isinstance(a, bool) and not isinstance(b, bool):
        return float(a) == float(b)
    return a == b


# ── jsonl primitives ────────────────────────────────────────────────────────────

def _read_entries(session_id: str) -> list[dict[str, Any]]:
    try:
        lines = _jsonl(session_id).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _append_entry(session_id: str, entry: dict[str, Any]) -> None:
    path = _jsonl(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _rewrite_entries(session_id: str, entries: list[dict[str, Any]]) -> None:
    path = _jsonl(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in entries),
        encoding="utf-8",
    )
    tmp.replace(path)


def current_version(session_id: str) -> int:
    """The session's monotonic model version (0 = never journaled)."""
    entries = _read_entries(session_id)
    return int(entries[-1]["version"]) if entries else 0


# ── capture helpers ─────────────────────────────────────────────────────────────

def _sheet_rows(session_id: str, sheet: str) -> list[dict[str, Any]] | None:
    page = _orig["get_sheet_page"](session_id, sheet, offset=0, limit=10_000_000)
    if page is None:
        return None
    return list(page.get("rows") or [])


def _numeric_summary(rows: list[dict[str, Any]], columns: list[str] | None) -> dict[str, dict[str, float]]:
    """Per-column sum/mean/min/max over numeric values (bounded column count)."""
    if not rows:
        return {}
    cols = columns or [c for c in rows[0].keys()]
    out: dict[str, dict[str, float]] = {}
    for col in cols[:_SUMMARY_COL_CAP]:
        vals = [
            float(r[col]) for r in rows
            if isinstance(r.get(col), (int, float)) and not isinstance(r.get(col), bool)
            and not (isinstance(r[col], float) and math.isnan(r[col]))
        ]
        if vals:
            out[col] = {
                "sum": sum(vals), "mean": sum(vals) / len(vals),
                "min": min(vals), "max": max(vals),
            }
    return out


def _snapshot_sheet(session_id: str, entry_id: int, sheet: str, rows: list[dict[str, Any]]) -> str:
    sdir = _snapshot_dir(session_id, entry_id)
    sdir.mkdir(parents=True, exist_ok=True)
    # Sheet names are safe ids (store-validated) but keep the filename tame.
    fname = f"{sheet.replace('/', '_')}.json.gz"
    with gzip.open(sdir / fname, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, default=str)
    return fname


def _load_sheet_snapshot(session_id: str, entry_id: int, fname: str) -> list[dict[str, Any]]:
    with gzip.open(_snapshot_dir(session_id, entry_id) / fname, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _session_db_path(session_id: str) -> Path:
    from . import session_store as ss
    return ss.SESSION_DIR / session_id / "project.db"


def _snapshot_model(session_id: str, entry_id: int) -> dict[str, Any] | None:
    """Full-fidelity session snapshot; returns the ``undo`` ref or None if empty."""
    sdir = _snapshot_dir(session_id, entry_id)
    if model_store.USE_SQLITE:
        src_path = _session_db_path(session_id)
        if not src_path.exists():
            return None
        sdir.mkdir(parents=True, exist_ok=True)
        # sqlite backup API is WAL-safe (a plain file copy can miss WAL pages).
        src = sqlite3.connect(str(src_path))
        try:
            dest = sqlite3.connect(str(sdir / "project.db"))
            try:
                src.backup(dest)
            finally:
                dest.close()
        finally:
            src.close()
        return {"strategy": "model-snapshot", "snapshotRef": "project.db"}
    from . import session_store as ss
    src_dir = ss.SESSION_DIR / session_id
    if not src_dir.exists():
        return None
    sdir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_dir, sdir / "session", dirs_exist_ok=True)
    return {"strategy": "model-snapshot", "snapshotRef": "session"}


def _restore_model(session_id: str, entry_id: int, ref: str) -> None:
    from . import session_store as ss
    dest_dir = ss.SESSION_DIR / session_id
    if model_store.USE_SQLITE:
        src = _snapshot_dir(session_id, entry_id) / ref
        dest_dir.mkdir(parents=True, exist_ok=True)
        tmp = dest_dir / "project.db.tmp"
        shutil.copy2(src, tmp)
        # Drop stale WAL/SHM so the restored db is read as-is.
        for ext in ("-wal", "-shm"):
            side = dest_dir / f"project.db{ext}"
            if side.exists():
                side.unlink()
        tmp.replace(dest_dir / "project.db")
        return
    src_dir = _snapshot_dir(session_id, entry_id) / ref
    shutil.rmtree(dest_dir, ignore_errors=True)
    shutil.copytree(src_dir, dest_dir)


# ── inverse ops (patch) ─────────────────────────────────────────────────────────

def inverse_patch_ops(
    before_rows: list[dict[str, Any]], ops: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Forward-replay ``ops`` against ``before_rows``; return (inverse_ops, cell_diffs).

    Ops apply in order and shift indices, so each op's inverse is computed
    against the state *at its application time*; inverses are emitted in
    reverse order so applying them as one batch restores the original rows.
    ``cell_diffs`` records ``set`` before/after pairs for the timeline.
    """
    state = [dict(r) for r in before_rows]
    inverses: list[dict[str, Any]] = []
    diffs: list[dict[str, Any]] = []
    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        if kind == "set":
            i, col = op.get("row"), op.get("column")
            if isinstance(i, int) and 0 <= i < len(state) and isinstance(col, str):
                before = state[i].get(col)
                after = op.get("value")
                if not values_equal(before, after):
                    diffs.append({"row": i, "column": col, "before": before, "after": after})
                inverses.append({"op": "set", "row": i, "column": col, "value": before})
                state[i][col] = after
        elif kind == "addRow":
            values = op.get("values") if isinstance(op.get("values"), dict) else {}
            at = op.get("index")
            idx = at if isinstance(at, int) and 0 <= at <= len(state) else len(state)
            state.insert(idx, dict(values))
            inverses.append({"op": "deleteRows", "rows": [idx]})
        elif kind == "deleteRows":
            drop = sorted({i for i in (op.get("rows") or []) if isinstance(i, int) and 0 <= i < len(state)})
            # Ascending re-insertion restores the original positions.
            restore = [{"op": "addRow", "values": dict(state[i]), "index": i} for i in drop]
            inverses.extend(reversed(restore))
            state = [r for idx, r in enumerate(state) if idx not in set(drop)]
    inverses.reverse()
    return inverses, diffs


def _summarize_ops(ops: list[dict[str, Any]]) -> str:
    sets = sum(1 for o in ops if isinstance(o, dict) and o.get("op") == "set")
    adds = sum(1 for o in ops if isinstance(o, dict) and o.get("op") == "addRow")
    dels = sum(
        len(o.get("rows") or []) for o in ops if isinstance(o, dict) and o.get("op") == "deleteRows"
    )
    parts = []
    if sets:
        parts.append(f"{sets} set")
    if adds:
        parts.append(f"+{adds} row" + ("s" if adds != 1 else ""))
    if dels:
        parts.append(f"-{dels} row" + ("s" if dels != 1 else ""))
    return ", ".join(parts) or "no-op"


# ── recording ───────────────────────────────────────────────────────────────────

def _next_id(session_id: str) -> int:
    return current_version(session_id) + 1


def _record(
    session_id: str,
    *,
    kind: str,
    sheets: list[dict[str, Any]],
    summary: str,
    undo: dict[str, Any],
    detail: dict[str, Any] | None = None,
    entry_id: int | None = None,
    reverts: int | None = None,
) -> dict[str, Any]:
    ctx = actor_context.current()
    entry = {
        "id": entry_id if entry_id is not None else _next_id(session_id),
        "version": entry_id if entry_id is not None else _next_id(session_id),
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actor": ctx.actor,
        "origin": {
            "endpoint": ctx.endpoint,
            "requestId": ctx.request_id,
            "conversationId": ctx.conversation_id,
        },
        "kind": kind,
        "sheets": sheets,
        "summary": summary,
        "undo": undo,
    }
    if detail:
        entry["detail"] = detail
    if reverts is not None:
        entry["reverts"] = reverts
    _append_entry(session_id, entry)
    _enforce_retention(session_id)
    events_bus.publish(session_id, "session.version", {
        "sessionId": session_id,
        "version": entry["version"],
        "entryId": entry["id"],
        "actor": entry["actor"],
        "kind": kind,
        "sheets": [{"name": s.get("name"), "kind": s.get("kind")} for s in sheets],
        "summary": summary,
        "ts": entry["ts"],
    })
    return entry


def _enforce_retention(session_id: str) -> None:
    """Cap entry count and snapshot bytes; evicted entries stay listed but their
    ``undo.strategy`` is downgraded to ``none`` (no longer revertible)."""
    try:
        entries = _read_entries(session_id)
        changed = False
        if len(entries) > _MAX_ENTRIES:
            for e in entries[: len(entries) - _MAX_ENTRIES]:
                changed |= _evict_snapshot(session_id, e)
            entries = entries[len(entries) - _MAX_ENTRIES:]
            changed = True
        snap_root = _dir(session_id) / "snapshots"
        if snap_root.exists():
            def dir_size(p: Path) -> int:
                return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            total = dir_size(snap_root)
            if total > _MAX_SNAPSHOT_BYTES:
                by_entry = {e["id"]: e for e in entries}
                for d in sorted(snap_root.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 0):
                    if total <= _MAX_SNAPSHOT_BYTES:
                        break
                    total -= dir_size(d)
                    entry = by_entry.get(int(d.name)) if d.name.isdigit() else None
                    if entry is not None:
                        _evict_snapshot(session_id, entry)
                        changed = True
                    else:
                        shutil.rmtree(d, ignore_errors=True)
        if changed:
            _rewrite_entries(session_id, entries)
    except Exception:  # noqa: BLE001 — retention is best-effort
        logger.warning("journal retention pass failed for %s", session_id, exc_info=True)


def _evict_snapshot(session_id: str, entry: dict[str, Any]) -> bool:
    sdir = _snapshot_dir(session_id, int(entry["id"]))
    if sdir.exists():
        shutil.rmtree(sdir, ignore_errors=True)
    undo = entry.get("undo") or {}
    if undo.get("strategy") not in (None, "none"):
        entry["undo"] = {"strategy": "none"}
        return True
    return False


# ── wrapped mutators ────────────────────────────────────────────────────────────

def _journaled_patch_sheet(session_id: str, sheet: str, ops: list[dict[str, Any]]):
    with _lock(session_id):
        try:
            before = _sheet_rows(session_id, sheet)
        except Exception:  # noqa: BLE001
            before = None
        result = _orig["patch_sheet"](session_id, sheet, ops)
        if result is None:
            return None
        try:
            entry_id = _next_id(session_id)
            existed = before is not None
            inverse, diffs = inverse_patch_ops(before or [], ops)
            undo: dict[str, Any]
            payload = json.dumps(inverse, default=str)
            if not existed:
                # patch_sheet created the sheet — undo would need sheet deletion,
                # which the store has no primitive for; fall back to non-revertible.
                undo = {"strategy": "none"}
            elif len(payload) > _INLINE_UNDO_LIMIT:
                fname = _snapshot_sheet(session_id, entry_id, f"__inverse__{sheet}", inverse)
                undo = {"strategy": "inverse-ops", "sheet": sheet, "snapshotRef": fname}
            else:
                undo = {"strategy": "inverse-ops", "sheet": sheet, "inverseOps": inverse}
            _record(
                session_id,
                kind="patch",
                sheets=[{
                    "name": sheet, "kind": result.get("kind"),
                    "rowsBefore": len(before or []), "rowsAfter": result.get("total"),
                }],
                summary=f"edit {sheet}: {_summarize_ops(ops)}",
                undo=undo,
                detail={"cellDiffs": diffs[:_DIFF_ROW_CAP], "truncated": len(diffs) > _DIFF_ROW_CAP},
                entry_id=entry_id,
            )
        except Exception:  # noqa: BLE001 — journaling never breaks the edit
            logger.warning("journal record failed (patch %s/%s)", session_id, sheet, exc_info=True)
        return result


def _journaled_transform_series(session_id: str, sheet: str, op: str, params: dict[str, Any]):
    with _lock(session_id):
        try:
            before = _sheet_rows(session_id, sheet)
        except Exception:  # noqa: BLE001
            before = None
        result = _orig["transform_series"](session_id, sheet, op, params)
        if result is None:
            return None
        try:
            entry_id = _next_id(session_id)
            cols = params.get("columns") or None
            undo: dict[str, Any] = {"strategy": "none"}
            summary_before: dict[str, Any] = {}
            if before is not None:
                fname = _snapshot_sheet(session_id, entry_id, sheet, before)
                undo = {"strategy": "sheet-snapshot", "sheet": sheet, "snapshotRef": fname}
                summary_before = _numeric_summary(before, cols)
            after_rows = _sheet_rows(session_id, sheet) or []
            _record(
                session_id,
                kind="series-transform",
                sheets=[{
                    "name": sheet, "kind": "series",
                    "rowsBefore": len(before or []), "rowsAfter": result.get("total"),
                }],
                summary=f"transform {sheet}: {op}" + (f" on {len(cols)} column(s)" if cols else ""),
                undo=undo,
                detail={
                    "op": op,
                    "params": {k: v for k, v in params.items() if v is not None},
                    "columnsBefore": summary_before,
                    "columnsAfter": _numeric_summary(after_rows, cols),
                },
                entry_id=entry_id,
            )
        except Exception:  # noqa: BLE001
            logger.warning("journal record failed (transform %s/%s)", session_id, sheet, exc_info=True)
        return result


def _meta_sheets(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [s for s in (meta or {}).get("sheets", []) if isinstance(s, dict)]


def _model_replace_entry(session_id: str, summary_prefix: str, fn: Callable[[], Any]):
    """Shared capture→mutate→record shape for save_model / merge_static_model."""
    with _lock(session_id):
        before_meta = None
        entry_id = None
        undo: dict[str, Any] = {"strategy": "none"}
        try:
            before_meta = _orig["get_meta"](session_id)
            entry_id = _next_id(session_id)
            snap = _snapshot_model(session_id, entry_id)
            if snap is not None:
                undo = snap
        except Exception:  # noqa: BLE001
            logger.warning("journal capture failed (%s %s)", summary_prefix, session_id, exc_info=True)
        result = fn()
        if result is None:
            # Mutation didn't happen (e.g. merge into an empty session) — drop
            # the pre-taken snapshot so it doesn't leak.
            if entry_id is not None:
                shutil.rmtree(_snapshot_dir(session_id, entry_id), ignore_errors=True)
            return None
        try:
            after_meta = result if isinstance(result, dict) and "sheets" in result else _orig["get_meta"](session_id)
            before_sheets = {s["name"]: s for s in _meta_sheets(before_meta)}
            after_sheets = {s["name"]: s for s in _meta_sheets(after_meta)}
            sheets = []
            for name, s in after_sheets.items():
                b = before_sheets.get(name)
                sheets.append({
                    "name": name, "kind": s.get("kind"),
                    "rowsBefore": (b or {}).get("rowCount"), "rowsAfter": s.get("rowCount"),
                    "added": b is None,
                })
            for name, b in before_sheets.items():
                if name not in after_sheets:
                    sheets.append({
                        "name": name, "kind": b.get("kind"),
                        "rowsBefore": b.get("rowCount"), "rowsAfter": None, "removed": True,
                    })
            n_added = sum(1 for s in sheets if s.get("added"))
            n_removed = sum(1 for s in sheets if s.get("removed"))
            bits = [f"{len(after_sheets)} sheet(s)"]
            if n_added:
                bits.append(f"{n_added} new")
            if n_removed:
                bits.append(f"{n_removed} removed")
            _record(
                session_id,
                kind="model-replace",
                sheets=sheets,
                summary=f"{summary_prefix}: {', '.join(bits)}",
                undo=undo,
                entry_id=entry_id,
            )
        except Exception:  # noqa: BLE001
            logger.warning("journal record failed (%s %s)", summary_prefix, session_id, exc_info=True)
        return result


def _journaled_save_model(session_id: str, model, *, filename: str = "", scenario_name: str = ""):
    return _model_replace_entry(
        session_id, "replace model",
        lambda: _orig["save_model"](session_id, model, filename=filename, scenario_name=scenario_name),
    )


def _journaled_merge_static_model(session_id: str, model):
    return _model_replace_entry(
        session_id, "merge static sheets",
        lambda: _orig["merge_static_model"](session_id, model),
    )


def _journaled_clear(session_id: str) -> bool:
    with _lock(session_id):
        entry_id = None
        undo: dict[str, Any] = {"strategy": "none"}
        try:
            entry_id = _next_id(session_id)
            snap = _snapshot_model(session_id, entry_id)
            if snap is not None:
                undo = snap
        except Exception:  # noqa: BLE001
            logger.warning("journal capture failed (clear %s)", session_id, exc_info=True)
        cleared = _orig["clear"](session_id)
        if not cleared:
            if entry_id is not None:
                shutil.rmtree(_snapshot_dir(session_id, entry_id), ignore_errors=True)
            return cleared
        try:
            _record(
                session_id, kind="clear", sheets=[],
                summary="session cleared", undo=undo, entry_id=entry_id,
            )
        except Exception:  # noqa: BLE001
            logger.warning("journal record failed (clear %s)", session_id, exc_info=True)
        return cleared


def wrap_model_store() -> None:
    """Install the journal wrappers on the :mod:`model_store` facade (idempotent).

    Store-internal calls (e.g. ``sqlite_store.save_model`` → module-local
    ``clear``) bypass the facade attributes, so wrapping here journals exactly
    one entry per facade-level mutation.
    """
    if _orig:
        return
    _orig.update({
        "save_model": model_store.save_model,
        "merge_static_model": model_store.merge_static_model,
        "patch_sheet": model_store.patch_sheet,
        "transform_series": model_store.transform_series,
        "clear": model_store.clear,
        "get_meta": model_store.get_meta,
        "get_sheet_page": model_store.get_sheet_page,
    })
    model_store.save_model = _journaled_save_model  # type: ignore[assignment]
    model_store.merge_static_model = _journaled_merge_static_model  # type: ignore[assignment]
    model_store.patch_sheet = _journaled_patch_sheet  # type: ignore[assignment]
    model_store.transform_series = _journaled_transform_series  # type: ignore[assignment]
    model_store.clear = _journaled_clear  # type: ignore[assignment]
    logger.info("journal: model_store facade wrapped")


def record_external_replace(session_id: str, summary: str, fn: Callable[[], Any]):
    """Journal a model replacement that bypasses the facade (e.g. an example's
    ``project.db`` copied over the session). Runs ``fn`` under the session lock
    with a model-snapshot capture; same semantics as ``save_model``."""
    return _model_replace_entry(session_id, summary, fn)


# ── read/undo API (used by the /api/session/journal router) ─────────────────────

def list_entries(session_id: str, limit: int = 50, before: int | None = None) -> list[dict[str, Any]]:
    """Newest-first entries (undo payloads stripped; diffs fetched lazily)."""
    entries = _read_entries(session_id)
    if before is not None:
        entries = [e for e in entries if e["id"] < before]
    out = []
    for e in reversed(entries[-limit:] if before is None else entries):
        slim = {k: v for k, v in e.items() if k != "detail"}
        slim["undo"] = {"strategy": (e.get("undo") or {}).get("strategy", "none")}
        slim["hasDetail"] = "detail" in e
        out.append(slim)
        if len(out) >= limit:
            break
    return out


def entry_diff(session_id: str, entry_id: int) -> dict[str, Any] | None:
    """The detailed diff for one entry (lazy; capped)."""
    for e in _read_entries(session_id):
        if e["id"] == entry_id:
            return {
                "id": e["id"], "kind": e["kind"], "sheets": e.get("sheets", []),
                "summary": e.get("summary"), "detail": e.get("detail") or {},
                "undoStrategy": (e.get("undo") or {}).get("strategy", "none"),
            }
    return None


def _entry_sheet_names(entry: dict[str, Any]) -> set[str]:
    if entry.get("kind") in ("model-replace", "clear", "revert") and not entry.get("sheets"):
        return {"*"}
    names = {str(s.get("name")) for s in entry.get("sheets", []) if isinstance(s, dict)}
    return names or {"*"}


def _overlaps(a: set[str], b: set[str]) -> bool:
    return "*" in a or "*" in b or bool(a & b)


def _apply_undo(session_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Apply one entry's inverse via the RAW store functions; returns redo-undo info.

    Runs inside the caller's session lock. The returned dict is the ``undo``
    block for the ``revert`` entry that the caller records (so redo works).
    """
    undo = entry.get("undo") or {}
    strategy = undo.get("strategy")
    entry_id = int(entry["id"])
    if strategy == "inverse-ops":
        sheet = undo["sheet"]
        inverse = undo.get("inverseOps")
        if inverse is None:
            inverse = _load_sheet_snapshot(session_id, entry_id, undo["snapshotRef"])
        # Redo = the inverse of the inverse, computed against the CURRENT rows
        # (the state the inverse is about to be applied to) — after the undo it
        # would be inverted against the wrong base.
        current = _sheet_rows(session_id, sheet)
        if current is None:
            raise RuntimeError(f"undo failed: sheet {sheet!r} no longer exists")
        redo_ops, _ = inverse_patch_ops(current, inverse)
        if _orig["patch_sheet"](session_id, sheet, inverse) is None:
            raise RuntimeError(f"undo failed: sheet {sheet!r} no longer exists")
        payload = json.dumps(redo_ops, default=str)
        if len(payload) > _INLINE_UNDO_LIMIT:
            new_id = _next_id(session_id)
            fname = _snapshot_sheet(session_id, new_id, f"__inverse__{sheet}", redo_ops)
            return {"strategy": "inverse-ops", "sheet": sheet, "snapshotRef": fname, "_entryId": new_id}
        return {"strategy": "inverse-ops", "sheet": sheet, "inverseOps": redo_ops}
    if strategy == "sheet-snapshot":
        sheet = undo["sheet"]
        new_id = _next_id(session_id)
        current = _sheet_rows(session_id, sheet)
        redo_ref = _snapshot_sheet(session_id, new_id, sheet, current or [])
        rows = _load_sheet_snapshot(session_id, entry_id, undo["snapshotRef"])
        # Restore by rewriting the whole sheet through patch ops: delete all, add all.
        n_now = len(current or [])
        ops: list[dict[str, Any]] = []
        if n_now:
            ops.append({"op": "deleteRows", "rows": list(range(n_now))})
        ops.extend({"op": "addRow", "values": r} for r in rows)
        if _orig["patch_sheet"](session_id, sheet, ops) is None:
            raise RuntimeError(f"undo failed: sheet {sheet!r} no longer exists")
        return {"strategy": "sheet-snapshot", "sheet": sheet, "snapshotRef": redo_ref, "_entryId": new_id}
    if strategy == "model-snapshot":
        new_id = _next_id(session_id)
        redo = _snapshot_model(session_id, new_id)
        _restore_model(session_id, entry_id, undo["snapshotRef"])
        out = redo or {"strategy": "none"}
        out["_entryId"] = new_id
        return out
    raise ValueError(f"entry {entry_id} is not revertible (strategy: {strategy or 'none'})")


def undo(session_id: str, entry_id: int) -> dict[str, Any]:
    """Undo a single entry. 409-style conflict when a later entry overlaps."""
    with _lock(session_id):
        entries = _read_entries(session_id)
        target = next((e for e in entries if e["id"] == entry_id), None)
        if target is None:
            raise KeyError(f"journal entry {entry_id} not found")
        strategy = (target.get("undo") or {}).get("strategy", "none")
        if strategy in (None, "none"):
            raise ValueError(f"entry {entry_id} is not revertible (strategy: none)")
        mine = _entry_sheet_names(target)
        for later in entries:
            if later["id"] > entry_id and _overlaps(mine, _entry_sheet_names(later)):
                raise ConflictError(
                    f"a later change (v{later['id']}) touches the same sheet(s); "
                    "use revert-to-here instead"
                )
        redo_undo = _apply_undo(session_id, target)
        new_id = redo_undo.pop("_entryId", None)
        entry = _record(
            session_id,
            kind="revert",
            sheets=target.get("sheets", []),
            summary=f"undo v{entry_id}: {target.get('summary', '')}",
            undo=redo_undo,
            entry_id=new_id,
            reverts=entry_id,
        )
        return {"version": entry["version"], "undone": [entry_id]}


def revert_to(session_id: str, to_version: int) -> dict[str, Any]:
    """Undo every entry newer than ``to_version`` (newest first)."""
    with _lock(session_id):
        entries = _read_entries(session_id)
        pending = [e for e in entries if e["id"] > to_version]
        if not pending:
            return {"version": current_version(session_id), "undone": []}
        blocked = [e["id"] for e in pending if (e.get("undo") or {}).get("strategy", "none") == "none"]
        if blocked:
            raise ValueError(
                f"cannot revert past v{min(blocked)}: its undo snapshot was evicted"
            )
        undone: list[int] = []
        last = None
        for e in reversed(pending):
            redo_undo = _apply_undo(session_id, e)
            new_id = redo_undo.pop("_entryId", None)
            last = _record(
                session_id,
                kind="revert",
                sheets=e.get("sheets", []),
                summary=f"undo v{e['id']}: {e.get('summary', '')}",
                undo=redo_undo,
                entry_id=new_id,
                reverts=int(e["id"]),
            )
            undone.append(int(e["id"]))
        return {"version": (last or {}).get("version", current_version(session_id)), "undone": undone}


def purge(session_id: str) -> None:
    """Delete the session's journal + snapshots (Settings-level action)."""
    with _lock(session_id):
        shutil.rmtree(_dir(session_id), ignore_errors=True)


class ConflictError(RuntimeError):
    """Undo blocked by a later overlapping entry (HTTP 409)."""
