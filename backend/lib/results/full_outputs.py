"""Extract every PyPSA output attribute from a solved network as JSON.

This is the schema-driven equivalent of `pypsa.Network.export_to_excel`:
for every component class the schema marks as having `status=output`
attributes, we pull the static (`p_nom_opt`, `mu_*`) and time-varying
(`p`, `q`, `marginal_price`, `state_of_charge` …) values out of the
solved network and return them as a JSON-serialisable dict.

The dict shape mirrors what the frontend already understands:

    {
        "static":  { "<list_name>": { "<component_name>": { "<attr>": value, ... }, ... }, ... },
        "series":  { "<list_name>-<attr>": [
                       { "name": "<timestamp>", "<component_name>": value, ... },
                       ...
                     ], ... },
    }

The frontend combines `model[<list_name>]` (input columns the user
provided) with `outputs.static[<list_name>]` (output columns PyPSA
produced) when assembling the Export-Project workbook. The series
sheets are written verbatim alongside the input time-series sheets.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd
import pypsa

from ..pypsa_schema import (
    component_schema,
    load_pypsa_schema,
    non_component_sheets,
)


def _safe_scalar(value: Any) -> Any:
    """Convert a pandas/numpy scalar to a JSON-safe primitive."""
    if value is None:
        return None
    if isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and math.isnan(value)) else value
    if hasattr(value, "item"):
        try:
            v = value.item()
            if isinstance(v, float) and math.isnan(v):
                return None
            return v
        except (ValueError, TypeError):
            pass
    if pd.isna(value):
        return None
    return value


def _component_output_attrs(sheet_name: str) -> tuple[list[str], list[str]]:
    """Return (static_output_attrs, series_output_attrs) for a sheet."""
    schema = component_schema(sheet_name)
    if not schema:
        return [], []
    static, series = [], []
    for attr in schema.get("attributes", []):
        if attr.get("status") != "output":
            continue
        storage = attr.get("storage", "static")
        if storage == "series":
            series.append(attr["attribute"])
        elif storage == "static_or_series":
            # Hybrid attributes are recorded as series in solved results;
            # the static side is duplicated only when the user supplied it.
            series.append(attr["attribute"])
        else:
            static.append(attr["attribute"])
    return static, series


def _series_snapshot_row(snapshot: Any) -> dict[str, Any]:
    if isinstance(snapshot, tuple) and len(snapshot) == 2:
        period = int(snapshot[0])
        timestep = snapshot[1]
        try:
            stamp = pd.Timestamp(timestep).isoformat()
        except Exception:
            stamp = str(timestep)
        return {"period": period, "name": stamp, "timestamp": stamp}
    try:
        stamp = pd.Timestamp(snapshot).isoformat()
    except Exception:
        stamp = str(snapshot)
    return {"name": stamp, "timestamp": stamp}


def build_full_outputs(network: pypsa.Network) -> dict[str, Any]:
    """Walk every documented component and return its solved output values.

    Args:
        network: solved ``pypsa.Network`` instance.

    Returns:
        ``{"static": {...}, "series": {...}}`` — see module docstring.
    """
    schema = load_pypsa_schema()
    skip = non_component_sheets()
    static_out: dict[str, dict[str, dict[str, Any]]] = {}
    series_out: dict[str, list[dict[str, Any]]] = {}

    for list_name in schema.get("components", {}).keys():
        if list_name in skip:
            continue
        if list_name not in network.components.keys():
            continue

        static_attrs, series_attrs = _component_output_attrs(list_name)
        comp = network.components[list_name]
        static_frame: pd.DataFrame = comp.static

        # ── Static output attributes ─────────────────────────────────────
        if static_attrs and not static_frame.empty:
            sheet_static: dict[str, dict[str, Any]] = {}
            for attr in static_attrs:
                if attr not in static_frame.columns:
                    continue
                col = static_frame[attr]
                for component_name, value in col.items():
                    safe = _safe_scalar(value)
                    if safe is None:
                        continue
                    sheet_static.setdefault(str(component_name), {})[attr] = safe
            if sheet_static:
                static_out[list_name] = sheet_static

        # ── Time-series output attributes ────────────────────────────────
        t_frame = getattr(network, f"{list_name}_t", None)
        if t_frame is None or not series_attrs:
            continue
        for attr in series_attrs:
            df = getattr(t_frame, attr, None)
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                continue
            rows: list[dict[str, Any]] = []
            for snapshot in df.index:
                row = _series_snapshot_row(snapshot)
                for component_name in df.columns:
                    safe = _safe_scalar(df.at[snapshot, component_name])
                    if safe is not None:
                        row[str(component_name)] = safe
                rows.append(row)
            if rows:
                series_out[f"{list_name}-{attr}"] = rows

    return {"static": static_out, "series": series_out}
