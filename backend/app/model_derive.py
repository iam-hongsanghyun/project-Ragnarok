"""Derive a filtered working model from a stored master model (pure, no I/O).

A *master* model is an ordinary ``{sheet: rows}`` workbook model — typically
imported from a multi-year Excel project — stored under its own session slot
(``<session>__master``, see :mod:`backend.app.routers.master`). This module
carves a working model out of it:

* **Year selection** filters the ``snapshots`` sheet and every time-series
  sheet to the chosen calendar years (the time axis genuinely changes).
* **Attribute filters** (``{sheet, column, values}``) select the rows of a
  static sheet whose column value is among the chosen values — the generic
  "select component → select attribute → pick values" filter.
* **Vintage filtering** (always on when years are selected) excludes
  components that do not exist in any selected year per PyPSA's
  ``build_year``/``lifetime`` convention.

Excluded components are NOT deleted. PyPSA has a native ``active`` boolean on
every real component (default ``True``; inactive components are skipped by the
optimization), so the default ``mode="deactivate"`` merely writes
``active = False`` on them — the data stays in the tables and a re-derive can
bring it back. Buses and carriers carry no ``active`` flag in PyPSA, so a
filtered-out bus/carrier stays in its sheet and the *components attached to
it* (bus references / carrier users) are deactivated instead. ``mode="remove"``
keeps the old hard-delete semantics for API callers that want a trimmed model.

Everything here is pure data-in/data-out so it unit-tests without a store.
"""
from __future__ import annotations

import math
import re
from typing import Any, Literal

from . import timeseries
from .session_store import is_series_sheet

# Columns that reference a bus on any component sheet (bus, bus0, bus1, …).
_BUS_COL = re.compile(r"^bus\d*$")

# Sheets never touched by filtering: app metadata + the network-wide params.
_METADATA_PREFIX = "RAGNAROK_"
_SKIP_SHEETS = ("network",)

# Component sheets whose PyPSA schema has the ``active`` attribute. Used as the
# fallback when the live schema is unavailable (pure unit tests); the router
# path always resolves against the installed PyPSA via :func:`active_sheets`.
_ACTIVE_SHEETS_FALLBACK = frozenset({
    "generators", "loads", "lines", "links", "storage_units", "stores",
    "transformers", "shunt_impedances",
})

DeriveMode = Literal["deactivate", "remove"]


def active_sheets() -> frozenset[str]:
    """Sheets whose PyPSA schema carries the ``active`` input attribute."""
    try:
        from backend.pypsa.pypsa_schema import component_sheets as schema_sheets
        from backend.pypsa.pypsa_schema import input_static_attributes
    except Exception:  # pragma: no cover — schema unavailable outside the app
        return _ACTIVE_SHEETS_FALLBACK
    try:
        return frozenset(
            sheet for sheet in schema_sheets() if "active" in input_static_attributes(sheet)
        )
    except Exception:  # pragma: no cover
        return _ACTIVE_SHEETS_FALLBACK


def _norm(value: Any) -> str:
    """Normalise a cell for value matching — same rule as ``distinct_values``."""
    if value is None:
        return ""
    return str(value).strip()


def _as_bool(value: Any, default: bool = True) -> bool:
    """Read a workbook cell as a boolean (Excel may carry 'FALSE'/'0'/blank)."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("false", "0", "no", "off"):
        return False
    if s in ("true", "1", "yes", "on"):
        return True
    return default


def component_sheets(model: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Static sheets that hold named components (have a ``name`` column)."""
    out: list[str] = []
    for sheet, rows in model.items():
        if sheet == "snapshots" or sheet.startswith(_METADATA_PREFIX) or sheet in _SKIP_SHEETS:
            continue
        if is_series_sheet(sheet, rows):
            continue
        if rows and any("name" in r for r in rows[:5]):
            out.append(sheet)
    return out


def snapshot_years(model: dict[str, list[dict[str, Any]]]) -> list[int]:
    """Sorted distinct calendar years present in the model's snapshots."""
    rows = model.get("snapshots") or []
    if not rows:
        return []
    index_col = timeseries.series_index_col(list(rows[0].keys()))
    years = {y for r in rows if (y := timeseries.year_of(r.get(index_col))) is not None}
    return sorted(years)


def _to_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _exists_in_years(row: dict[str, Any], years: set[int]) -> bool:
    """PyPSA vintage rule: ``build_year <= y < build_year + lifetime`` for some y.

    Rows without a parseable ``build_year`` always exist (PyPSA's default is 0,
    i.e. "always there"); a missing/non-positive ``lifetime`` means infinite.
    """
    build_year = _to_float(row.get("build_year"))
    if build_year is None or build_year <= 0:
        return True
    lifetime = _to_float(row.get("lifetime"))
    end = math.inf if lifetime is None or lifetime <= 0 else build_year + lifetime
    return any(build_year <= y < end for y in years)


def derive_model(
    master: dict[str, list[dict[str, Any]]],
    *,
    years: list[int] | None = None,
    filters: list[dict[str, Any]] | None = None,
    vintage: bool = True,
    mode: DeriveMode = "deactivate",
    active_capable: frozenset[str] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Derive a working model from ``master`` and report what was excluded.

    Args:
        master: The master ``{sheet: rows}`` model (not mutated).
        years: Calendar years to keep; ``None``/empty keeps every year.
        filters: ``[{sheet, column, values}]`` attribute filters — a row of
            ``sheet`` is selected when ``str(row[column]).strip()`` is in
            ``values``. ANDed when a sheet appears in several filters.
        vintage: Exclude components whose ``build_year``/``lifetime`` window
            misses every selected year (only applies when years are selected).
        mode: ``"deactivate"`` (default) writes ``active = False`` on excluded
            components — PyPSA skips them in the solve, the rows stay. Sheets
            without an ``active`` attribute (buses, carriers) always keep their
            rows; exclusion cascades to the components that reference them.
            ``"remove"`` hard-deletes excluded rows (and, for buses/carriers,
            their dependants + their series columns).
        active_capable: Sheets that support ``active`` — defaults to
            :func:`active_sheets` (the installed PyPSA schema).

    Returns:
        ``(model, report)`` where ``report`` is ``{years, snapshots, mode,
        excluded: {sheet: n}, components: {sheet: n_rows}}`` — ``excluded``
        counts deactivated (or removed) rows per sheet.

    Raises:
        ValueError: when the master is empty or the selection leaves no
            snapshots (the caller turns this into a 400).
    """
    if not master:
        raise ValueError("No master model to derive from.")
    year_set = {int(y) for y in years} if years else None
    can_deactivate = active_sheets() if active_capable is None else active_capable

    model: dict[str, list[dict[str, Any]]] = {
        sheet: [dict(r) for r in rows] for sheet, rows in master.items()
    }

    # 1 — year selection on the time axis and every series sheet (real removal:
    # there is no "inactive snapshot" in PyPSA — the time axis itself changes).
    if year_set:
        for sheet, rows in model.items():
            if not rows or sheet.startswith(_METADATA_PREFIX):
                continue
            if sheet != "snapshots" and not is_series_sheet(sheet, rows):
                continue
            index_col = timeseries.series_index_col(list(rows[0].keys()))
            model[sheet] = [r for r in rows if timeseries.year_of(r.get(index_col)) in year_set]
        if not model.get("snapshots"):
            raise ValueError(
                f"Selected years {sorted(year_set)} leave no snapshots in the master."
            )

    # 2 — decide which component rows are EXCLUDED (selected = survives).
    comp_sheets = component_sheets(model)
    excluded: dict[str, set[int]] = {sheet: set() for sheet in comp_sheets}

    carriers_filtered = False
    for flt in filters or []:
        sheet = str(flt.get("sheet") or "")
        column = str(flt.get("column") or "")
        values = {_norm(v) for v in (flt.get("values") or []) if _norm(v)}
        rows = model.get(sheet)
        if not sheet or not column or not values or rows is None or sheet not in excluded:
            continue
        for i, r in enumerate(rows):
            if _norm(r.get(column)) not in values:
                excluded[sheet].add(i)
        if sheet == "carriers":
            carriers_filtered = True

    if vintage and year_set:
        for sheet in comp_sheets:
            for i, r in enumerate(model[sheet]):
                if not _exists_in_years(r, year_set):
                    excluded[sheet].add(i)

    # 3 — cascade: components referencing an excluded bus (or an excluded
    # carrier, when the carriers sheet was filtered) are excluded too. Buses
    # and carriers have no ``active`` flag in PyPSA, so in deactivate mode this
    # cascade IS how a bus/carrier filter takes effect.
    if "buses" in excluded:
        dead_buses = {
            _norm(r.get("name"))
            for i, r in enumerate(model["buses"]) if i in excluded["buses"]
        }
        if dead_buses:
            for sheet in comp_sheets:
                if sheet == "buses":
                    continue
                rows = model[sheet]
                bus_cols = [c for c in (rows[0].keys() if rows else []) if _BUS_COL.match(c)]
                for i, r in enumerate(rows):
                    if any(_norm(r.get(c)) in dead_buses for c in bus_cols if _norm(r.get(c))):
                        excluded[sheet].add(i)
    if carriers_filtered and "carriers" in excluded:
        dead_carriers = {
            _norm(r.get("name"))
            for i, r in enumerate(model["carriers"]) if i in excluded["carriers"]
        }
        if dead_carriers:
            for sheet in comp_sheets:
                if sheet == "carriers":
                    continue
                for i, r in enumerate(model[sheet]):
                    if _norm(r.get("carrier")) in dead_carriers:
                        excluded[sheet].add(i)

    # 4 — apply the exclusions.
    report_excluded: dict[str, int] = {}
    if mode == "deactivate":
        for sheet in comp_sheets:
            if sheet not in can_deactivate:
                # No ``active`` in the PyPSA schema (buses, carriers, …): rows
                # stay verbatim; their exclusion already cascaded above.
                continue
            n = 0
            for i, r in enumerate(model[sheet]):
                if i in excluded[sheet]:
                    r["active"] = False
                    n += 1
                elif "active" in r:
                    r["active"] = _as_bool(r.get("active"))
            if n:
                # Make the flag visible on every row of the sheet, not only the
                # deactivated ones — an explicit column reads better in the grid.
                for r in model[sheet]:
                    r.setdefault("active", True)
                report_excluded[sheet] = n
    else:  # remove
        alive_names: dict[str, set[str]] = {}
        for sheet in comp_sheets:
            rows = model[sheet]
            kept = [r for i, r in enumerate(rows) if i not in excluded[sheet]]
            if len(kept) < len(rows):
                report_excluded[sheet] = len(rows) - len(kept)
            model[sheet] = kept
            alive_names[sheet] = {_norm(r.get("name")) for r in kept}
        # Prune series columns of removed assets.
        for sheet, rows in model.items():
            if not rows or not is_series_sheet(sheet, rows):
                continue
            comp = sheet.split("-", 1)[0]
            if comp not in alive_names:
                continue
            index_col = timeseries.series_index_col(list(rows[0].keys()))
            keep_cols = {index_col} | alive_names[comp]
            model[sheet] = [{k: v for k, v in r.items() if k in keep_cols} for r in rows]

    report = {
        "years": sorted(year_set) if year_set else snapshot_years(model),
        "snapshots": len(model.get("snapshots") or []),
        "mode": mode,
        "excluded": report_excluded,
        "components": {s: len(model[s]) for s in comp_sheets},
    }
    return model, report
