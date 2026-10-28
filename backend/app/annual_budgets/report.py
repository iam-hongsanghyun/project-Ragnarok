"""Annual budgets read back from a solved network: the declared budget against what the solve achieved.

The module writes ``annual x sum(w)/8760`` into PyPSA (``__init__.compute_table``); after the solve this module
asks PyPSA what the budgeted quantity came to, so the results can show budget, achieved value and dual side by side:

* a generator ``e_sum_max`` / ``e_sum_min``: the generator's energy, ``n.statistics.supply`` (weighted by the
  ``generators`` snapshot weighting, the weighting ``e_sum`` itself uses). PyPSA stores no dual for ``e_sum``, so
  ``dual`` is ``None``.
* a ``primary_energy`` GlobalConstraint on ``co2_emissions``: the constraint's left-hand side,
  :func:`backend.app.emissions.primary_energy_emissions` (``E = sum w y p/eta ef``, the same terms PyPSA builds;
  in a pathway with ``investment_period`` only that period's rows). ``dual`` is ``global_constraints.mu``.
* any other target (an ``operational_limit`` or a primary-energy limit on another attribute): ``achieved`` is
  ``None`` and the row says so; nothing is estimated.
"""
from __future__ import annotations

import math
from typing import Any

import pypsa

from ...pypsa.results.stat_metrics import asset_statistic, combine_periods
from ..emissions import primary_energy_emissions

#: ``achieved`` is binding when it is within this relative distance of the written horizon value.
BINDING_RTOL = 1e-4


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _generator_energy(network: pypsa.Network, name: str) -> float | None:
    if name not in network.generators.index:
        return None
    energy = combine_periods(asset_statistic(network, "supply", ["Generator"]))
    if energy.empty:
        return None
    try:
        return float(energy.loc[("Generator", name)])
    except KeyError:
        return None


def _constraint_emissions(network: pypsa.Network, name: str) -> tuple[float | None, str]:
    """``(left-hand side, unit)`` of a CO2 ``primary_energy`` constraint, ``(None, reason)`` otherwise."""
    gc = network.global_constraints
    if name not in gc.index:
        return None, "constraint not in the run"
    row = gc.loc[name]
    if str(row.get("type", "")) != "primary_energy" or str(row.get("carrier_attribute", "")) != "co2_emissions":
        return None, "achieved value is reported for CO2 primary_energy constraints only"
    period = _finite(row.get("investment_period")) if "investment_period" in gc.columns else None
    target = network
    if period is not None and getattr(network, "has_investment_periods", False):
        from ...pypsa.results.derive_outputs import period_view_network

        target = period_view_network(network, int(period))
    return float(primary_energy_emissions(target).total), "tCO2"


def budget_report(network: pypsa.Network, table: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The declared budget table with ``achieved``, ``achievedUnit``, ``dual`` and ``binding`` per row.

    Args:
        network: the solved (or output-injected) network of the run.
        table: ``results["annualBudgets"]``: the module's table (``component``, ``name``, ``attribute``, ``annual``,
            ``horizonYears``, ``value``, ``scope``).

    Returns:
        One dict per row: the input keys plus ``achieved`` (``float | None``), ``achievedUnit`` (``"MWh"`` / ``"tCO2"`` or
        the reason it is missing), ``dual`` (``float | None``, currency per unit of the budget) and ``binding``
        (``bool | None``: the achieved value sits on the written bound).
    """
    out: list[dict[str, Any]] = []
    for entry in table:
        row = dict(entry)
        achieved: float | None = None
        unit = ""
        dual: float | None = None
        if row.get("component") == "generators":
            achieved, unit = _generator_energy(network, str(row["name"])), "MWh"
        elif row.get("component") == "global_constraints":
            achieved, unit = _constraint_emissions(network, str(row["name"]))
            gc = network.global_constraints
            if str(row["name"]) in gc.index and "mu" in gc.columns:
                dual = _finite(gc.at[str(row["name"]), "mu"])
        value = _finite(row.get("value"))
        row["achieved"] = achieved
        row["achievedUnit"] = unit
        row["dual"] = dual
        row["binding"] = (
            None if achieved is None or value is None
            else abs(achieved - value) <= BINDING_RTOL * max(abs(value), 1.0)
        )
        out.append(row)
    return out
