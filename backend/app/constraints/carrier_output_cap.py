"""Per-snapshot fleet output limits: ``RAGNAROK_CarrierOutputCap`` (<=) and ``RAGNAROK_CarrierOutputFloor`` (>=) as declared linopy constraints.

Two wide TEMPORAL sheets of the same shape: first column ``snapshot`` (the labels of the ``snapshots`` sheet), then one
column per GROUP of generators, values in MW. A blank cell is no limit at that hour. For every snapshot ``t`` and group
``k`` with a value, the group's summed dispatch is bounded; the units stay free to share it by merit order (this is not
a per-unit ``p_max_pu`` / ``p_min_pu``).

A column names its group in one of two ways:

* a carrier name (``gas``): the generators of that carrier, as before;
* a selector ``column=value`` joined by ``&``, a value's alternatives by ``|`` (``fuel=lng``, ``fuel=coal&region=서울경기``,
  ``carrier=ccgt|lng_st``): the generators whose column holds the value. A column a generator does not carry (or leaves
  blank) is read from its bus, so a ``region`` written on the buses groups the generators on them.

Algorithm:
    $$\\sum_{g \\in G_k} p_{g,t} \\le \\bar P_{k,t} \\quad\\text{(cap)}, \\qquad \\sum_{g \\in G_k} p_{g,t} \\ge \\underline P_{k,t} \\quad\\text{(floor)} \\qquad \\forall (k,t)\\ \\text{with a value}$$
    ASCII: sum_{g in group k} p[g,t] <= cap[k,t];  sum_{g in group k} p[g,t] >= floor[k,t]
    where p_{g,t} is the Generator-p dispatch of generator g in snapshot t (MW) and the limit is the sheet cell (MW).
    Power, not energy: no snapshot weighting enters. The linopy constraints are ``carrier_output_cap_<column>`` and
    ``carrier_output_floor_<column>`` (one per column, over the hours it holds a value); their duals are reported in
    ``appliedConstraints``.

Run paths: single period (plain optimise, security-constrained) and rolling horizon - the hook is called once per
window and the sheets are read at the window's own snapshots, so nothing is apportioned. Multi-investment-period
(pathway) and stochastic runs are refused (the dispatch variable carries a period / scenario index the sheets have no
column for), as are power-flow and contingency modes, which solve no LP and would silently ignore the limits.
A floor the group cannot reach (above what its generators can give that hour) makes the LP infeasible: it is the
sheet's to respect.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

from backend.app import module_hooks as mh
from backend.pypsa.network.snapshots import parse_snapshot_labels

SHEET = "RAGNAROK_CarrierOutputCap"
FLOOR_SHEET = "RAGNAROK_CarrierOutputFloor"
SHEETS = (SHEET, FLOOR_SHEET)
CONSTRAINT_PREFIX = "carrier_output_cap_"
FLOOR_PREFIX = "carrier_output_floor_"
_PREFIX = {SHEET: CONSTRAINT_PREFIX, FLOOR_SHEET: FLOOR_PREFIX}
_WORD = {SHEET: "cap", FLOOR_SHEET: "floor"}
_INDEX = "snapshot"


def _blank(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, float) and math.isnan(value))


def read_caps(model: dict[str, Any] | None, sheet: str = SHEET) -> pd.DataFrame:
    """A limit sheet as a frame: index = snapshot labels (parsed to datetimes when they are), columns = groups, MW.

    Blank cells are ``NaN`` (no cap). Raises ``HTTPException(400)`` on a non-numeric or negative cap, a duplicate
    snapshot label, or a row without a label: a cap that is mis-read must stop the run, not loosen it.
    """
    rows = [r for r in ((model or {}).get(sheet) or []) if isinstance(r, dict)]
    if not rows:
        return pd.DataFrame()
    word = _WORD.get(sheet, "cap")
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
            raise HTTPException(status_code=400, detail=f"{sheet}: row {i + 1} has no `{_INDEX}` label.")
        labels.append(str(label))
        for c in carriers:
            v = r.get(c)
            if _blank(v):
                data[c].append(float("nan"))
                continue
            try:
                x = float(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{sheet}: {word} for '{c}' at {label} is not a number ({v!r}).") from None
            if not math.isfinite(x) or x < 0:
                raise HTTPException(status_code=400, detail=f"{sheet}: {word} for '{c}' at {label} must be a finite MW >= 0, got {v!r}.")
            data[c].append(x)
    try:
        index: pd.Index = parse_snapshot_labels(labels)
    except Exception:  # noqa: BLE001 - non-datetime labels: keep them as text
        index = pd.Index(labels, dtype="object")
    if index.has_duplicates:
        raise HTTPException(status_code=400, detail=f"{sheet}: duplicate `{_INDEX}` labels (e.g. {index[index.duplicated()][0]}).")
    return pd.DataFrame(data, index=index)


def has_caps(model: dict[str, Any] | None, sheets: tuple[str, ...] = SHEETS) -> bool:
    """True when a limit sheet holds at least one non-blank value."""
    return any(not _blank(v) for sh in sheets for r in ((model or {}).get(sh) or []) if isinstance(r, dict)
               for k, v in r.items() if k != _INDEX)


def parse_group(key: str) -> list[tuple[str, set[str]]] | None:
    """A selector column ``col=a|b&col2=c`` as ``[(col, {a, b}), (col2, {c})]``; ``None`` for a plain carrier name."""
    if "=" not in key:
        return None
    out: list[tuple[str, set[str]]] = []
    for part in key.split("&"):
        col, _, vals = part.partition("=")
        col = col.strip()
        if not col or not vals.strip():
            raise HTTPException(status_code=400, detail=f"Output limit column {key!r}: each part must be column=value.")
        out.append((col, {v.strip() for v in vals.split("|") if v.strip()}))
    return out


def model_frames(model: dict[str, Any] | None, network: Any = None) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Generators and buses with every column the sheets wrote (``fuel``, ``region`` …), indexed by name.

    The PyPSA network keeps only the schema's attributes, so a selector reads the model's own rows; with ``network``
    the generators are those the network holds (a transform or window may have dropped some).
    """
    def frame(sheet: str) -> pd.DataFrame:
        rows = [r for r in ((model or {}).get(sheet) or []) if isinstance(r, dict) and not _blank(r.get("name"))]
        df = pd.DataFrame(rows)
        return df.set_index(df["name"].astype(str)) if not df.empty else df

    gens, buses = frame("generators"), frame("buses")
    if network is not None:
        idx = network.generators.index.astype(str)
        gens = gens.reindex(idx) if not gens.empty else pd.DataFrame(index=idx)
        for col in ("carrier", "bus"):  # the network's own values where the model row is missing
            if col in network.generators:
                own = network.generators[col].astype(object)
                own.index = idx
                gens[col] = gens[col].where(gens[col].notna(), own) if col in gens else own
    return gens, (buses if not buses.empty else None)


def group_members(key: str, generators: pd.DataFrame, buses: pd.DataFrame | None = None) -> list[str]:
    """The generators a limit column names: a carrier, or a selector read on the generator, else on its bus."""
    sel = parse_group(key)
    if sel is None:
        return generators.index[generators["carrier"].astype(str) == key].tolist() if "carrier" in generators else []
    keep = pd.Series(True, index=generators.index)
    for col, vals in sel:
        own = generators[col].astype(object) if col in generators else pd.Series(None, index=generators.index, dtype=object)
        if buses is not None and col in buses and "bus" in generators:
            on_bus = generators["bus"].map(buses[col]).astype(object)
            own = own.where(own.notna() & (own.astype(str).str.strip() != ""), on_bus)
        keep &= own.astype(str).isin(vals) & own.notna()
    return generators.index[keep].tolist()


def refused_modes(ctx: mh.RunContext) -> list[str]:
    """The active run modes this cap cannot be honoured in."""
    modes = []
    if ctx.pathway is not None and bool(getattr(ctx.pathway, "enabled", False)):
        modes.append("multi-investment-period pathway")
    if ctx.stochastic is not None and bool(getattr(ctx.stochastic, "enabled", False)):
        modes.append("stochastic")
    if ctx.pf_enabled:
        modes.append("power-flow")
    if ctx.contingency_enabled:
        modes.append("contingency")
    return modes


def guard(ctx: mh.RunContext) -> None:
    if not has_caps(ctx.model):
        return
    modes = refused_modes(ctx)
    if modes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{SHEET} / {FLOOR_SHEET} hold fleet output limits, which cannot be applied in {', '.join(modes)} mode "
                "(the dispatch variable carries a period / scenario index the sheet has no column for, or no LP is solved). "
                "Clear the sheets or run single-period / rolling-horizon."
            ),
        )


def _aligned(caps: pd.DataFrame, snapshots: pd.Index) -> pd.DataFrame:
    """``caps`` on the run's snapshots (NaN where the sheet has no row or no cap)."""
    if caps.empty:
        return caps
    if isinstance(snapshots, pd.MultiIndex):
        raise HTTPException(status_code=400, detail=f"{SHEET} cannot be applied to a multi-period snapshot index.")
    idx = snapshots
    if isinstance(caps.index, pd.DatetimeIndex) and not isinstance(idx, pd.DatetimeIndex):
        idx = pd.Index(parse_snapshot_labels(list(map(str, idx))))
    return caps.reindex(idx)


def prepare(ctx: mh.RunContext) -> Callable[[Any, Any], None] | None:
    if not has_caps(ctx.model):
        return None
    modes = refused_modes(ctx)
    if modes:  # the guard already refused; repeated here so a direct caller of the constraints hook is safe too
        guard(ctx)
    n = ctx.network
    if n is None:
        return None
    notes = ctx.notes
    gens, buses = model_frames(ctx.model, n)
    plan: list[tuple[str, str, list[str], pd.Series]] = []  # (sheet, column, generators, MW by snapshot)
    for sheet in SHEETS:
        caps = read_caps(ctx.model, sheet)
        if caps.empty:
            continue
        on_run = _aligned(caps, n.snapshots)
        word = _WORD[sheet]
        for c in caps.columns:
            series = on_run[c]
            names = group_members(str(c), gens, buses)
            if not names:
                notes.append(f"{sheet}: '{c}' names no generators - its {word} is ignored.")
                continue
            if series.notna().sum() == 0:
                if caps[c].notna().any():
                    notes.append(f"{sheet}: '{c}' has values, but none on the modelled snapshots - not applied.")
                continue
            plan.append((sheet, str(c), names, series))
            notes.append(f"{sheet}: '{c}' ({len(names)} generators) output {word} in {int(series.notna().sum())} of {len(series)} snapshots (MW).")
    if not plan:
        return None

    def contribute(net: Any, snapshots: Any) -> None:
        p = net.model["Generator-p"]
        dim = next(d for d in p.dims if d != "snapshot")
        index = p.coords["snapshot"].to_index()
        if isinstance(index, pd.MultiIndex) or "scenario" in p.dims:
            raise HTTPException(status_code=400, detail=f"{SHEET} / {FLOOR_SHEET} cannot be applied to a multi-period or stochastic model.")
        import xarray as xr

        for sheet, key, names, series in plan:
            lim = series.reindex(index)  # the window being optimised; rolling horizon reads its own slice
            mask = lim.notna().to_numpy()
            if not mask.any():
                continue
            rhs = xr.DataArray(np.where(mask, lim.to_numpy(dtype=float), 0.0), coords={"snapshot": index}, dims="snapshot")
            keep = xr.DataArray(mask, coords={"snapshot": index}, dims="snapshot")
            fleet = p.sel({dim: names}).sum(dim)
            expr = fleet <= rhs if sheet == SHEET else fleet >= rhs
            net.model.add_constraints(expr, name=f"{_PREFIX[sheet]}{key}", mask=keep)

    return contribute



def realign(
    rows: list[dict[str, Any]],
    new_labels: list[str],
    new_index: pd.DatetimeIndex,
    *,
    mode: str,
    sheet: str = SHEET,
) -> list[dict[str, Any]]:
    """The sheet re-expressed on a transformed time axis (Forge slice / merge / temporal reduction).

    ``mode="filter"`` (a slice, a merge): keep the rows whose snapshot is still on the axis.
    ``mode="blocks"`` (resample, downsample, segment): each new snapshot takes the MEAN cap of the original snapshots it
    now stands for (those from it up to the next kept snapshot); a block with any blank hour stays blank, so a partly
    capped block is never capped. The mean is a valid relaxation of the hourly caps (block mean output <= mean cap).
    Rows are emitted at ``new_labels`` (the reduced ``snapshots`` sheet's spelling), in order.
    """
    caps = read_caps({sheet: rows}, sheet)
    if caps.empty or not isinstance(caps.index, pd.DatetimeIndex) or len(new_index) != len(new_labels):
        return rows
    if mode == "filter":
        keep = caps.reindex(new_index)
        keep = keep.dropna(how="all")
        label_of = dict(zip(new_index, new_labels))
        return [{_INDEX: label_of[t], **{c: (None if pd.isna(v) else float(v)) for c, v in r.items()}} for t, r in keep.iterrows()]
    old = caps.sort_index()
    pos = np.asarray(new_index.searchsorted(old.index, side="right")) - 1
    out: list[dict[str, Any]] = []
    grouped = old.assign(_pos=pos)
    grouped = grouped[grouped["_pos"] >= 0]
    for k, block in grouped.groupby("_pos"):
        cells: dict[str, Any] = {_INDEX: new_labels[int(k)]}
        for c in old.columns:
            col = block[c]
            cells[c] = float(col.mean()) if col.notna().all() else None
        if any(v is not None for c, v in cells.items() if c != _INDEX):
            out.append(cells)
    return out
