"""The project's app state: every setting the app holds, in one key -> string format.

The browser keeps its settings (Settings, each module's options, plugin configs, the live
run controls, view state) as ``localStorage`` key -> string pairs. A project carries all of
them, verbatim, in the ``_app_state`` table of its ``project.db`` (see
:mod:`backend.app.sqlite_store`), so opening the project restores the app exactly as it was
saved. Which keys travel is decided by the browser (``lib/appState``): secrets, caches and
per-user learning progress stay out.

Outside ``project.db`` the same pairs travel as the ``RAGNAROK_AppState`` sheet - in an
exported workbook, in a run's input-model snapshot, and in any model pushed into a session.
:func:`split_from_model` takes that sheet out of a model before it is stored, so app state
never sits among the model sheets. A value longer than one Excel cell is split across rows
(``part`` 0, 1, ...).
"""
from __future__ import annotations

from typing import Any

#: Sheet name of the app state when it travels inside a model or a workbook.
SHEET = "RAGNAROK_AppState"

#: Excel caps a cell at 32 767 characters; stay safely under it.
_CHUNK = 30_000


def to_rows(state: dict[str, str]) -> list[dict[str, Any]]:
    """``{key: value}`` -> sheet rows ``{key, part, value}`` (long values split across parts)."""
    rows: list[dict[str, Any]] = []
    for key in sorted(state):
        value = str(state[key])
        parts = [value[i:i + _CHUNK] for i in range(0, len(value), _CHUNK)] or [""]
        rows.extend({"key": key, "part": n, "value": chunk} for n, chunk in enumerate(parts))
    return rows


def from_rows(rows: list[Any]) -> dict[str, str]:
    """Sheet rows -> ``{key: value}``, joining parts in order. Rows without a key are skipped."""
    parts: dict[str, dict[int, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        try:
            part = int(row.get("part") or 0)
        except (TypeError, ValueError):
            part = 0
        parts.setdefault(key, {})[part] = _as_text(row.get("value"))
    return {key: "".join(chunks[i] for i in sorted(chunks)) for key, chunks in parts.items()}


def _as_text(value: Any) -> str:
    """A cell back to the browser's string: a spreadsheet reader may have turned ``"true"`` / ``"3"`` into a bool / number."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def split_from_model(model: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Return ``(model without the app-state sheet, its state or None when the model had none)``."""
    if SHEET not in model:
        return model, None
    rest = {name: rows for name, rows in model.items() if name != SHEET}
    rows = model.get(SHEET)
    return rest, from_rows(rows if isinstance(rows, list) else [])
