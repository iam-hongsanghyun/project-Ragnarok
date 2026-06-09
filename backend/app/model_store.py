"""Model-store facade — selects the session storage backend at startup.

All app code (routers, run/queue) goes through this module instead of importing
a concrete store, so the storage engine is a one-line config flip:

* ``RAGNAROK_STORE=legacy`` (default) — JSON + Parquet files (:mod:`session_store`).
* ``RAGNAROK_STORE=sqlite`` — one ``project.db`` per session (:mod:`sqlite_store`).

The public API (signatures + JSON shapes) is identical for both, so the
``/api/session/*`` endpoint contract and the frontend are unchanged either way.
"""
from __future__ import annotations

import os

from . import session_store, sqlite_store

USE_SQLITE = os.environ.get("RAGNAROK_STORE", "legacy").strip().lower() == "sqlite"
_impl = sqlite_store if USE_SQLITE else session_store

# ── delegated public API (identical surface in both backends) ───────────────────
save_model = _impl.save_model
merge_static_model = _impl.merge_static_model
get_meta = _impl.get_meta
get_sheet_page = _impl.get_sheet_page
get_series_window = _impl.get_series_window
load_full_model = _impl.load_full_model
save_controls = _impl.save_controls
get_controls = _impl.get_controls
patch_sheet = _impl.patch_sheet
clear = _impl.clear
has_model = _impl.has_model
is_series_sheet = _impl.is_series_sheet


def distinct_values(session_id: str, sheet: str, column: str) -> list[str] | None:
    """Distinct non-empty string values of ``column`` in ``sheet`` (sorted).

    Uses the backend's native query (SQLite ``SELECT DISTINCT``) when available;
    otherwise computes it from the sheet rows so the capability works on the
    legacy store too.
    """
    native = getattr(_impl, "distinct_values", None)
    if native is not None:
        return native(session_id, sheet, column)
    page = get_sheet_page(session_id, sheet, offset=0, limit=10_000_000)
    if page is None or not column:
        return [] if page is not None else None
    seen: set[str] = set()
    for row in page.get("rows", []):
        v = row.get(column)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            seen.add(s)
    return sorted(seen)


__all__ = [
    "USE_SQLITE", "save_model", "merge_static_model", "get_meta", "get_sheet_page",
    "get_series_window", "load_full_model", "save_controls", "get_controls",
    "patch_sheet", "clear", "has_model", "is_series_sheet", "distinct_values",
]
