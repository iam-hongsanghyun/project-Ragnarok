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
                       { "snapshot": "<timestamp>", "<component_name>": value, ... },
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

import numpy as np
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


def _iso_timestamp(value: Any) -> str:
    """Naive ISO-8601 timestamp (``YYYY-MM-DDTHH:MM:SS``) for workbook export."""
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return str(value)


def _series_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a (snapshot × component) output frame to the list-of-row dicts
    the frontend expects, vectorised.

    The naive version did a per-cell ``df.at[snapshot, col]`` label lookup —
    O(snapshots × components) of hashed lookups, which for a multi-bus
    full-year run is tens of millions of calls and dominates the post-solve
    time. Here we drop to numpy positional access (and a whole-array
    ``tolist()`` on the common all-finite path), preserving the original
    semantics: NaN cells are omitted, finite values become Python floats.
    """
    cols = [str(c) for c in df.columns]
    index_rows = [_series_snapshot_row(s) for s in df.index]
    rows: list[dict[str, Any]] = []

    # Numeric fast path — every output series (p, q, marginal_price, soc, mu_*)
    # is float. Object/mixed frames fall through to the slow, exact path.
    try:
        arr = df.to_numpy(dtype=float)
    except (ValueError, TypeError):
        arr = None

    if arr is not None:
        finite = np.isfinite(arr)
        if bool(finite.all()):
            # No NaN to drop → emit every column; tolist() does the float
            # conversion in C, so there's no Python per-cell work.
            for base, vals in zip(index_rows, arr.tolist()):
                row = dict(base)
                row.update(zip(cols, vals))
                rows.append(row)
        else:
            for i, base in enumerate(index_rows):
                row = dict(base)
                ri = arr[i]
                fi = finite[i]
                for j, col in enumerate(cols):
                    if fi[j]:
                        row[col] = float(ri[j])
                rows.append(row)
        return rows

    # Object/mixed fallback (rare): preserve exact _safe_scalar semantics.
    values = df.to_numpy()
    for i, base in enumerate(index_rows):
        row = dict(base)
        ri = values[i]
        for j, col in enumerate(cols):
            safe = _safe_scalar(ri[j])
            if safe is not None:
                row[col] = safe
        rows.append(row)
    return rows


def _series_snapshot_row(snapshot: Any) -> dict[str, Any]:
    """Build the index cell(s) for one output time-series row.

    Uses a single PyPSA-standard ``snapshot`` column to match the input
    temporal sheets (``snapshots``, ``loads-p_set`` …) and PyPSA's own
    ``*_t`` frame index. Multi-investment results additionally carry the
    ``period`` level. (Earlier versions emitted redundant ``name`` and
    ``timestamp`` columns holding the same value; the frontend readers keep
    a fallback so those legacy workbooks still import.)
    """
    if isinstance(snapshot, tuple) and len(snapshot) == 2:
        period = int(snapshot[0])
        timestep = snapshot[1]
        stamp = _iso_timestamp(timestep)
        return {"period": period, "snapshot": stamp}
    return {"snapshot": _iso_timestamp(snapshot)}


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
        # Prefer the historical `network.<list_name>_t` accessor (always present
        # for older components like generators/loads/lines). New components
        # (e.g. processes) only expose dynamic frames via `comp.dynamic`, so
        # fall back to that — also a `Dict` supporting `getattr(t, attr)`.
        t_frame = getattr(network, f"{list_name}_t", None)
        if t_frame is None:
            t_frame = comp.dynamic
        if t_frame is None or not series_attrs:
            continue
        for attr in series_attrs:
            df = getattr(t_frame, attr, None)
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                continue
            rows = _series_rows(df)
            if rows:
                series_out[f"{list_name}-{attr}"] = rows

    return {"static": static_out, "series": series_out}
