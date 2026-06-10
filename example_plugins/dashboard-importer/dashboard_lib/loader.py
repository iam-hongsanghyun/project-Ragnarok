"""Load a PyPSA network from Excel and filter assets / temporal data by year."""
from __future__ import annotations

import re

import pypsa
import pandas as pd

# pandas 3.0 defaults to Arrow-backed strings; xarray/PyPSA requires numpy object arrays
pd.options.mode.string_storage = "python"


# Bus-reference column names by component plural attribute name.  Used by
# :func:`_normalize_names_to_str` to know which columns hold bus identifiers
# and therefore need str-casting.  ``filter_components_by_year`` does not
# use this — it lets PyPSA enumerate components for us.
_BUS_REF_COLS = {
    "generators":     ["bus"],
    "loads":          ["bus"],
    "storage_units":  ["bus"],
    "stores":         ["bus"],
    "lines":          ["bus0", "bus1"],
    "transformers":   ["bus0", "bus1"],
    "links":          ["bus0", "bus1"],
}


_FLOAT_INT_ARTIFACT = re.compile(r"^(-?\d+)\.0+$")


def _canon_label(value: object) -> str:
    """Canonicalise a name/reference to a **string**.

    Names are always strings — never reinterpreted as numbers.  The only
    transformation is stripping the *float-coercion artifact*: when Excel reads
    an integer ID column that contains a blank/NaN cell, pandas turns the whole
    column to float, so ``71`` arrives as ``71.0`` while a bus named ``71`` (an
    int column with no blanks) stays ``71``.  A plain ``str()`` then yields
    ``"71.0"`` vs ``"71"`` — they no longer match and the generator is dropped
    as having an undefined bus.  We therefore collapse a trailing ``.0`` on an
    otherwise all-digit string (``"71.0"`` → ``"71"``) and leave everything else
    untouched: ``"007"`` stays ``"007"``, ``"3.5"`` stays ``"3.5"``, ``"강원"``
    and ``"KR_GG_01"`` pass through (stripped).

    Args:
        value: A raw index/label/reference cell value.

    Returns:
        The canonical string label.
    """
    if value is None:
        return ""
    s = str(value).strip()
    m = _FLOAT_INT_ARTIFACT.match(s)
    return m.group(1) if m else s


def _normalize_names_to_str(network: pypsa.Network) -> None:
    """Canonicalise every component name and bus reference to ``str`` in place.

    PyPSA matches component indices and bus references with strict equality, so
    a load whose ``loads.index`` is the string ``"1"`` and whose ``loads_t.p_set``
    column is the integer ``1`` is silently dropped from the optimisation —
    the objective collapses to 0 and every generator sits at 0 output.

    To eliminate this entire class of dtype mismatch, we canonicalise everything
    via :func:`_canon_label` (which also collapses integral floats like ``71.0``
    to ``"71"`` so a float-typed ``bus`` column still matches an int-named bus):

    * every static-component DataFrame's index (``buses.index``,
      ``generators.index``, ``loads.index`` …);
    * every bus-reference column (``generators.bus``, ``lines.bus0``,
      ``lines.bus1`` …);
    * every time-series wide-table's columns (``generators_t.p_max_pu.columns``,
      ``loads_t.p_set.columns`` …).

    Args:
        network: The PyPSA Network to normalise (modified in place).
    """
    for component in network.iterate_components():
        df = component.df
        # 1. Static-component index
        if not df.empty:
            df.index = df.index.map(_canon_label)
        # 2. Bus-reference columns (known by plural attribute name)
        for col in _BUS_REF_COLS.get(component.list_name, []):
            if col in df.columns:
                df[col] = df[col].map(_canon_label)
        # 3. Time-series wide-table column labels
        pnl = component.pnl
        if pnl is None:
            continue
        for _, ts_df in list(pnl.items()):
            if ts_df is None or ts_df.empty:
                continue
            ts_df.columns = ts_df.columns.map(_canon_label)


def filter_components_by_year(network: pypsa.Network, target_year: int) -> None:
    """Drop every dated component that is inactive in *target_year*.

    A component is **active** in ``target_year`` when:

        (build_year is NaN OR build_year ≤ target_year)
        AND (close_year is NaN OR close_year > target_year)

    A missing / NaN ``build_year`` is treated as "pre-existing" (always built),
    a missing / NaN ``close_year`` as "never closed".  Components whose tables
    don't carry a ``build_year`` column at all are left untouched.

    Walks every PyPSA component table via ``network.iterate_components()``.
    A table with no ``build_year`` column is left alone — so the filter
    applies wherever you put the date columns, with no hardcoded component
    list to maintain.

    Args:
        network:     PyPSA Network (modified in place).
        target_year: Simulation year — the year the assets must be active in.
    """
    for component in network.iterate_components():
        df = component.df
        if df.empty or "build_year" not in df.columns:
            continue

        build = pd.to_numeric(df["build_year"], errors="coerce")
        active = build.isna() | (build <= target_year)

        if "close_year" in df.columns:
            close = pd.to_numeric(df["close_year"], errors="coerce")
            active = active & (close.isna() | (close > target_year))

        total = len(df)
        inactive = df.index[~active]
        if len(inactive):
            network.remove(component.name, list(inactive))
            print(
                f"  Removed {len(inactive)} {component.list_name} inactive in {target_year}"
                f"  (active {total - len(inactive)} of {total})"
            )


def select_base_year_temporal(network: pypsa.Network, base_year: int) -> None:
    """Restrict snapshots to those in ``base_year``.

    Hook for workbooks that may eventually carry multi-year temporal data
    (e.g. ``loads_t.p_set`` covering both 2024 and 2025).  When the imported
    snapshots all fall inside ``base_year`` (today's KPG193 / Planned_Model
    files always do — they're single-year 2024 profiles) this is a no-op.

    Once a multi-year profile is plumbed through the workbook, this function
    will pick the ``base_year`` slice automatically.  Subsequent scaling
    (``scale_load``) and snapshot slicing (``slice_snapshots``) then operate
    on that slice.

    Args:
        network:   PyPSA Network (modified in place).
        base_year: Calendar year of the temporal profile to keep.
    """
    if len(network.snapshots) == 0:
        return

    try:
        years = pd.DatetimeIndex(network.snapshots).year
    except Exception:
        return   # snapshots aren't datetime-coercible — nothing to filter

    mask = years == base_year
    if mask.all():
        return   # already a single-year base_year profile — common case
    if not mask.any():
        print(
            f"  Base-year filter: no snapshots match base_year={base_year} "
            f"(available years: {sorted(set(years))}); keeping all snapshots"
        )
        return

    kept = network.snapshots[mask]
    network.set_snapshots(kept)
    print(
        f"  Base-year filter: kept {len(kept)} of {len(years)} snapshots "
        f"for base_year={base_year}"
    )


def build_network_for_year(excel_path: str, target_year: int) -> pypsa.Network:
    """Load the network from Excel and filter assets active in ``target_year``.

    Pipeline:

    1. ``pypsa.Network.import_from_excel``
    2. :func:`_normalize_names_to_str` (str-cast every index / bus reference)
    3. :func:`filter_components_by_year` (drop assets not active in
       ``target_year`` across generators, storage_units, stores, lines,
       transformers, and links)

    Temporal filtering by ``base_year`` is **not** done here — call
    :func:`select_base_year_temporal` after this if needed.

    Args:
        excel_path:  Path to the network Excel file (e.g.
                     ``Planned_Model_SH.xlsx`` or ``kpg193_pypsa_import.xlsx``).
        target_year: Simulation year.

    Returns:
        PyPSA Network with only the target-year-active components.
    """
    network = pypsa.Network()
    network.import_from_excel(excel_path)
    _normalize_names_to_str(network)
    filter_components_by_year(network, target_year)
    return network
