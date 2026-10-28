"""P2X results read from a stored run: LCOH, LCOA, LCOM, e-fuel cost, cost waterfall, RFNBO compliance.

Everything is computed from the run's stored model, solved outputs and options — the
same numbers the UI shows, server-side (the UI only draws them). Money is in the
model's currency (the technology file is EUR2025; no FX is applied).

Algorithm (levelised cost of hydrogen):
    $$\\mathrm{LCOH}=\\frac{C_{ely}+C_{comp}+C_{stor}+C_{elec}+C_{water}+C_{wear}}{M_{H_2}}$$
    $$C_{x}=P_x\\,\\bigl(\\hat k_x + y\\,f_x\\bigr)\\ (\\text{capex}+\\text{FOM}),\\qquad
      C_{elec}=\\sum_t w_t\\,p_t\\,\\lambda_t\\ \\text{(nodal)}\\ \\ \\text{or}\\ \\
      \\pi_{PPA}E_{matched}+\\sum_t w_t\\,(p_t-m_t)^+\\lambda_t\\ \\text{(PPA)}$$
    $$M_{H_2}=\\frac{1000}{LHV_{H_2}}\\sum_t w_t\\,(-p^{1}_{ely,t})$$
    ASCII: LCOH = (C_ely + C_comp + C_stor + C_elec + C_water + C_wear) / M_H2.
    C_x = P_x * (k_hat_x + f_x): installed capacity P_x (MW or MWh, ``p_nom_opt`` / ``e_nom_opt``), k_hat_x = PyPSA's effective
    capital cost per unit over the run window (``n.components[..].capital_cost`` of the network rebuilt from the stored model:
    overnight_cost x annuity(r, L) x n.nyears with the row's own discount_rate; not recomputed here) and f_x = the row's
    ``fom_cost`` per unit per modelled horizon, which PyPSA adds UNSCALED (``n.statistics.fom``). A chain saved with a folded
    ``capital_cost`` (older sessions) is split into capex and FOM with f / (a + f) instead.
    C_elec: nodal = sum_t w_t p_t lambda_t (lambda = marginal price of the AC bus, EUR/MWh);
    PPA = pi_PPA * E_matched + nodal price on the unmatched energy, where
    pi_PPA = (annualised cost + operating cost of the designated generators) / their energy, and
    m_t the designated output (MW). C_wear = stack replacement (stack cost / stack life per
    MWh_el), C_water = water use x supply cost; both are in the electrolyser Link's marginal cost.
    M_H2 in kg: w_t in h, p in MW (LHV), LHV_H2 in kWh/kg.

LCOA / LCOM / e-fuel cost: the same sum for the synthesis link of the product, plus the hydrogen it
takes valued at the LCOH, the electricity it draws, its share of the N2 (ASU) or CO2 supply
(by CO2 consumed), and the product tank, divided by the product produced (t or MWh_LHV).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from backend.app.p2x import rfnbo as rf
from .. import results_derived as rd
from . import technologies as tech
from .chains import PRODUCTS, REGISTRY_SHEET

HOURS_PER_YEAR = 8760.0
ELECTRICITY_MODES = ("nodal", "ppa")


class P2XResultsError(ValueError):
    """The run has no P2X chain or lacks the series the metrics need."""


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


class _Run:
    """Series access for one stored run, optionally one investment period."""

    def __init__(self, bundle: dict[str, Any], period: int | None) -> None:
        self.model: dict[str, list[dict[str, Any]]] = bundle.get("model") or {}
        result = bundle.get("result") or {}
        outputs = result.get("outputs") or {}
        series = outputs.get("series") or {}
        if not series:
            raise P2XResultsError("The run has no stored output series (was it solved and stored?).")
        self.static: dict[str, dict[str, dict[str, Any]]] = outputs.get("static") or {}
        self.options: dict[str, Any] = bundle.get("options") or {}
        self.scenario: dict[str, Any] = bundle.get("scenario") or {}
        self.meta: dict[str, Any] = result.get("runMeta") or {}
        self.period = period
        probe = next((rows for rows in series.values() if rows), [])
        total_rows = len(probe) or 1
        hours = _f(self.meta.get("modeledHours"), 0.0)
        self.row_hours = hours / total_rows if hours > 0 else _f(self.meta.get("snapshotWeight"), 1.0) or 1.0
        self.series = rd.filter_series_by_period(series, period)
        rows = next((r for r in self.series.values() if r), [])
        self.snapshots: list[str] = [str(r.get("snapshot")) for r in rows]
        self.n = len(self.snapshots)
        self.w = np.full(self.n, self.row_hours, dtype=float)
        self.years = float(self.w.sum()) / HOURS_PER_YEAR
        self.rows = {s: {str(r.get("name")): r for r in model_rows if r.get("name") not in (None, "")}
                     for s, model_rows in self.model.items() if isinstance(model_rows, list) and s != REGISTRY_SHEET}
        disc = self.scenario.get("discountRate")
        self.discount: float | None = _f(disc) if disc not in (None, "") else None
        self._network: Any = None
        self.window_share = (self.n * self.row_hours) / (total_rows * self.row_hours) if total_rows else 1.0   # period slice / stored window

    def network(self) -> Any:
        """The network rebuilt from the stored model, scenario and options (no solve): PyPSA's own effective costs live on it."""
        if self._network is None:
            from fastapi import HTTPException

            from ...pypsa.network import build_stored_network
            try:
                self._network, _ = build_stored_network(self.model, self.scenario, self.options)
            except HTTPException as exc:
                raise P2XResultsError(f"Could not rebuild the run's network to read its effective costs: {exc.detail}") from exc
        return self._network

    def effective_capital(self, sheet: str, name: str) -> float:
        """PyPSA's effective capital cost of one component, per unit of nominal capacity, over the run window (currency per MW / MWh), times the share of the stored window a period slice covers.

        Read from ``n.components[<sheet>].capital_cost`` of the rebuilt network, i.e. PyPSA's ``periodized_cost`` without fom:
        ``overnight_cost x annuity(r, L) x n.nyears`` for an overnight row and the row's ``capital_cost`` as is otherwise.
        """
        try:
            return _f(self.network().components[sheet].capital_cost[name]) * self.window_share
        except KeyError:
            return 0.0

    def effective_fom(self, sheet: str, name: str) -> float:
        """The row's ``fom_cost`` as PyPSA charges it: per unit of capacity per MODELLED HORIZON, NOT scaled by the window years
        (``n.statistics.fom`` = ``fom_cost x p_nom_opt``), times the share of the stored window a period slice covers."""
        try:
            return _f(self.network().components[sheet].static["fom_cost"][name]) * self.window_share
        except KeyError:
            return 0.0

    def col(self, sheet: str, name: str) -> np.ndarray:
        rows = self.series.get(sheet) or []
        return np.array([_f(r.get(name)) for r in rows], dtype=float) if rows else np.zeros(self.n)

    def row(self, sheet: str, name: str) -> dict[str, Any]:
        return self.rows.get(sheet, {}).get(name, {})

    def capacity(self, sheet: str, name: str) -> float:
        comp = self.static.get(sheet, {}).get(name, {})
        attr = "e_nom_opt" if sheet == "stores" else "p_nom_opt"
        if comp.get(attr) is not None:
            return _f(comp[attr])
        return _f(self.row(sheet, name).get("e_nom" if sheet == "stores" else "p_nom"))

    def active(self, sheet: str, name: str) -> bool:
        """Pathway: ``build_year <= period < build_year + lifetime`` (always true for a single-period run)."""
        if self.period is None:
            return True
        row = self.row(sheet, name)
        by, life = int(_f(row.get("build_year"))), _f(row.get("lifetime"), math.inf) or math.inf
        return by == 0 or by <= self.period < by + life


def _series_sheet(reg: dict[str, Any], role: str, port: int) -> str:
    """Series sheet of port ``port`` of a chain component: ``processes-pN`` or ``links-pN``.

    The registry records each component's sheet, so a chain built before the Process switch (``links``)
    and one built after read through the same code. Process and Link flows share the sign convention
    (``p_i = -rate_i * p`` / ``-efficiency_i * p``; positive = drawn from the bus)."""
    comp = reg["components"][role]
    return f"{'processes' if comp.get('sheet') == 'processes' else 'links'}-p{port}"


def _native(row: dict[str, Any]) -> bool:
    """The row carries PyPSA's own cost split (``overnight_cost`` + ``fom_cost``) rather than a folded ``capital_cost``."""
    return row.get("overnight_cost") not in (None, "")


def _fixed_charge(run: _Run, reg: dict[str, Any], role: str) -> dict[str, float]:
    """Window capex and FOM of one chain component (see the module docstring).

    Capex = capacity x PyPSA's effective capital cost (read from the rebuilt network, never recomputed from the workbook).
    FOM: ``fom_cost`` x capacity - PyPSA's per-horizon charge (``n.statistics.fom``), not pro-rated by the window years; for a chain
    saved with a folded ``capital_cost`` the charge is split with ``f / (a + f)``.
    """
    comp = reg["components"].get(role)
    if not comp or not run.active(comp["sheet"], comp["name"]):
        return {"capacity": 0.0, "capex": 0.0, "fom": 0.0}
    row = run.row(comp["sheet"], comp["name"])
    capacity = run.capacity(comp["sheet"], comp["name"])
    total = capacity * run.effective_capital(comp["sheet"], comp["name"])
    if _native(row):
        return {"capacity": capacity, "capex": total, "fom": capacity * run.effective_fom(comp["sheet"], comp["name"])}
    fc = reg["fixedCosts"][role]
    share = tech.fom_share(fc["fomPct"], fc["lifetimeYears"], float(reg["discountRate"]))
    return {"capacity": capacity, "capex": total * (1 - share), "fom": total * share}


def _energy(run: _Run, arr: np.ndarray) -> float:
    return float((arr * run.w).sum())


def lcoh_from_components(costs: dict[str, float], h2_mwh_lhv: float, h2_lhv_kwh_per_kg: float) -> dict[str, float]:
    """LCOH from cost components (currency) and the H2 produced (MWh, LHV).

    Args:
        costs: component -> cost over the window (currency); summed.
        h2_mwh_lhv: hydrogen produced, MWh (LHV).
        h2_lhv_kwh_per_kg: hydrogen LHV, kWh/kg.

    Returns:
        ``{kg, total, lcoh, per_component: {...}}`` with ``lcoh`` in currency per kg H2.
    """
    kg = tech.mwh_to_kg(h2_mwh_lhv, h2_lhv_kwh_per_kg)
    total = float(sum(costs.values()))
    return {"kg": kg, "total": total, "lcoh": total / kg if kg > 0 else float("nan"),
            "perComponent": {k: (v / kg if kg > 0 else float("nan")) for k, v in costs.items()}}


def _cum(steps: list[tuple[str, float]]) -> list[dict[str, Any]]:
    out, acc = [], 0.0
    for label, v in steps:
        acc += v
        out.append({"label": label, "value": v, "cumulative": acc})
    return out


def _chain_costs(run: _Run, reg: dict[str, Any], mode: str, cfg: dict[str, Any]) -> dict[str, Any]:
    comps = reg["components"]
    anchor = reg["buses"]["anchor"]
    price = run.col("buses-marginal_price", anchor)
    if not len(price):
        price = np.zeros(run.n)

    def link(role: str, sheet_series: str) -> np.ndarray:
        return run.col(sheet_series, comps[role]["name"]) if role in comps else np.zeros(run.n)

    def nodal_cost(power_mw: np.ndarray) -> float:
        return float((power_mw * price * run.w).sum())

    warnings: list[str] = []
    r_run = run.discount
    legacy = not _native(run.row(comps["electrolyser"]["sheet"], comps["electrolyser"]["name"]))
    if r_run is not None and abs(r_run - float(reg["discountRate"])) > 1e-9:
        if legacy:
            warnings.append(f"The run's discount rate ({r_run:g}) differs from the one the chain was built with "
                            f"({reg['discountRate']:g}); FOM was folded into the capital cost at the build rate, so the capex/FOM "
                            "split is approximate and the optimum slightly off the intended costs.")
        else:
            warnings.append(f"The run's discount rate ({r_run:g}) differs from the discount_rate on the chain's rows "
                            f"({reg['discountRate']:g}): PyPSA annualises each row with its own rate, so the chain was costed at "
                            f"{reg['discountRate']:g}. Rebuild the chain at the run's rate (or edit discount_rate) to align them.")
    ely = comps["electrolyser"]["name"]
    p0 = link("electrolyser", "links-p0")
    p1 = link("electrolyser", "links-p1")
    e_el = _energy(run, p0)
    h2_mwh = -_energy(run, p1)
    cap_ely = run.capacity("links", ely)

    # designated generation (for matching, and for the PPA price)
    cfg_n = rf.normalise_config(run.options.get("rfnboConfig"))
    sets = rf.resolve_sets(run.model, {**cfg_n, "designatedGenerators": cfg_n["designatedGenerators"] or list(reg.get("designatedGenerators", []))})
    designated = [g for g in sets["designated"] if g in run.rows.get("generators", {})]
    des_mw = np.sum([run.col("generators-p", g) for g in designated], axis=0) if designated else np.zeros(run.n)
    ely_all = [e for e in sets["electrolysers"] if e in run.rows.get("links", {})] or [ely]
    ely_mw_all = np.sum([run.col("links-p0", e) for e in ely_all], axis=0)
    matched_mw = np.minimum(p0, des_mw) if designated else np.zeros(run.n)
    matched_mwh = _energy(run, matched_mw)

    nodal_el = nodal_cost(p0)
    elec_ely = nodal_el
    ppa: dict[str, Any] = {"available": bool(designated)}
    if designated:
        cost = 0.0
        for g in designated:
            row = run.row("generators", g)
            if run.active("generators", g):
                if _f(row.get("p_nom_extendable")) or str(row.get("p_nom_extendable")).lower() in ("true", "1"):
                    cap_g = run.capacity("generators", g)
                    cost += cap_g * (run.effective_capital("generators", g) + (run.effective_fom("generators", g) if _native(row) else 0.0))
            cost += _f(row.get("marginal_cost")) * _energy(run, run.col("generators-p", g))
        e_des = _energy(run, des_mw)
        pi = cost / e_des if e_des > 0 else float("nan")
        ppa.update({"pricePerMwh": pi, "designatedEnergyMwh": e_des, "designatedCost": cost, "matchedMwh": matched_mwh})
        if mode == "ppa" and e_des > 0:
            unmatched_cost = nodal_cost(np.maximum(p0 - matched_mw, 0.0))
            elec_ely = pi * matched_mwh + unmatched_cost
    elif mode == "ppa":
        warnings.append("PPA electricity cost needs designated generators; fell back to nodal price.")

    # ── hydrogen side
    ely_fix = _fixed_charge(run, reg, "electrolyser")
    comp_fix = _fixed_charge(run, reg, "compressor")
    sto_fix = _fixed_charge(run, reg, "h2_store")
    elec_comp = nodal_cost(link("compressor", "links-p2")) if "compressor" in comps else 0.0
    wear = e_el * float(reg["electrolyser"]["stackWearEurPerMwhEl"])
    water = e_el * float(reg["electrolyser"]["waterM3PerMwhEl"]) * float(reg["electrolyser"]["waterCostEurPerM3"])
    h2_costs = {
        "Electricity (electrolyser)": elec_ely,
        "Electrolyser capex": ely_fix["capex"], "Electrolyser FOM": ely_fix["fom"],
        "Stack replacement": wear, "Water": water,
        "Compression": comp_fix["capex"] + comp_fix["fom"] + elec_comp,
        "H2 storage": sto_fix["capex"] + sto_fix["fom"],
    }
    lhv_h2 = float(reg["lhvKwhPerKg"]["H2"])
    h2 = lcoh_from_components(h2_costs, h2_mwh, lhv_h2)
    hours_window = float(run.w.sum())
    eff = float(reg["electrolyser"]["efficiencyLhv"])
    ely_stats = {
        "name": ely, "capacityMw": cap_ely, "electricityMwh": e_el, "h2Mwh": h2_mwh, "h2Tonnes": h2["kg"] / 1000.0,
        "capacityFactor": e_el / (cap_ely * hours_window) if cap_ely > 0 and hours_window > 0 else 0.0,
        "fullLoadHours": e_el / cap_ely if cap_ely > 0 else 0.0,
        "fullLoadHoursPerYear": (e_el / cap_ely / run.years) if cap_ely > 0 and run.years > 0 else 0.0,
        "efficiencyLhv": eff, "windowYears": run.years,
    }

    # ── derivative products
    asu_cost = 0.0
    if "asu" in comps:
        f = _fixed_charge(run, reg, "asu")
        asu_cost = f["capex"] + f["fom"] + nodal_cost(link("asu", _series_sheet(reg, "asu", 0)))
    co2_cost = 0.0
    if "co2_supply" in comps:
        f = _fixed_charge(run, reg, "co2_supply")
        mc = _f(run.row(comps["co2_supply"]["sheet"], comps["co2_supply"]["name"]).get("marginal_cost"))
        co2_p0 = link("co2_supply", _series_sheet(reg, "co2_supply", 0))
        co2_cost = f["capex"] + f["fom"] + nodal_cost(co2_p0) + mc * _energy(run, co2_p0)
    co2_used = {p: max(_energy(run, run.col(_series_sheet(reg, f"synth_{p}", 3), comps[f"synth_{p}"]["name"])), 0.0)
                for p in PRODUCTS if f"synth_{p}" in comps and PRODUCTS[p]["feed"] == "co2"}
    co2_total = sum(co2_used.values())
    products: dict[str, Any] = {}
    for p in PRODUCTS:
        role = f"synth_{p}"
        if role not in comps:
            continue
        meta = PRODUCTS[p]
        lhv = float(reg["lhvKwhPerKg"][p])                                     # kWh/kg = MWh/t
        name = comps[role]["name"]
        p0s, p1s = run.col(_series_sheet(reg, role, 0), name), run.col(_series_sheet(reg, role, 1), name)
        h2_in = _energy(run, p0s)
        out_mwh = -_energy(run, p1s)
        syn_fix = _fixed_charge(run, reg, role)
        vom = _f(run.row(comps[role]["sheet"], name).get("marginal_cost")) * h2_in
        elec = nodal_cost(run.col(_series_sheet(reg, role, 2), name))
        store = _fixed_charge(run, reg, f"store_{p}")
        h2_kg_in = tech.mwh_to_kg(h2_in, lhv_h2)
        feed = asu_cost if meta["feed"] == "n2" else (co2_cost * co2_used[p] / co2_total if co2_total > 0 else 0.0)
        scale = h2_kg_in / h2["kg"] if h2["kg"] > 0 else 0.0                   # share of the plant's H2 this product takes
        comp_parts = {k: h2_costs[k] * scale for k in h2_costs}                # this product's share of each H2 cost
        terms = {**{f"H2: {k}": v for k, v in comp_parts.items()},
                 "Synthesis capex": syn_fix["capex"], "Synthesis FOM": syn_fix["fom"], "Synthesis VOM": vom,
                 "Synthesis electricity": elec, "N2 supply (ASU)" if meta["feed"] == "n2" else "CO2 supply": feed,
                 "Product storage": store["capex"] + store["fom"]}
        total = float(sum(terms.values()))
        tonnes = out_mwh / lhv                                                  # MWh / (MWh/t)
        unit_per_t = total / tonnes if tonnes > 0 else float("nan")
        entry: dict[str, Any] = {
            "product": p, "label": meta["label"], "producedMwh": out_mwh, "producedTonnes": tonnes, "h2InMwh": h2_in,
            "totalCost": total, "costPerTonne": unit_per_t, "costPerMwh": total / out_mwh if out_mwh > 0 else float("nan"),
            "synthesisCapacityMw": syn_fix["capacity"], "components": terms,
            "synthesisFullLoadHours": h2_in / syn_fix["capacity"] if syn_fix["capacity"] > 0 else 0.0,
        }
        if p == "eFuel":
            dens = float(reg.get("efuelDensityTPerM3", 0.8))                    # t/m3 = kg/l
            mwh_per_litre = dens * lhv / 1000.0
            entry["costPerLitre"] = entry["costPerMwh"] * mwh_per_litre
            entry["energyPerLitreMwh"] = mwh_per_litre
        scale_u = 1.0 / tonnes if tonnes > 0 else float("nan")
        entry["waterfall"] = {"unit": "per t" if p != "eFuel" else "per MWh_LHV", "steps": _cum(
            [(k, v * (scale_u if p != "eFuel" else (1.0 / out_mwh if out_mwh > 0 else float("nan")))) for k, v in terms.items()])}
        products[p] = entry

    waterfall_h2 = _cum([(k, v) for k, v in h2["perComponent"].items()])
    return {
        "warnings": warnings, "electrolyser": ely_stats,
        "lcoh": {"perKg": h2["lcoh"], "totalCost": h2["total"], "h2Kg": h2["kg"], "perComponent": h2["perComponent"],
                 "costs": h2_costs, "electricityMode": mode if not (mode == "ppa" and not designated) else "nodal",
                 "waterfall": {"unit": "per kg H2", "steps": waterfall_h2}},
        "products": products, "ppa": ppa, "matching": {"matchedMw": matched_mw, "designatedMw": des_mw, "designated": designated,
                                                       "electrolysers": ely_all, "electrolyserMwAll": ely_mw_all, "price": price},
        "nodalCost": nodal_el,
    }


def p2x_results(bundle: dict[str, Any], *, period: int | None = None, electricity_cost: str = "nodal",
                chain_id: str | None = None) -> dict[str, Any]:
    """Everything the P2X results panel shows, for one stored run.

    Args:
        bundle: ``run_store.get_run(name)`` (model, result with outputs, options, scenario).
        period: investment period of a pathway run (series sliced to it); ``None`` = whole horizon.
        electricity_cost: ``"nodal"`` (nodal price x consumption) or ``"ppa"`` (designated generators' cost).
        chain_id: which chain when the model has several (default the first).

    Raises:
        P2XResultsError: no chain in the run's model, or no stored series.
    """
    if electricity_cost not in ELECTRICITY_MODES:
        raise P2XResultsError(f"electricity_cost must be one of {ELECTRICITY_MODES}.")
    run = _Run(bundle, period)
    chains = rf.registry_chains(run.model)
    if not chains:
        raise P2XResultsError("This run's model has no P2X chain (no RAGNAROK_P2X sheet). Build one in the P2X tab first.")
    reg = next((c for c in chains if c["chainId"] == chain_id), chains[0]) if chain_id else chains[0]
    if chain_id and reg["chainId"] != chain_id:
        raise P2XResultsError(f"No P2X chain {chain_id!r}. Chains: {[c['chainId'] for c in chains]}.")
    cfg = rf.normalise_config(run.options.get("rfnboConfig"))
    costs = _chain_costs(run, reg, electricity_cost, cfg)
    m = costs.pop("matching")
    snapshots = run.snapshots
    comp = None
    if m["designated"]:
        comp = rf.compliance(snapshots, m["electrolyserMwAll"], m["designatedMw"], run.w, m["price"], cfg["priceRule"])
    sets = rf.resolve_sets(run.model, {**cfg, "designatedGenerators": cfg["designatedGenerators"] or list(reg.get("designatedGenerators", []))})
    checks = {"additionality": rf.check_additionality(run.model, cfg, sets), "geographic": rf.check_geography(run.model, cfg, sets)}
    # Art. 4 grid alternatives (reported only)
    gens = run.rows.get("generators", {})
    carriers = run.rows.get("carriers", {})
    res_c = set(cfg["gridAlternatives"]["renewableCarriers"])
    res_e = tot_e = emis = 0.0
    for g, row in gens.items():
        e = _energy(run, run.col("generators-p", g))
        c = str(row.get("carrier") or "")
        tot_e += e
        if c in res_c:
            res_e += e
        ef = _f((carriers.get(c) or {}).get("co2_emissions"))
        eff = _f(row.get("efficiency"), 1.0) or 1.0
        emis += e * ef / eff
    buses = run.rows.get("buses", {})
    load_mwh = sum(_energy(run, run.col("loads-p", ln)) for ln, row in run.rows.get("loads", {}).items()
                   if str((buses.get(str(row.get("bus"))) or {}).get("carrier") or "").strip().lower() in
                   {"", "ac", "dc", "electricity", "elec", "power"})
    grid_alt = rf.grid_alternatives(res_e, tot_e, emis, load_mwh, cfg, costs["electrolyser"]["fullLoadHours"], float(run.w.sum()))
    # series for the charts
    soc_name = reg["components"].get("h2_store", {}).get("name")
    soc = run.col("stores-e", soc_name).tolist() if soc_name else []
    ely_p0 = run.col("links-p0", reg["components"]["electrolyser"]["name"])
    series = {
        "snapshots": snapshots, "electrolyserMw": ely_p0.tolist(), "designatedMw": m["designatedMw"].tolist(),
        "matchedMw": m["matchedMw"].tolist(), "gridMw": np.maximum(ely_p0 - m["matchedMw"], 0.0).tolist(),
        "h2SocMwh": soc, "h2SocTonnes": [tech.mwh_to_kg(v, float(reg["lhvKwhPerKg"]["H2"])) / 1000.0 for v in soc],
        "priceAc": m["price"].tolist(),
    }
    stored_cfg = {k: v for k, v in (run.options.get("rfnboConfig") or {}).items()}
    return {
        "chainId": reg["chainId"], "chains": [c["chainId"] for c in chains], "period": period, "currency": str(run.options.get("currencySymbol") or "EUR"),
        "electricityCost": costs["lcoh"]["electricityMode"], "electricityCostRequested": electricity_cost,
        "windowYears": run.years, "snapshots": run.n, "hoursPerRow": run.row_hours,
        "lcoh": costs["lcoh"], "electrolyser": costs["electrolyser"], "products": costs["products"], "ppa": costs["ppa"],
        "rfnbo": {"matchingEnabled": bool(cfg["enabled"]), "config": stored_cfg, "designated": m["designated"],
                  "electrolysers": m["electrolysers"], "compliance": comp, "checks": checks, "gridAlternatives": grid_alt,
                  "regulation": "Commission Delegated Regulation (EU) 2023/1184, Arts. 3-8"},
        "series": series, "warnings": costs["warnings"],
        "basis": "Costs in the model currency. Technology defaults are EUR2025 (PyPSA/technology-data v0.15.0, costs_2030.csv + DEA).",
    }
