"""Asset-swap / repowering what-if (DW2) — "profit of gas → solar?"

Retire a carrier and replace it with another carrier at the same buses;
re-solve; and report the before-vs-after delta: system cost, operating (fuel +
carbon) cost, emissions, the replacement's capex, and a simple payback. Answers
the repowering decision as a number, with the assumptions exposed.

Two sizing modes:

* **Fixed** (default) — the replacement is built capacity-for-capacity at
  ``retired MW × replace_ratio`` and is *not* extendable, so the re-solve only
  redispatches it. ``p_nom_opt == p_nom`` by construction.
* **Sized** (``size_replacement=True``) — the replacement is extendable with
  ``p_nom_max = retired MW × replace_ratio``, so the ratio becomes a ceiling and
  the LP picks the build against the availability profile and CAPEX. This is the
  mode that answers "how much wind does it take to replace this coal?"

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

from ...app import carbon_pricing
from pypsa.costs import annuity as _pypsa_annuity

from ..utils.emissions import primary_energy_emissions
from .market import HOURS_PER_YEAR
from .stat_metrics import fixed_cost_of, fixed_cost_table, nyears_by_period, overnight_capex_table

_log = logging.getLogger("pypsa.solver")

_DEFAULT_LIFETIME = 25.0


def _truthy(value: Any) -> bool:
    """Sheet-cell truth test (``True`` / ``"TRUE"`` / ``1`` all count)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in ("true", "1", "yes")


def _system_cost(net: pypsa.Network) -> float:
    return float(net.statistics.capex().sum() + net.statistics.opex().sum())


def _operating_cost(net: pypsa.Network) -> float:
    return float(net.statistics.opex().sum())


def _emissions(net: pypsa.Network, factors: dict[str, float]) -> float:
    """System emissions (tCO2) on PyPSA's ``primary_energy`` basis (RB10).

    Generators p/eta * co2_emissions (signed, period-weighted in a pathway solve) plus
    non-cyclic StorageUnit/Store depletion - the same total as the reported run
    emissions, so a swap's delta is on the basis of the constraint it competes with.
    A swap that trades efficiency (old gas -> new CCGT) shows its true emissions delta.
    """
    if net.generators.empty and net.storage_units.empty and net.stores.empty:
        return 0.0
    return primary_energy_emissions(net, factors).total


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
    """Normalise retire filters; fall back to a single carrier filter.

    ``assetSwapConfig.removeCarrier`` is a kept back-compat alias for API clients
    (pre-``removeFilters``); the GUI sends ``removeFilters``. Pinned by
    ``test_asset_swap``.
    """
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
    size_replacement: bool = False,
    add_storage_mw: float = 0.0,
    add_storage_hours: float = 4.0,
    add_storage_capex_per_mw: float = 0.0,
    currency: str,
    emissions_factors: dict[str, float],
    solver_options: dict[str, Any] | None = None,
    io_api: str = "direct",
) -> dict[str, Any] | None:
    """Retire the generators matching ``remove_filters`` (carrier/company/…),
    add ``add_carrier`` in their place, re-solve, and return the delta.

    With ``size_replacement`` the replacement is extendable up to
    ``retired MW × replace_ratio`` and the LP chooses the build; otherwise it is
    fixed at that capacity.
    """
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
    marg_cost = float(existing_add.get("marginal_cost", add_marginal_cost)) if existing_add else add_marginal_cost
    profile_ref = _profile_ref(model, add_carrier)

    # CAPEX. The panel's cost inputs are PER YEAR (/MW/yr), a module input; the rows this module
    # sends to PyPSA are PyPSA's own columns, written visibly into the "after" model:
    #   * the replacement's capital_cost = the yearly input x n.nyears (PyPSA's per-horizon basis);
    #   * a target carrier that already exists in the model is inherited as is - its
    #     overnight_cost / discount_rate / lifetime / fom_cost, or its per-horizon capital_cost.
    # Nothing is annuitised here; the reported annual figures are read back from n.statistics.
    discount_rate = float(scenario.get("discountRate", 0.0) or 0.0)
    nyears = float(sum(nyears_by_period(base_network).values()) / max(1, len(nyears_by_period(base_network))))
    if existing_add:
        inherited_cost = {
            k: existing_add[k] for k in ("capital_cost", "overnight_cost", "discount_rate", "lifetime", "fom_cost")
            if k in existing_add and existing_add[k] not in (None, "")
        }
    else:
        inherited_cost = {"capital_cost": add_capital_cost * nyears}

    # Build the "after" model: drop the matched gens, add replacements sized at
    # `replace_ratio` × the retired capacity (renewables often need oversizing).
    # In sizing mode that product is the extendable unit's p_nom_max instead.
    ratio = max(0.0, float(replace_ratio or 1.0))
    after = copy.deepcopy(model)
    after["generators"] = [r for r in after.get("generators", []) if str(r.get("name", "")) not in removed_names]
    replacements: list[dict[str, Any]] = []
    removed_capacity = 0.0
    added_capacity = 0.0
    replacement_cap_mw = 0.0
    bus_capacity: dict[str, float] = {}
    for r in removed:
        p_nom = float(r.get("p_nom", 0.0) or 0.0)
        removed_capacity += p_nom
        new_p = p_nom * ratio
        replacement_cap_mw += new_p
        bus_capacity[str(r.get("bus"))] = bus_capacity.get(str(r.get("bus")), 0.0) + p_nom
        row: dict[str, Any] = {
            "name": f"{r.get('name')}_repl",
            "bus": r.get("bus"),
            "carrier": add_carrier,
            "p_nom": new_p,
            **inherited_cost,
            "marginal_cost": marg_cost,
        }
        if size_replacement:
            # The LP sizes it: start at zero, build up to the ratio ceiling.
            row.update({
                "p_nom": 0.0,
                "p_nom_extendable": True,
                "p_nom_min": 0.0,
                "p_nom_max": new_p,
            })
            row.setdefault("lifetime", _DEFAULT_LIFETIME)
        else:
            added_capacity += new_p
        replacements.append(row)
    after["generators"].extend(replacements)

    # Ensure the target carrier exists (zero-emission unless already declared).
    carriers = after.setdefault("carriers", [])
    if not any(str(c.get("name", "")) == add_carrier for c in carriers):
        carriers.append({"name": add_carrier})

    # Optional paired storage — a battery co-located with the new units, split
    # across the retired buses in proportion to the capacity retired there.
    storage_mw = max(0.0, float(add_storage_mw or 0.0))
    added_storage_mw = 0.0
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
                "capital_cost": float(add_storage_capex_per_mw or 0.0) * nyears,
                "cyclic_state_of_charge": True,
            })

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
            extra_functionality=carbon_pricing.extra_functionality,
        )
    except Exception as exc:  # noqa: BLE001 — never sink the run over the what-if
        _log.warning("asset-swap re-solve failed (→%s): %s", add_carrier, exc)
        return None
    if not getattr(after_net, "is_solved", False):
        return None

    # Sized mode: the built MW is a solve OUTPUT — read p_nom_opt back (a unit
    # the LP declined to build contributes 0, and PyPSA can return -0.0).
    if size_replacement:
        repl_names = [r["name"] for r in replacements]
        opt = after_net.generators["p_nom_opt"].reindex(repl_names).fillna(0.0)
        added_capacity = float(opt.clip(lower=0.0).sum())

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

    # The fixed charge of what the swap added, from n.statistics (per YEAR = / n.nyears).
    added_names = [r["name"] for r in replacements]
    added_ess = [r["name"] for r in after.get("storage_units", []) if str(r.get("name", "")).startswith("__swap_ess_")]
    fixed = fixed_cost_table(after_net, ["Generator", "StorageUnit"])
    annualised_capex = sum(fixed_cost_of(fixed, "Generator", n)["annual"] for n in added_names) + sum(
        fixed_cost_of(fixed, "StorageUnit", n)["annual"] for n in added_ess
    )
    overnight_all = overnight_capex_table(after_net, ["Generator", "StorageUnit"])
    resolved = [overnight_all.get(("Generator", n), float("nan")) for n in added_names] + [
        overnight_all.get(("StorageUnit", n), float("nan")) for n in added_ess
    ]
    if resolved and all(v == v for v in resolved):
        overnight_capex = float(sum(resolved))
    else:
        # PyPSA cannot back out an overnight cost from a per-horizon capital_cost without a
        # discount_rate / lifetime: use PyPSA's annuity at the run's rate over the default life.
        overnight_capex = (
            annualised_capex / float(_pypsa_annuity(discount_rate, _DEFAULT_LIFETIME)) if annualised_capex > 0 else 0.0
        )
    # ``statistics.opex()`` integrates over the modelled window of H represented
    # hours, so the saving is a window total; a payback in YEARS needs the
    # annual saving: × 8760/H.
    #   paybackYears = overnight_capex / (opex_savings_window · 8760/H)
    opex_savings = before["operatingCost"] - after_m["operatingCost"]
    H = float(base_network.snapshot_weightings["objective"].sum())
    annual_savings = opex_savings * (HOURS_PER_YEAR / H) if H > 0 else 0.0
    payback = round(overnight_capex / annual_savings, 2) if annual_savings > 1e-9 and overnight_capex > 0 else None

    remove_summary = " · ".join(f"{f['field']} ∈ {{{', '.join(f['values'])}}}" for f in filters)
    _log.info("asset-swap [%s]→%s %s×%.2f (%.0f MW built) +%.0fMW ess: Δcost=%.1f Δemissions=%.1f",
              remove_summary, add_carrier, "≤" if size_replacement else "", ratio, added_capacity,
              added_storage_mw, delta["systemCost"], delta["emissionsTonnes"])
    return {
        "removeSummary": remove_summary,
        "removeFilters": filters,
        "removedCount": len(removed),
        "addCarrier": add_carrier,
        "replaceRatio": round(ratio, 3),
        "sizedReplacement": bool(size_replacement),
        "addedStorageMW": round(added_storage_mw, 2),
        "currency": currency,
        "removedCapacityMW": round(removed_capacity, 2),
        "addedCapacityMW": round(added_capacity, 2),
        "replacementCapMW": round(replacement_cap_mw, 2),
        "replacementCapex": round(annualised_capex, 2),
        "replacementFirm": replacement_firm,
        "before": before,
        "after": after_m,
        "delta": delta,
        "paybackYears": payback,
    }
