"""Serialise a built ``pypsa.Network`` back into the app's workbook-model JSON.

The inverse of :func:`pypsa.network.build_network`. The frontend consumes
``{sheet: rows[]}`` payloads everywhere (workbook open, project import), so any
network we produce server-side — a netCDF/HDF5 import, or a clustered/reduced
network from a transform — is handed back in that same shape.
"""

from __future__ import annotations

from typing import Any

import pypsa

from ..pypsa_schema import (
    component_sheets,
    input_static_attributes,
    input_temporal_attributes,
)


def network_to_model(network: pypsa.Network) -> dict[str, list[dict[str, Any]]]:
    """Round-trip a built network into the in-memory model shape.

    For each schema-known component class, emit a row per component (static
    columns) and turn any non-empty ``*_t`` dynamic frame into a
    ``<list_name>-<attr>`` sheet with one row per snapshot. Columns are filtered
    to the schema's input attributes so only user-facing fields are emitted.
    """
    model: dict[str, list[dict[str, Any]]] = {}
    model["snapshots"] = [{"snapshot": str(ts)} for ts in list(network.snapshots)]
    if network.name:
        model["network"] = [{"name": str(network.name)}]
    for sheet in component_sheets():
        if sheet in {"network", "snapshots"}:
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
                    if val is None or (hasattr(val, "__float__") and (val != val)):
                        continue  # NaN
                    d[str(col)] = val.item() if hasattr(val, "item") else val
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
                row_d: dict[str, Any] = {"snapshot": str(ts)}
                for col, val in ser.items():
                    if val is None or (hasattr(val, "__float__") and (val != val)):
                        continue
                    row_d[str(col)] = val.item() if hasattr(val, "item") else val
                ts_rows.append(row_d)
            if ts_rows:
                model[f"{sheet}-{attr}"] = ts_rows
    return model
