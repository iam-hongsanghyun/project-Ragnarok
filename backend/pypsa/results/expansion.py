"""Capacity expansion result extraction helpers.

Called after network.optimize() has solved.  Returns the `expansionResults`
payload that the frontend uses to render the Capacity Expansion section.

Every cost figure is read from PyPSA, none is converted here: ``n.statistics.capex`` /
``expanded_capex`` / ``installed_capex`` / ``overnight_cost`` / ``fom`` and the component's
``capital_cost`` property (PyPSA's periodised cost per unit for the modelled horizon). The only
arithmetic is dividing a horizon figure by ``n.nyears`` where a per-year figure is shown
(``capex_annual``), and the field says so.
"""
from __future__ import annotations

import math
from typing import Any

import pypsa

from .pathway_periods import active_assets, is_pathway, period_objective_weights, periods
from .stat_metrics import asset_statistic, nyears_by_period


def _safe_number(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return fallback if math.isnan(number) else number


#: PyPSA component class -> (list name, nominal column, optimum column, extendable column, bus column, unit)
_KINDS: tuple[tuple[str, str, str, str, str, str, str | None], ...] = (
    ("Generator", "generators", "p_nom", "p_nom_opt", "p_nom_extendable", "bus", None),
    ("StorageUnit", "storage_units", "p_nom", "p_nom_opt", "p_nom_extendable", "bus", None),
    ("Store", "stores", "e_nom", "e_nom_opt", "e_nom_extendable", "bus", "MWh"),
    ("Link", "links", "p_nom", "p_nom_opt", "p_nom_extendable", "bus0", None),
    ("Process", "processes", "p_nom", "p_nom_opt", "p_nom_extendable", "bus0", None),
    ("Line", "lines", "s_nom", "s_nom_opt", "s_nom_extendable", "bus0", "MVA"),
    ("Transformer", "transformers", "s_nom", "s_nom_opt", "s_nom_extendable", "bus0", "MVA"),
)

_LIST_NAME = {kind[0]: kind[1] for kind in _KINDS}


def _by_name(frame: Any, comp: str, pathway: bool) -> dict[str, dict[int, float]]:
    """A statistics frame as ``{asset: {period: value}}`` (NaN = inactive and dropped)."""
    out: dict[str, dict[int, float]] = {}
    if frame is None or getattr(frame, "empty", True):
        return out
    for (c, name), row in frame.iterrows():
        if c != comp:
            continue
        vals = row.dropna()
        if vals.empty:
            continue
        out[str(name)] = {int(col): float(v) for col, v in vals.items()}
    return out


def build_expansion_results(network: pypsa.Network) -> list[dict[str, Any]]:
    """Return a list of expansion result dicts for all extendable assets.

    Each dict contains:
        name          – component name
        component     – 'Generator' | 'StorageUnit' | 'Store' | 'Link' | 'Process' | 'Line' | 'Transformer'
        carrier       – carrier string
        bus           – bus name
        p_nom_mw      – installed / fixed capacity (workbook value)
        p_nom_opt_mw  – optimised capacity from PyPSA
        delta_mw      – p_nom_opt − p_nom  (positive = new build)
        capital_cost  – PyPSA's periodised cost per unit for the MODELLED HORIZON
                        (``c.capital_cost``: ``capital_cost``, or overnight x annuity x nyears)
        capex_horizon – ``n.statistics.capex`` over the horizon (installed + expanded, no fom)
        capex_annual  – ``capex_horizon / n.nyears``: the same figure PER YEAR (a display basis)
        capex_expanded / capex_installed – ``expanded_capex`` / ``installed_capex`` over the horizon:
                        the new-build part and the part already sunk (existing ``p_nom``)
        overnight_total – ``n.statistics.overnight_cost`` (currency, not periodised)
        fom_total     – ``n.statistics.fom`` over the horizon (``fom_cost`` as PyPSA charged it)
        nyears        – the horizon in years the horizon figures refer to

    Multi-investment (pathway) runs add, per row:
        active_periods   – investment periods in which the asset exists
                           (``build_year <= period < build_year + lifetime``)
        capex_by_period  – ``{period: periodised CAPEX of that period}`` (the statistic with the
                           investment-period objective weight divided out), 0 outside active periods
        capex_weighted   – the statistic as PyPSA weights it: the CAPEX term of the LP objective
    """
    pathway = is_pathway(network)
    present = [
        (comp, lst, nom, opt, ext, bus, unit)
        for (comp, lst, nom, opt, ext, bus, unit) in _KINDS
        if getattr(network, lst, None) is not None and not getattr(network, lst).empty
        and ext in getattr(network, lst).columns and bool(getattr(network, lst)[ext].astype(bool).any())
    ]
    if not present:
        return []
    comps = [p[0] for p in present]
    frames = {
        key: asset_statistic(network, key, comps)
        for key in ("capex", "installed_capex", "expanded_capex", "overnight_cost", "fom")
    }
    ny = nyears_by_period(network)
    period_w = period_objective_weights(network) if pathway else {}

    results: list[dict[str, Any]] = []
    for comp, lst, nom, opt, ext, bus_col, unit in present:
        static = getattr(network, lst)
        ext_static = static[static[ext].astype(bool)]
        try:
            capital = network.components[lst].capital_cost
        except Exception:  # noqa: BLE001 - e.g. overnight_cost over periods of unequal length
            capital = static["capital_cost"]
        by = {key: _by_name(frame, comp, pathway) for key, frame in frames.items()}
        for name in ext_static.index:
            p_nom = _safe_number(ext_static.at[name, nom])
            p_nom_opt = _safe_number(ext_static.at[name, opt], p_nom) if opt in ext_static.columns else p_nom
            capital_cost = _safe_number(capital.get(name)) if hasattr(capital, "get") else 0.0
            row: dict[str, Any] = {
                "name": name,
                "component": comp,
                "carrier": str(ext_static.at[name, "carrier"]) if "carrier" in ext_static.columns else "",
                "bus": str(ext_static.at[name, bus_col]),
                "p_nom_mw": round(p_nom, 1),
                "p_nom_opt_mw": round(p_nom_opt, 1),
                "delta_mw": round(p_nom_opt - p_nom, 1),
                "capital_cost": round(capital_cost, 2),
            }
            if unit:
                row["unit"] = unit
            capex = by["capex"].get(str(name), {})
            if pathway:
                weighted = sum(capex.values())
                per_period = {p: v / (period_w.get(p, 1.0) or 1.0) for p, v in capex.items()}
                first = next(iter(per_period), None)
                horizon = per_period[first] if first is not None else capital_cost * p_nom_opt
                nyears = ny.get(first, 1.0) if first is not None else 1.0
                row["capex_horizon"] = round(horizon)
                row["nyears"] = round(nyears, 6)
                row["capex_annual"] = round(horizon / nyears) if nyears else 0
                row["capex_weighted"] = round(weighted)
            else:
                horizon = capex.get(0, capital_cost * p_nom_opt) if capex else capital_cost * p_nom_opt
                nyears = ny.get(0, 1.0)
                row["capex_horizon"] = round(horizon)
                row["nyears"] = round(nyears, 6)
                row["capex_annual"] = round(horizon / nyears) if nyears else 0
            for key, field in (("expanded_capex", "capex_expanded"), ("installed_capex", "capex_installed")):
                vals = by[key].get(str(name))
                if vals:
                    row[field] = round(next(iter(vals.values())) / (period_w.get(next(iter(vals)), 1.0) or 1.0)
                                       if pathway else vals.get(0, 0.0))
            overnight = by["overnight_cost"].get(str(name))
            if overnight:
                row["overnight_total"] = round(next(iter(overnight.values())))
            if not pathway:
                fom = by["fom"].get(str(name), {}).get(0)
                if fom:
                    row["fom_total"] = round(fom)
            results.append(row)

    _annotate_pathway(network, results, period_w)
    return results


def _annotate_pathway(network: pypsa.Network, results: list[dict[str, Any]], weights: dict[int, float]) -> None:
    """Add active periods and per-period CAPEX (pathway runs); ``capex_horizon`` is one active period's."""
    if not is_pathway(network):
        return
    masks = {
        list_name: {p: active_assets(network, list_name, p) for p in periods(network)}
        for list_name in set(_LIST_NAME.values())
    }
    for row in results:
        per_period = masks[_LIST_NAME[row["component"]]]
        by_period = {
            p: float(row["capex_horizon"]) if bool(mask.get(row["name"], True)) else 0.0
            for p, mask in per_period.items()
        }
        row["active_periods"] = [p for p, v in by_period.items() if bool(per_period[p].get(row["name"], True))]
        row["capex_by_period"] = {str(p): round(v) for p, v in by_period.items()}
        if "capex_weighted" not in row:
            row["capex_weighted"] = round(sum(weights[p] * v for p, v in by_period.items()))
