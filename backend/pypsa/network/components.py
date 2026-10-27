from __future__ import annotations

import re
from typing import Any, Iterable

import pandas as pd
import pypsa

from ..pypsa_schema import bus_reference_attributes
from ..utils.coerce import number
from .snapshots import parse_snapshot_labels

# PyPSA multi-port Links: ``bus2``/``efficiency2`` … ``busN``/``efficiencyN``
# are legitimate per-port attributes (CHP heat co-products, CO₂ tracking, …)
# even though the static schema CSV only declares ``bus0``/``bus1``/
# ``efficiency``. PyPSA registers the extra ports dynamically the moment a
# ``bus{N}`` column exists, so the builder must let these columns through its
# schema filter rather than strip them.
_RE_EXTRA_PORT = re.compile(r"^(?:bus|efficiency)[2-9]\d*$")


def _is_extra_port_attr(sheet: str, attr: str) -> bool:
    """True for a multi-port Link attribute (``bus2``, ``efficiency3``, …)."""
    return sheet == "links" and bool(_RE_EXTRA_PORT.match(str(attr)))


def _extra_port_columns(sheet: str, columns: Iterable[Any]) -> set[str]:
    """Multi-port Link columns present in ``columns`` (empty for other sheets)."""
    return {str(c) for c in columns if _is_extra_port_attr(sheet, str(c))}


def _normalize_extra_port_columns(df: pd.DataFrame, sheet: str) -> pd.DataFrame:
    """Make multi-port Link columns safe for ``network.add``.

    ``bus{N}`` must be strings — a row that doesn't use the port carries NaN
    after the DataFrame build, and PyPSA only treats the *empty string* as
    "port unused". ``efficiency{N}`` must be numeric; blanks coerce to NaN so
    PyPSA fills its own per-port default (1.0) at add time.
    """
    for col in _extra_port_columns(sheet, df.columns):
        if col.startswith("bus"):
            df[col] = df[col].fillna("").astype(str).str.strip()
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


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
    extra_bus_cols = sorted(
        c for c in _extra_port_columns(sheet, df.columns) if c.startswith("bus")
    )
    if not bus_cols and not extra_bus_cols:
        return df
    schema_required = {
        attr["attribute"]
        for attr in bus_reference_attributes(sheet)
        if attr.get("required")
    }
    required = [c for c in bus_cols if c in ("bus", "bus0", "bus1") and c in schema_required]
    if not required and not extra_bus_cols:
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
    # Multi-port refs (bus2+) are optional: blank means "port unused" and is
    # fine, but a non-blank ref to a missing bus would fail PyPSA's consistency
    # check at solve time — drop the row loudly instead.
    for col in extra_bus_cols:
        for name, bus in df[col].items():
            if pd.isna(bus) or str(bus).strip() == "":
                continue
            if str(bus) not in valid_buses:
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
    notes: list[str] | None = None,
) -> pd.Index:
    """Assign a time-series sheet to ``network.<list_name>_t.<attr>``.

    Timezone designators on the sheet's labels are dropped (wall-clock kept) so
    ``...T00:00:00Z`` stamps match the naive snapshot index. Snapshots the sheet
    has **no row for** stay NaN here and are returned, so the caller can refuse
    the run once the modelled window is known (a NaN ``p_max_pu``/``p_min_pu``
    silently drops the bound in the LP). A blank cell inside a covered row is
    filled from the component's static value and reported in ``notes``.

    Returns:
        The snapshot labels with no row in this sheet (empty when fully covered).
    """
    no_gap: pd.Index = pd.Index([])
    df = pd.DataFrame(rows)
    label_col = next(
        (k for k in ("snapshot", "datetime", "name", "index", "timestep") if k in df.columns),
        None,
    )
    if label_col is None:
        return no_gap
    data = df.drop(columns=[label_col, *([c for c in ("period",) if c in df.columns])])
    if data.empty:
        return no_gap
    static_frame = network.components[list_name].static
    valid_cols = [c for c in data.columns if c in static_frame.index]
    if not valid_cols:
        return no_gap
    data = data[valid_cols].apply(pd.to_numeric, errors="coerce")
    if isinstance(network.snapshots, pd.MultiIndex):
        if "period" in df.columns:
            periods = df["period"].apply(lambda v: int(number(v))).tolist()
            labels = df[label_col]
            try:
                timesteps = parse_snapshot_labels(labels)
            except Exception:
                timesteps = pd.Index(labels.astype(str))
            data.index = pd.MultiIndex.from_arrays([periods, timesteps], names=["period", "timestep"])
            data.index.name = "snapshot"
        elif len(df.index) == len(network.snapshots):
            data.index = network.snapshots
        else:
            try:
                idx = parse_snapshot_labels(df[label_col])
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
                return no_gap
            data = pd.concat(pieces)
    else:
        try:
            data.index = parse_snapshot_labels(df[label_col])
        except Exception:
            data.index = pd.Index(df[label_col].astype(str))
        # Single-period: dedupe input time-series rows when the same timestamp
        # appears more than once (pathway workbooks list each timestep once
        # per period). Keep first occurrence so reindex succeeds.
        if data.index.has_duplicates:
            data = data[~data.index.duplicated(keep="first")]
    uncovered: pd.Index = no_gap
    if len(network.snapshots) > 0:
        if isinstance(network.snapshots, pd.MultiIndex) and not isinstance(data.index, pd.MultiIndex):
            covered = network.snapshots.get_level_values("timestep").isin(data.index)
            data = data.reindex(network.snapshots, level="timestep")
        else:
            covered = network.snapshots.isin(data.index)
            data = data.reindex(network.snapshots)
        uncovered = network.snapshots[~covered]
        # Blank cells in a covered row -> the component's static value (what an
        # absent column would have used), not a NaN that drops the bound.
        static_values = static_frame[attr] if attr in static_frame.columns else None
        if static_values is not None:
            blanks = 0
            for col in data.columns:
                hole = data[col].isna() & covered
                if hole.any():
                    blanks += int(hole.sum())
                    data.loc[hole, col] = static_values.get(col)
            if blanks and notes is not None:
                notes.append(
                    f"Time-series '{list_name}-{attr}': {blanks} blank cell(s) filled "
                    f"from the static '{attr}' value."
                )
    t_frame = getattr(network, list_name + "_t")
    current = getattr(t_frame, attr)
    # Re-stitch via concat (avoid the per-column-insert performance warning).
    merged = pd.concat(
        [current.drop(columns=[c for c in current.columns if c in data.columns]), data],
        axis=1,
    )
    setattr(t_frame, attr, merged)
    return uncovered
