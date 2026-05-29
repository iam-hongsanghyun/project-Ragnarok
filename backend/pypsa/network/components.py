from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa

from ..pypsa_schema import bus_reference_attributes, input_temporal_attributes
from ..utils.coerce import number


def _has_name(row: dict[str, Any]) -> bool:
    name = row.get("name")
    return name is not None and str(name).strip() != ""


def _strip_blank_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop columns that are entirely null or blank — let PyPSA defaults apply."""
    df = df.dropna(axis=1, how="all")
    for col in list(df.columns):
        if df[col].astype(str).str.strip().eq("").all():
            df = df.drop(columns=[col])
    return df


def _ordered_component_sheets(network: pypsa.Network) -> list[tuple[str, str]]:
    """Return [(sheet_name, pypsa_class_name), …] in dependency-safe order.

    Carriers and buses must be added before anything that references them. The
    remainder follows PyPSA's own component registry order.
    """
    keys = list(network.components.keys())
    priority = {"carriers": 0, "buses": 1}
    sortable: list[tuple[int, int, str, str]] = []
    for i, list_name in enumerate(keys):
        comp = network.components[list_name]
        sortable.append((priority.get(list_name, 99), i, list_name, comp.name))
    sortable.sort()
    return [(list_name, cls) for _, _, list_name, cls in sortable]


def _bus_ref_columns_for_list(network: pypsa.Network, list_name: str) -> list[str]:
    defaults = network.components[list_name].defaults
    return [a for a in defaults.index if a == "bus" or (a.startswith("bus") and a[3:].isdigit())]


def _drop_broken_bus_refs(
    df: pd.DataFrame,
    cls: str,
    network: pypsa.Network,
    sheet: str,
    notes: list[str],
) -> pd.DataFrame:
    """Drop rows where a *required* bus reference points to a missing bus.

    The schema is the source of truth for which bus references are required —
    components like ``global_constraints`` declare ``bus`` as optional, so an
    absent ``bus`` column on those sheets must not delete every row.
    """
    bus_cols = _bus_ref_columns_for_list(network, sheet)
    if not bus_cols:
        return df
    schema_required = {
        attr["attribute"]
        for attr in bus_reference_attributes(sheet)
        if attr.get("required")
    }
    required = [c for c in bus_cols if c in ("bus", "bus0", "bus1") and c in schema_required]
    if not required:
        return df
    valid_buses = set(network.buses.index)
    keep_mask = pd.Series(True, index=df.index)
    skipped: list[str] = []
    for col in required:
        if col not in df.columns:
            notes.append(f"Sheet '{sheet}' has no '{col}' column — all rows skipped.")
            return df.iloc[0:0]
        for name, bus in df[col].items():
            if pd.isna(bus) or str(bus).strip() == "" or str(bus) not in valid_buses:
                keep_mask[name] = False
                skipped.append(f"{name} ({col}='{bus}')")
    dropped = (~keep_mask).sum()
    if dropped:
        notes.append(
            f"{cls}: {int(dropped)} row(s) skipped — bus reference missing: "
            f"{', '.join(skipped[:5])}{' …' if len(skipped) > 5 else ''}"
        )
    return df[keep_mask]


def _ensure_carriers(network: pypsa.Network, carriers: pd.Series) -> None:
    """Auto-add any carrier referenced by a component but missing from carriers sheet."""
    referenced = {str(c).strip() for c in carriers.dropna().unique() if str(c).strip()}
    missing = referenced - set(network.carriers.index)
    for name in missing:
        network.add("Carrier", name)


def _apply_ts_sheet(
    network: pypsa.Network,
    rows: list[dict[str, Any]],
    list_name: str,
    attr: str,
) -> None:
    """Assign a time-series sheet to ``network.<list_name>_t.<attr>``."""
    df = pd.DataFrame(rows)
    label_col = next(
        (k for k in ("snapshot", "datetime", "name", "index", "timestep") if k in df.columns),
        None,
    )
    if label_col is None:
        return
    data = df.drop(columns=[label_col, *([c for c in ("period",) if c in df.columns])])
    if data.empty:
        return
    static_frame = network.components[list_name].static
    valid_cols = [c for c in data.columns if c in static_frame.index]
    if not valid_cols:
        return
    data = data[valid_cols].apply(pd.to_numeric, errors="coerce")
    if isinstance(network.snapshots, pd.MultiIndex):
        if "period" in df.columns:
            periods = df["period"].apply(lambda v: int(number(v))).tolist()
            labels = df[label_col]
            try:
                timesteps = pd.to_datetime(labels)
            except Exception:
                timesteps = pd.Index(labels.astype(str))
            data.index = pd.MultiIndex.from_arrays([periods, timesteps], names=["period", "timestep"])
            data.index.name = "snapshot"
        elif len(df.index) == len(network.snapshots):
            data.index = network.snapshots
        else:
            try:
                idx = pd.to_datetime(df[label_col])
            except Exception:
                idx = pd.Index(df[label_col].astype(str))
            pieces = []
            periods = list(network.snapshots.get_level_values("period").unique())
            for period in periods:
                period_data = data.copy()
                period_data.index = idx
                period_data = pd.concat({period: period_data}, names=["period", "timestep"])
                period_data.index.name = "snapshot"
                pieces.append(period_data)
            if not pieces:
                return
            data = pd.concat(pieces)
    else:
        try:
            data.index = pd.to_datetime(df[label_col])
        except Exception:
            data.index = pd.Index(df[label_col].astype(str))
        # Single-period: dedupe input time-series rows when the same timestamp
        # appears more than once (pathway workbooks list each timestep once
        # per period). Keep first occurrence so reindex succeeds.
        if data.index.has_duplicates:
            data = data[~data.index.duplicated(keep="first")]
    if len(network.snapshots) > 0:
        if isinstance(network.snapshots, pd.MultiIndex) and not isinstance(data.index, pd.MultiIndex):
            data = data.reindex(network.snapshots, level="timestep")
        else:
            data = data.reindex(network.snapshots)
    t_frame = getattr(network, list_name + "_t")
    current = getattr(t_frame, attr)
    # Re-stitch via concat (avoid the per-column-insert performance warning).
    merged = pd.concat(
        [current.drop(columns=[c for c in current.columns if c in data.columns]), data],
        axis=1,
    )
    setattr(t_frame, attr, merged)
