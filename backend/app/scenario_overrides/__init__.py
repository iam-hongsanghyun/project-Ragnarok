"""Per-scenario model overrides — compact cell patches applied at run time.

A scenario preset may carry ``modelOverrides``: a list of
``{sheet, name, column, value}`` cell patches (e.g. ``generators · solar1 ·
p_nom = 500``). They let scenarios differ in the *model* — capacity above all —
without each scenario carrying a whole network. The patch is applied to the run's
model snapshot in :func:`main._resolve_payload_model`, so the solved (and stored)
run reflects the override and it shows up in both the scenario diff and the
results Comparison.

Pure + no I/O so it is unit-tested directly.
"""

from __future__ import annotations

from typing import Any


def apply_model_overrides(
    model: dict[str, list[dict[str, Any]]], overrides: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Return a shallow copy of ``model`` with each override cell set.

    Each override is ``{sheet, name, column, value}`` and patches the row whose
    ``name`` matches, on the named sheet. Overrides that reference a missing sheet
    or component name are skipped (an override only edits an existing component —
    it never invents rows). Only the touched sheets are copied; others are shared.
    """
    if not overrides:
        return model

    # Group overrides by sheet so each touched sheet is copied once.
    by_sheet: dict[str, list[dict[str, Any]]] = {}
    for ov in overrides:
        if not isinstance(ov, dict):
            continue
        sheet = ov.get("sheet")
        name = ov.get("name")
        column = ov.get("column")
        if not sheet or name is None or not column:
            continue
        by_sheet.setdefault(str(sheet), []).append(ov)

    if not by_sheet:
        return model

    out = dict(model)
    for sheet, patches in by_sheet.items():
        rows = model.get(sheet)
        if not isinstance(rows, list):
            continue
        new_rows = [dict(r) if isinstance(r, dict) else r for r in rows]
        index = {
            str(r.get("name")): i
            for i, r in enumerate(new_rows)
            if isinstance(r, dict) and r.get("name") is not None
        }
        for ov in patches:
            i = index.get(str(ov.get("name")))
            if i is None:
                continue
            new_rows[i][str(ov.get("column"))] = ov.get("value")
        out[sheet] = new_rows
    return out
