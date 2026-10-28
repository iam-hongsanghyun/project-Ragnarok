"""Placeholder bounds: a finite 1e9+ value standing for "no limit".

Workbooks from upstream tooling store ``1e12`` in ``p_nom_max`` / ``e_sum_max`` / ``lifetime`` instead of the
``inf`` they meant. PyPSA uses a value as given, so such a cell feeds a huge right-hand side into the LP (HiGHS
warns about row bounds spanning 12 orders of magnitude). Ragnarok does not snap them at run time any more:
this module only FINDS them (for the model check) and the Forge action
(``backend.app.forge_helpers.clean_placeholder_bounds``) rewrites them visibly, as blank cells that take
PyPSA's own default (``inf`` / ``-inf``).
"""
from __future__ import annotations

import math
from typing import Any

#: A finite value with at least this magnitude on an upper (or lower) bound column reads as "no limit".
PLACEHOLDER_THRESHOLD = 1e9


def bound_direction(column: str) -> int:
    """``+1`` for an upper-bound column, ``-1`` for a lower-bound one, ``0`` for any other column.

    Upper: ``*_nom_max``, ``*_sum_max``, ``lifetime``, ``v_ang_max`` (default ``inf``);
    lower: ``*_sum_min`` (default ``-inf``).
    """
    if column.endswith("_nom_max") or column.endswith("_sum_max") or column in ("lifetime", "v_ang_max"):
        return 1
    if column.endswith("_sum_min"):
        return -1
    return 0


def is_placeholder(column: str, value: Any) -> bool:
    """Whether ``value`` in ``column`` is a finite 1e9+ stand-in for an infinite bound."""
    direction = bound_direction(column)
    if direction == 0 or value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(number):
        return False
    return number >= PLACEHOLDER_THRESHOLD if direction > 0 else number <= -PLACEHOLDER_THRESHOLD


def find_placeholders(model: dict[str, Any]) -> list[tuple[str, str, str, float]]:
    """Every placeholder cell of a workbook as ``(sheet, row name, column, value)``.

    Static component sheets only (a sheet name with ``-`` is a time series).
    """
    found: list[tuple[str, str, str, float]] = []
    for sheet, rows in model.items():
        if not isinstance(rows, list) or "-" in sheet or sheet.startswith("RAGNAROK_"):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for column, value in row.items():
                if is_placeholder(str(column), value):
                    found.append((sheet, str(row.get("name", "")), str(column), float(value)))
    return found
