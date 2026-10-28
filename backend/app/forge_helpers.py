"""Forge / Build helpers shared by the GUI and MCP — pure, no I/O.

Python ports of three browser-only modules, kept behaviour-identical (parity
tests in ``backend/tests/test_forge_build_helpers.py`` replay the fixtures of the
TS suites):

* ``lib/forge/snap.ts``         -> :func:`haversine_km`, :func:`snap_sheet`
* ``lib/build/conversions.ts``  -> :data:`CONVERSION_TEMPLATES`,
  :func:`build_conversion_fragment`
* ``lib/forge/adjust.ts``       -> :func:`apply_adjustments`, :func:`revert_adjustments`

Algorithm (haversine, snap):
    $$a = \\sin^2(\\Delta\\varphi/2) + \\cos\\varphi_1\\cos\\varphi_2\\sin^2(\\Delta\\lambda/2),
    \\quad d = 2R\\,\\arcsin(\\min(1,\\sqrt a))$$
    ASCII: a = sin(dlat/2)^2 + cos(lat1)*cos(lat2)*sin(dlon/2)^2; d = 2R*asin(min(1, sqrt(a)))
    with phi = latitude, lambda = longitude (radians), R = 6371.0088 km (IUGG mean radius).
"""

from __future__ import annotations

import math
from typing import Any

Row = dict[str, Any]
Model = dict[str, list[Row]]

EARTH_RADIUS_KM = 6371.0088

_MISSING = object()


def _num(value: Any) -> float:
    """``numberValue`` of lib/utils/helpers.ts — non-numeric -> 0."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else 0.0
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return 0.0
        return parsed if math.isfinite(parsed) else 0.0
    return 0.0


def _str(value: Any) -> str:
    """``stringValue`` — None -> ''."""
    return "" if value is None else str(value)


def _js_number(value: Any) -> float:
    """JS ``Number(x)`` for a cell: ``_MISSING`` (undefined) -> NaN, ``None``/'' -> 0."""
    if value is _MISSING:
        return math.nan
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return 0.0
        try:
            return float(text)
        except ValueError:
            return math.nan
    return math.nan


# ── Forge: spatial snap ──────────────────────────────────────────────────────


def haversine_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Great-circle distance between two lat/lon points, km."""
    d_lat = math.radians(lat_b - lat_a)
    d_lon = math.radians(lon_b - lon_a)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat_a)) * math.cos(math.radians(lat_b)) * math.sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


SNAP_ANCHORS: tuple[tuple[str, str, str], ...] = (
    ("x", "y", "bus"),
    ("x0", "y0", "bus0"),
    ("x1", "y1", "bus1"),
)


def anchor_coord(row: Row, x_key: str, y_key: str) -> tuple[float, float] | None:
    """``(lat, lon)`` of a row's coordinate anchor, or None when absent/non-finite."""
    x = row.get(x_key)
    y = row.get(y_key)
    if x is None or x == "" or y is None or y == "":
        return None
    lon, lat = _num(x), _num(y)
    # numberValue maps junk to 0, exactly as the TS does; only finite values pass.
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    return lat, lon


def build_targets(rows: list[Row]) -> list[dict[str, Any]]:
    """Rows with a finite x/y and a name, as snap targets (x = lon, y = lat)."""
    out = []
    for row in rows:
        c = anchor_coord(row, "x", "y")
        name = _str(row.get("name")).strip()
        if c and name:
            out.append({"name": name, "lat": c[0], "lon": c[1]})
    return out


def _nearest(targets: list[dict[str, Any]], lat: float, lon: float) -> tuple[dict[str, Any], float] | None:
    best: dict[str, Any] | None = None
    best_km = math.inf
    for t in targets:
        km = haversine_km(lat, lon, t["lat"], t["lon"])
        if km < best_km:
            best_km, best = km, t
    return (best, best_km) if best is not None else None


def snap_sheet(rows: list[Row], targets: list[dict[str, Any]], buffer_km: float) -> dict[str, Any]:
    """Snap each row's bus / bus0 / bus1 to the nearest target within ``buffer_km``.

    Returns ``{rows, assigned, outside, noCoords, anchors}``; out-of-buffer
    anchors are listed in ``outside`` and left unchanged. Input rows are not mutated.
    """
    outside: list[dict[str, Any]] = []
    anchors_used: list[str] = []
    assigned = 0
    no_coords = 0
    out_rows: list[Row] = []
    for i, row in enumerate(rows):
        nxt: Row | None = None
        had_anchor = False
        for x_key, y_key, bus_key in SNAP_ANCHORS:
            c = anchor_coord(row, x_key, y_key)
            if not c:
                continue
            had_anchor = True
            near = _nearest(targets, c[0], c[1])
            if not near:
                continue
            target, km = near
            label = _str(row.get("name")).strip() or f"row {i + 1}"
            if km <= buffer_km:
                if _str(row.get(bus_key)).strip() != target["name"]:
                    if nxt is None:
                        nxt = dict(row)
                    nxt[bus_key] = target["name"]
                assigned += 1
                if bus_key not in anchors_used:
                    anchors_used.append(bus_key)
            else:
                outside.append({"name": label, "field": bus_key, "km": km, "nearest": target["name"]})
        if not had_anchor:
            no_coords += 1
        out_rows.append(nxt if nxt is not None else row)
    return {
        "rows": out_rows,
        "assigned": assigned,
        "outside": outside,
        "noCoords": no_coords,
        "anchors": anchors_used,
    }


def sheet_snappable(rows: list[Row]) -> bool:
    return any(anchor_coord(r, a[0], a[1]) is not None for r in rows for a in SNAP_ANCHORS)


# ── Build: conversion templates ──────────────────────────────────────────────

_POWER_CARRIERS = {"", "ac", "dc", "electricity", "elec", "power"}
_BUS_PREFIX = {"hydrogen": "H2", "heat": "heat", "gas": "gas"}


def _power() -> dict[str, Any]:
    return {"role": "power"}


def _carrier(name: str, fuel: bool = False) -> dict[str, Any]:
    ep: dict[str, Any] = {"role": "carrier", "carrier": name}
    if fuel:
        ep["fuel"] = True
    return ep


def _tpl(id_: str, label: str, description: str, link_carrier: str, input_: dict, output: dict,
         efficiency: float, capital_cost: float, lifetime: float, **extra: Any) -> dict[str, Any]:
    return {
        "id": id_, "label": label, "description": description, "linkCarrier": link_carrier,
        "input": input_, "output": output, "efficiency": efficiency,
        "capitalCost": capital_cost, "lifetime": lifetime, **extra,
    }


CONVERSION_TEMPLATES: list[dict[str, Any]] = [
    _tpl("ccgt", "CCGT (gas → electricity)", "Combined-cycle gas turbine burning gas to make power.",
         "CCGT", _carrier("gas", True), _power(), 0.55, 40000, 30, fuelCost=25, co2=0.20),
    _tpl("ocgt", "OCGT (gas → electricity)", "Open-cycle gas turbine — a cheaper, lower-efficiency peaker.",
         "OCGT", _carrier("gas", True), _power(), 0.39, 25000, 30, fuelCost=25, co2=0.20),
    _tpl("chp", "CHP (gas → electricity + heat)", "Gas combined heat & power; co-produces electricity and heat.",
         "CHP", _carrier("gas", True), _power(), 0.40, 60000, 25,
         output2=_carrier("heat"), efficiency2=0.45, fuelCost=25, co2=0.20),
    _tpl("electrolyser", "Electrolyser (electricity → hydrogen)", "Uses power to split water into hydrogen.",
         "electrolysis", _power(), _carrier("hydrogen"), 0.70, 90000, 20),
    _tpl("fuel_cell", "Hydrogen fuel cell (hydrogen → electricity)", "Converts stored hydrogen back into power.",
         "fuel cell", _carrier("hydrogen"), _power(), 0.50, 90000, 20),
    _tpl("heat_pump", "Heat pump (electricity → heat)", "Electric heat pump with a coefficient of performance above 1.",
         "heat pump", _power(), _carrier("heat"), 3.0, 60000, 20),
    _tpl("resistive_heater", "Resistive heater (electricity → heat)", "Direct electric heating (power-to-heat).",
         "resistive heater", _power(), _carrier("heat"), 0.99, 5000, 20),
    _tpl("gas_boiler", "Gas boiler (gas → heat)", "Burns gas to make heat.",
         "gas boiler", _carrier("gas", True), _carrier("heat"), 0.90, 5000, 20, fuelCost=25, co2=0.20),
    _tpl("methanation", "Methanation (hydrogen → gas)", "Sabatier process converting hydrogen to synthetic gas.",
         "methanation", _carrier("hydrogen"), _carrier("gas"), 0.60, 100000, 25),
]


def _norm(value: Any) -> str:
    return _str(value).strip().lower()


def _unique_name(base: str, taken: set[str]) -> str:
    if base not in taken:
        taken.add(base)
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    out = f"{base}_{i}"
    taken.add(out)
    return out


def default_anchor_bus(model: Model) -> str | None:
    """First electricity-carrier bus, else the first bus."""
    buses = model.get("buses") or []
    elec = next((b for b in buses if _norm(b.get("carrier")) in _POWER_CARRIERS), None)
    chosen = elec if elec is not None else (buses[0] if buses else None)
    name = _str(chosen.get("name")) if chosen else ""
    return name or None


def get_template(template_id: str) -> dict[str, Any] | None:
    return next((t for t in CONVERSION_TEMPLATES if t["id"] == template_id), None)


def build_conversion_fragment(
    template: dict[str, Any], *, anchor_bus: str, p_nom: float, extendable: bool,
    name: str | None, model: Model, discount_rate: float | None = None,
) -> dict[str, Any]:
    """Fragment (``{"sheets": ...}``) adding one conversion technology to ``model``.

    Reuses existing carrier buses / fuel supplies / carriers and emits only
    genuinely-new rows. An extendable conversion carries PyPSA's own cost columns: ``overnight_cost``
    (the template's price), ``fom_cost`` (per modelled horizon: ``fomPct`` % of it per year x the
    workbook's horizon in years), ``lifetime`` and ``discount_rate``, with ``capital_cost`` left
    blank - PyPSA annuitises it. Raises ``ValueError`` if the anchor bus is unknown, or an extendable
    conversion is asked for without a ``discount_rate`` (PyPSA refuses an overnight_cost without one).
    """
    buses = model.get("buses") or []
    anchor = next((b for b in buses if _str(b.get("name")) == anchor_bus), None)
    if anchor is None:
        raise ValueError(f'Anchor bus "{anchor_bus}" not found.')

    taken_bus = {_str(b.get("name")) for b in buses}
    new_buses: list[Row] = []

    def resolve_bus(ep: dict[str, Any]) -> str:
        if ep["role"] == "power":
            return anchor_bus
        carrier = ep["carrier"]
        existing = next((b for b in buses if _norm(b.get("carrier")) == _norm(carrier)), None)
        if existing is not None:
            return _str(existing.get("name"))
        created = next((b for b in new_buses if _norm(b.get("carrier")) == _norm(carrier)), None)
        if created is not None:
            return _str(created.get("name"))
        bus_name = _unique_name(_BUS_PREFIX.get(carrier, carrier), taken_bus)
        row: Row = {"name": bus_name, "carrier": carrier}
        for key in ("x", "y"):
            if anchor.get(key) not in (None, ""):
                row[key] = anchor[key]
        new_buses.append(row)
        return bus_name

    bus0 = resolve_bus(template["input"])
    bus1 = resolve_bus(template["output"])
    bus2 = resolve_bus(template["output2"]) if template.get("output2") else None

    existing_carriers = {_str(c.get("name")) for c in model.get("carriers") or []}
    new_carriers: list[Row] = []

    def ensure_carrier(cname: str, co2: float = 0) -> None:
        if not cname or cname in existing_carriers or any(c["name"] == cname for c in new_carriers):
            return
        row: Row = {"name": cname}
        if co2:
            row["co2_emissions"] = co2
        new_carriers.append(row)

    ensure_carrier(template["linkCarrier"])
    for ep in (template["input"], template["output"], template.get("output2")):
        if ep and ep["role"] == "carrier":
            ensure_carrier(ep["carrier"], (template.get("co2") or 0) if ep.get("fuel") else 0)

    gens = model.get("generators") or []
    taken_gen = {_str(g.get("name")) for g in gens}
    new_gens: list[Row] = []
    if template["input"].get("fuel"):
        fuel_carrier = template["input"]["carrier"]
        has_supply = any(
            _str(g.get("bus")) == bus0 and _norm(g.get("carrier")) == _norm(fuel_carrier) for g in gens
        )
        if not has_supply:
            new_gens.append({
                "name": _unique_name(f"{_BUS_PREFIX.get(fuel_carrier, fuel_carrier)}_supply", taken_gen),
                "bus": bus0, "carrier": fuel_carrier, "p_nom_extendable": True,
                "capital_cost": 0, "marginal_cost": template.get("fuelCost") or 0,
            })

    taken_link = {_str(l.get("name")) for l in model.get("links") or []}
    link: Row = {
        "name": _unique_name((name or "").strip() or template["id"], taken_link),
        "bus0": bus0, "bus1": bus1, "carrier": template["linkCarrier"], "efficiency": template["efficiency"],
    }
    if bus2:
        link["bus2"] = bus2
        link["efficiency2"] = template.get("efficiency2") or 0
    if extendable:
        if discount_rate is None:
            raise ValueError(
                "An extendable conversion needs a discount rate: its overnight_cost is annuitised by PyPSA "
                "with the row's own discount_rate. Set Settings -> Discount rate (or pass discount_rate)."
            )
        from ..pypsa.network.cost_basis import horizon_years

        link["p_nom_extendable"] = True
        link["overnight_cost"] = template["capitalCost"]
        link["fom_cost"] = round(
            float(template["capitalCost"]) * float(template.get("fomPct") or 0.0) / 100.0 * horizon_years(model), 6
        )
        link["discount_rate"] = float(discount_rate)
    else:
        link["p_nom"] = p_nom
    if template.get("marginalCost"):
        link["marginal_cost"] = template["marginalCost"]
    if template.get("lifetime"):
        link["lifetime"] = template["lifetime"]

    sheets: dict[str, list[Row]] = {"links": [link]}
    if new_carriers:
        sheets["carriers"] = new_carriers
    if new_buses:
        sheets["buses"] = new_buses
    if new_gens:
        sheets["generators"] = new_gens
    return {"sheets": sheets}


# ── Forge: fill discount_rate ────────────────────────────────────────────────

#: Component sheets whose rows can carry PyPSA's cost columns.
_COST_SHEETS = ("generators", "storage_units", "stores", "lines", "links", "processes", "transformers")


def fill_discount_rate(model: Model, rate: float, *, overwrite: bool = False) -> dict[str, Any]:
    """Write ``discount_rate`` into every row that carries an ``overnight_cost``.

    PyPSA annuitises ``overnight_cost`` with the ROW's own ``discount_rate`` and refuses a row that has
    none; Ragnarok no longer fills it in at run time. This is the visible action that does: the
    Settings -> Discount rate value lands in the workbook column, where it can be read and edited
    per asset. Rows that already carry a rate are left alone unless ``overwrite``.

    Returns:
        ``{sheets, filled, overwritten, skipped}``; ``sheets`` holds only the changed sheets' rows.

    Raises:
        ValueError: ``rate`` is not a fraction in [0, 1) (a percentage typed as 5 would be 500 %).
    """
    if not 0.0 <= float(rate) < 1.0:
        raise ValueError(f"discount rate must be a fraction in [0, 1) (0.05 = 5 %), got {rate!r}.")
    changed: dict[str, list[Row]] = {}
    filled = overwritten = skipped = 0
    for sheet in _COST_SHEETS:
        rows = _copy_rows(model, sheet)
        touched = False
        for row in rows:
            if _str(row.get("overnight_cost")).strip() in ("", "nan", "NaN", "None"):
                continue
            have = _str(row.get("discount_rate")).strip() not in ("", "nan", "NaN", "None")
            if have and not overwrite:
                skipped += 1
                continue
            row["discount_rate"] = float(rate)
            touched = True
            if have:
                overwritten += 1
            else:
                filled += 1
        if touched:
            changed[sheet] = rows
    return {"sheets": changed, "filled": filled, "overwritten": overwritten, "skipped": skipped}


def clean_placeholder_bounds(model: Model) -> dict[str, Any]:
    """Blank every placeholder bound (a finite 1e9+ value standing for "no limit").

    The visible replacement of the run-time snap to +/-inf: the offending cells are cleared, so the row takes
    PyPSA's own default (``inf`` for ``*_nom_max`` / ``*_sum_max`` / ``lifetime`` / ``v_ang_max``, ``-inf`` for
    ``*_sum_min``). A genuine finite cap is never touched. See :mod:`backend.pypsa.network.placeholders`.

    Returns:
        ``{sheets, cleaned, cells}``; ``sheets`` holds only the changed sheets' rows, ``cells`` lists
        ``{sheet, name, column, value}``.
    """
    from ..pypsa.network.placeholders import find_placeholders

    cells = find_placeholders(model)
    changed: dict[str, list[Row]] = {}
    for sheet, name, column, _value in cells:
        rows = changed.setdefault(sheet, _copy_rows(model, sheet))
        for row in rows:
            if _str(row.get("name")) == name and column in row:
                row.pop(column)
    return {
        "sheets": changed,
        "cleaned": len(cells),
        "cells": [{"sheet": sh, "name": nm, "column": col, "value": val} for sh, nm, col, val in cells],
    }


# ── Forge: bulk adjust / revert ──────────────────────────────────────────────

_SEP = "\x00"


def _cell_key(sheet: str, name: str, attribute: str) -> str:
    return f"{sheet}{_SEP}{name}{_SEP}{attribute}"


def columns_of(rows: list[Row]) -> list[str]:
    keys: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            keys.update(row)
    return sorted(keys)


def row_matches(row: Row, filters: list[dict[str, Any]]) -> bool:
    """Equality match on every filter that has both a column and a value."""
    for f in filters:
        column, value = f.get("column"), f.get("value")
        if not column or value is None or value == "":
            continue
        cell = row.get(column)
        if _str(cell).strip() != str(value).strip():
            return False
    return True


def apply_action(current: float, action: str, amount: float) -> float:
    if action == "multiply":
        return current * (amount / 100)
    if action == "add":
        return current + amount
    return amount  # 'set'


def _copy_rows(model: Model, sheet: str) -> list[Row]:
    return [dict(r) for r in model.get(sheet) or []]


def apply_adjustments(
    model: Model, adjustments: list[dict[str, Any]], baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply adjustments in order onto a copy of ``model`` (later ones see earlier results).

    Returns ``{sheets, changed, perAdjustment, baseline}``; ``sheets`` holds only
    changed sheets. The first time a cell changes its original value goes into
    ``baseline`` (never overwritten; ``None`` = attribute absent originally).
    """
    working: dict[str, list[Row]] = {}
    next_baseline: dict[str, Any] = dict(baseline or {})
    per_adjustment: list[int] = []
    changed = 0
    for adj in adjustments:
        sheet, attribute = adj.get("sheet"), adj.get("attribute")
        if not sheet or not attribute:
            per_adjustment.append(0)
            continue
        rows = working.setdefault(sheet, _copy_rows(model, sheet))
        action, amount = adj.get("action", "set"), float(adj.get("amount", 0))
        count = 0
        for row in rows:
            if not row_matches(row, adj.get("filters") or []):
                continue
            current = _js_number(row.get(attribute, _MISSING))
            finite = math.isfinite(current)
            if action != "set" and not finite:
                continue
            nxt = apply_action(current if finite else 0.0, action, amount)
            if nxt != current or not finite:
                key = _cell_key(sheet, _str(row.get("name")), attribute)
                if key not in next_baseline:
                    next_baseline[key] = row.get(attribute)  # absent -> None
                row[attribute] = int(nxt) if float(nxt).is_integer() and abs(nxt) < 1e15 else nxt
                count += 1
        per_adjustment.append(count)
        changed += count
    touched: dict[str, list[Row]] = {}
    for i, adj in enumerate(adjustments):
        sheet = adj.get("sheet")
        if per_adjustment[i] > 0 and sheet in working:
            touched[sheet] = working[sheet]
    return {"sheets": touched, "changed": changed, "perAdjustment": per_adjustment, "baseline": next_baseline}


def revert_adjustments(
    model: Model, adjustments: list[dict[str, Any]], baseline: dict[str, Any],
) -> dict[str, Any]:
    """Restore targeted cells to their original value from ``baseline`` (idempotent)."""
    working: dict[str, list[Row]] = {}
    changed_sheets: list[str] = []
    reverted = 0
    for adj in adjustments:
        sheet, attribute = adj.get("sheet"), adj.get("attribute")
        if not sheet or not attribute:
            continue
        rows = working.setdefault(sheet, _copy_rows(model, sheet))
        for row in rows:
            if not row_matches(row, adj.get("filters") or []):
                continue
            key = _cell_key(sheet, _str(row.get("name")), attribute)
            if key not in baseline:
                continue
            orig = baseline[key]
            if orig is None:
                if attribute in row:
                    del row[attribute]
                    reverted += 1
                    if sheet not in changed_sheets:
                        changed_sheets.append(sheet)
            elif row.get(attribute, _MISSING) != orig:
                row[attribute] = orig
                reverted += 1
                if sheet not in changed_sheets:
                    changed_sheets.append(sheet)
    return {"sheets": {s: working[s] for s in changed_sheets}, "reverted": reverted}


def match_count(model: Model, sheet: str, filters: list[dict[str, Any]]) -> int:
    return sum(1 for r in model.get(sheet) or [] if row_matches(r, filters))
