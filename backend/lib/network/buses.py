from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from ..utils.coerce import number, text
from ..utils.workbook import workbook_rows


def add_buses(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
) -> None:
    buses = workbook_rows(model, "buses")
    if not buses:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Workbook has no buses.")
    for row in buses:
        name = text(row.get("name"))
        if not name:
            continue
        network.add(
            "Bus",
            name,
            x=number(row.get("x")),
            y=number(row.get("y")),
            v_nom=number(row.get("v_nom"), 154.0),
            carrier=text(row.get("carrier"), "AC"),
            v_mag_pu_set=number(row.get("v_mag_pu_set"), 1.0),
        )


def parse_ts_sheet(
    model: dict[str, list[dict[str, Any]]],
    sheet_name: str,
    snapshots: pd.Index,
    snapshot_start: int = 0,
    snapshot_window: int | None = None,
    step: int = 1,
) -> dict[str, np.ndarray] | None:
    """Parse a time-series sheet (rows = timesteps, columns = component names).
    Returns a dict mapping component name → float array aligned to snapshots,
    or None if the sheet is absent or empty.

    When *step* > 1 the TS sheet is downsampled with ``arr[::step]`` before
    alignment, matching the PyPSA convention of selecting every N-th snapshot.
    If the raw row count equals ``len(snapshots)`` (sheet was already
    pre-aggregated) the slice is skipped."""
    rows = model.get(sheet_name) or []
    if not rows:
        return None
    # Identify which keys are timestamp/index columns vs data columns
    index_keys = {"snapshot", "datetime", "name", "index", "timestep"}
    data_keys = [k for k in rows[0].keys() if k.lower() not in index_keys]
    if not data_keys:
        return None
    result: dict[str, np.ndarray] = {}
    n_snap = len(snapshots)
    for key in data_keys:
        vals = [number(r.get(key), 0.0) for r in rows]
        arr = np.array(vals, dtype=float)
        if len(arr) != n_snap:
            stop = len(arr) if snapshot_window is None else min(len(arr), snapshot_start + snapshot_window)
            arr = arr[snapshot_start:stop]
            if step > 1:
                arr = arr[::step]
        if len(arr) == n_snap:
            result[key] = arr
    return result if result else None


def add_loads(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    snapshots: pd.Index,
    snapshot_start: int = 0,
    snapshot_window: int | None = None,
    step: int = 1,
) -> dict[str, float]:
    """Add loads using workbook data only.
    If 'loads-p_set' sheet is present its time-series takes priority;
    otherwise the static p_set is used as a flat constant."""
    ts_p_set = parse_ts_sheet(
        model,
        "loads-p_set",
        snapshots,
        snapshot_start=snapshot_start,
        snapshot_window=snapshot_window,
        step=step,
    )
    load_totals: dict[str, float] = defaultdict(float)

    for row in workbook_rows(model, "loads"):
        name = text(row.get("name"))
        bus = text(row.get("bus"))
        if not name or bus not in network.buses.index:
            continue
        p_set_static = number(row.get("p_set"), 0.0)
        network.add(
            "Load",
            name,
            bus=bus,
            carrier=text(row.get("carrier"), "load"),
            q_set=number(row.get("q_set")),
        )
        if ts_p_set and name in ts_p_set:
            network.loads_t.p_set.loc[:, name] = ts_p_set[name]
        else:
            network.loads_t.p_set.loc[:, name] = p_set_static
        load_totals[bus] += p_set_static
    return dict(load_totals)
