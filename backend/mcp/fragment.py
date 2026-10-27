"""Merge a backend-built ``WorkbookFragment`` into a working model — the MCP twin
of the web UI's ``lib/workbook/mergeFragment.ts``.

Importers, siting scans and PyPSA-Earth builds return a *fragment* (sheet rows,
optional ``snapshots`` and a ``provenance`` row) without touching the session.
The GUI merges it client-side on "Add to workbook"; the agent path has no
browser, so the same rules live here:

* static sheets get the new rows appended with name dedupe (existing rows win;
  colliding names get ``_2`` / ``_3`` / … and references are rewritten);
* ``carriers`` is unioned by name, an existing carrier merged attribute-wise
  (existing non-empty values win; a fuel-price fragment overwrites and also
  sets ``marginal_cost = fuel_cost_thermal / efficiency`` on its generators);
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
import math
from typing import Any

Rows = list[dict[str, Any]]
Model = dict[str, Rows]

CARRIERS_SHEET = "carriers"
SNAPSHOTS_SHEET = "snapshots"
PROVENANCE_SHEET = "RAGNAROK_Provenance"
FUEL_PRICES_DB = "fuel_prices"
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


def _union_carriers(existing: Rows, incoming: Rows, overwrite: bool = False) -> Rows:
    """Union by name; an existing carrier is merged attribute-wise — existing
    non-empty values win, empty ones are filled (``overwrite``: fragment wins)."""
    by_name: dict[str, dict[str, Any]] = {}
    for r in existing:
        if isinstance(r.get("name"), str) and r["name"]:
            by_name[r["name"]] = dict(r)
    unnamed = [
        r for r in existing if not (isinstance(r.get("name"), str) and r["name"])
    ]
    for raw in incoming:
        name = raw.get("name")
        if not (isinstance(name, str) and name):
            continue
        row = by_name.get(name)
        if row is None:
            by_name[name] = dict(raw)
            continue
        for k, v in raw.items():
            if k == "name" or not _filled(v):
                continue
            if overwrite or not _filled(row.get(k)):
                row[k] = v
    return list(by_name.values()) + unnamed


def _apply_fuel_cost(generators: Rows, carriers: Rows) -> Rows:
    """Fuel-price fragments: generators of a priced carrier get
    ``marginal_cost = fuel_cost_thermal / efficiency`` (blank/≤0 efficiency → 1)."""
    thermal: dict[str, float] = {}
    for c in carriers:
        try:
            t = float(c.get("fuel_cost_thermal"))
        except (TypeError, ValueError):
            continue
        if (
            isinstance(c.get("name"), str)
            and _filled(c.get("fuel_cost_thermal"))
            and not math.isnan(t)
        ):
            thermal[c["name"]] = t
    if not thermal:
        return generators
    out: Rows = []
    for g in generators:
        t = thermal.get(g.get("carrier")) if isinstance(g.get("carrier"), str) else None
        if t is None:
            out.append(g)
            continue
        try:
            eff = float(g["efficiency"]) if _filled(g.get("efficiency")) else 1.0
        except (TypeError, ValueError):
            eff = 1.0
        if not eff > 0:
            eff = 1.0
        out.append({**g, "marginal_cost": round(t / eff, 4)})
    return out


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
        prov = fragment.get("provenance")
        fuel_prices = (
            isinstance(prov, dict) and prov.get("database_id") == FUEL_PRICES_DB
        )
        out[CARRIERS_SHEET] = _union_carriers(
            list(out.get(CARRIERS_SHEET) or []), sheets[CARRIERS_SHEET], fuel_prices
        )
        if fuel_prices and isinstance(out.get("generators"), list):
            out["generators"] = _apply_fuel_cost(
                out["generators"], sheets[CARRIERS_SHEET]
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
