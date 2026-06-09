"""Redistribute a fixed annual demand (MWh) between groups of buses/regions.

Designed to run **after** :func:`~dashboard_lib.scaling.scale_load` (so the
entered MWh amounts are absolute and final) and **before**
:func:`~dashboard_lib.region.aggregate_by_region` (so a user may select each
end of a move at *any* resolution — individual buses, province, or any group
column — independently of whether/how region aggregation is enabled) and
**before** snapshot slicing (so an annual MWh is the sum over the full year).

User input
----------
A single GUI table, ``dashboard.demand_redist_rules``, with **one row per
move**.  Each row moves ``amount_mwh`` of annual demand from a source
(``from_resolution`` + ``from_value``) to a destination (``to_resolution`` +
``to_value``).  The two ends are independent and may use different resolutions:

=============== ========== ============= ========== ============
from_resolution from_value  to_resolution to_value   amount_mwh
=============== ========== ============= ========== ============
bus             204         group2        전남        5_000_000
group1          수도권       province      강원        2_000_000
=============== ========== ============= ========== ============

* ``*_resolution`` — ``bus`` matches an exact bus name; any other value
  (``province`` / ``group1`` / ``group2`` / ``group3`` / ``singlenode``) is
  resolved to a set of buses through ``dashboard.province_mapping`` using the
  same logic as region aggregation.
* ``*_value`` — the bus name, or the region label produced by that resolution.
* ``amount_mwh`` — annual MWh moved by this row's move (> 0).

Moves are applied sequentially in table order, so a later move sees the effect
of earlier ones.

Algorithm:
    Let ``X`` be the MWh to move, ``D`` the source group's current annual
    energy and ``I`` the destination group's.  Every per-snapshot demand cell
    of the source group is multiplied by ``f_dec``; the destination group by
    ``f_inc``::

        $$ f_{dec} = \\frac{D - X}{D}, \\qquad f_{inc} = \\frac{I + X}{I} $$

        f_dec = (D - X) / D
        f_inc = (I + X) / I

    A single uniform factor per group is exactly "distribute proportionally to
    the current temporal demand": each cell loses/gains in proportion to its
    present value, so the temporal shape and the inter-bus split within the
    group are preserved.  Energy is conserved: ``-X`` removed, ``+X`` added.

Symbols (units):
    X      annual energy moved by the move           [MWh]
    D, I   group annual energy before the move        [MWh]
    f_*    dimensionless scale factor applied to every demand cell of a group
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd
import pypsa

from . import region as region_mod

if TYPE_CHECKING:
    from dashboard_lib.settings import Dashboard

_REQUIRED_COLUMNS = (
    "from_resolution",
    "from_value",
    "to_resolution",
    "to_value",
    "amount_mwh",
)


@dataclass
class _Move:
    """One redistribution move resolved to bus sets and an amount.

    Attributes:
        source: Bus names forming the source group (demand removed).
        dest:   Bus names forming the destination group (demand added).
        amount: Annual MWh moved from source to destination (> 0).
    """

    source: set[str]
    dest: set[str]
    amount: float


def redistribute_demand(network: pypsa.Network, dashboard: "Dashboard") -> None:
    """Move annual demand between bus/region groups, modifying *network* in place.

    Reads ``dashboard.settings.demand_redistribution`` (gate) and
    ``dashboard.demand_redist_rules`` (moves).  Moves are applied sequentially
    in table order, so a later move sees the effect of earlier ones.

    Args:
        network:   PyPSA Network to modify in place.  Expected after load
            scaling and before region aggregation / snapshot slicing.
        dashboard: Parsed :class:`~dashboard_lib.settings.Dashboard`.

    Raises:
        ValueError: On any invalid move — missing columns, unknown bus/region,
            blank from/to, non-positive or missing amount, an amount exceeding
            the source group's energy, or overlapping source/destination.
    """
    settings = dashboard.settings
    if not getattr(settings, "demand_redistribution", False):
        return

    rules_df = dashboard.demand_redist_rules
    if rules_df is None or rules_df.empty:
        print("  Demand redistribution: enabled but no moves provided — skipping")
        return

    moves = _parse_moves(network, dashboard, rules_df)
    if not moves:
        print("  Demand redistribution: no valid moves found — skipping")
        return

    for i, move in enumerate(moves, 1):
        _apply_move(network, i, move)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_moves(
    network: pypsa.Network,
    dashboard: "Dashboard",
    rules_df: pd.DataFrame,
) -> list[_Move]:
    """Parse the moves table into a list of validated :class:`_Move`.

    Each non-blank row is one move: its ``from``/``to`` ends are resolved to bus
    sets (caching bus↔region maps per resolution) and its amount validated.
    """
    df = rules_df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Demand redistribution table missing columns {missing}; "
            f"found {list(df.columns)}"
        )

    # Cache bus<->region resolution per resolution column (built lazily).
    region_cache: dict[str, dict[str, str]] = {}

    moves: list[_Move] = []
    for pos, (_, row) in enumerate(df.iterrows(), 1):
        from_res = _cell_str(row.get("from_resolution")).lower()
        from_val = _cell_str(row.get("from_value"))
        to_res = _cell_str(row.get("to_resolution")).lower()
        to_val = _cell_str(row.get("to_value"))
        amount_cell = _cell_str(row.get("amount_mwh"))

        # Skip wholly blank rows (the SDK can emit trailing empties).
        if not any((from_res, from_val, to_res, to_val, amount_cell)):
            continue

        label = f"move {pos}"
        if not from_res or not from_val:
            raise ValueError(
                f"Demand redistribution {label}: 'from' resolution and value are required"
            )
        if not to_res or not to_val:
            raise ValueError(
                f"Demand redistribution {label}: 'to' resolution and value are required"
            )
        amount = _parse_amount(row.get("amount_mwh"))
        if amount is None:
            raise ValueError(f"Demand redistribution {label}: amount_mwh is required")
        if amount <= 0:
            raise ValueError(
                f"Demand redistribution {label}: amount_mwh must be > 0, got {amount}"
            )

        source = _resolve_member(network, dashboard, from_res, from_val, region_cache, label, "from")
        dest = _resolve_member(network, dashboard, to_res, to_val, region_cache, label, "to")
        overlap = source & dest
        if overlap:
            raise ValueError(
                f"Demand redistribution {label}: bus(es) {sorted(overlap)} appear "
                f"in both the 'from' and 'to' group"
            )
        moves.append(_Move(source=source, dest=dest, amount=amount))

    return moves


def _cell_str(raw: object) -> str:
    """Coerce a table cell to a trimmed string; NaN/None become ``""``."""
    if raw is None:
        return ""
    if isinstance(raw, float) and raw != raw:  # NaN
        return ""
    return str(raw).strip()


def _parse_amount(raw: object) -> float | None:
    """Parse an ``amount_mwh`` cell to float; ``None`` when blank/NaN."""
    if raw is None:
        return None
    if isinstance(raw, float) and raw != raw:  # NaN
        return None
    text = str(raw).strip()
    if not text:
        return None
    value = pd.to_numeric(text, errors="coerce")
    if pd.isna(value):
        raise ValueError(f"Demand redistribution: amount_mwh {raw!r} is not a number")
    return float(value)


def _resolve_member(
    network: pypsa.Network,
    dashboard: "Dashboard",
    resolution: str,
    value: str,
    region_cache: dict[str, dict[str, str]],
    label: str,
    side: str,
) -> set[str]:
    """Resolve one (resolution, value) end to the set of matching bus names."""
    if resolution == "bus":
        if value not in network.buses.index:
            raise ValueError(
                f"Demand redistribution {label} ({side}): bus {value!r} "
                f"not found in the network"
            )
        return {value}

    if dashboard.province_mapping is None and resolution != "province":
        raise ValueError(
            f"Demand redistribution {label} ({side}): resolution "
            f"{resolution!r} needs a province_mapping table (none provided)"
        )

    bus_to_region = region_cache.get(resolution)
    if bus_to_region is None:
        prov_to_region, _ = region_mod._build_province_to_region(
            dashboard.province_mapping, resolution
        )
        bus_to_region = region_mod._build_bus_to_region(network, prov_to_region)
        region_cache[resolution] = bus_to_region

    matches = {bus for bus, region in bus_to_region.items() if region == value}
    if not matches:
        raise ValueError(
            f"Demand redistribution {label} ({side}): no buses match "
            f"resolution={resolution!r} value={value!r}"
        )
    return matches


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def _member_loads(network: pypsa.Network, bus_set: set[str]) -> list[str]:
    """Return the load names whose bus is in *bus_set*."""
    loads = network.loads
    if loads.empty or "bus" not in loads.columns:
        return []
    return [name for name in loads.index if str(loads.at[name, "bus"]) in bus_set]


def _group_energy(network: pypsa.Network, member_loads: list[str]) -> float:
    """Total annual energy of *member_loads* (MWh, full-year column sums).

    Uses :func:`region._member_demand_series` so static-only loads (broadcast
    across snapshots) and time-series loads are accounted identically.
    """
    ts_df = getattr(network.loads_t, "p_set", None)
    snapshots = network.snapshots
    total = 0.0
    for name in member_loads:
        series = region_mod._member_demand_series(network, name, ts_df, snapshots)
        total += float(series.sum())
    return total


def _scale_members(network: pypsa.Network, member_loads: list[str], factor: float) -> None:
    """Multiply every member load's demand by *factor* in place.

    Time-series members scale their ``loads_t.p_set`` column; static-only
    members scale their ``network.loads.p_set`` value.  A uniform factor scales
    the group's total energy by the same factor while preserving every cell's
    relative contribution (temporal shape and inter-bus split).
    """
    ts_df = getattr(network.loads_t, "p_set", None)
    for name in member_loads:
        if ts_df is not None and name in ts_df.columns:
            network.loads_t.p_set[name] = ts_df[name] * factor
        elif "p_set" in network.loads.columns:
            current = pd.to_numeric(network.loads.at[name, "p_set"], errors="coerce")
            network.loads.at[name, "p_set"] = float(current) * factor if pd.notna(current) else 0.0


def _apply_move(network: pypsa.Network, idx: int, move: _Move) -> None:
    """Apply one redistribution move to *network* in place."""
    amount = move.amount

    dec_loads = _member_loads(network, move.source)
    inc_loads = _member_loads(network, move.dest)

    energy_dec = _group_energy(network, dec_loads)
    energy_inc = _group_energy(network, inc_loads)

    if energy_dec <= 0:
        raise ValueError(
            f"Demand redistribution move {idx}: 'from' group has no demand "
            f"to move (annual energy {energy_dec:.1f} MWh)"
        )
    if amount > energy_dec:
        raise ValueError(
            f"Demand redistribution move {idx}: amount {amount:.1f} MWh exceeds "
            f"the 'from' group's available {energy_dec:.1f} MWh"
        )
    if energy_inc <= 0:
        raise ValueError(
            f"Demand redistribution move {idx}: 'to' group has no demand to "
            f"scale proportionally (annual energy {energy_inc:.1f} MWh)"
        )

    f_dec = (energy_dec - amount) / energy_dec
    f_inc = (energy_inc + amount) / energy_inc

    _scale_members(network, dec_loads, f_dec)
    _scale_members(network, inc_loads, f_inc)

    print(
        f"  Demand redistribution move {idx}: moved {amount:.0f} MWh "
        f"(from ×{f_dec:.4f}, to ×{f_inc:.4f})"
    )
