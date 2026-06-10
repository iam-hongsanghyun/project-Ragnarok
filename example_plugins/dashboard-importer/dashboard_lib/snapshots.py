"""Snapshot window slicing for PyPSA networks."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pypsa

# Accepted snapshot-start formats. ISO (with a ``T`` or a space) is primary;
# the legacy ``dd/mm/yyyy HH:MM`` is still accepted for old configs.
_START_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M")


def _parse_start(start: str) -> datetime:
    """Parse a snapshot-start string. Prefers ISO (``YYYY-MM-DDTHH:MM``)."""
    s = str(start).strip()
    try:
        return datetime.fromisoformat(s)  # 'YYYY-MM-DDTHH:MM' and with a space
    except ValueError:
        pass
    for fmt in _START_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Unrecognised snapshot start {start!r}; use ISO format 'YYYY-MM-DDTHH:MM' "
        f"(e.g. 2030-01-01T00:00)"
    )


def _relabel_snapshots(network: pypsa.Network, new_index: pd.DatetimeIndex) -> None:
    """Rename the snapshot index to *new_index* in place, preserving all data.

    ``set_snapshots`` realigns time-varying data by label (new labels → NaN), so
    instead we overwrite the index of ``snapshot_weightings`` and every dynamic
    frame directly. ``network.snapshots`` is derived from
    ``snapshot_weightings.index``, so it picks up the new dates automatically.
    """
    network.snapshot_weightings.index = new_index
    for component in network.iterate_components():
        dynamic = getattr(component, "dynamic", None)
        if dynamic is None:
            dynamic = getattr(component, "pnl", None)
        if not dynamic:
            continue
        for df in dynamic.values():
            if df is not None and len(df.index) == len(new_index):
                df.index = new_index


def slice_snapshots(network: pypsa.Network, start: str, length: int) -> None:
    """Slice to a window and re-date it to the year in *start*.

    The model's temporal data lives in the base year (e.g. 2024). This selects
    a window starting at *start*'s month/day/hour (so the right profile is
    used), then **re-dates** the window to a contiguous hourly range beginning
    at *start* itself — so the output snapshots carry the year the user asked
    for (e.g. 2030), not the base year.

    Args:
        network: PyPSA Network to modify in place.
        start: Snapshot start timestamp, ISO ``YYYY-MM-DDTHH:MM`` (legacy
            ``dd/mm/yyyy HH:MM`` also accepted).
        length: Number of snapshots (hours) to retain.

    Raises:
        ValueError: When *start* is unparseable, or no snapshot matches its
            month/day/hour.
    """
    dt = _parse_start(start)

    # Model snapshot labels are day-first strings (e.g. "13/1/2024 0:00").
    idx = pd.to_datetime(network.snapshots, dayfirst=True)
    matches = (idx.month == dt.month) & (idx.day == dt.day) & (idx.hour == dt.hour)
    if not matches.any():
        raise ValueError(
            f"No snapshot matching month={dt.month} day={dt.day} hour={dt.hour}"
        )

    pos = int(matches.argmax())
    # Select the window (subset of existing labels → data preserved).
    network.snapshots = network.snapshots[pos : pos + length]

    # Re-date the window to a contiguous hourly range starting at `dt`, so the
    # snapshots carry the requested year instead of the base year.
    new_index = pd.date_range(start=dt, periods=len(network.snapshots), freq="h")
    new_index.name = network.snapshots.name or "snapshot"
    _relabel_snapshots(network, new_index)

    print(
        f"  Snapshots sliced: {dt.isoformat()} + {length}h  "
        f"(source index {pos}–{pos + len(new_index) - 1}, re-dated to {dt.year})"
    )
