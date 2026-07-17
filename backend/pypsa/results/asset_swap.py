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

from ..utils.emissions import per_generator_emission_factor
from .finance import _crf
from .market import HOURS_PER_YEAR

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
    # Per-generator co2_emissions / η (thermal basis, M3): a swap that trades
    # efficiency (e.g. old gas → new CCGT) shows the true emissions delta.
    eff_ef = per_generator_emission_factor(net, factors)
    total = 0.0
    for g in net.generators.index:
        if g not in net.generators_t.p.columns:
            continue
        f = float(eff_ef.get(g, 0.0))
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


def _norm_filters(remove_filters: list[dict[str, Any]] | None, remove_carrier: str) -> list[dict[str, Any]]:
    """Normalise retire filters; fall back to a single carrier filter (legacy)."""
    out: list[dict[str, Any]] = []
    for f in remove_filters or []:
        field = str((f or {}).get("field", "")).strip()
        values = [str(v).strip() for v in ((f or {}).get("values") or []) if str(v).strip()]
        if field and values:
            out.append({"field": field, "values": values})
    if not out and remove_carrier.strip():
        out.append({"field": "carrier", "values": [remove_carrier.strip()]})
    return out


def build_asset_swap(
    base_network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any],
    build_network,  # injected to avoid a circular import
    *,
    remove_filters: list[dict[str, Any]] | None,
    remove_carrier: str,
    add_carrier: str,
    add_capital_cost: float,
    add_marginal_cost: float,
    replace_ratio: float = 1.0,
    add_storage_mw: float = 0.0,
    add_storage_hours: float = 4.0,
    add_storage_capex_per_mw: float = 0.0,
    currency: str,
    emissions_factors: dict[str, float],
    solver_options: dict[str, Any] | None = None,
    io_api: str = "direct",
) -> dict[str, Any] | None:
    """Retire the generators matching ``remove_filters`` (carrier/company/…),
    add ``add_carrier`` 1:1, re-solve, and return the delta."""
    if not getattr(base_network, "is_solved", False):
        return None
    add_carrier = (add_carrier or "").strip()
    filters = _norm_filters(remove_filters, remove_carrier)
    if not add_carrier or not filters:
        return None

    def _matches(r: dict[str, Any]) -> bool:
        # AND across filters; OR within a filter's values.
        return all(str(r.get(f["field"], "")).strip() in set(f["values"]) for f in filters)

    gens = model.get("generators") or []
    removed = [r for r in gens if _matches(r)]
    if not removed:
        return None
    removed_names = {str(r.get("name", "")) for r in removed}

    # Inherit the target carrier's cost/profile from an existing unit if present.
    existing_add = next((r for r in gens if str(r.get("carrier", "")) == add_carrier), None)
    cap_cost = float(existing_add.get("capital_cost", add_capital_cost)) if existing_add else add_capital_cost
    marg_cost = float(existing_add.get("marginal_cost", add_marginal_cost)) if existing_add else add_marginal_cost
    profile_ref = _profile_ref(model, add_carrier)

    # Build the "after" model: drop the matched gens, add replacements sized at
    # `replace_ratio` × the retired capacity (renewables often need oversizing).
    ratio = max(0.0, float(replace_ratio or 1.0))
    after = copy.deepcopy(model)
    after["generators"] = [r for r in after.get("generators", []) if str(r.get("name", "")) not in removed_names]
    replacements: list[dict[str, Any]] = []
    removed_capacity = 0.0
    added_capacity = 0.0
    bus_capacity: dict[str, float] = {}
    for r in removed:
        p_nom = float(r.get("p_nom", 0.0) or 0.0)
        removed_capacity += p_nom
        new_p = p_nom * ratio
        added_capacity += new_p
        bus_capacity[str(r.get("bus"))] = bus_capacity.get(str(r.get("bus")), 0.0) + p_nom
        replacements.append({
            "name": f"{r.get('name')}_repl",
            "bus": r.get("bus"),
            "carrier": add_carrier,
            "p_nom": new_p,
            "capital_cost": cap_cost,
            "marginal_cost": marg_cost,
        })
    after["generators"].extend(replacements)

    # Ensure the target carrier exists (zero-emission unless already declared).
    carriers = after.setdefault("carriers", [])
    if not any(str(c.get("name", "")) == add_carrier for c in carriers):
        carriers.append({"name": add_carrier})

    # Optional paired storage — a battery co-located with the new units, split
    # across the retired buses in proportion to the capacity retired there.
    storage_mw = max(0.0, float(add_storage_mw or 0.0))
    added_storage_mw = 0.0
    storage_capex = 0.0
    if storage_mw > 0 and removed_capacity > 0:
        if not any(str(c.get("name", "")) == "battery" for c in carriers):
            carriers.append({"name": "battery"})
        after_storage = after.setdefault("storage_units", [])
        for i, (bus, cap) in enumerate(bus_capacity.items()):
            mw = storage_mw * (cap / removed_capacity)
            if mw <= 0:
                continue
            added_storage_mw += mw
            after_storage.append({
                "name": f"__swap_ess_{i}",
                "bus": bus,
                "carrier": "battery",
                "p_nom": mw,
                "max_hours": max(0.5, float(add_storage_hours or 4.0)),
                "marginal_cost": 0.0,
                "capital_cost": float(add_storage_capex_per_mw or 0.0),
                "cyclic_state_of_charge": True,
            })
        storage_capex = added_storage_mw * float(add_storage_capex_per_mw or 0.0)

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
        _log.warning("asset-swap re-solve failed (→%s): %s", add_carrier, exc)
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

    annualised_capex = cap_cost * added_capacity + storage_capex
    r = float(scenario.get("discountRate", 0.0) or 0.0)
    overnight_capex = annualised_capex / _crf(r, _DEFAULT_LIFETIME) if annualised_capex > 0 else 0.0
    # ``statistics.opex()`` integrates over the modelled window of H represented
    # hours, so the saving is a window total; a payback in YEARS needs the
    # annual saving: × 8760/H.
    #   paybackYears = overnight_capex / (opex_savings_window · 8760/H)
    opex_savings = before["operatingCost"] - after_m["operatingCost"]
    H = float(base_network.snapshot_weightings["objective"].sum())
    annual_savings = opex_savings * (HOURS_PER_YEAR / H) if H > 0 else 0.0
    payback = round(overnight_capex / annual_savings, 2) if annual_savings > 1e-9 and overnight_capex > 0 else None

    remove_summary = " · ".join(f"{f['field']} ∈ {{{', '.join(f['values'])}}}" for f in filters)
    _log.info("asset-swap [%s]→%s ×%.2f +%.0fMW ess: Δcost=%.1f Δemissions=%.1f",
              remove_summary, add_carrier, ratio, added_storage_mw, delta["systemCost"], delta["emissionsTonnes"])
    return {
        "removeSummary": remove_summary,
        "removeFilters": filters,
        "removedCount": len(removed),
        "addCarrier": add_carrier,
        "replaceRatio": round(ratio, 3),
        "addedStorageMW": round(added_storage_mw, 2),
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
