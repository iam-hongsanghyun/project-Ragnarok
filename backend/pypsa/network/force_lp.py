"""Force-LP companion step: the maintenance relaxation PyPSA has no switch for.

Force-LP is PyPSA's own ``linearized_unit_commitment`` (``optimise_options.py``): the committable binaries become
continuous and every unit-commitment constraint stays. PyPSA offers no such switch for the scheduled-maintenance binaries
(``maintainable``), so a Force-LP run that meets a maintainable unit is refused (``network/__init__.py``) and this step is
the way out: it writes ``maintainable = False`` into the workbook rows, visibly, once, and is reversible by the user.
"""
from __future__ import annotations

from typing import Any

_SHEETS = ("generators", "links", "processes")
_TRUE = {"true", "1", "1.0", "yes", "y", "t", "on"}


def relax_maintenance(model: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """A copy of ``model`` with ``maintainable`` False on every generator / link / process (input not mutated).

    Returns ``(model, changed)`` with ``changed`` = ``[{sheet, name}]``.
    """
    out = dict(model)
    changed: list[dict[str, str]] = []
    for sheet in _SHEETS:
        rows = model.get(sheet)
        if not isinstance(rows, list):
            continue
        new_rows = []
        for row in rows:
            if isinstance(row, dict) and str(row.get("maintainable", "")).strip().lower() in _TRUE:
                row = {**row, "maintainable": False}
                changed.append({"sheet": sheet, "name": str(row.get("name", ""))})
            new_rows.append(row)
        out[sheet] = new_rows
    return out, changed
