"""Asset-swap / repowering what-if (DW2) — "profit of gas → solar?"

Retire a carrier and replace it, capacity-for-capacity, with another carrier at
the same buses; re-solve; and report the before-vs-after delta: system cost,
operating (fuel + carbon) cost, emissions, the replacement's capex, and a simple
payback. Answers the repowering decision as a number, with the assumptions
exposed.

The replacement inherits the target carrier's cost and (for a weather-driven
carrier) its availability profile from an existing generator of that carrier, so
a solar replacement is weather-limited rather than firm. If the target carrier
isn't in the model yet, user-supplied costs are used and the units are firm
(flagged via ``replacementFirm``).
"""
from __future__ import annotations

import copy
import logging
from typing import Any

import pypsa

from .finance import _crf

_log = logging.getLogger("pypsa.solver")

_DEFAULT_LIFETIME = 25.0


def _system_cost(net: pypsa.Network) -> float:
    return float(net.statistics.capex().sum() + net.statistics.opex().sum())


def _operating_cost(net: pypsa.Network) -> float:
    return float(net.statistics.opex().sum())


def _emissions(net: pypsa.Network, factors: dict[str, float]) -> float:
    if net.generators.empty or net.generators_t.p.empty:
        return 0.0
    w = net.snapshot_weightings["objective"].to_numpy()
    total = 0.0
    for g in net.generators.index:
        if g not in net.generators_t.p.columns:
            continue
        f = float(factors.get(str(net.generators.at[g, "carrier"]), 0.0))
        if f:
            total += f * float((net.generators_t.p[g].to_numpy() * w).sum())
    return total


def _profile_ref(model: dict[str, list[dict[str, Any]]], carrier: str) -> str | None:
    """Name of an existing generator of ``carrier`` that has a p_max_pu column."""
    pmax = model.get("generators-p_max_pu") or []
    if not pmax:
        return None
    cols = set().union(*[set(r.keys()) for r in pmax]) - {"snapshot", "name", "datetime", "timestamp"}
    for row in model.get("generators", []) or []:
        if str(row.get("carrier", "")) == carrier and str(row.get("name", "")) in cols:
            return str(row["name"])
    return None


def build_asset_swap(
    base_network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any],
    build_network,  # injected to avoid a circular import
    *,
    remove_carrier: str,
    add_carrier: str,
    add_capital_cost: float,
    add_marginal_cost: float,
    currency: str,
    emissions_factors: dict[str, float],
    solver_options: dict[str, Any] | None = None,
    io_api: str = "direct",
) -> dict[str, Any] | None:
    """Retire ``remove_carrier``, add ``add_carrier`` 1:1, re-solve, return the delta."""
    if not getattr(base_network, "is_solved", False):
        return None
    remove_carrier = (remove_carrier or "").strip()
    add_carrier = (add_carrier or "").strip()
    if not remove_carrier or not add_carrier:
        return None
    removed = [r for r in (model.get("generators") or []) if str(r.get("carrier", "")) == remove_carrier]
    if not removed:
        return None

    # Inherit the target carrier's cost/profile from an existing unit if present.
    existing_add = next((r for r in (model.get("generators") or []) if str(r.get("carrier", "")) == add_carrier), None)
    cap_cost = float(existing_add.get("capital_cost", add_capital_cost)) if existing_add else add_capital_cost
    marg_cost = float(existing_add.get("marginal_cost", add_marginal_cost)) if existing_add else add_marginal_cost
    profile_ref = _profile_ref(model, add_carrier)

    # Build the "after" model: drop removed carrier's gens, add 1:1 replacements.
    after = copy.deepcopy(model)
    after["generators"] = [r for r in after.get("generators", []) if str(r.get("carrier", "")) != remove_carrier]
    replacements: list[dict[str, Any]] = []
    removed_capacity = 0.0
    added_capacity = 0.0
    for r in removed:
        p_nom = float(r.get("p_nom", 0.0) or 0.0)
        removed_capacity += p_nom
        added_capacity += p_nom
        replacements.append({
            "name": f"{r.get('name')}_repl",
            "bus": r.get("bus"),
            "carrier": add_carrier,
            "p_nom": p_nom,
            "capital_cost": cap_cost,
            "marginal_cost": marg_cost,
        })
    after["generators"].extend(replacements)

    # Ensure the target carrier exists (zero-emission unless already declared).
    carriers = after.setdefault("carriers", [])
    if not any(str(c.get("name", "")) == add_carrier for c in carriers):
        carriers.append({"name": add_carrier})

    # Copy the target carrier's availability profile onto the replacements.
    replacement_firm = True
    if profile_ref:
        replacement_firm = False
        pmax_rows = after.get("generators-p_max_pu") or []
        for prow in pmax_rows:
            if profile_ref in prow:
                val = prow[profile_ref]
                for rep in replacements:
                    prow[rep["name"]] = val

    try:
        after_net, _ = build_network(after, scenario, options)
        after_net.optimize(
            solver_name="highs",
            solver_options=solver_options or {},
            io_api=io_api,
            include_objective_constant=False,
        )
    except Exception as exc:  # noqa: BLE001 — never sink the run over the what-if
        _log.warning("asset-swap re-solve failed (%s→%s): %s", remove_carrier, add_carrier, exc)
        return None
    if not getattr(after_net, "is_solved", False):
        return None

    before = {
        "systemCost": round(_system_cost(base_network), 2),
        "operatingCost": round(_operating_cost(base_network), 2),
        "emissionsTonnes": round(_emissions(base_network, emissions_factors), 2),
    }
    after_m = {
        "systemCost": round(_system_cost(after_net), 2),
        "operatingCost": round(_operating_cost(after_net), 2),
        "emissionsTonnes": round(_emissions(after_net, emissions_factors), 2),
    }
    delta = {
        "systemCost": round(after_m["systemCost"] - before["systemCost"], 2),
        "operatingCost": round(after_m["operatingCost"] - before["operatingCost"], 2),
        "emissionsTonnes": round(after_m["emissionsTonnes"] - before["emissionsTonnes"], 2),
    }

    annualised_capex = cap_cost * added_capacity
    r = float(scenario.get("discountRate", 0.0) or 0.0)
    overnight_capex = annualised_capex / _crf(r, _DEFAULT_LIFETIME) if annualised_capex > 0 else 0.0
    opex_savings = before["operatingCost"] - after_m["operatingCost"]
    payback = round(overnight_capex / opex_savings, 2) if opex_savings > 1e-9 and overnight_capex > 0 else None

    _log.info("asset-swap %s→%s: Δcost=%.1f Δemissions=%.1f", remove_carrier, add_carrier, delta["systemCost"], delta["emissionsTonnes"])
    return {
        "removeCarrier": remove_carrier,
        "addCarrier": add_carrier,
        "currency": currency,
        "removedCapacityMW": round(removed_capacity, 2),
        "addedCapacityMW": round(added_capacity, 2),
        "replacementCapex": round(annualised_capex, 2),
        "replacementFirm": replacement_firm,
        "before": before,
        "after": after_m,
        "delta": delta,
        "paybackYears": payback,
    }
