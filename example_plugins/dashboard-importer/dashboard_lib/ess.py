"""Add energy-storage (ESS) units at the buses where generator replacement happened.

Runs **immediately after** :func:`~dashboard_lib.generator_replacement.replace_generators`
and **before** region aggregation — so each ESS sits on the original replacement
bus and is carried onto its region bus by the aggregation's bus-remap, exactly
like any other component.

User input (``dashboard.settings``)
-----------------------------------
* ``add_ess`` — master toggle.
* ``ess_carrier`` — storage carrier name; **added to the network's carriers when
  it doesn't already exist**.
* ``ess_hours`` — energy/power ratio → ``StorageUnit.max_hours``.
* ``ess_efficiency`` — **round-trip** efficiency; split as ``√`` to
  ``efficiency_store`` and ``efficiency_dispatch`` (the battery convention).
* ``ess_sizing_mode`` — ``"proportional"`` (a % of the bus's total replaced
  generator capacity) or ``"fixed"`` (a flat MW per bus).
* ``ess_proportion_pct`` / ``ess_fixed_mw`` — the value for the chosen mode.
* ``ess_capital_cost`` — annualised capital cost per MW (drives expansion).
* ``ess_expandable`` — when True, ``p_nom_extendable = True`` with
  ``ess_p_nom_min`` / ``ess_p_nom_max`` (``0``/blank max → unbounded).

One StorageUnit ``ESS_<bus>`` is added per replacement bus. ``p_nom`` is the
sized capacity (the expansion *starting point* when extendable).

Algorithm:
    p_nom_b = ess_fixed_mw                                   (fixed)
    p_nom_b = replaced_capacity_b · ess_proportion_pct/100   (proportional)
    eta_store = eta_dispatch = sqrt(ess_efficiency)

Symbols (units):
    replaced_capacity_b   Σ original p_nom replaced at bus b   [MW]
    p_nom_b               ESS power rating at bus b            [MW]
    max_hours             energy/power ratio                  [h]
"""
from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import pandas as pd
import pypsa

if TYPE_CHECKING:
    from dashboard_lib.settings import Dashboard

logger = logging.getLogger(__name__)


def _unique_name(network: pypsa.Network, candidate: str) -> str:
    """Return *candidate* or a suffixed variant not already a storage-unit name."""
    if candidate not in network.storage_units.index:
        return candidate
    i = 2
    while f"{candidate}_{i}" in network.storage_units.index:
        i += 1
    return f"{candidate}_{i}"


def add_storage_at_replaced_buses(
    network: pypsa.Network,
    dashboard: "Dashboard",
    replaced_by_bus: dict[str, float],
) -> None:
    """Add one ESS StorageUnit per replacement bus, modifying *network* in place.

    No-op when ``settings.add_ess`` is False or nothing was replaced.

    Args:
        network:         PyPSA Network to modify in place.
        dashboard:       Parsed :class:`~dashboard_lib.settings.Dashboard`.
        replaced_by_bus: ``{bus: total replaced p_nom}`` from
            :func:`~dashboard_lib.generator_replacement.replace_generators`.
    """
    s = dashboard.settings
    if not getattr(s, "add_ess", False) or not replaced_by_bus:
        return

    carrier = str(getattr(s, "ess_carrier", "ESS") or "ESS").strip() or "ESS"
    if carrier not in network.carriers.index:
        network.add("Carrier", carrier)
        logger.info("ESS: added missing carrier %r", carrier)

    # Round-trip efficiency split √ into the per-direction efficiencies.
    rt = float(getattr(s, "ess_efficiency", 0.9) or 0.0)
    rt = min(max(rt, 0.0), 1.0)
    eff = math.sqrt(rt) if rt > 0 else 1.0

    mode = str(getattr(s, "ess_sizing_mode", "proportional") or "proportional").strip().lower()
    fixed_mw = float(getattr(s, "ess_fixed_mw", 0.0) or 0.0)
    proportion = float(getattr(s, "ess_proportion_pct", 0.0) or 0.0) / 100.0
    max_hours = float(getattr(s, "ess_hours", 4.0) or 0.0)
    capital_cost = float(getattr(s, "ess_capital_cost", 0.0) or 0.0)
    lifetime = float(getattr(s, "ess_lifetime", 15.0) or 15.0)
    expandable = bool(getattr(s, "ess_expandable", False))
    expansion_mode = str(getattr(s, "ess_expansion_mode", "proportional") or "proportional").strip().lower()
    p_nom_min_in = float(getattr(s, "ess_p_nom_min", 0.0) or 0.0)
    p_nom_max_in = float(getattr(s, "ess_p_nom_max", 0.0) or 0.0)

    def _bound(value: float, replaced_cap: float) -> float:
        """Resolve a min/max input to MW: a % of the bus's replaced capacity in
        proportional mode, else the value as-is (MW)."""
        return replaced_cap * value / 100.0 if expansion_mode == "proportional" else value

    # Province lookup so the ESS carries the bus's province (region aggregation
    # remaps by bus anyway, but a province keeps it consistent with its neighbours).
    bus_province = {}
    if "province" in network.buses.columns:
        bus_province = {
            str(b): str(network.buses.at[b, "province"])
            for b in network.buses.index
            if pd.notna(network.buses.at[b, "province"])
        }

    added = 0
    total_mw = 0.0
    for bus, replaced_cap in replaced_by_bus.items():
        bus = str(bus)
        if bus not in network.buses.index:
            continue
        p_nom = fixed_mw if mode == "fixed" else float(replaced_cap) * proportion
        p_nom = max(p_nom, 0.0)
        # Skip a zero-power, non-expandable ESS (nothing to model).
        if p_nom <= 0.0 and not expandable:
            continue

        name = _unique_name(network, f"ESS_{bus}")
        attrs: dict[str, object] = {
            "bus": bus,
            "carrier": carrier,
            "p_nom": p_nom,
            "max_hours": max_hours,
            "efficiency_store": eff,
            "efficiency_dispatch": eff,
            "capital_cost": capital_cost,
            # Finite lifetime so the backend annuitises the (overnight) capital
            # cost — PyPSA's default lifetime is +inf, which has no annuity.
            "lifetime": lifetime,
            "p_nom_extendable": bool(expandable),
        }
        if expandable:
            attrs["p_nom_min"] = _bound(p_nom_min_in, float(replaced_cap))
            # PyPSA treats a missing p_nom_max as +inf; only set a finite cap.
            if p_nom_max_in > 0.0:
                attrs["p_nom_max"] = _bound(p_nom_max_in, float(replaced_cap))
        network.add("StorageUnit", name, **attrs)
        if "province" in network.storage_units.columns and bus_province.get(bus):
            network.storage_units.at[name, "province"] = bus_province[bus]
        added += 1
        total_mw += p_nom

    sizing = f"fixed {fixed_mw:g} MW" if mode == "fixed" else f"{proportion * 100:g}% of replaced p_nom"
    if expandable:
        unit = "%" if expansion_mode == "proportional" else "MW"
        max_label = f"{p_nom_max_in:g}{unit}" if p_nom_max_in > 0 else "inf"
        exp = f", extendable [{p_nom_min_in:g}{unit}, {max_label}]"
    else:
        exp = ""
    logger.info(
        "ESS: added %d storage unit(s) (%.0f MW total) on '%s' carrier "
        "[%s, %g h, round-trip η=%.2f%s]",
        added, total_mw, carrier, sizing, max_hours, rt, exp,
    )
