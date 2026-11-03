"""The fuel-costs module's inputs: the fuel-price series, the flat carrier price and the variable O&M rows.

Three visible inputs, all in the workbook:

* ``RAGNAROK_FuelPrices`` - a wide TEMPORAL sheet: ``snapshot`` plus one column per fuel carrier, values in
  currency/MWh_thermal. A blank cell is "no price for that carrier at that snapshot" (the unit keeps the
  workbook's own marginal cost there, and the run reports it).
* the ``carriers`` column ``fuel_cost_thermal`` (written by the fuel-price importer): a CONSTANT price for a
  carrier that has no column in the sheet.
* ``RAGNAROK_VariableOM`` - static rows ``{component, name, vom}`` or ``{component, carrier, vom}``,
  ``vom`` in currency/MWh of electric output; a name row beats a carrier row; no row = 0 (reported).

Everything here is pure (model rows in, frames out). Malformed input raises ``HTTPException(400)``: a price that is
mis-read must stop the run, not quietly change the merit order.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from fastapi import HTTPException

from backend.pypsa.network.snapshots import parse_snapshot_labels

SHEET_PRICES = "RAGNAROK_FuelPrices"
SHEET_VOM = "RAGNAROK_VariableOM"
FLAT_COLUMN = "fuel_cost_thermal"
VOM_COMPONENTS = ("Generator", "Link")
_INDEX = "snapshot"


def _blank(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, float) and math.isnan(value))


def _number(value: Any) -> float | None:
    """The finite float of ``value``, ``None`` for blank / non-numeric / non-finite / bool."""
    if _blank(value) or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _rows(model: dict[str, Any] | None, sheet: str) -> list[dict[str, Any]]:
    return [r for r in ((model or {}).get(sheet) or []) if isinstance(r, dict)]


# ── the price series ───────────────────────────────────────────────────────────────

def read_price_sheet(model: dict[str, Any] | None) -> pd.DataFrame:
    """``RAGNAROK_FuelPrices`` as a frame: index = snapshot labels (datetimes when they parse), columns = carriers.

    Blank cells are ``NaN``. Raises ``HTTPException(400)`` on a row without a label, a duplicate label or a
    non-numeric price. Negative prices are legitimate (a gas glut) and kept.
    """
    rows = _rows(model, SHEET_PRICES)
    if not rows:
        return pd.DataFrame()
    carriers: list[str] = []
    for r in rows:
        for k in r:
            if k != _INDEX and str(k).strip() and k not in carriers:
                carriers.append(k)
    labels: list[str] = []
    data: dict[str, list[float]] = {c: [] for c in carriers}
    for i, r in enumerate(rows):
        label = r.get(_INDEX)
        if _blank(label):
            raise HTTPException(status_code=400, detail=f"{SHEET_PRICES}: row {i + 1} has no `{_INDEX}` label.")
        labels.append(str(label))
        for c in carriers:
            v = r.get(c)
            if _blank(v):
                data[c].append(float("nan"))
                continue
            x = _number(v)
            if x is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"{SHEET_PRICES}: price of '{c}' at {label} is not a finite number ({v!r}).",
                )
            data[c].append(x)
    try:
        index: pd.Index = parse_snapshot_labels(labels)
    except Exception:  # noqa: BLE001 - non-datetime labels stay text
        index = pd.Index(labels, dtype="object")
    if index.has_duplicates:
        raise HTTPException(status_code=400, detail=f"{SHEET_PRICES}: duplicate `{_INDEX}` labels (e.g. {index[index.duplicated()][0]}).")
    return pd.DataFrame(data, index=index)


def flat_prices(model: dict[str, Any] | None) -> dict[str, float]:
    """``carriers.fuel_cost_thermal`` per carrier (currency/MWh_thermal); blank / non-numeric rows are left out."""
    out: dict[str, float] = {}
    for r in _rows(model, "carriers"):
        name = r.get("name")
        x = _number(r.get(FLAT_COLUMN))
        if isinstance(name, str) and name and x is not None:
            out[name] = x
    return out


def align_to_snapshots(frame: pd.DataFrame, snapshots: pd.Index) -> pd.DataFrame:
    """``frame`` on the run's snapshots (``NaN`` where the sheet has no row).

    A pathway run indexes snapshots by ``(period, timestamp)``: the timestamp level is matched, so one price
    row serves every period that carries that timestamp.
    """
    if frame.empty:
        return pd.DataFrame(index=snapshots)
    idx = snapshots.get_level_values(-1) if isinstance(snapshots, pd.MultiIndex) else snapshots
    if isinstance(frame.index, pd.DatetimeIndex) and not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = parse_snapshot_labels([str(v) for v in idx])
        except Exception:  # noqa: BLE001 - labels that are not dates cannot match a dated sheet
            return pd.DataFrame(float("nan"), index=snapshots, columns=frame.columns)
    elif not isinstance(frame.index, pd.DatetimeIndex) and isinstance(idx, pd.DatetimeIndex):
        frame = frame.copy()
        frame.index = frame.index.astype(str)
        idx = pd.Index([str(v) for v in idx])
    out = frame.reindex(idx)
    out.index = snapshots
    return out


@dataclass(frozen=True)
class PriceSet:
    """Prices on the run's snapshots (currency/MWh_thermal; ``NaN`` = none) and where each carrier's came from."""

    frame: pd.DataFrame
    source: dict[str, str] = field(default_factory=dict)  # carrier -> "series" | "flat"


def price_set(model: dict[str, Any] | None, snapshots: pd.Index) -> PriceSet:
    """Per-snapshot price of every priced carrier. A carrier with a column in the sheet takes the sheet (blank = no
    price, NOT the flat value); a carrier without one takes its flat ``fuel_cost_thermal`` as a constant series."""
    sheet = read_price_sheet(model)
    cols: dict[str, pd.Series] = {}
    source: dict[str, str] = {}
    if not sheet.empty:
        aligned = align_to_snapshots(sheet, snapshots)
        for c in aligned.columns:
            cols[str(c)] = aligned[c].astype(float)
            source[str(c)] = "series"
    for c, value in flat_prices(model).items():
        if c in cols:
            continue
        cols[c] = pd.Series(float(value), index=snapshots, dtype=float)
        source[c] = "flat"
    return PriceSet(pd.DataFrame(cols, index=snapshots, dtype=float), source)


def priced_carriers(model: dict[str, Any] | None) -> set[str]:
    """Carriers that carry a price somewhere in the workbook (a sheet column with a value, or a flat price)."""
    sheet = read_price_sheet(model)
    out = {str(c) for c in sheet.columns if sheet[c].notna().any()} if not sheet.empty else set()
    sheet_columns = {str(c) for c in sheet.columns}
    out |= {c for c in flat_prices(model) if c not in sheet_columns}
    return out


# ── variable O&M ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VomTable:
    """``vom`` (currency/MWh_el) by ``(component, name)`` and by ``(component, carrier)``."""

    by_name: dict[tuple[str, str], float] = field(default_factory=dict)
    by_carrier: dict[tuple[str, str], float] = field(default_factory=dict)

    def lookup(self, component: str, name: str, carrier: str) -> tuple[float | None, str]:
        """``(vom, source)``: the name row, else the carrier row, else ``(None, "none")``."""
        if (component, name) in self.by_name:
            return self.by_name[(component, name)], "name"
        if (component, carrier) in self.by_carrier:
            return self.by_carrier[(component, carrier)], "carrier"
        return None, "none"


def read_vom(model: dict[str, Any] | None) -> VomTable:
    """The ``RAGNAROK_VariableOM`` rows. Raises ``HTTPException(400)`` naming every row that cannot be read."""
    by_name: dict[tuple[str, str], float] = {}
    by_carrier: dict[tuple[str, str], float] = {}
    problems: list[str] = []
    for i, row in enumerate(_rows(model, SHEET_VOM)):
        comp = str(row.get("component") or "").strip()
        name = str(row.get("name") or "").strip()
        carrier = str(row.get("carrier") or "").strip()
        vom = _number(row.get("vom"))
        if not (comp or name or carrier) and _blank(row.get("vom")):
            continue
        if comp not in VOM_COMPONENTS:
            problems.append(f"row {i + 1}: component must be one of {', '.join(VOM_COMPONENTS)}, got {comp!r}")
        elif not (name or carrier):
            problems.append(f"row {i + 1}: give a name or a carrier")
        elif vom is None or vom < 0:
            problems.append(f"row {i + 1}: vom must be a finite number >= 0 (currency/MWh of electric output)")
        elif name:  # a name row wins over a carrier row; the carrier cell of a name row is ignored
            by_name[(comp, name)] = vom
        else:
            by_carrier[(comp, carrier)] = vom
    if problems:
        raise HTTPException(status_code=400, detail=f"{SHEET_VOM}: " + "; ".join(problems))
    return VomTable(by_name, by_carrier)


# ── is the module on? ───────────────────────────────────────────────────────────────

def has_inputs(model: dict[str, Any] | None) -> bool:
    """True when the workbook carries a price sheet with rows, a VOM sheet with rows, or any flat carrier price."""
    return bool(_rows(model, SHEET_PRICES) or _rows(model, SHEET_VOM) or flat_prices(model))


def is_enabled(model: dict[str, Any] | None, options: dict[str, Any] | None) -> bool:
    """``options.fuelCosts.enabled`` when it is a boolean, else on exactly when the model has an input (so a model
    without any is untouched)."""
    block = (options or {}).get("fuelCosts")
    if isinstance(block, dict) and isinstance(block.get("enabled"), bool):
        return bool(block["enabled"])
    return has_inputs(model)


# ── a transformed time axis ─────────────────────────────────────────────────────────

def realign(rows: list[dict[str, Any]], new_labels: list[str], new_index: pd.DatetimeIndex, *, mode: str) -> list[dict[str, Any]]:
    """The price sheet re-expressed on a transformed time axis (Forge slice / merge / temporal reduction).

    ``mode="filter"`` (a slice, a merge): keep the rows whose snapshot is still on the axis.
    ``mode="blocks"`` (resample, downsample, segment): each new snapshot takes the MEAN of the non-blank prices of the original
    snapshots it now stands for (from it up to the next kept snapshot); a block with no price stays blank. Rows are emitted at
    ``new_labels`` (the reduced ``snapshots`` sheet's spelling), in order.
    """
    prices = read_price_sheet({SHEET_PRICES: rows})
    if prices.empty or not isinstance(prices.index, pd.DatetimeIndex) or len(new_index) != len(new_labels):
        return rows
    if mode == "filter":
        keep = prices.reindex(new_index).dropna(how="all")
        label_of = dict(zip(new_index, new_labels))
        return [{_INDEX: label_of[t], **{c: (None if pd.isna(v) else float(v)) for c, v in r.items()}} for t, r in keep.iterrows()]
    old = prices.sort_index()
    pos = pd.Series(new_index.searchsorted(old.index, side="right") - 1, index=old.index)
    out: list[dict[str, Any]] = []
    for k, block in old[pos >= 0].groupby(pos[pos >= 0]):
        cells: dict[str, Any] = {_INDEX: new_labels[int(k)]}
        for c in old.columns:
            col = block[c].dropna()
            cells[c] = float(col.mean()) if len(col) else None
        if any(v is not None for c, v in cells.items() if c != _INDEX):
            out.append(cells)
    return out
