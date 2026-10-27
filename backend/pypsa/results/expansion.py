"""Capacity expansion result extraction helpers.

Called after network.optimize() has solved.  Returns the `expansionResults`
payload that the frontend uses to render the Capacity Expansion section.
"""
from __future__ import annotations

import math
from typing import Any

import pypsa

from .market import capex_window_scale
from .pathway_periods import active_assets, is_pathway, period_objective_weights, periods


def _safe_number(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return fallback if math.isnan(number) else number


def build_expansion_results(network: pypsa.Network) -> list[dict[str, Any]]:
    """Return a list of expansion result dicts for all extendable assets.

    Each dict contains:
        name          – component name
        component     – 'Generator' | 'StorageUnit'
        carrier       – carrier string
        bus           – bus name
        p_nom_mw      – installed / fixed capacity (workbook value)
        p_nom_opt_mw  – optimised capacity from PyPSA
        delta_mw      – p_nom_opt − p_nom  (positive = new build)
        capital_cost  – annualised capital cost ($/MW/yr from network)
        capex_annual  – capital_cost × p_nom_opt  (total annual CAPEX, $)

    Multi-investment (pathway) runs add, per row:
        active_periods   – investment periods in which the asset exists
                           (``build_year <= period < build_year + lifetime``)
        capex_by_period  – ``{period: annual CAPEX}``, 0 outside active periods
        capex_weighted   – Σ_p objective_weight(p) × capex_by_period[p], the
                           CAPEX term of the LP objective

    When the solve engineer recorded ``ragnarok_capex_window_scale`` the LP's
    ``capital_cost`` was already scaled to the modelled window; ``capital_cost``
    and ``capex_annual`` are reported back on the annual basis.
    """
    results: list[dict[str, Any]] = []

    # ── Generators ────────────────────────────────────────────────────────────
    ext_gen = network.generators[network.generators.p_nom_extendable]
    for name in ext_gen.index:
        p_nom = _safe_number(ext_gen.at[name, "p_nom"])
        p_nom_opt = _safe_number(ext_gen.at[name, "p_nom_opt"], p_nom)
        capital_cost = _safe_number(ext_gen.at[name, "capital_cost"])
        results.append(
            {
                "name": name,
                "component": "Generator",
                "carrier": str(ext_gen.at[name, "carrier"]),
                "bus": str(ext_gen.at[name, "bus"]),
                "p_nom_mw": round(p_nom, 1),
                "p_nom_opt_mw": round(p_nom_opt, 1),
                "delta_mw": round(p_nom_opt - p_nom, 1),
                "capital_cost": round(capital_cost, 2),
                "capex_annual": round(capital_cost * p_nom_opt),
            }
        )

    # ── Storage units ─────────────────────────────────────────────────────────
    if not network.storage_units.empty:
        ext_su = network.storage_units[network.storage_units.p_nom_extendable]
        for name in ext_su.index:
            p_nom = _safe_number(ext_su.at[name, "p_nom"])
            p_nom_opt = _safe_number(ext_su.at[name, "p_nom_opt"], p_nom)
            capital_cost = _safe_number(ext_su.at[name, "capital_cost"])
            results.append(
                {
                    "name": name,
                    "component": "StorageUnit",
                    "carrier": str(ext_su.at[name, "carrier"]),
                    "bus": str(ext_su.at[name, "bus"]),
                    "p_nom_mw": round(p_nom, 1),
                    "p_nom_opt_mw": round(p_nom_opt, 1),
                    "delta_mw": round(p_nom_opt - p_nom, 1),
                    "capital_cost": round(capital_cost, 2),
                    "capex_annual": round(capital_cost * p_nom_opt),
                }
            )

    # ── Stores (energy capacity optimisation) ────────────────────────────────
    if not network.stores.empty and "e_nom_extendable" in network.stores.columns:
        ext_st = network.stores[network.stores.e_nom_extendable]
        for name in ext_st.index:
            e_nom = _safe_number(ext_st.at[name, "e_nom"])
            e_nom_opt = _safe_number(ext_st.at[name, "e_nom_opt"], e_nom) if "e_nom_opt" in ext_st.columns else e_nom
            capital_cost = _safe_number(ext_st.at[name, "capital_cost"]) if "capital_cost" in ext_st.columns else 0.0
            results.append(
                {
                    "name": name,
                    "component": "Store",
                    "carrier": str(ext_st.at[name, "carrier"]) if "carrier" in ext_st.columns else "",
                    "bus": str(ext_st.at[name, "bus"]),
                    "p_nom_mw": round(e_nom, 1),
                    "p_nom_opt_mw": round(e_nom_opt, 1),
                    "delta_mw": round(e_nom_opt - e_nom, 1),
                    "capital_cost": round(capital_cost, 2),
                    "capex_annual": round(capital_cost * e_nom_opt),
                    "unit": "MWh",
                }
            )

    # ── Links (p_nom_extendable) ───────────────────────────────────────────────
    if not network.links.empty and "p_nom_extendable" in network.links.columns:
        ext_li = network.links[network.links.p_nom_extendable]
        for name in ext_li.index:
            p_nom = _safe_number(ext_li.at[name, "p_nom"])
            p_nom_opt = _safe_number(ext_li.at[name, "p_nom_opt"], p_nom) if "p_nom_opt" in ext_li.columns else p_nom
            capital_cost = _safe_number(ext_li.at[name, "capital_cost"]) if "capital_cost" in ext_li.columns else 0.0
            results.append(
                {
                    "name": name,
                    "component": "Link",
                    "carrier": str(ext_li.at[name, "carrier"]) if "carrier" in ext_li.columns else "",
                    "bus": str(ext_li.at[name, "bus0"]),
                    "p_nom_mw": round(p_nom, 1),
                    "p_nom_opt_mw": round(p_nom_opt, 1),
                    "delta_mw": round(p_nom_opt - p_nom, 1),
                    "capital_cost": round(capital_cost, 2),
                    "capex_annual": round(capital_cost * p_nom_opt),
                }
            )

    # ── Lines (s_nom_extendable) ───────────────────────────────────────────────
    if not network.lines.empty and "s_nom_extendable" in network.lines.columns:
        ext_ln = network.lines[network.lines.s_nom_extendable]
        for name in ext_ln.index:
            s_nom = _safe_number(ext_ln.at[name, "s_nom"])
            s_nom_opt = _safe_number(ext_ln.at[name, "s_nom_opt"], s_nom) if "s_nom_opt" in ext_ln.columns else s_nom
            capital_cost = _safe_number(ext_ln.at[name, "capital_cost"]) if "capital_cost" in ext_ln.columns else 0.0
            results.append(
                {
                    "name": name,
                    "component": "Line",
                    "carrier": "",
                    "bus": str(ext_ln.at[name, "bus0"]),
                    "p_nom_mw": round(s_nom, 1),
                    "p_nom_opt_mw": round(s_nom_opt, 1),
                    "delta_mw": round(s_nom_opt - s_nom, 1),
                    "capital_cost": round(capital_cost, 2),
                    "capex_annual": round(capital_cost * s_nom_opt),
                    "unit": "MVA",
                }
            )

    # ── Transformers (s_nom_extendable) ───────────────────────────────────────
    if not network.transformers.empty and "s_nom_extendable" in network.transformers.columns:
        ext_tr = network.transformers[network.transformers.s_nom_extendable]
        for name in ext_tr.index:
            s_nom = _safe_number(ext_tr.at[name, "s_nom"])
            s_nom_opt = _safe_number(ext_tr.at[name, "s_nom_opt"], s_nom) if "s_nom_opt" in ext_tr.columns else s_nom
            capital_cost = _safe_number(ext_tr.at[name, "capital_cost"]) if "capital_cost" in ext_tr.columns else 0.0
            results.append(
                {
                    "name": name,
                    "component": "Transformer",
                    "carrier": "",
                    "bus": str(ext_tr.at[name, "bus0"]),
                    "p_nom_mw": round(s_nom, 1),
                    "p_nom_opt_mw": round(s_nom_opt, 1),
                    "delta_mw": round(s_nom_opt - s_nom, 1),
                    "capital_cost": round(capital_cost, 2),
                    "capex_annual": round(capital_cost * s_nom_opt),
                    "unit": "MVA",
                }
            )

    _apply_window_scale(network, results)
    _annotate_pathway(network, results)
    return results


_LIST_NAME = {
    "Generator": "generators",
    "StorageUnit": "storage_units",
    "Store": "stores",
    "Link": "links",
    "Line": "lines",
    "Transformer": "transformers",
}


def _apply_window_scale(network: pypsa.Network, results: list[dict[str, Any]]) -> None:
    """Undo the solve's window scaling so ``capital_cost`` / ``capex_annual`` stay annual."""
    scale = capex_window_scale(network)
    if scale is None or scale <= 0:
        return
    for row in results:
        row["capital_cost"] = round(row["capital_cost"] / scale, 2)
        row["capex_annual"] = round(row["capex_annual"] / scale)


def _annotate_pathway(network: pypsa.Network, results: list[dict[str, Any]]) -> None:
    """Add active periods and per-period / objective-weighted CAPEX (pathway runs)."""
    if not is_pathway(network):
        return
    weights = period_objective_weights(network)
    masks = {
        list_name: {p: active_assets(network, list_name, p) for p in periods(network)}
        for list_name in set(_LIST_NAME.values())
    }
    for row in results:
        per_period = masks[_LIST_NAME[row["component"]]]
        # `capex_annual` here is already capital_cost x p_nom_opt of the (single) asset.
        by_period = {
            p: float(row["capex_annual"]) if bool(mask.get(row["name"], True)) else 0.0
            for p, mask in per_period.items()
        }
        row["active_periods"] = [p for p, v in by_period.items() if bool(per_period[p].get(row["name"], True))]
        row["capex_by_period"] = {str(p): round(v) for p, v in by_period.items()}
        row["capex_weighted"] = round(sum(weights[p] * v for p, v in by_period.items()))
