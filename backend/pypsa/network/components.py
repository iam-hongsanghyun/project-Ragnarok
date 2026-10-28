from __future__ import annotations

import re
from typing import Any, Iterable

import pandas as pd
import pypsa

from ..utils.coerce import number
from .snapshots import parse_snapshot_labels

# PyPSA multi-port Links: ``bus2``/``efficiency2`` … ``busN``/``efficiencyN``
# are legitimate per-port attributes (CHP heat co-products, CO₂ tracking, …)
# even though the static schema CSV only declares ``bus0``/``bus1``/
# ``efficiency``. PyPSA registers the extra ports dynamically the moment a
# ``bus{N}`` column exists, so the builder must let these columns through its
# schema filter rather than strip them.
_RE_EXTRA_PORT = re.compile(r"^(?:bus|efficiency|delay|cyclic_delay)[2-9]\d*$")
# PyPSA 1.4 ``Process`` is the N-port generalisation of Link: ``bus{N}`` with
# per-port ``rate{N}`` (signed flow ratio), ``delay{N}`` and ``cyclic_delay{N}``.
# Its schema declares ports 0 and 1 only; ports >= 2 register dynamically.
_RE_EXTRA_PORT_PROCESS = re.compile(r"^(?:bus|rate|delay|cyclic_delay)[2-9]\d*$")


def _is_extra_port_attr(sheet: str, attr: str) -> bool:
    """True for a multi-port Link/Process attribute (``bus2``, ``rate3``, ``delay2`` …)."""
    if sheet == "links":
        return bool(_RE_EXTRA_PORT.match(str(attr)))
    if sheet == "processes":
        return bool(_RE_EXTRA_PORT_PROCESS.match(str(attr)))
    return False


def _extra_port_columns(sheet: str, columns: Iterable[Any]) -> set[str]:
    """Multi-port Link/Process columns present in ``columns`` (empty for other sheets)."""
    return {str(c) for c in columns if _is_extra_port_attr(sheet, str(c))}


def _normalize_extra_port_columns(df: pd.DataFrame, sheet: str) -> pd.DataFrame:
    """Make multi-port columns safe for ``network.add``.

    ``bus{N}`` must be strings — a row that doesn't use the port carries NaN
    after the DataFrame build, and PyPSA only treats the *empty string* as
    "port unused". ``efficiency{N}``/``rate{N}``/``delay{N}`` must be numeric;
    blanks coerce to NaN so PyPSA fills its own per-port default at add time.
    ``cyclic_delay{N}`` is boolean (blank -> False).
    """
    for col in _extra_port_columns(sheet, df.columns):
        if col.startswith("bus"):
            df[col] = df[col].fillna("").astype(str).str.strip()
        elif col.startswith("cyclic_delay"):
            df[col] = df[col].map(
                lambda v: False if v is None or (isinstance(v, float) and pd.isna(v))
                else (str(v).strip().lower() in ("1", "true", "yes", "t") if isinstance(v, str) else bool(v))
            ).astype(bool)
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


def refuse_unknown_buses(network: pypsa.Network) -> None:
    """Refuse a model whose components point at buses that do not exist.

    PyPSA's own ``check_for_unknown_buses`` (the one ``n.consistency_check`` runs) is called
    strictly for every component; Ragnarok used to drop such rows with a note, so a typo
    in a bus name silently removed a generator or a line.

    Raises:
        HTTPException: 400 carrying PyPSA's message (component list and the offending names).
    """
    from fastapi import HTTPException
    from pypsa.consistency import ConsistencyError, check_for_unknown_buses

    for component in network.components:
        if component.static.empty:
            continue
        try:
            check_for_unknown_buses(network, component, strict=True)
        except ConsistencyError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"{exc} The run is refused rather than dropping those rows silently.",
            ) from exc


def _ensure_carriers(network: pypsa.Network, carriers: pd.Series, notes: list[str] | None = None) -> None:
    """Auto-add any carrier referenced by a component but missing from carriers sheet (said in ``notes``)."""
    referenced = {str(c).strip() for c in carriers.dropna().unique() if str(c).strip()}
    missing = sorted(referenced - set(network.carriers.index))
    for name in missing:
        network.add("Carrier", name)
    if missing and notes is not None:
        notes.append(f"Carriers referenced but not on the carriers sheet were added with PyPSA defaults: {', '.join(missing)}.")


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
