"""Serialise a built ``pypsa.Network`` back into the app's workbook-model JSON.

The inverse of :func:`pypsa.network.build_network`. The frontend consumes
``{sheet: rows[]}`` payloads everywhere (workbook open, project import), so any
network we produce server-side — a netCDF/HDF5 import, or a clustered/reduced
network from a transform — is handed back in that same shape.
"""

from __future__ import annotations

import math
from typing import Any

import pypsa

from ..pypsa_schema import (
    component_sheets,
    input_static_attributes,
    input_temporal_attributes,
)

# Derived components PyPSA recomputes from topology — never round-tripped as data
# (``sub_networks`` rows carry a live ``SubNetwork`` object in ``obj``).
_SKIP_SHEETS = {"network", "snapshots", "sub_networks"}

# Cell values safe to emit into the workbook model (JSON-friendly scalars).
_JSON_SCALARS = (str, bool, int, float)


def _scalar(val: Any) -> tuple[bool, Any]:
    """``(keep, value)`` — coerce a cell to a JSON-safe scalar or drop it.

    Drops ``None``, any non-scalar object (e.g. a ``SubNetwork`` or other
    component reference), and every NON-FINITE float so the payload always
    serialises. ``NaN``/``±inf`` are dropped rather than emitted: PyPSA defaults
    ``p_nom_max``/``lifetime`` to ``inf`` and ``_sanitize_placeholder_bounds``
    deliberately restores ``±inf``, but ``Infinity`` is not valid JSON — Starlette
    renders responses with ``allow_nan=False``, so the endpoint 500s. Omitting the
    cell is lossless: ``build_network`` re-applies the same PyPSA default on the
    way back in.
    """
    if val is None:
        return False, None
    if hasattr(val, "item"):  # numpy / pandas scalar → python scalar
        try:
            val = val.item()
        except Exception:  # noqa: BLE001
            return False, None
    if isinstance(val, float) and not math.isfinite(val):  # NaN / ±inf
        return False, None
    if isinstance(val, _JSON_SCALARS):
        return True, val
    return False, None


def _snapshot_cells(ts: Any) -> dict[str, Any]:
    """Workbook cells addressing one snapshot: ``{snapshot}`` or ``{period, snapshot}``.

    A multi-investment-period network indexes snapshots by a ``(period,
    timestep)`` MultiIndex, so ``pandas`` hands each entry over as a tuple.
    ``str(tuple)`` would write the Python repr — ``"(2030, Timestamp('2030-01-01
    00:00:00'))"`` — into the sheet, which no longer parses as a date and takes
    the run back to single-period. Split the tuple into the ``period`` /
    ``snapshot`` column pair the ``snapshots`` sheet and
    ``_snapshots_index`` both expect instead.
    """
    if isinstance(ts, tuple):
        if len(ts) == 2:
            period, timestep = ts
            return {"period": _period_cell(period), "snapshot": str(timestep)}
        # Deeper index than PyPSA's (period, timestep) — keep the last level as
        # the timestamp and the first as the period rather than guess.
        return {"period": _period_cell(ts[0]), "snapshot": str(ts[-1])}
    return {"snapshot": str(ts)}


def _period_cell(period: Any) -> Any:
    """A period label as an int when it is one (PyPSA periods are years)."""
    keep, val = _scalar(period)
    if not keep:
        return str(period)
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, float) and val.is_integer():
        return int(val)
    return val


def network_to_model(network: pypsa.Network) -> dict[str, list[dict[str, Any]]]:
    """Round-trip a built network into the in-memory model shape.

    For each schema-known component class, emit a row per component (static
    columns) and turn any non-empty ``*_t`` dynamic frame into a
    ``<list_name>-<attr>`` sheet with one row per snapshot. Columns are filtered
    to the schema's input attributes so only user-facing fields are emitted.

    Multi-period networks keep their ``(period, timestep)`` index as the
    ``period`` + ``snapshot`` column pair on every temporal sheet, so a
    pathway model survives the round-trip (see :func:`_snapshot_cells`).
    """
    model: dict[str, list[dict[str, Any]]] = {}
    model["snapshots"] = [_snapshot_cells(ts) for ts in list(network.snapshots)]
    if network.name:
        model["network"] = [{"name": str(network.name)}]
    for sheet in component_sheets():
        if sheet in _SKIP_SHEETS:
            continue
        if sheet not in network.components.keys():
            continue
        comp = network.components[sheet]
        static = comp.static
        allowed_static = input_static_attributes(sheet)
        if static is not None and len(static) > 0:
            rows: list[dict[str, Any]] = []
            for name, row in static.iterrows():
                d: dict[str, Any] = {"name": str(name)}
                for col, val in row.items():
                    if allowed_static and col not in allowed_static:
                        continue
                    keep, sval = _scalar(val)
                    if keep:
                        d[str(col)] = sval
                rows.append(d)
            if rows:
                model[sheet] = rows
        allowed_temporal = input_temporal_attributes(sheet)
        dynamic = getattr(comp, "dynamic", None)
        if dynamic is None:
            continue
        for attr in list(dynamic.keys()):
            if allowed_temporal and attr not in allowed_temporal:
                continue
            df = dynamic[attr]
            if df is None or df.empty:
                continue
            ts_rows: list[dict[str, Any]] = []
            for ts, ser in df.iterrows():
                row_d: dict[str, Any] = _snapshot_cells(ts)
                for col, val in ser.items():
                    keep, sval = _scalar(val)
                    if keep:
                        row_d[str(col)] = sval
                ts_rows.append(row_d)
            if ts_rows:
                model[f"{sheet}-{attr}"] = ts_rows
    return model
