"""Per-snapshot carrier output cap: the ``RAGNAROK_CarrierOutputCap`` sheet as a declared linopy constraint.

A wide TEMPORAL sheet: first column ``snapshot`` (the labels of the ``snapshots`` sheet), then one column per
carrier name, values in MW. A blank cell is no cap at that hour. For every snapshot ``t`` and carrier ``c`` with a
cap, the FLEET's summed dispatch is bounded; the units stay free to share it by merit order (this is not a per-unit
``p_max_pu``).

Algorithm:
    $$\\sum_{g:\\,\\mathrm{carrier}(g)=c} p_{g,t} \\le \\bar P_{c,t} \\qquad \\forall (c,t)\\ \\text{with a cap}$$
    ASCII: sum_{g in carrier c} p[g,t] <= cap[c,t]
    where p_{g,t} is the Generator-p dispatch of generator g in snapshot t (MW) and cap is the sheet cell (MW).
    Power, not energy: no snapshot weighting enters. The linopy constraint is ``carrier_output_cap_<carrier>``
    (one per carrier, over the capped snapshots); its dual is reported in ``appliedConstraints``.

Run paths: single period (plain optimise, security-constrained) and rolling horizon - the hook is called once per
window and the sheet is read at the window's own snapshots, so nothing is apportioned. Multi-investment-period
(pathway) and stochastic runs are refused (the dispatch variable carries a period / scenario index the sheet has no
column for), as are power-flow and contingency modes, which solve no LP and would silently ignore the cap.
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
CONSTRAINT_PREFIX = "carrier_output_cap_"
_INDEX = "snapshot"


def _blank(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, float) and math.isnan(value))


def read_caps(model: dict[str, Any] | None) -> pd.DataFrame:
    """The sheet as a frame: index = snapshot labels (parsed to datetimes when they are), columns = carriers, MW.

    Blank cells are ``NaN`` (no cap). Raises ``HTTPException(400)`` on a non-numeric or negative cap, a duplicate
    snapshot label, or a row without a label: a cap that is mis-read must stop the run, not loosen it.
    """
    rows = [r for r in ((model or {}).get(SHEET) or []) if isinstance(r, dict)]
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
            raise HTTPException(status_code=400, detail=f"{SHEET}: row {i + 1} has no `{_INDEX}` label.")
        labels.append(str(label))
        for c in carriers:
            v = r.get(c)
            if _blank(v):
                data[c].append(float("nan"))
                continue
            try:
                x = float(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{SHEET}: cap for '{c}' at {label} is not a number ({v!r}).") from None
            if not math.isfinite(x) or x < 0:
                raise HTTPException(status_code=400, detail=f"{SHEET}: cap for '{c}' at {label} must be a finite MW >= 0, got {v!r}.")
            data[c].append(x)
    try:
        index: pd.Index = parse_snapshot_labels(labels)
    except Exception:  # noqa: BLE001 - non-datetime labels: keep them as text
        index = pd.Index(labels, dtype="object")
    if index.has_duplicates:
        raise HTTPException(status_code=400, detail=f"{SHEET}: duplicate `{_INDEX}` labels (e.g. {index[index.duplicated()][0]}).")
    return pd.DataFrame(data, index=index)


def has_caps(model: dict[str, Any] | None) -> bool:
    """True when the sheet holds at least one non-blank cap."""
    return any(not _blank(v) for r in ((model or {}).get(SHEET) or []) if isinstance(r, dict) for k, v in r.items() if k != _INDEX)


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
                f"{SHEET} holds carrier output caps, which cannot be applied in {', '.join(modes)} mode "
                "(the dispatch variable carries a period / scenario index the sheet has no column for, or no LP is solved). "
                "Clear the sheet or run single-period / rolling-horizon."
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
    caps = read_caps(ctx.model)
    n = ctx.network
    if n is None or caps.empty:
        return None
    on_run = _aligned(caps, n.snapshots)
    notes = ctx.notes
    carriers = {str(c) for c in n.generators["carrier"]}
    plan: dict[str, pd.Series] = {}
    for c in caps.columns:
        series = on_run[c]
        if c not in carriers:
            notes.append(f"{SHEET}: carrier '{c}' has no generators - its cap is ignored.")
            continue
        if series.notna().sum() == 0:
            if caps[c].notna().any():
                notes.append(f"{SHEET}: carrier '{c}' has caps, but none on the modelled snapshots - not applied.")
            continue
        plan[c] = series
        notes.append(f"{SHEET}: {c} fleet output capped in {int(series.notna().sum())} of {len(series)} snapshots (MW).")

    def contribute(net: Any, snapshots: Any) -> None:
        p = net.model["Generator-p"]
        dim = next(d for d in p.dims if d != "snapshot")
        index = p.coords["snapshot"].to_index()
        if isinstance(index, pd.MultiIndex) or "scenario" in p.dims:
            raise HTTPException(status_code=400, detail=f"{SHEET} cannot be applied to a multi-period or stochastic model.")
        import xarray as xr

        for carrier, series in plan.items():
            cap = series.reindex(index)  # the window being optimised; rolling horizon reads its own slice
            mask = cap.notna().to_numpy()
            if not mask.any():
                continue
            names = net.generators.index[net.generators["carrier"] == carrier].tolist()
            rhs = xr.DataArray(np.where(mask, cap.to_numpy(dtype=float), 0.0), coords={"snapshot": index}, dims="snapshot")
            keep = xr.DataArray(mask, coords={"snapshot": index}, dims="snapshot")
            fleet = p.sel({dim: names}).sum(dim)
            net.model.add_constraints(fleet <= rhs, name=f"{CONSTRAINT_PREFIX}{carrier}", mask=keep)

    return contribute



def realign(
    rows: list[dict[str, Any]],
    new_labels: list[str],
    new_index: pd.DatetimeIndex,
    *,
    mode: str,
) -> list[dict[str, Any]]:
    """The sheet re-expressed on a transformed time axis (Forge slice / merge / temporal reduction).

    ``mode="filter"`` (a slice, a merge): keep the rows whose snapshot is still on the axis.
    ``mode="blocks"`` (resample, downsample, segment): each new snapshot takes the MEAN cap of the original snapshots it
    now stands for (those from it up to the next kept snapshot); a block with any blank hour stays blank, so a partly
    capped block is never capped. The mean is a valid relaxation of the hourly caps (block mean output <= mean cap).
    Rows are emitted at ``new_labels`` (the reduced ``snapshots`` sheet's spelling), in order.
    """
    caps = read_caps({SHEET: rows})
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
