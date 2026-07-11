"""Scale or add demand for a group of buses/regions (dashboard-importer).

Complements :mod:`~dashboard_lib.demand_redistribution` (which *moves* energy
between groups, conserving the total): this module *changes* the total — grow
or shrink a region's demand by a ratio, or add/remove a flat MW or an annual
MWh amount.

Designed to run in the same pipeline slot as redistribution: **after**
:func:`~dashboard_lib.scaling.scale_load` (entered amounts are absolute and
final), **before** :func:`~dashboard_lib.region.aggregate_by_region` (groups
may be selected at any resolution) and **before** snapshot slicing (annual
amounts are full-year sums). Adjustments run after redistribution moves.

User input
----------
A single GUI table, ``dashboard.demand_adjust_rules``, with **one row per
adjustment**. Each row selects a group (``resolution`` + ``value``, same
semantics as redistribution) and applies ``mode`` with ``amount``:

=========== ========== ========== ============
resolution  value      mode       amount
=========== ========== ========== ============
group2      전남        multiply   1.10
bus         204        add_mw     100
province    강원        add_mwh    2_000_000
=========== ========== ========== ============

Rules apply sequentially in table order, so a later rule sees the effect of
earlier ones.

Algorithm:
    Let ``E`` be the group's annual energy, ``E_i`` member load *i*'s annual
    energy, and ``A`` the entered amount.

    * ``multiply`` — every demand cell of the group × ``A`` (``A > 0``)::

          $$ p_i(t) \\leftarrow A \\cdot p_i(t) $$

          p_i(t) <- A * p_i(t)

    * ``add_mw`` — the group total rises by ``A`` MW at **every snapshot**;
      each member gets a constant adder proportional to its share of the
      group's annual energy (so the inter-bus split of the added block matches
      the existing split)::

          $$ p_i(t) \\leftarrow p_i(t) + A \\cdot \\frac{E_i}{E} $$

          p_i(t) <- p_i(t) + A * E_i / E

    * ``add_mwh`` — the group's annual energy rises by ``A`` MWh via one
      uniform factor (identical math to the redistribution destination side;
      temporal shape and inter-bus split preserved)::

          $$ f = \\frac{E + A}{E}, \\qquad p_i(t) \\leftarrow f \\cdot p_i(t) $$

          f = (E + A) / E ;  p_i(t) <- f * p_i(t)

    Negative ``A`` decreases demand in both add modes; a rule that would push
    any demand cell below zero is rejected.

Symbols (units):
    A      entered amount — factor [-] for multiply, [MW] for add_mw,
           annual [MWh] for add_mwh
    E      group annual energy before the rule [MWh]
    E_i    member load i's annual energy before the rule [MWh]
    p_i(t) member load i's demand at snapshot t [MW]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd
import pypsa

from . import region as region_mod
from .demand_redistribution import (
    _cell_str,
    _group_energy,
    _member_loads,
    _parse_amount,
    _resolve_member,
    _scale_members,
)

if TYPE_CHECKING:
    from dashboard_lib.settings import Dashboard

_REQUIRED_COLUMNS = ("resolution", "value", "mode", "amount")
_MODES = ("multiply", "add_mw", "add_mwh")


@dataclass
class _Rule:
    """One adjustment rule resolved to a bus set, a mode, and an amount.

    Attributes:
        buses:  Bus names forming the adjusted group.
        mode:   One of ``multiply`` / ``add_mw`` / ``add_mwh``.
        amount: Factor (multiply), MW (add_mw), or annual MWh (add_mwh).
    """

    buses: set[str]
    mode: str
    amount: float


def adjust_demand(network: pypsa.Network, dashboard: "Dashboard") -> None:
    """Scale/add demand for bus/region groups, modifying *network* in place.

    Reads ``dashboard.settings.demand_adjustment`` (gate) and
    ``dashboard.demand_adjust_rules`` (rules). Rules are applied sequentially
    in table order, so a later rule sees the effect of earlier ones.

    Args:
        network:   PyPSA Network to modify in place. Expected after load
            scaling and redistribution, before region aggregation / snapshot
            slicing.
        dashboard: Parsed :class:`~dashboard_lib.settings.Dashboard`.

    Raises:
        ValueError: On any invalid rule — missing columns, unknown bus/region
            or mode, missing amount, non-positive multiply factor, a decrease
            exceeding the group's demand, or an add_mw that would push a
            demand cell below zero.
    """
    settings = dashboard.settings
    if not getattr(settings, "demand_adjustment", False):
        return

    rules_df = dashboard.demand_adjust_rules
    if rules_df is None or rules_df.empty:
        print("  Demand adjustment: enabled but no rules provided — skipping")
        return

    rules = _parse_rules(network, dashboard, rules_df)
    if not rules:
        print("  Demand adjustment: no valid rules found — skipping")
        return

    for i, rule in enumerate(rules, 1):
        _apply_rule(network, i, rule)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_rules(
    network: pypsa.Network,
    dashboard: "Dashboard",
    rules_df: pd.DataFrame,
) -> list[_Rule]:
    """Parse the rules table into a list of validated :class:`_Rule`."""
    df = rules_df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Demand adjustment table missing columns {missing}; "
            f"found {list(df.columns)}"
        )

    region_cache: dict[str, dict[str, str]] = {}

    rules: list[_Rule] = []
    for pos, (_, row) in enumerate(df.iterrows(), 1):
        resolution = _cell_str(row.get("resolution")).lower()
        value = _cell_str(row.get("value"))
        mode = _cell_str(row.get("mode")).lower()
        amount_cell = _cell_str(row.get("amount"))

        # Skip wholly blank rows (the SDK can emit trailing empties).
        if not any((resolution, value, mode, amount_cell)):
            continue

        label = f"rule {pos}"
        if not resolution or not value:
            raise ValueError(
                f"Demand adjustment {label}: resolution and value are required"
            )
        if mode not in _MODES:
            raise ValueError(
                f"Demand adjustment {label}: mode must be one of {_MODES}, "
                f"got {mode!r}"
            )
        amount = _parse_amount(row.get("amount"))
        if amount is None:
            raise ValueError(f"Demand adjustment {label}: amount is required")
        if mode == "multiply" and amount <= 0:
            raise ValueError(
                f"Demand adjustment {label}: multiply factor must be > 0, "
                f"got {amount}"
            )

        buses = _resolve_member(
            network, dashboard, resolution, value, region_cache, label, "group"
        )
        rules.append(_Rule(buses=buses, mode=mode, amount=amount))

    return rules


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def _add_flat_mw(
    network: pypsa.Network,
    member_loads: list[str],
    group_energy: float,
    amount_mw: float,
    idx: int,
) -> None:
    """Add a constant per-member MW slice of *amount_mw* to every snapshot.

    Member *i*'s adder is ``amount_mw * E_i / E`` — proportional to its share
    of the group's annual energy — so the group total rises by exactly
    *amount_mw* at each snapshot while the inter-bus split of the added block
    matches the existing split.
    """
    ts_df = getattr(network.loads_t, "p_set", None)
    snapshots = network.snapshots

    shares: dict[str, float] = {}
    for name in member_loads:
        series = region_mod._member_demand_series(network, name, ts_df, snapshots)
        shares[name] = float(series.sum()) / group_energy

    # Validate BEFORE mutating: a negative amount must not push any cell < 0.
    if amount_mw < 0:
        for name in member_loads:
            adder = amount_mw * shares[name]
            if ts_df is not None and name in ts_df.columns:
                new_min = float(ts_df[name].min()) + adder
            else:
                current = pd.to_numeric(network.loads.at[name, "p_set"], errors="coerce")
                new_min = (float(current) if pd.notna(current) else 0.0) + adder
            if new_min < 0:
                raise ValueError(
                    f"Demand adjustment rule {idx}: adding {amount_mw} MW would "
                    f"push load {name!r} below zero (min {new_min:.3f} MW)"
                )

    for name in member_loads:
        adder = amount_mw * shares[name]
        if ts_df is not None and name in ts_df.columns:
            network.loads_t.p_set[name] = ts_df[name] + adder
        elif "p_set" in network.loads.columns:
            current = pd.to_numeric(network.loads.at[name, "p_set"], errors="coerce")
            base = float(current) if pd.notna(current) else 0.0
            network.loads.at[name, "p_set"] = base + adder


def _apply_rule(network: pypsa.Network, idx: int, rule: _Rule) -> None:
    """Apply one adjustment rule to *network* in place."""
    member_loads = _member_loads(network, rule.buses)
    energy = _group_energy(network, member_loads)
    if energy <= 0:
        raise ValueError(
            f"Demand adjustment rule {idx}: group has no demand to adjust "
            f"(annual energy {energy:.1f} MWh)"
        )

    if rule.mode == "multiply":
        _scale_members(network, member_loads, rule.amount)
        print(f"  Demand adjustment rule {idx}: scaled group ×{rule.amount:.4f}")
        return

    if rule.mode == "add_mwh":
        if energy + rule.amount < 0:
            raise ValueError(
                f"Demand adjustment rule {idx}: removing {-rule.amount:.1f} MWh "
                f"exceeds the group's available {energy:.1f} MWh"
            )
        factor = (energy + rule.amount) / energy
        _scale_members(network, member_loads, factor)
        print(
            f"  Demand adjustment rule {idx}: {rule.amount:+.0f} MWh/yr "
            f"(×{factor:.4f})"
        )
        return

    # add_mw — flat MW on the group total, split by annual-energy share.
    _add_flat_mw(network, member_loads, energy, rule.amount, idx)
    print(f"  Demand adjustment rule {idx}: {rule.amount:+.1f} MW at every snapshot")
