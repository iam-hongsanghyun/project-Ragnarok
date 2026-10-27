"""Add energy-storage (ESS) units: at replacement buses, or at hand-picked groups.

Two entry points share the technical settings (carrier, hours, efficiency,
capital cost, lifetime):

* :func:`add_storage_at_replaced_buses` — one ESS per generator-replacement
  bus, sized from the replaced capacity (the original feature).
* :func:`add_storage_at_selected_buses` — one ESS per bus of each group picked
  in the ``ess_placement_rules`` table (fixed MW, possibly 0, or extendable).

Both run **before** region aggregation — so each ESS sits on its original bus
and is carried onto its region bus by the aggregation's bus-remap, exactly
like any other component.

User input (``dashboard.settings``)
-----------------------------------
* ``add_ess`` — master toggle.
* ``ess_carrier`` — storage carrier name; **added to the network's carriers when
  it doesn't already exist**.
* ``ess_hours`` — energy/power ratio → ``StorageUnit.max_hours``.
* ``ess_efficiency`` — **round-trip** efficiency as a fraction in (0, 1];
  split as ``√`` to ``efficiency_store`` and ``efficiency_dispatch`` (the
  battery convention). A value above 1 is read as a percent (``90`` → 0.9); 0,
  blank or anything unusable falls back to :data:`DEFAULT_ROUND_TRIP` and says
  so — it never silently becomes a lossless battery.
* ``ess_sizing_mode`` — ``"proportional"`` (a % of the bus's total replaced
  generator capacity) or ``"fixed"`` (a flat MW per bus).
* ``ess_proportion_pct`` / ``ess_fixed_mw`` — the value for the chosen mode.
* ``ess_capital_cost`` — **overnight** capital cost per MW of power (drives
  expansion). The backend annuitises it over ``ess_lifetime`` at the project
  discount rate, so this is *not* an annualised figure.
* ``ess_expandable`` — when True, ``p_nom_extendable = True`` with
  ``ess_p_nom_min`` / ``ess_p_nom_max`` (``0``/blank max → unbounded). An
  extendable ESS with **zero capital cost and no maximum** is free, unbounded
  storage; it is built (placeholders are a supported workflow) but logs a
  warning.

One StorageUnit ``ESS_<bus>`` is added per replacement bus. ``p_nom`` is the
sized capacity (the expansion *starting point* when extendable).

Algorithm:
    p_nom_b = ess_fixed_mw                                   (fixed)
    p_nom_b = replaced_capacity_b · ess_proportion_pct/100   (proportional)
    eta_store = eta_dispatch = sqrt(round_trip)      round_trip = resolve_round_trip(ess_efficiency)

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

DEFAULT_ROUND_TRIP = 0.9


def resolve_round_trip(raw: object) -> tuple[float, str | None]:
    """Round-trip efficiency as a fraction in (0, 1], plus a note when it was adjusted.

    * ``0 < x <= 1`` — used as given.
    * ``1 < x <= 100`` — a percent (``90`` → ``0.9``).
    * ``0``, blank, negative, > 100 or unparseable — :data:`DEFAULT_ROUND_TRIP`.

    The previous behaviour turned ``0`` into a lossless battery (η = 1) and
    clamped ``90`` to 1 — both silently.
    """
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        value = 0.0
    if math.isnan(value) or value <= 0.0:  # NaN, zero, negative
        return DEFAULT_ROUND_TRIP, (
            f"ESS round-trip efficiency {raw!r} is unset or not positive; "
            f"using the default {DEFAULT_ROUND_TRIP:g}"
        )
    if value <= 1.0:
        return value, None
    if value <= 100.0:
        return value / 100.0, f"ESS round-trip efficiency {value:g} read as {value:g}% = {value / 100.0:g}"
    return DEFAULT_ROUND_TRIP, (
        f"ESS round-trip efficiency {value:g} is out of range (0-1 or 1-100 %); "
        f"using the default {DEFAULT_ROUND_TRIP:g}"
    )


def _round_trip_setting(settings: object) -> float:
    rt, note = resolve_round_trip(getattr(settings, "ess_efficiency", DEFAULT_ROUND_TRIP))
    if note:
        logger.warning("%s", note)
        print(f"  {note}")
    return rt


def _warn_free_unbounded(expandable: bool, capital_cost: float, p_nom_max: float, where: str) -> None:
    """Warn loudly when an extendable ESS has no cost and no ceiling.

    That is free, unlimited storage: the optimiser builds as much as it likes.
    It stays a warning, not an error, because zero-cost placeholder units that
    the user prices later in the editor are a supported workflow.
    """
    if expandable and capital_cost <= 0.0 and p_nom_max <= 0.0:
        msg = (
            f"{where}: extendable ESS has zero capital cost and no maximum — the optimiser "
            "will treat it as unlimited free storage. Set ess_capital_cost > 0 or a maximum "
            "(ess_p_nom_max / the rule's capacity_mw) before solving."
        )
        logger.warning("%s", msg)
        print(f"  WARNING: {msg}")


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
    rt = _round_trip_setting(s)
    eff = math.sqrt(rt)

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
    _warn_free_unbounded(expandable, capital_cost, p_nom_max_in, "ESS at replaced buses")

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


# ---------------------------------------------------------------------------
# Placement at hand-picked buses/regions (ess_placement_rules table)
# ---------------------------------------------------------------------------

_PLACEMENT_COLUMNS = ("resolution", "value", "mode", "capacity_mw")
_PLACEMENT_MODES = ("fixed", "extendable")


def add_storage_at_selected_buses(network: pypsa.Network, dashboard: "Dashboard") -> None:
    """Add one ESS StorageUnit at every bus of each selected group, in place.

    Reads ``dashboard.settings.ess_placement`` (gate) and
    ``dashboard.ess_placement_rules`` (rules). Each rule selects a group
    (``resolution`` + ``value``, resolved exactly like the demand tables) and
    adds one unit **per bus** of the group:

    * ``fixed`` — every unit gets ``capacity_mw`` as its ``p_nom``. Zero is
      allowed on purpose: it creates editable placeholder units.
    * ``extendable`` — every unit starts at ``p_nom = 0`` with
      ``p_nom_extendable = True``; ``capacity_mw`` (> 0) becomes each unit's
      ``p_nom_max`` ceiling, 0/blank leaves the expansion unbounded.

    Carrier, duration, round-trip efficiency, capital cost, and lifetime come
    from the shared ESS settings (``ess_carrier`` / ``ess_hours`` /
    ``ess_efficiency`` / ``ess_capital_cost`` / ``ess_lifetime``).

    Args:
        network:   PyPSA Network to modify in place (before region aggregation).
        dashboard: Parsed :class:`~dashboard_lib.settings.Dashboard`.

    Raises:
        ValueError: On any invalid rule — missing columns, unknown bus/region
            or mode, or a missing/negative capacity. An ``extendable`` rule with
            zero capital cost and no ``capacity_mw`` ceiling only warns.
    """
    s = dashboard.settings
    if not getattr(s, "ess_placement", False):
        return

    rules_df = dashboard.ess_placement_rules
    if rules_df is None or rules_df.empty:
        print("  ESS placement: enabled but no rules provided — skipping")
        return

    # Resolution/value → bus set uses the demand tables' resolver. Imported
    # lazily: this module is also loaded standalone (no package context) by
    # the replacement-ESS path, which must not require the sibling module.
    from .demand_redistribution import _cell_str, _parse_amount, _resolve_member

    df = rules_df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in _PLACEMENT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"ESS placement table missing columns {missing}; found {list(df.columns)}"
        )

    carrier = str(getattr(s, "ess_carrier", "ESS") or "ESS").strip() or "ESS"
    if carrier not in network.carriers.index:
        network.add("Carrier", carrier)
        logger.info("ESS placement: added missing carrier %r", carrier)

    rt = _round_trip_setting(s)
    eff = math.sqrt(rt)
    max_hours = float(getattr(s, "ess_hours", 4.0) or 0.0)
    capital_cost = float(getattr(s, "ess_capital_cost", 0.0) or 0.0)
    lifetime = float(getattr(s, "ess_lifetime", 15.0) or 15.0)

    bus_province = {}
    if "province" in network.buses.columns:
        bus_province = {
            str(b): str(network.buses.at[b, "province"])
            for b in network.buses.index
            if pd.notna(network.buses.at[b, "province"])
        }

    region_cache: dict[str, dict[str, str]] = {}
    added = 0
    fixed_mw_total = 0.0
    for pos, (_, row) in enumerate(df.iterrows(), 1):
        resolution = _cell_str(row.get("resolution")).lower()
        value = _cell_str(row.get("value"))
        mode = _cell_str(row.get("mode")).lower()
        capacity_cell = _cell_str(row.get("capacity_mw"))

        # Skip wholly blank rows (the SDK can emit trailing empties).
        if not any((resolution, value, mode, capacity_cell)):
            continue

        label = f"rule {pos}"
        if not resolution or not value:
            raise ValueError(f"ESS placement {label}: resolution and value are required")
        if mode not in _PLACEMENT_MODES:
            raise ValueError(
                f"ESS placement {label}: mode must be one of {_PLACEMENT_MODES}, got {mode!r}"
            )
        capacity = _parse_amount(row.get("capacity_mw"))
        if capacity is None:
            capacity = 0.0
        if capacity < 0:
            raise ValueError(
                f"ESS placement {label}: capacity_mw must be >= 0, got {capacity}"
            )

        _warn_free_unbounded(
            mode == "extendable", capital_cost, capacity, f"ESS placement {label}"
        )
        buses = _resolve_member(
            network, dashboard, resolution, value, region_cache, label, "group"
        )
        for bus in sorted(buses):
            name = _unique_name(network, f"ESS_{bus}")
            attrs: dict[str, object] = {
                "bus": bus,
                "carrier": carrier,
                "p_nom": capacity if mode == "fixed" else 0.0,
                "max_hours": max_hours,
                "efficiency_store": eff,
                "efficiency_dispatch": eff,
                "capital_cost": capital_cost,
                # Finite lifetime so the backend annuitises the (overnight)
                # capital cost — PyPSA's default lifetime is +inf (no annuity).
                "lifetime": lifetime,
                "p_nom_extendable": mode == "extendable",
            }
            if mode == "extendable" and capacity > 0:
                attrs["p_nom_max"] = capacity
            network.add("StorageUnit", name, **attrs)
            if "province" in network.storage_units.columns and bus_province.get(bus):
                network.storage_units.at[name, "province"] = bus_province[bus]
            added += 1
            if mode == "fixed":
                fixed_mw_total += capacity
        cap_label = (
            f"{capacity:g} MW each"
            if mode == "fixed"
            else f"extendable [0, {capacity:g} MW]" if capacity > 0 else "extendable [0, inf]"
        )
        print(
            f"  ESS placement {label}: {len(buses)} unit(s) at "
            f"{resolution}={value!r} ({cap_label})"
        )

    logger.info(
        "ESS placement: added %d storage unit(s) (%.0f MW fixed total) on '%s' "
        "carrier [%g h, round-trip η=%.2f]",
        added, fixed_mw_total, carrier, max_hours, rt,
    )
