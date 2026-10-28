"""Plant results read from a stored run and aggregated by plant id (a server-side groupby).

Everything is computed from the run's stored model (the ``RAGNAROK_PLANTS`` registry and the ``plant`` column), its
solved series and its options, like the P2X results: the UI and MCP only draw them.

Algorithm (per plant, over the run window; ``w_t`` snapshot weighting in h, ``p`` in MW):
    $$E_{el}=\\sum_t w_t\\,p^{el}_t,\\qquad CF=\\frac{E_{el}}{P_{el}\\,\\sum_t w_t},\\qquad
      s_t=\\frac{h_t}{h_t+g_t},\\qquad x_t=\\frac{s_t/L_H}{s_t/L_H+(1-s_t)/L_G}$$
    $$M^{act}=e_g\\sum_t w_t\\,g_t + e_h\\sum_t w_t\\,h_t,\\qquad
      M^{gas}=e_g\\sum_t w_t\\,(g_t+h_t),\\qquad M^{avoided}=M^{gas}-M^{act}$$
    Fixed charge of an extendable component: ``P (k_eff + y f)``, ``k_eff`` = PyPSA's effective capital cost per unit over the window (read from
    the rebuilt network), ``f`` = ``fom_cost`` per year, ``y`` = window years.
    ASCII: E_el = sum w*p_el; CF = E_el/(P_el*sum w); s_t = h/(h+g); x_t = (s/L_H)/(s/L_H+(1-s)/L_G);
    avoided = e_g*sum w*(g+h) - (e_g*sum w*g + e_h*sum w*h) = (e_g - e_h) * sum w*h.
    ``g`` and ``h`` are the gas and H2 fuel flows (MW_th, LHV), ``e_g`` = 0.198 and ``e_h`` = 0 tCO2/MWh_th, ``L_*`` MJ/Nm3.
    The comparison is the *same dispatch burnt as 100 % gas* (same fuel energy; an H2 derate, if on, is not re-priced).
    For the simple co-firing generator ``g = (1-s) E_el/eta`` and ``h = s E_el/eta`` with the fixed share ``s``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ...pypsa.network import cofiring as cf
from ..p2x.results import P2XResultsError, _f, _Run
from .registry import plant_ids, plant_rows, registry_map

TOL = 1e-6


class PlantResultsError(ValueError):
    """The run has no plants, or an unknown plant id was asked for."""


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes") if not isinstance(v, bool) else v


def _energy(run: _Run, arr: np.ndarray) -> float:
    return float((arr * run.w).sum())


def _series(run: _Run, sheet: str, attr: str, name: str) -> np.ndarray:
    return run.col(f"{sheet}-{attr}", name)


def _fixed(run: _Run, sheet: str, name: str, row: dict[str, Any], capacity: float, extendable: bool) -> float:
    """Capital charge of an extendable component over the window: capacity x PyPSA's effective capital cost (read from the network rebuilt
    from the stored model, never recomputed) + ``fom_cost`` x capacity x window years when the row carries PyPSA's cost split."""
    if not extendable:
        return 0.0
    total = capacity * run.effective_capital(sheet, name)
    if row.get("overnight_cost") not in (None, ""):
        total += capacity * _f(row.get("fom_cost")) * run.years
    return total


def _component(run: _Run, comp: dict[str, str]) -> dict[str, Any]:
    """Capacity, throughput and cost of one component (see the module docstring for the cost convention)."""
    sheet, name = comp["sheet"], comp["name"]
    row = run.row(sheet, name)
    out: dict[str, Any] = {"sheet": sheet, "name": name, "role": comp.get("role", "")}
    if sheet in ("generators", "links", "processes", "storage_units"):
        cap = run.capacity(sheet, name)
        out["capacity"], out["capacityUnit"] = cap, "MW"
        if sheet == "generators":
            thr = _energy(run, _series(run, sheet, "p", name))
        elif sheet == "storage_units":
            thr = _energy(run, _series(run, sheet, "p_dispatch", name))
        else:
            thr = _energy(run, _series(run, sheet, "p0", name))
        out["throughputMwh"] = thr
        op = _f(row.get("marginal_cost")) * thr
        ext = _truthy(row.get("p_nom_extendable"))
        out["operatingCost"], out["fixedCost"], out["extendable"] = op, _fixed(run, sheet, name, row, cap, ext), ext
    elif sheet == "stores":
        cap = run.capacity(sheet, name)
        out.update({"capacity": cap, "capacityUnit": "MWh", "throughputMwh": 0.0, "operatingCost": 0.0})
        ext = _truthy(row.get("e_nom_extendable"))
        out["fixedCost"] = _fixed(run, sheet, name, row, cap, ext)
        out["extendable"] = ext
    return out


def _starts(run: _Run, sheet: str, name: str, power: np.ndarray) -> tuple[int, str]:
    """Number of starts: the solved ``start_up`` series of a committable unit, else off-to-on steps of the dispatch."""
    su = run.series.get(f"{sheet}-start_up")
    if su and name in (su[0] if su else {}):
        return round(float(np.sum([_f(r.get(name)) for r in su]))), "solved (committable)"
    on = power > TOL
    return int(np.sum(on[1:] & ~on[:-1]) + (1 if on.size and on[0] else 0)), "counted from dispatch (not committable)"


def _gas_ef(run: _Run, reg: dict[str, Any]) -> float:
    row = run.rows.get("carriers", {}).get("gas") or {}
    ef = row.get("co2_emissions")
    if ef not in (None, ""):
        return _f(ef)
    return _f((reg.get("fuel") or {}).get("gasCo2") or (reg.get("blend") or {}).get("gasCo2"), 0.198)


def _fuel_price(run: _Run, bus: str) -> tuple[np.ndarray, str]:
    """Price (per MWh_th) of the fuel on ``bus``: its nodal marginal price, or - in a MILP (commitment) the duals are absent
    and every price reads 0 - the marginal cost of the supplier generator at that bus."""
    price = run.col("buses-marginal_price", bus)
    if price.size and float(np.abs(price).max()) > 0.0:
        return price, "nodal price of the fuel bus"
    mc = [_f(g.get("marginal_cost")) for g in run.model.get("generators") or [] if str(g.get("bus")) == bus]
    return np.full(run.n, mc[0] if mc else 0.0), "marginal cost of the fuel-bus supplier (no duals in a MILP)"


def _plant(run: _Run, pid: str, reg: dict[str, Any] | None, include_series: bool) -> dict[str, Any]:
    rows = plant_rows(run.model, pid)
    comps = (reg or {}).get("components") or [{"sheet": s, "name": n, "role": ""} for s, ns in rows.items() for n in ns]
    comps = [c for c in comps if c["sheet"] in ("generators", "links", "processes", "storage_units", "stores")
             and c["name"] in run.rows.get(c["sheet"], {})]
    parts = [_component(run, c) for c in comps]
    # A fuel supplier may be shared (a second plant reuses the gas bus the first one created), so its cost is not booked on the
    # plant that happens to own the row: suppliers are listed but excluded from the plant's cost; the fuel each plant burns is
    # valued below at the nodal price of its fuel bus instead.
    for p in parts:
        p["sharedSupply"] = p.get("role") in ("gas supply", "H2 supply")
    own = [p for p in parts if not p["sharedSupply"]]
    out: dict[str, Any] = {
        "plantId": pid, "type": (reg or {}).get("type"), "label": (reg or {}).get("label") or pid, "bus": (reg or {}).get("bus"),
        "components": parts, "operatingCost": sum(p.get("operatingCost", 0.0) for p in own),
        "fixedCost": sum(p.get("fixedCost", 0.0) for p in own), "fuelCost": 0.0, "warnings": [],
    }
    ptype = (reg or {}).get("type")
    main = (reg or {}).get("main")
    power_series = (reg or {}).get("powerSeries")
    hours = float(run.w.sum())
    eta = float((reg or {}).get("efficiency") or 1.0)
    ac_bus = (reg or {}).get("bus")
    price = run.col("buses-marginal_price", ac_bus) if ac_bus else np.zeros(run.n)
    gen = np.zeros(run.n)
    if main and power_series:
        sheet = power_series[0]
        if sheet == "links":
            gen = -run.col("links-p1", main["name"])
        elif sheet == "generators":
            gen = run.col("generators-p", main["name"])
        else:
            gen = run.col("storage_units-p_dispatch", main["name"]) - run.col("storage_units-p_store", main["name"])
    out["generationMwh"] = _energy(run, gen)
    cap_main = run.capacity(main["sheet"], main["name"]) if main and main["sheet"] in run.rows else 0.0
    cap_el = cap_main * eta if main and main["sheet"] == "links" else cap_main
    out["capacityMwEl"] = cap_el
    if ptype in ("generator", "ccgt", "ocgt", "cofiring_simple", "cofiring_network", "bess"):
        out["capacityFactor"] = out["generationMwh"] / (cap_el * hours) if cap_el > 0 and hours > 0 else 0.0
        out["fullLoadHours"] = out["generationMwh"] / cap_el if cap_el > 0 else 0.0
        out["revenueAtBusPrice"] = float((gen * price * run.w).sum())
    if ptype == "bess" and main:
        ch, dis = _series(run, "storage_units", "p_store", main["name"]), _series(run, "storage_units", "p_dispatch", main["name"])
        e_cap = cap_main * _f(run.row("storage_units", main["name"]).get("max_hours"), 1.0)
        out["storage"] = {"chargeMwh": _energy(run, ch), "dischargeMwh": _energy(run, dis), "energyCapacityMwh": e_cap,
                          "equivalentCycles": _energy(run, dis) / e_cap if e_cap > 0 else 0.0}
        out["generationMwh"] = out["storage"]["dischargeMwh"]
        out["capacityFactor"] = out["generationMwh"] / (cap_el * hours) if cap_el > 0 and hours > 0 else 0.0
    if ptype in ("ccgt", "ocgt", "cofiring_simple", "cofiring_network") and main:
        starts, basis = _starts(run, main["sheet"], main["name"], gen)
        out["starts"], out["startsBasis"] = starts, basis
        ef = _gas_ef(run, reg or {})
        K = (reg or {}).get("lhvMjPerNm3") or (reg.get("blend") or {}).get("lhvMjPerNm3") or {}
        lh, lg = float(K.get("H2", 10.78)), float(K.get("CH4", 35.8))
        if ptype == "cofiring_network":
            g = run.col("links-p0", reg["feeders"]["gas"])
            h = run.col("links-p0", reg["feeders"]["h2"])
        elif ptype == "cofiring_simple":
            fuel = gen / eta if eta > 0 else np.zeros(run.n)
            s = float(reg["blend"]["energyShare"])
            g, h = (1.0 - s) * fuel, s * fuel
        else:
            g, h = run.col("links-p0", main["name"]), np.zeros(run.n)
        e_g, e_h = _energy(run, g), _energy(run, h)
        ef_h = _f(((reg.get("blend") or {}).get("h2Co2") if ptype == "cofiring_simple" else None), 0.0)
        actual = ef * e_g + ef_h * e_h
        baseline = ef * (e_g + e_h)
        share = e_h / (e_g + e_h) if (e_g + e_h) > TOL else 0.0
        fuel_cost = 0.0
        bases = []
        for bus, flow in ((reg.get("gasBus"), g), (reg.get("h2Bus"), h)):
            if bus:
                price, basis = _fuel_price(run, bus)
                fuel_cost += float((flow * price * run.w).sum())
                bases.append(basis)
        out["fuelCost"] = fuel_cost
        out["fuelCostBasis"] = ("fuel flows x " + " / ".join(dict.fromkeys(bases)) + "; supplier rows are shared and not booked on a plant") if bases else ""
        out["fuel"] = {"gasMwhTh": e_g, "h2MwhTh": e_h, "totalMwhTh": e_g + e_h, "h2EnergyShare": share,
                       "h2VolShare": cf.energy_to_vol_share(min(max(share, 0.0), 1.0), lh, lg) if (e_g + e_h) > TOL else 0.0,
                       "h2KgEquivalent": e_h * 1000.0 / 33.33, "lhvMjPerNm3": {"H2": lh, "CH4": lg}}
        out["emissions"] = {"gasCo2TPerMwhTh": ef, "actualT": actual, "gasOnlyBaselineT": baseline, "avoidedT": baseline - actual,
                            "avoidedShare": (baseline - actual) / baseline if baseline > TOL else 0.0,
                            "basis": "same dispatch and fuel energy burnt as 100 % gas; H2 emits 0 at the stack"}
        if ptype != "ccgt" and ptype != "ocgt":
            sh = cf.hourly_shares(h, g, lh, lg)
            on = (h + g) > TOL
            out["cofiring"] = {
                "hoursOn": int(on.sum()), "maxHourlyEnergyShare": float(sh["energy"][on].max()) if on.any() else 0.0,
                "minHourlyEnergyShare": float(sh["energy"][on].min()) if on.any() else 0.0,
                "maxHourlyVolShare": float(sh["vol"][on].max()) if on.any() else 0.0,
                "minHourlyVolShare": float(sh["vol"][on].min()) if on.any() else 0.0,
                "blend": (reg.get("blend") if ptype == "cofiring_network" else {k: reg["blend"][k] for k in ("energyShare", "volShare", "marginalCost", "carrierCo2")}),
                "derate": reg.get("derate"),
            }
            if include_series:
                out["series"] = {"snapshots": run.snapshots, "generationMw": gen.tolist(), "h2Mw": h.tolist(), "gasMw": g.tolist(),
                                 "h2EnergyShare": sh["energy"].tolist(), "h2VolShare": sh["vol"].tolist()}
    out["totalCost"] = out["operatingCost"] + out["fixedCost"] + out["fuelCost"]
    if ptype == "p2x":
        from ..p2x import results as p2x_results
        try:
            res = p2x_results.p2x_results({"model": run.model, "result": {"outputs": {"series": run.series, "static": run.static}, "runMeta": run.meta},
                                           "options": run.options, "scenario": run.scenario}, chain_id=pid)
            out["p2x"] = {"lcohPerKg": res["lcoh"]["perKg"], "h2Tonnes": res["electrolyser"]["h2Tonnes"],
                          "electrolyserCapacityFactor": res["electrolyser"]["capacityFactor"],
                          "products": {k: {"costPerTonne": v["costPerTonne"], "producedTonnes": v["producedTonnes"]} for k, v in res["products"].items()}}
        except P2XResultsError as exc:
            out["warnings"].append(f"P2X results unavailable: {exc}")
    return out


def plant_results(bundle: dict[str, Any], *, plant_id: str | None = None, period: int | None = None, include_series: bool = True) -> dict[str, Any]:
    """Results of every plant of a stored run (or one), grouped by the ``plant`` id.

    Args:
        bundle: ``run_store.get_run(name)`` (model, result with outputs, options, scenario).
        plant_id: only this plant.
        period: investment period of a pathway run (series sliced to it).
        include_series: per-hour series (H2 share, flows) for co-firing plants.

    Raises:
        PlantResultsError: the model has no plant, or ``plant_id`` is unknown, or no stored series.
    """
    try:
        run = _Run(bundle, period)
    except P2XResultsError as exc:
        raise PlantResultsError(str(exc)) from exc
    ids = plant_ids(run.model)
    if not ids:
        raise PlantResultsError("This run's model has no plants (no `plant` column and no RAGNAROK_PLANTS sheet). Add one from Build -> Generators.")
    if plant_id is not None and plant_id not in ids:
        raise PlantResultsError(f"No plant {plant_id!r} in this run. Plants: {ids}.")
    regs = registry_map(run.model)
    plants = [_plant(run, pid, regs.get(pid), include_series) for pid in ids if plant_id in (None, pid)]
    keys = ("generationMwh", "operatingCost", "fixedCost", "fuelCost", "totalCost")
    totals: dict[str, float] = {k: float(sum(p.get(k, 0.0) for p in plants)) for k in keys}
    fuel_plants = [p for p in plants if "fuel" in p]
    totals.update({
        "gasMwhTh": float(sum(p["fuel"]["gasMwhTh"] for p in fuel_plants)), "h2MwhTh": float(sum(p["fuel"]["h2MwhTh"] for p in fuel_plants)),
        "emissionsT": float(sum(p["emissions"]["actualT"] for p in fuel_plants)),
        "emissionsAvoidedT": float(sum(p["emissions"]["avoidedT"] for p in fuel_plants)),
        "starts": int(sum(p.get("starts", 0) for p in plants)),
    })
    return {"currency": str(run.options.get("currencySymbol") or "EUR"), "windowYears": run.years, "hoursPerRow": run.row_hours,
            "period": period, "plants": plants, "totals": totals,
            "basis": "Costs in the model currency; fixed charge = capacity x PyPSA's effective capital cost (rebuilt network, run's discount rate, window-scaled) + fom_cost x capacity x window years; extendable components only."}
