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
from .stat_metrics import asset_statistic


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

    # ── Processes (p_nom_extendable, P29) ──────────────────────────────────────
    processes = getattr(network, "processes", None)
    if processes is not None and not processes.empty and "p_nom_extendable" in processes.columns:
        ext_pr = processes[processes.p_nom_extendable]
        for name in ext_pr.index:
            p_nom = _safe_number(ext_pr.at[name, "p_nom"])
            p_nom_opt = _safe_number(ext_pr.at[name, "p_nom_opt"], p_nom) if "p_nom_opt" in ext_pr.columns else p_nom
            capital_cost = _safe_number(ext_pr.at[name, "capital_cost"]) if "capital_cost" in ext_pr.columns else 0.0
            results.append(
                {
                    "name": name,
                    "component": "Process",
                    "carrier": str(ext_pr.at[name, "carrier"]) if "carrier" in ext_pr.columns else "",
                    "bus": str(ext_pr.at[name, "bus0"]),
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

    _apply_native_costs(network, results)
    _apply_window_scale(network, results)
    _apply_statistics_capex(network, results)
    _annotate_pathway(network, results)
    return results


_LIST_NAME = {
    "Generator": "generators",
    "StorageUnit": "storage_units",
    "Store": "stores",
    "Link": "links",
    "Process": "processes",
    "Line": "lines",
    "Transformer": "transformers",
}


_NOM_OPT_COL = {
    "Generator": "p_nom_opt", "StorageUnit": "p_nom_opt", "Link": "p_nom_opt",
    "Store": "e_nom_opt", "Process": "p_nom_opt", "Line": "s_nom_opt", "Transformer": "s_nom_opt",
}


def _apply_native_costs(network: pypsa.Network, results: list[dict[str, Any]]) -> None:
    """Read PyPSA-native ``overnight_cost`` / ``fom_cost`` (PyPSA 1.1+) into the rows.

    PyPSA prices an extendable asset at
    $$ c = \\text{overnight}\\cdot a(r, L)\\cdot n_{years} + \\text{fom\\_cost} $$
    (``pypsa.costs.periodized_cost``); a finite ``overnight_cost`` overrides
    ``capital_cost``. ASCII: cost = overnight * annuity(r, L) * nyears + fom_cost.
    For such rows ``capital_cost`` / ``capex_annual`` are reported as the ANNUAL
    annuity (overnight * a) so they share the basis of Ragnarok-annuitised rows,
    and ``native_cost`` is set so the window scaling is not undone twice.
    ``fom_cost`` is added to the objective unscaled (per modelled horizon); it is
    reported per row as ``fom_cost`` / ``fom_total`` (currency) — previously these
    objective terms were invisible in the reports.
    """
    from pypsa.costs import annuity

    for row in results:
        comp_name = _LIST_NAME[row["component"]]
        static = network.components[comp_name].static
        name = row["name"]
        if name not in static.index:
            continue
        opt_col = _NOM_OPT_COL[row["component"]]
        opt = _safe_number(static.at[name, opt_col]) if opt_col in static.columns else row["p_nom_opt_mw"]
        overnight = _safe_number(static.at[name, "overnight_cost"], float("nan")) if "overnight_cost" in static.columns else float("nan")
        if not math.isnan(overnight):
            rate = _safe_number(static.at[name, "discount_rate"], 0.0) if "discount_rate" in static.columns else 0.0
            life = _safe_number(static.at[name, "lifetime"], float("inf")) if "lifetime" in static.columns else float("inf")
            annual = overnight * float(annuity(rate, life))
            row["capital_cost"] = round(annual, 2)
            row["capex_annual"] = round(annual * opt)
            row["native_cost"] = True
        fom = _safe_number(static.at[name, "fom_cost"]) if "fom_cost" in static.columns else 0.0
        if fom:
            row["fom_cost"] = round(fom, 2)
            row["fom_total"] = round(fom * opt)


def _apply_statistics_capex(network: pypsa.Network, results: list[dict[str, Any]]) -> None:
    """Take CAPEX / FOM from ``n.statistics`` (P28), on the annual basis.

    ``capex_annual`` is ``n.statistics.capex`` (PyPSA 1.3+: periodised investment
    cost, *excluding* ``fom_cost``) per asset, converted back to a per-year charge:

    $$ K^{annual} = \\frac{\\text{capex}^{stat}}{b}, \\qquad
       b = \\begin{cases} n_{years} & \\text{native overnight cost (PyPSA scales by the window)}\\\\
       s_{window} & \\text{Ragnarok-annuitised, scaled by the builder}\\\\ 1 & \\text{unscaled}\\end{cases} $$

    with $n_{years} = \\sum_t w^{obj}_t / 8760$ and, in a pathway run, the statistic
    already multiplied by the investment-period ``objective`` weight (divided out
    here). ASCII: capex_annual = stat_capex / basis. Added per row, same basis:
    ``capex_expanded`` (``expanded_capex``: the part above ``p_nom``),
    ``capex_installed`` (``installed_capex``: existing ``p_nom``; they sum to
    ``capex_annual``), ``overnight_total`` (``overnight_cost``: currency, not
    periodised; only where PyPSA can resolve it) and ``fom_total`` (``fom``,
    single-period only - PyPSA adds it unscaled per modelled horizon). A row the
    statistics cannot resolve (unsolved or rebuilt network) keeps the
    ``capital_cost x p_nom_opt`` figure computed above. A pathway row with a
    native ``overnight_cost`` also keeps it (per-period ``nyears`` is not exposed).
    """
    if not results:
        return
    pathway = is_pathway(network)
    scale = capex_window_scale(network)
    nyears = float(network.snapshot_weightings["objective"].sum()) / 8760.0 if not pathway else float("nan")
    comps = sorted({r["component"] for r in results})
    period_w = period_objective_weights(network) if pathway else {}

    frames = {
        key: asset_statistic(network, key, comps)
        for key in ("capex", "installed_capex", "expanded_capex", "fom")
    }
    overnight: dict[str, Any] = {}
    for comp in comps:
        frame = asset_statistic(network, "overnight_cost", [comp])
        if not frame.empty:
            overnight[comp] = frame

    def _single(frame: Any, comp: str, name: str) -> float | None:
        """The asset's value; in a pathway the first active period, de-weighted."""
        if frame is None or getattr(frame, "empty", True) or (comp, name) not in frame.index:
            return None
        row = frame.loc[(comp, name)]
        vals = row.dropna()
        if vals.empty:
            return None
        if pathway:
            col = vals.index[0]
            return float(vals.iloc[0]) / (period_w.get(int(col), 1.0) or 1.0)
        return float(vals.iloc[0])

    for row in results:
        comp, name = row["component"], row["name"]
        native = bool(row.get("native_cost"))
        if native:
            if pathway:
                continue
            basis = nyears
        else:
            basis = scale or 1.0
        if not basis or basis != basis:
            continue
        capex = _single(frames["capex"], comp, name)
        if capex is None:
            continue
        row["capex_annual"] = round(capex / basis)
        for key, field in (("expanded_capex", "capex_expanded"), ("installed_capex", "capex_installed")):
            val = _single(frames[key], comp, name)
            if val is not None:
                row[field] = round(val / basis)
        ov = _single(overnight.get(comp), comp, name)
        if ov is not None:
            row["overnight_total"] = round(ov)
        if not pathway:
            fom = _single(frames["fom"], comp, name)
            if fom:
                row["fom_total"] = round(fom)


def _apply_window_scale(network: pypsa.Network, results: list[dict[str, Any]]) -> None:
    """Undo the solve's window scaling so ``capital_cost`` / ``capex_annual`` stay annual."""
    scale = capex_window_scale(network)
    if scale is None or scale <= 0:
        return
    for row in results:
        if row.get("native_cost"):
            continue  # PyPSA scaled it itself; already reported on the annual basis
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
