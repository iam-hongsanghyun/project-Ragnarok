"""Merge a backend-built ``WorkbookFragment`` into a working model — the MCP twin
of the web UI's ``lib/workbook/mergeFragment.ts``.

Importers, siting scans and PyPSA-Earth builds return a *fragment* (sheet rows,
optional ``snapshots`` and a ``provenance`` row) without touching the session.
The GUI merges it client-side on "Add to workbook"; the agent path has no
browser, so the same rules live here:

* static sheets get the new rows appended with name dedupe (existing rows win;
  colliding names get ``_2`` / ``_3`` / … and references are rewritten);
* ``carriers`` is unioned by name;
* ``RAGNAROK_Provenance`` gains one row per fetch;
* with ``snapshots``, the ``snapshots`` sheet becomes the sorted union and every
  temporal sheet is widened to it — ``loads-p_set`` constant-extends from the
  nearest imported value, ``generators-p_max_pu`` pads with 1.0, others stay
  empty.

Unlike the TS original, a renamed component is also renamed in the temporal
columns of the same fragment, so its profile follows it.

Pure functions, stdlib only (this subpackage imports nothing from backend.app).
"""

from __future__ import annotations

import bisect
from typing import Any

Rows = list[dict[str, Any]]
Model = dict[str, Rows]

CARRIERS_SHEET = "carriers"
SNAPSHOTS_SHEET = "snapshots"
PROVENANCE_SHEET = "RAGNAROK_Provenance"
_BUS_REFS = ("bus", "bus0", "bus1", "bus2", "bus3", "bus4")


def _filled(v: Any) -> bool:
    return v is not None and v != ""


def _is_temporal(sheet: str, rows: Rows) -> bool:
    return "-" in sheet and any("snapshot" in r for r in rows)


def _pad_mode(sheet: str) -> str:
    component, _, attribute = sheet.partition("-")
    if component == "loads" and attribute == "p_set":
        return "constant"
    if component == "generators" and attribute == "p_max_pu":
        return "one"
    return "empty"


def _dedupe(name: str, taken: set[str]) -> str:
    if name not in taken:
        taken.add(name)
        return name
    i = 2
    while f"{name}_{i}" in taken:
        i += 1
    out = f"{name}_{i}"
    taken.add(out)
    return out


def _append_with_dedupe(
    existing: Rows, incoming: Rows, rename: dict[str, str], sheet: str
) -> Rows:
    taken = {
        r["name"] for r in existing if isinstance(r.get("name"), str) and r["name"]
    }
    out = list(existing)
    for raw in incoming:
        row = dict(raw)
        name = row.get("name")
        if isinstance(name, str) and name:
            final = _dedupe(name, taken)
            if final != name:
                rename[f"{sheet}::{name}"] = final
            row["name"] = final
        out.append(row)
    return out


def _union_carriers(existing: Rows, incoming: Rows) -> Rows:
    by_name: dict[str, dict[str, Any]] = {}
    for r in existing:
        if isinstance(r.get("name"), str):
            by_name[r["name"]] = r
    for raw in incoming:
        name = raw.get("name")
        if isinstance(name, str) and name and name not in by_name:
            by_name[name] = dict(raw)
    return list(by_name.values())


def _index_by_snapshot(rows: Rows) -> dict[str, dict[str, Any]]:
    return {
        r["snapshot"]: r
        for r in rows
        if isinstance(r.get("snapshot"), str) and r["snapshot"]
    }


def _nearest(
    imported: dict[str, dict[str, Any]], ordered: list[str], snap: str, col: str
) -> Any:
    lo = bisect.bisect_left(ordered, snap)
    for cand in (
        ordered[lo - 1] if lo > 0 else None,
        ordered[lo] if lo < len(ordered) else None,
    ):
        if cand is not None and _filled(imported[cand].get(col)):
            return imported[cand][col]
    for cand in ordered:
        if _filled(imported[cand].get(col)):
            return imported[cand][col]
    return None


def _merge_temporal(existing: Rows, incoming: Rows, union: list[str], pad: str) -> Rows:
    e_map = _index_by_snapshot(existing)
    i_map = _index_by_snapshot(incoming)
    i_sorted = sorted(i_map)
    e_cols = {k for r in existing for k in r if k != "snapshot"}
    i_cols = {k for r in incoming for k in r if k != "snapshot"}
    out: Rows = []
    for snap in union:
        row: dict[str, Any] = {"snapshot": snap}
        e_row = e_map.get(snap) or {}
        i_row = i_map.get(snap) or {}
        for col in e_cols:
            if _filled(e_row.get(col)):
                row[col] = e_row[col]
        for col in i_cols:
            if _filled(i_row.get(col)):
                row[col] = i_row[col]
            elif col in row:
                continue
            elif pad == "one":
                row[col] = 1.0
            elif pad == "constant":
                v = _nearest(i_map, i_sorted, snap, col)
                if v is not None:
                    row[col] = v
        out.append(row)
    return out


def _rename_columns(rows: Rows, component: str, rename: dict[str, str]) -> Rows:
    mapping = {
        old.split("::", 1)[1]: new
        for old, new in rename.items()
        if old.startswith(f"{component}::")
    }
    if not mapping:
        return rows
    return [{mapping.get(k, k): v for k, v in r.items()} for r in rows]


def merge_fragment(model: Model, fragment: dict[str, Any]) -> Model:
    """Return ``model`` with ``fragment`` merged in (``model`` is not mutated)."""
    out: Model = dict(model)
    sheets: dict[str, Rows] = dict(fragment.get("sheets") or {})
    snapshots = [
        s for s in (fragment.get("snapshots") or []) if isinstance(s, str) and s
    ]
    rename: dict[str, str] = {}

    temporal = [s for s, rows in sheets.items() if _is_temporal(s, rows)]
    static = [s for s in sheets if s not in temporal]

    # Buses first so later sheets in the same fragment can follow a renamed bus.
    order = (["buses"] if "buses" in static else []) + [
        s for s in static if s not in ("buses", CARRIERS_SHEET, SNAPSHOTS_SHEET)
    ]
    for sheet in order:
        incoming = sheets.get(sheet) or []
        if not incoming:
            continue
        rewritten = []
        for raw in incoming:
            row = dict(raw)
            for ref in _BUS_REFS:
                v = row.get(ref)
                if isinstance(v, str) and f"buses::{v}" in rename:
                    row[ref] = rename[f"buses::{v}"]
            rewritten.append(row)
        out[sheet] = _append_with_dedupe(
            list(out.get(sheet) or []), rewritten, rename, sheet
        )

    if sheets.get(CARRIERS_SHEET):
        out[CARRIERS_SHEET] = _union_carriers(
            list(out.get(CARRIERS_SHEET) or []), sheets[CARRIERS_SHEET]
        )

    # A fragment may carry its window as a ``snapshots`` sheet instead of a list.
    if not snapshots and sheets.get(SNAPSHOTS_SHEET):
        snapshots = [
            r["snapshot"]
            for r in sheets[SNAPSHOTS_SHEET]
            if isinstance(r.get("snapshot"), str)
        ]

    for sheet in temporal:
        sheets[sheet] = _rename_columns(sheets[sheet], sheet.partition("-")[0], rename)

    if snapshots:
        existing_rows = list(out.get(SNAPSHOTS_SHEET) or [])
        existing = [
            r["snapshot"]
            for r in existing_rows
            if isinstance(r.get("snapshot"), str) and r["snapshot"]
        ]
        union = sorted(set(existing) | set(snapshots))
        by_snap = {
            r["snapshot"]: r
            for r in existing_rows
            if isinstance(r.get("snapshot"), str)
        }
        out[SNAPSHOTS_SHEET] = [by_snap.get(s) or {"snapshot": s} for s in union]
        for sheet in temporal:
            out[sheet] = _merge_temporal(
                list(out.get(sheet) or []), sheets[sheet], union, _pad_mode(sheet)
            )
    else:
        for sheet in temporal:
            out[sheet] = list(out.get(sheet) or []) + list(sheets[sheet])

    prov = fragment.get("provenance")
    if isinstance(prov, dict):
        row = {
            k: prov.get(k)
            for k in (
                "database_id",
                "country_iso",
                "country_name",
                "filters_json",
                "convert_options_json",
                "fetch_timestamp",
                "row_counts_json",
            )
        }
        row["kind"] = "data-import"
        out[PROVENANCE_SHEET] = list(out.get(PROVENANCE_SHEET) or []) + [row]

    return out
