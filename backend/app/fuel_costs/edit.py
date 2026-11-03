"""Edits of the fuel-costs module's inputs: the price sheet, the flat carrier price, the VOM rows and the scenario rows.

Pure functions (model rows in, rows out) behind ``POST /api/fuel-costs/{price,vom,scenario-price}/{set,remove}``. Every
result is re-read with the module's own readers (:func:`read_price_sheet`, :func:`read_vom`, :func:`read_price_scenarios`),
so what is written is exactly what a run will accept; anything they would refuse is a ``HTTPException(400)`` here, with a
sentence that names the valid choices. Nothing in this file touches a store.

A price has two homes, and the module reads them in a fixed order (see :func:`.inputs.price_set`): a carrier with a column
in ``RAGNAROK_FuelPrices`` takes the sheet, a carrier without one takes ``carriers.fuel_cost_thermal``. So a constant
is written to the carriers column and a series to the sheet; replacing one by the other is refused until the first is
removed, because the sheet would otherwise silently win.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import HTTPException

from backend.pypsa.network.snapshots import parse_snapshot_labels

from ..importers.databases.fuel_prices import native_unit, to_thermal
from .inputs import (
    _INDEX,
    FLAT_COLUMN,
    SHEET_PRICE_SCENARIOS,
    SHEET_PRICES,
    SHEET_VOM,
    VOM_COMPONENTS,
    _blank,
    _number,
    _rows,
    flat_prices,
    priced_carriers,
    read_price_scenarios,
    read_price_sheet,
    read_vom,
)


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _few(names: list[str], n: int = 8) -> str:
    shown = ", ".join(repr(x) for x in names[:n])
    return shown + (f" ... ({len(names)} in all)" if len(names) > n else "")


# ── the model's vocabulary ───────────────────────────────────────────────────────────

def known_carriers(model: dict[str, Any]) -> list[str]:
    """Carrier names of the ``carriers`` sheet plus every carrier a Generator / Link row uses."""
    out: dict[str, None] = {}
    for sheet in ("carriers", "generators", "links"):
        for r in _rows(model, sheet):
            c = r.get("name") if sheet == "carriers" else r.get("carrier")
            if isinstance(c, str) and c.strip():
                out[c.strip()] = None
    return sorted(out)


def check_carrier(model: dict[str, Any], carrier: str) -> str:
    carrier = (carrier or "").strip()
    if not carrier:
        raise _bad("give a carrier (the name used in the carriers sheet, e.g. 'gas').")
    known = known_carriers(model)
    if carrier not in known:
        raise _bad(f"unknown carrier {carrier!r}; valid: {_few(known)}. A price is matched by the exact carrier name, so a misspelt one would never apply.")
    return carrier


class _Axis:
    """The model's snapshot axis: label spelling and position of each timestamp."""

    def __init__(self, model: dict[str, Any]) -> None:
        labels = [str(r["snapshot"]) for r in _rows(model, "snapshots") if not _blank(r.get("snapshot"))]
        self.labels = labels
        try:
            self.index: pd.Index = parse_snapshot_labels(labels) if labels else pd.Index([])
        except Exception:  # noqa: BLE001 - text labels
            self.index = pd.Index(labels, dtype="object")
        self.dated = isinstance(self.index, pd.DatetimeIndex)
        self.position = {k: i for i, k in enumerate(self.index)}
        self.label_of = dict(zip(self.index, labels))

    def key(self, label: Any) -> Any:
        """The comparable key of one label (a Timestamp for a dated axis, else its text)."""
        text = str(label).strip()
        if not self.dated:
            return text
        try:
            return parse_snapshot_labels([text])[0]
        except Exception as exc:
            raise _bad(f"snapshot {text!r} is not a date/time; the model's snapshots are dated (e.g. {self.labels[0]!r}).") from exc

    def known(self) -> bool:
        return bool(self.labels)

    def span(self) -> str:
        return f"{self.labels[0]!r} to {self.labels[-1]!r} ({len(self.labels)} snapshots)"


# ── prices ──────────────────────────────────────────────────────────────────────────────

def convert_price(carrier: str, value: Any, unit: str) -> float:
    """``value`` as currency/MWh_thermal (``unit`` = ``MWh_th`` or the carrier's native unit)."""
    x = _number(value)
    if x is None:
        raise _bad(f"price must be a finite number, got {value!r} (currency per {unit}).")
    try:
        return to_thermal(carrier, x, unit or "MWh_th")
    except ValueError as exc:
        raise _bad(str(exc)) from exc


def price_column_cells(price_rows: list[dict[str, Any]], carrier: str) -> int:
    return sum(1 for r in price_rows if not _blank(r.get(carrier)))


def set_flat_price(model: dict[str, Any], price_rows: list[dict[str, Any]], carrier: str, thermal: float) -> list[dict[str, Any]]:
    """The ``carriers`` rows with ``fuel_cost_thermal`` of ``carrier`` set (a row is added for a carrier only used by units)."""
    sheet_cols = {k for r in price_rows for k in r if k != _INDEX}
    if carrier in sheet_cols:
        raise _bad(
            f"carrier {carrier!r} already has a price series in {SHEET_PRICES} ({price_column_cells(price_rows, carrier)} values), and a series "
            f"supersedes the constant. Remove it first (remove=true) or pass series=[...] to replace it."
        )
    rows = [dict(r) for r in _rows(model, "carriers")]
    for r in rows:
        if r.get("name") == carrier:
            r[FLAT_COLUMN] = thermal
            break
    else:
        rows.append({"name": carrier, FLAT_COLUMN: thermal})
    return rows


def _series_points(series: Any) -> list[tuple[str, Any]]:
    if not isinstance(series, list) or not series:
        raise _bad("series must be a non-empty list of {snapshot, price} (price in currency per unit).")
    out: list[tuple[str, Any]] = []
    for i, p in enumerate(series):
        if not isinstance(p, dict) or _blank(p.get("snapshot")) or "price" not in p:
            raise _bad(f"series[{i}] must be {{snapshot, price}}, got {p!r}.")
        out.append((str(p["snapshot"]), p["price"]))
    return out


def set_price_series(
    model: dict[str, Any], price_rows: list[dict[str, Any]], carrier: str, series: Any, unit: str, merge: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The price sheet with the ``carrier`` column set from ``series`` (``[{snapshot, price}]``).

    ``merge=False`` makes the column exactly the given snapshots (the others become blank: "no price"); ``merge=True`` overwrites
    only the given snapshots. Snapshot labels must be on the model's axis (a price is matched to a snapshot exactly, with no
    carry-forward), and are written in the spelling of the model's ``snapshots`` sheet.
    """
    axis = _Axis(model)
    points = _series_points(series)
    values: dict[Any, float] = {}
    given_label: dict[Any, str] = {}
    off_axis: list[str] = []
    for label, raw in points:
        key = axis.key(label)
        if axis.known() and key not in axis.position:
            off_axis.append(label)
            continue
        if key in values:
            raise _bad(f"snapshot {label!r} appears twice in series.")
        values[key] = convert_price(carrier, raw, unit)
        given_label[key] = label
    if off_axis:
        raise _bad(f"{len(off_axis)} snapshot(s) are not on the model's axis (e.g. {_few(off_axis, 3)}); the model's snapshots run {axis.span()}. "
                   "A price applies only at the snapshot it is stated for.")

    carriers_in_sheet: list[str] = []
    for r in price_rows:
        for k in r:
            if k != _INDEX and k not in carriers_in_sheet:
                carriers_in_sheet.append(k)
    if carrier not in carriers_in_sheet:
        carriers_in_sheet.append(carrier)

    by_key: dict[Any, dict[str, Any]] = {}
    for r in price_rows:
        if _blank(r.get(_INDEX)):
            continue
        key = axis.key(r[_INDEX]) if axis.dated else str(r[_INDEX])
        by_key[key] = {c: r.get(c) for c in carriers_in_sheet}
        by_key[key][_INDEX] = r[_INDEX]
    if not merge:
        for cells in by_key.values():
            cells[carrier] = None
    for key, v in values.items():
        cells = by_key.setdefault(key, {c: None for c in carriers_in_sheet})
        cells[_INDEX] = axis.label_of.get(key, cells.get(_INDEX) or given_label[key])
        cells[carrier] = v

    def order(item: tuple[Any, dict[str, Any]]) -> tuple[int, int]:
        pos = axis.position.get(item[0])
        return (0, pos) if pos is not None else (1, 0)

    rows: list[dict[str, Any]] = []
    for _key, cells in sorted(by_key.items(), key=order):
        if all(_blank(cells.get(c)) for c in carriers_in_sheet):
            continue  # a snapshot with no price at all is not a row
        rows.append({_INDEX: cells[_INDEX], **{c: (None if _blank(cells.get(c)) else cells[c]) for c in carriers_in_sheet}})
    read_price_sheet({SHEET_PRICES: rows})  # the module's own reader: 400 on anything it would refuse
    arr = pd.Series(list(values.values()), dtype=float)
    info = {"snapshots": len(values), "min": float(arr.min()), "max": float(arr.max()), "mean": float(arr.mean()),
            "sheetRows": len(rows), "mode": "merge" if merge else "replace"}
    return rows, info


def remove_price(model: dict[str, Any], price_rows: list[dict[str, Any]], carrier: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None, dict[str, bool]]:
    """``(price rows, carriers rows or None, what was removed)``: the carrier's sheet column and its flat price are both dropped."""
    had_series = any(carrier in r for r in price_rows)
    flat = flat_prices(model)
    had_flat = carrier in flat
    if not had_series and not had_flat:
        priced = sorted(priced_carriers({**model, SHEET_PRICES: price_rows}))
        raise _bad(f"carrier {carrier!r} has no fuel price to remove; priced carriers: {_few(priced) if priced else 'none'}.")
    new_rows: list[dict[str, Any]] = []
    for r in price_rows:
        kept = {k: v for k, v in r.items() if k != carrier}
        if any(not _blank(v) for k, v in kept.items() if k != _INDEX):
            new_rows.append(kept)
    carriers_rows = None
    if had_flat:
        carriers_rows = [{k: v for k, v in dict(r).items() if not (r.get("name") == carrier and k == FLAT_COLUMN)} for r in _rows(model, "carriers")]
    return new_rows, carriers_rows, {"series": had_series, "flat": had_flat}


# ── variable O&M ────────────────────────────────────────────────────────────────────

def _vom_key(component: str, name: str, carrier: str) -> tuple[str, str, str]:
    return (component, "name", name) if name else (component, "carrier", carrier)


def _vom_target(model: dict[str, Any], component: str, name: str, carrier: str, *, must_exist: bool) -> tuple[str, str, str]:
    component = (component or "").strip()
    name, carrier = (name or "").strip(), (carrier or "").strip()
    if component not in VOM_COMPONENTS:
        raise _bad(f"component must be one of {', '.join(VOM_COMPONENTS)}, got {component!r}.")
    if bool(name) == bool(carrier):
        raise _bad("give either name (one unit) or carrier (every unit of that carrier), not both and not neither; a name row beats a carrier row.")
    if must_exist:
        units = _rows(model, "generators" if component == "Generator" else "links")
        if name:
            names = sorted({str(u.get("name")) for u in units if u.get("name")})
            if name not in names:
                raise _bad(f"no {component} named {name!r}; valid: {_few(names)}.")
        else:
            carriers = sorted({str(u.get("carrier")) for u in units if u.get("carrier")})
            if carrier not in carriers:
                raise _bad(f"no {component} has carrier {carrier!r}; carriers in use: {_few(carriers)}.")
    return _vom_key(component, name, carrier)


def _row_vom_key(r: dict[str, Any]) -> tuple[str, str, str]:
    name = str(r.get("name") or "").strip()
    return _vom_key(str(r.get("component") or "").strip(), name, str(r.get("carrier") or "").strip())


def set_vom(model: dict[str, Any], component: str, name: str | None, carrier: str | None, vom: Any) -> list[dict[str, Any]]:
    """The VOM rows with the row of ``(component, name | carrier)`` set to ``vom`` (currency/MWh of electric output)."""
    key = _vom_target(model, component, name or "", carrier or "", must_exist=True)
    x = _number(vom)
    if x is None or x < 0:
        raise _bad(f"vom must be a finite number >= 0 (currency per MWh of electric output), got {vom!r}.")
    rows = [dict(r) for r in _rows(model, SHEET_VOM) if _row_vom_key(r) != key]
    rows.append({"component": key[0], **({"name": key[2]} if key[1] == "name" else {"carrier": key[2]}), "vom": x})
    read_vom({SHEET_VOM: rows})
    return rows


def remove_vom(model: dict[str, Any], component: str, name: str | None, carrier: str | None) -> list[dict[str, Any]]:
    key = _vom_target(model, component, name or "", carrier or "", must_exist=False)
    existing = _rows(model, SHEET_VOM)
    rows = [dict(r) for r in existing if _row_vom_key(r) != key]
    if len(rows) == len(existing):
        have = [f"{k[0]} {k[2]}" for k in sorted({_row_vom_key(r) for r in existing})]
        raise _bad(f"no VOM row for {key[0]} {key[1]} {key[2]!r}; rows: {_few(have) if have else 'none'}.")
    return rows


# ── scenario prices ─────────────────────────────────────────────────────────────────

def _scenario_target(model: dict[str, Any], scenario: str, carrier: str, snapshot: Any) -> tuple[str, str, Any, str]:
    scenario = (scenario or "").strip()
    if not scenario:
        raise _bad("give a scenario (the scenario name used in options.stochasticConfig).")
    carrier = check_carrier(model, carrier)
    label = "" if _blank(snapshot) else str(snapshot).strip()
    key: Any = ""
    if label:
        axis = _Axis(model)
        key = axis.key(label)
        if axis.known() and key not in axis.position:
            raise _bad(f"snapshot {label!r} is not on the model's axis; the model's snapshots run {axis.span()}. Leave snapshot blank for every snapshot.")
        label = axis.label_of.get(key, label)
    return scenario, carrier, key, label


def _scenario_row_key(r: dict[str, Any], model: dict[str, Any]) -> tuple[str, str, Any]:
    snap = r.get("snapshot")
    key: Any = ""
    if not _blank(snap):
        try:
            key = _Axis(model).key(snap)
        except HTTPException:
            key = str(snap)
    return (str(r.get("scenario") or "").strip(), str(r.get("carrier") or "").strip(), key)


def set_scenario_price(
    model: dict[str, Any], scenario: str, carrier: str, snapshot: Any, price: Any, multiplier: Any, unit: str = "MWh_th",
) -> list[dict[str, Any]]:
    """The ``RAGNAROK_FuelPriceScenarios`` rows with one ``(scenario, carrier, snapshot)`` row set; ``price`` is
    currency per ``unit`` and stored as currency/MWh_thermal, ``multiplier`` scales the carrier's base price (price first)."""
    sc, car, key, label = _scenario_target(model, scenario, carrier, snapshot)
    if _blank(price) and _blank(multiplier):
        raise _bad("give a price (replaces the carrier's price in that scenario) or a multiplier (scales it), or both.")
    row: dict[str, Any] = {"scenario": sc, "carrier": car, "snapshot": label}
    if not _blank(price):
        row["price"] = convert_price(car, price, unit)
    if not _blank(multiplier):
        m = _number(multiplier)
        if m is None or m < 0:
            raise _bad(f"multiplier must be a finite number >= 0 (1.2 = +20 %), got {multiplier!r}.")
        row["multiplier"] = m
    rows = [dict(r) for r in _rows(model, SHEET_PRICE_SCENARIOS) if _scenario_row_key(r, model) != (sc, car, key)]
    rows.append(row)
    read_price_scenarios({SHEET_PRICE_SCENARIOS: rows})
    return rows


def remove_scenario_price(model: dict[str, Any], scenario: str, carrier: str, snapshot: Any) -> list[dict[str, Any]]:
    sc, car, key, _label = _scenario_target(model, scenario, carrier, snapshot)
    existing = _rows(model, SHEET_PRICE_SCENARIOS)
    rows = [dict(r) for r in existing if _scenario_row_key(r, model) != (sc, car, key)]
    if len(rows) == len(existing):
        have = sorted({f"{r.get('scenario')}/{r.get('carrier')}" for r in existing})
        raise _bad(f"no scenario price row for scenario {sc!r}, carrier {car!r}"
                   + (f", snapshot {snapshot!r}" if not _blank(snapshot) else " (all snapshots)")
                   + f"; rows: {_few(have) if have else 'none'}.")
    return rows


# ── a read of the inputs ────────────────────────────────────────────────────────────

_SUMMARY_ROWS = 200   # VOM / scenario rows returned by the read; the price list is one entry per carrier


def inputs_summary(model: dict[str, Any]) -> dict[str, Any]:
    """What the module will read: per carrier its price (series statistics or the flat value), the VOM rows and the scenario rows."""
    sheet = read_price_sheet(model)
    flat = flat_prices(model)
    prices: list[dict[str, Any]] = []
    for c in sheet.columns:
        col = sheet[c].dropna()
        prices.append({
            "carrier": str(c), "source": "series", "snapshots": len(col),
            "first": str(col.index[0]) if len(col) else None, "last": str(col.index[-1]) if len(col) else None,
            "min": float(col.min()) if len(col) else None, "max": float(col.max()) if len(col) else None,
            "mean": float(col.mean()) if len(col) else None,
            **({"flatIgnored": flat[str(c)]} if str(c) in flat else {}),
        })
    sheet_cols = {str(c) for c in sheet.columns}
    prices += [{"carrier": c, "source": "flat", "value": v} for c, v in sorted(flat.items()) if c not in sheet_cols]
    vom = [{k: v for k, v in r.items() if not _blank(v)} for r in _rows(model, SHEET_VOM)]
    scen = [{k: v for k, v in r.items() if not _blank(v)} for r in _rows(model, SHEET_PRICE_SCENARIOS)]
    read_vom(model)
    read_price_scenarios(model)
    notes: list[str] = []
    for label, rows in (("vom", vom), ("scenarioPrices", scen)):
        if len(rows) > _SUMMARY_ROWS:
            notes.append(f"{label}: showing {_SUMMARY_ROWS} of {len(rows)} rows; read the sheet with get_sheet_page for the rest.")
    vom, scen = vom[:_SUMMARY_ROWS], scen[:_SUMMARY_ROWS]
    native = {c: u for c in ("gas", "coal", "oil", "biomass", "nuclear") if (u := native_unit(c))}
    return {
        "sheets": {"prices": SHEET_PRICES, "vom": SHEET_VOM, "scenarioPrices": SHEET_PRICE_SCENARIOS, "flat": f"carriers.{FLAT_COLUMN}"},
        "units": {"price": "currency/MWh_thermal", "vom": "currency/MWh_el"},
        "nativeUnits": native,
        "prices": prices, "vom": vom, "scenarioPrices": scen,
        "active": bool(prices or vom or scen),
        **({"truncated": " ".join(notes)} if notes else {}),
    }


__all__ = [
    "check_carrier", "convert_price", "inputs_summary", "known_carriers", "remove_price", "remove_scenario_price", "remove_vom",
    "set_flat_price", "set_price_series", "set_scenario_price", "set_vom",
]
