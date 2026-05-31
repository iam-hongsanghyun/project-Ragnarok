"""WorkbookFragment-level helpers: name slugging, dedupe, provenance row.

All importers funnel through here so the merged workbook never has duplicate
component names and the ``RAGNAROK_Provenance`` sheet picks up one row per
fetch with a consistent shape.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..protocol import ConvertOptions, Provenance, Region, WorkbookFragment


_PROVENANCE_SHEET = "RAGNAROK_Provenance"
_CARRIERS_SHEET = "carriers"


_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def slugify_name(raw: str | None, fallback: str = "asset") -> str:
    """Normalise an upstream name to something safe for a workbook key."""
    if not raw:
        return fallback
    s = _NAME_RE.sub("_", str(raw).strip())
    s = s.strip("_")
    return s or fallback


def dedupe_name(name: str, taken: set[str]) -> str:
    """Return a name that is not in ``taken``, suffixing ``_2``, ``_3``, … as needed."""
    if name not in taken:
        taken.add(name)
        return name
    i = 2
    while f"{name}_{i}" in taken:
        i += 1
    final = f"{name}_{i}"
    taken.add(final)
    return final


def merge_carriers_into_fragment(
    fragment: WorkbookFragment,
    carrier_rows: list[dict[str, Any]],
) -> None:
    """Append unique carrier rows (keyed by ``name``) onto the fragment."""
    if not carrier_rows:
        return
    existing = fragment.sheets.setdefault(_CARRIERS_SHEET, [])
    seen = {str(r.get("name")) for r in existing if r.get("name")}
    for row in carrier_rows:
        name = str(row.get("name") or "")
        if not name or name in seen:
            continue
        existing.append(row)
        seen.add(name)


def build_provenance(
    *,
    database_id: str,
    region: Region,
    filters: dict[str, Any],
    options: ConvertOptions,
    fetch_timestamp: str,
    row_counts: dict[str, int],
) -> Provenance:
    return Provenance(
        database_id=database_id,
        country_iso=region.country_iso,
        country_name=region.country_name,
        filters_json=json.dumps(filters, sort_keys=True, default=str),
        convert_options_json=json.dumps(options.__dict__, sort_keys=True, default=str),
        fetch_timestamp=fetch_timestamp,
        row_counts_json=json.dumps(row_counts, sort_keys=True),
    )
