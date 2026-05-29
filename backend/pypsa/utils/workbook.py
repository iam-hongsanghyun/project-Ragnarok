from __future__ import annotations

from typing import Any


def workbook_rows(model: dict[str, list[dict[str, Any]]], sheet: str) -> list[dict[str, Any]]:
    """Return the rows of `model[sheet]` as a list, or [] if absent.

    Used by the JSON-model validator (`validate_model`) which inspects the
    in-memory workbook before the user clicks Run. The actual network is
    built from the uploaded xlsx file directly via PyPSA's own importer.
    """
    return list(model.get(sheet, []))
