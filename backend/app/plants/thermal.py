"""CCGT, OCGT and gas + H2 co-firing plants (and the small Generator / BESS templates).

Every builder takes the flat plant spec, the working model and a :class:`registry.Ctx` and queues rows; the
registry fields it returns (feeders, shares, derate, parameters) are what results and the blend constraint read.

Units: electric capacity ``pNom`` in MW_el; fuel flows in MW_th on a lower-heating-value basis; prices in
EUR/MWh_th (fuels) and EUR/MWh_el (VOM); capital cost as PyPSA ``overnight_cost`` with the fixed O&M as ``fom_cost``; formerly: the fixed O&M
NOT folded in: PyPSA's own split is used, ``overnight_cost`` (EUR/MW) + ``fom_cost`` (EUR/MW/yr) + ``lifetime`` on the row, ``capital_cost`` blank and
``discount_rate`` = the scenario / Settings rate passed in (PyPSA annualises ``overnight_cost`` with it).

Algorithm (simple co-firing generator):
    With H2 energy share ``s`` (LHV basis), rated efficiency ``eta``, fuel prices ``c_g``, ``c_h`` (EUR/MWh_th), gas emission
    factor ``e_g`` (tCO2/MWh_th) and variable O&M ``v`` (EUR/MWh_el):
    $$ mc = \\frac{(1-s)\\,c_g + s\\,c_h}{\\eta} + v,\\qquad e_{blend} = (1-s)\\,e_g $$
    ASCII: marginal_cost = ((1-s)*c_g + s*c_h)/eta + v;  carrier co2_emissions = (1-s)*e_g  (tCO2 per MWh_th of blend).
    The app converts a Generator's carrier factor with ``/ efficiency`` to tCO2 per MWh_el, so the generator carries
    ``efficiency = eta`` (and the same ``eta`` is in ``mc``).

Algorithm (turbine Link, fuel network):
    The turbine Link takes fuel at ``bus0`` (MW_th) and delivers ``eta`` of it at ``bus1`` (MW_el): ``p_nom = P_el / eta``,
    ``overnight_cost = k_el * eta`` and ``fom_cost = f k_el eta`` (EUR per MW_th), ``marginal_cost = v * eta``, ``start_up_cost = u * P_el`` (EUR per start).
    ASCII: p_nom_th = P_el/eta; overnight_cost_th = capex_el*eta; fom_cost_th = fom%*capex_el*eta; marginal_cost_th = vom_el*eta.

Opt-in extras of a committable fixed-size unit (:func:`uc_extras`, all blank = off, no existing number changes): part-load efficiency
(:mod:`.partload`: piecewise ``efficiency`` curve on a Link, ``stand_by_cost`` + incremental ``marginal_cost`` on a Generator), hot / warm / cold
start costs (:mod:`.startcosts`: native ``start_up_cost`` = hot cost, increments by the plants ``constraints`` hook) and start-up / shut-down time
(native ``ramp_limit_start_up`` / ``_shut_down`` through ``RAGNAROK_TimeUnits``).
"""

from __future__ import annotations

import math
from typing import Any


from backend.app.plants import cofiring as cf
from ...pypsa.network.cost_basis import horizon_years
from . import partload as pl
from . import startcosts as sc
from . import technologies as tech
from .registry import Ctx, PlantError

_AC = {"", "ac", "dc", "electricity", "elec", "power"}
TURBINES = {"ccgt": "CCGT", "ocgt": "OCGT"}
TIME_UNITS_SHEET = "RAGNAROK_TimeUnits"


def num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def opt(value: Any) -> float | None:
    out = num(value, 0.0)
    return out if out > 0 else None


def default_ac_bus(model: dict[str, list[dict[str, Any]]]) -> str | None:
    """First electricity-carrier bus, else the first bus (the Build conversions' rule)."""
    buses = model.get("buses") or []
    elec = next((b for b in buses if str(b.get("carrier") or "").strip().lower() in _AC), None)
    chosen = elec if elec is not None else (buses[0] if buses else None)
    return str(chosen.get("name")) if chosen and chosen.get("name") else None


def _find_bus(ctx: Ctx, explicit: Any, carriers: tuple[str, ...]) -> str | None:
    """An explicit bus (must exist) or the first existing bus whose carrier is one of ``carriers`` (case-insensitive)."""
    if explicit:
        if str(explicit) not in ctx.buses:
            raise PlantError(f"Bus {explicit!r} not found in the model.")
        return str(explicit)
    want = {c.lower() for c in carriers}
    for b in ctx.model.get("buses") or []:
        if str(b.get("carrier") or "").strip().lower() in want:
            return str(b.get("name"))
    return None


def uc_fields(P: dict[str, float], p_el_mw: float, committable: bool, extendable: bool, warnings: list[str]) -> dict[str, Any]:
    """Unit-commitment fields of a thermal unit; empty unless ``committable`` and the size is fixed.

    ``p_min_pu`` is a minimum load WHILE RUNNING only for a committable unit (otherwise it is an always-on floor),
    so none of these are written when the unit is not committable. The ramp and the minimum up / down times are NOT
    written here: they are stated in hours and per minute in ``RAGNAROK_TimeUnits`` (:func:`add_time_units`) and the
    time-units module converts them with the snapshot weights of each run.
    """
    if not committable:
        return {}
    if extendable:
        warnings.append("Unit commitment needs a fixed capacity (committable and extendable are mutually exclusive in the "
                        "LP): the commitment fields are NOT written; set a fixed MW to enforce minimum load, ramps, "
                        "minimum up/down time and start-up cost (MIP).")
        return {}
    return {"committable": True, "p_min_pu": round(P["min_load"], 6), "start_up_cost": round(P["start_up_cost"] * p_el_mw, 6)}


def add_time_units(ctx: Ctx, sheet: str, name: str, P: dict[str, float], committable: bool, extendable: bool,
                   spec: dict[str, Any] | None = None, p_min_pu: float | None = None) -> None:
    """Queue the ``RAGNAROK_TimeUnits`` rows of a committable thermal unit: HOURS and a rate PER MINUTE, never snapshots.

    ``min_up_time`` / ``min_down_time`` in hours; ``up_time_before`` = the minimum up time (the unit is not forced to
    stay on at the start of the horizon); ``ramp_limit_up`` / ``ramp_limit_down`` = the technology's ``ramp_rate`` (percent
    of capacity per minute) as a fraction per minute. Nothing here depends on the workbook's snapshot spacing.

    Opt-in (spec ``startUpMinutes`` / ``shutDownMinutes``, blank = no row): PyPSA's own ``ramp_limit_start_up`` / ``ramp_limit_shut_down``,
    written as the rate that takes the unit between standstill and its minimum load ``p_min_pu`` in that many minutes,
    ``p_min_pu / minutes`` per minute. The time-units module converts them with the run's step ``w`` (``min(1, rate x w)``, never below
    ``p_min_pu``); PyPSA bounds the output of the start (shut-down) snapshot with it, so it only bites when the step is longer than
    the minutes stated; at a shorter step the bound equals the minimum load and the module's run note says so.
    """
    if not committable or extendable:
        return
    rows: list[dict[str, Any]] = [
        {"component": sheet, "name": name, "attribute": "min_up_time", "value": P["min_up_time"], "unit": "hours"},
        {"component": sheet, "name": name, "attribute": "min_down_time", "value": P["min_down_time"], "unit": "hours"},
        {"component": sheet, "name": name, "attribute": "up_time_before", "value": P["min_up_time"], "unit": "hours"},
        {"component": sheet, "name": name, "attribute": "ramp_limit_up", "value": round(P["ramp_rate"] / 100.0, 9), "unit": "per_minute"},
        {"component": sheet, "name": name, "attribute": "ramp_limit_down", "value": round(P["ramp_rate"] / 100.0, 9), "unit": "per_minute"},
    ]
    pmin = P["min_load"] if p_min_pu is None else p_min_pu
    for key, attr in (("startUpMinutes", "ramp_limit_start_up"), ("shutDownMinutes", "ramp_limit_shut_down")):
        minutes = _maybe((spec or {}).get(key))
        if minutes is None:
            continue
        if minutes <= 0:
            raise PlantError(f"{key} must be > 0 minutes, got {minutes!r}.")
        rows.append({"component": sheet, "name": name, "attribute": attr, "value": round(pmin / minutes, 12), "unit": "per_minute"})
        ctx.warnings.append(f"{attr} {name} = p_min_pu {pmin:.6g} / {minutes:g} min = {pmin / minutes:.6g} of p_nom per minute (RAGNAROK_TimeUnits): PyPSA's native "
                            "start / shut-down limit; it bounds the output of the start (shut-down) snapshot only, and is never set below the minimum load.")
    ctx.sheets[TIME_UNITS_SHEET].extend(rows)
    ctx.warnings.append(
        f"Time units (RAGNAROK_TimeUnits): minimum up / down time {P['min_up_time']:g} h / {P['min_down_time']:g} h and a ramp of {P['ramp_rate']:g} %/min are stored in hours "
        "and per minute; every run converts them with its own snapshot weights (ramp = min(1, rate per hour x hours per snapshot), times = ceil(hours / step)), so the plant "
        "is right at any resolution. The run notes and POST /api/time-units/preview show the converted values."
    )


def _maybe(value: Any) -> float | None:
    """``None`` for blank / non-numeric, else the float (zero is a value here, unlike :func:`opt`)."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


UC_EXTRA_KEYS = ("minLoadEfficiency", "startCostHot", "startCostWarm", "startCostCold", "startWarmAfterHours", "startColdAfterHours",
                 "startUpMinutes", "shutDownMinutes")


def uc_extras(ctx: Ctx, spec: dict[str, Any], sheet: str, row: dict[str, Any], P: dict[str, float], p_el: float, eta: float,
              eta_rated: float, *, fuel_price: float | None = None) -> dict[str, Any]:
    """Opt-in refinements of a committable unit, applied to ``row`` in place; returns what to show in the preview and registry.

    * ``minLoadEfficiency``: part-load efficiency (:mod:`.partload`): a Link gets PyPSA's piecewise ``efficiency`` curve (sheet
      ``links-efficiency-pw``) and ``p_min_pu`` = fuel at minimum load per unit of ``p_nom``; a Generator gets ``stand_by_cost`` and an
      incremental ``marginal_cost`` from the fuel price ``fuel_price`` of its blend.
    * ``startCostHot`` / ``startCostWarm`` / ``startCostCold`` (+ ``startWarmAfterHours`` / ``startColdAfterHours``): per-start costs in EUR/MW_el;
      the native ``start_up_cost`` becomes the hot cost, the warm / cold increments are the plants module's constraint hook
      (:mod:`.startcosts`, sheet ``RAGNAROK_StartCosts``).

    Nothing is written for a unit that is not committable with a fixed size (the keys are ignored with a warning), and nothing changes
    unless a key is set.
    """
    extras: dict[str, Any] = {}
    asked = [k for k in UC_EXTRA_KEYS if _maybe(spec.get(k)) is not None]
    if not asked:
        return extras
    if not row.get("committable"):
        ctx.warnings.append(f"{', '.join(asked)} need a fixed-size unit with unit commitment (committable): not applied.")
        return extras
    eta_min_in = _maybe(spec.get("minLoadEfficiency"))
    if eta_min_in is not None:
        eta_min = eta_min_in * eta / eta_rated        # a derate (off by default) scales both points alike
        curve = pl.heat_rate_curve(p_el, P["min_load"], eta, eta_min)
        if sheet == "links":
            row.update({"efficiency": round(eta, pl.DIGITS), "p_nom": round(p_el / eta, pl.DIGITS), "p_min_pu": round(curve["minLoadPu"], pl.DIGITS)})
            ctx.sheets["links-efficiency-pw"].extend(pl.link_curve_rows(str(row["name"]), curve))
            route = "piecewise-link"
            ctx.warnings.append(
                f"Part-load efficiency {eta_min_in:g} at {P['min_load']:g} of {p_el:g} MW_el (full load {eta:g}): PyPSA piecewise efficiency curve "
                f"(sheet links-efficiency-pw, p_pu 0 / {curve['minLoadPu']:.6g} / 1) tied to the unit's status; no-load fuel F0 = {curve['noLoadFuelMw']:.6g} MW_th, "
                f"incremental heat rate b = {curve['incrementalHeatRate']:.6g} MW_th/MW_el (efficiency {curve['incrementalEfficiency']:.4f}); p_min_pu = {curve['minLoadPu']:.6g}. "
                "The curve makes the run a MIP and cannot be combined with stochastic scenarios; the variable O&M stays per MWh of fuel (x full-load efficiency).")
        else:
            if fuel_price is None:
                raise PlantError("Part-load efficiency on a Generator needs the fuel price of its blend.")
            row.update(pl.generator_terms(curve, fuel_price, P["vom"]))
            route = "stand-by-generator"
            ctx.warnings.append(
                f"Part-load efficiency {eta_min_in:g} at {P['min_load']:g} of {p_el:g} MW_el (full load {eta:g}): stand_by_cost = {row['stand_by_cost']:.6g} per hour committed "
                f"(= fuel price {fuel_price:g} x no-load fuel {curve['noLoadFuelMw']:.6g} MW_th) and marginal_cost = {row['marginal_cost']:.6g} per MWh_el "
                f"(= {fuel_price:g} x b {curve['incrementalHeatRate']:.6g} + VOM). The no-load fuel is priced but not counted in the carrier's CO2 (which is per MWh_th at the full-load efficiency).")
        extras["partLoad"] = pl.describe(curve, route, None if sheet == "links" else {"stand_by_cost": row["stand_by_cost"], "marginal_cost": row["marginal_cost"]})
    hot_in, warm, cold = _maybe(spec.get("startCostHot")), _maybe(spec.get("startCostWarm")), _maybe(spec.get("startCostCold"))
    if hot_in is not None or warm is not None or cold is not None:
        hot = P["start_up_cost"] if hot_in is None else hot_in
        w_after, c_after = _maybe(spec.get("startWarmAfterHours")), _maybe(spec.get("startColdAfterHours"))
        try:
            sc.check_spec(hot, warm, cold, w_after, c_after)
        except ValueError as exc:
            raise PlantError(str(exc)) from exc
        row["start_up_cost"] = round(hot * p_el, 6)          # PyPSA's single start cost = the hot cost; the hook adds the warm / cold increments
        tiers: dict[str, Any] = {"hotPerMw": hot, "hot": row["start_up_cost"], "nativeStartUpCost": row["start_up_cost"], "unit": "per start"}
        if warm is not None or cold is not None:
            ctx.sheets[sc.SHEET].extend(sc.rows_for(sheet, str(row["name"]), hot=row["start_up_cost"],
                                                    warm=None if warm is None else round(warm * p_el, 6),
                                                    cold=None if cold is None else round(cold * p_el, 6),
                                                    warm_after_h=w_after, cold_after_h=c_after))
            if warm is not None:
                tiers.update({"warmPerMw": warm, "warm": round(warm * p_el, 6), "warmAfterHours": w_after})
            if cold is not None:
                tiers.update({"coldPerMw": cold, "cold": round(cold * p_el, 6), "coldAfterHours": c_after})
            ctx.warnings.append(
                f"Start costs by offline time (RAGNAROK_StartCosts): hot {tiers['hot']:g}"
                + (f", warm {tiers['warm']:g} after {w_after:g} h off" if warm is not None else "")
                + (f", cold {tiers['cold']:g} after {c_after:g} h off" if cold is not None else "")
                + " per start. The native start_up_cost is the hot cost; the plants module adds the warm / cold increment to the objective at solve time "
                  "(hours -> snapshots with the run's weights; run notes list it). Needs a contiguous single-period run; under Force-LP it is a relaxation.")
        extras["startCosts"] = tiers
    return extras


def _turbine_params(spec: dict[str, Any], kind: str) -> dict[str, float]:
    """Technology parameters of ``kind`` with the spec's ``params`` overrides and the ``efficiency`` shortcut."""
    over = dict(spec.get("params") or {})
    if spec.get("efficiency") not in (None, ""):
        over[f"{kind}.efficiency"] = spec["efficiency"]
    P = tech.resolve_parameters(over)
    out = {**P[kind], **{f"fuel_{k}": v for k, v in P[tech.FUELS].items()}}
    if not 0.0 < out["efficiency"] <= 1.0:
        raise PlantError(f"efficiency must be in (0, 1], got {out['efficiency']!r}.")
    return out


def _size(spec: dict[str, Any]) -> tuple[bool, float, float | None]:
    ext = bool(spec.get("extendable"))
    return ext, num(spec.get("pNom")), opt(spec.get("pNomMax"))


def _cost(P: dict[str, float], r: float, per_mw: float, years: float) -> dict[str, float]:
    """PyPSA's own cost split for ``per_mw`` overnight EUR per MW: ``overnight_cost``, ``fom_cost`` and ``discount_rate`` ``r`` (the
    scenario / Settings rate the caller passes; PyPSA refuses an ``overnight_cost`` row without one). ``capital_cost`` stays blank;
    ``lifetime`` is set on the row.

    ``fom_cost`` is PyPSA's column: per MW per MODELLED HORIZON, added to the objective unscaled. The module's input is per year, so it
    writes ``fom_cost = per_mw x fom% x years`` with ``years`` = the workbook's horizon (:func:`...cost_basis.horizon_years`); the build
    shows both numbers. Change the snapshots and re-apply the plant to refresh it."""
    return {"overnight_cost": round(per_mw, 6), "fom_cost": round(per_mw * P["fom"] / 100.0 * years, 6), "discount_rate": r}


def _derated(spec: dict[str, Any], P: dict[str, float], share: float, warnings: list[str]) -> tuple[float, float, dict[str, Any]]:
    """``(efficiency, capacity factor, record)`` after the optional H2 derate (zero by default = off)."""
    fuels = tech.resolve_parameters(spec.get("params"))[tech.FUELS]
    d_eff, d_cap = fuels["h2_derate_efficiency_per_share"], fuels["h2_derate_capacity_per_share"]
    eta, cap = P["efficiency"], 1.0
    rec = {"applied": bool(d_eff or d_cap), "shareReference": share, "efficiencyLossPerShare": d_eff, "capacityLossPerShare": d_cap,
           "basis": "assumption (no source in the data file); off by default"}
    if rec["applied"]:
        eta = P["efficiency"] - d_eff * share
        cap = 1.0 - d_cap * share
        if not 0.0 < eta <= 1.0 or not 0.0 < cap <= 1.0:
            raise PlantError("The H2 derate leaves a non-positive efficiency or capacity.")
        warnings.append(f"H2 derate is ON (assumption, no source): efficiency {P['efficiency']:.4f} -> {eta:.4f}, capacity x{cap:.4f} "
                        f"at an H2 energy share of {share:.3f}.")
    return eta, cap, rec


def _gas_supply(ctx: Ctx, spec: dict[str, Any], P: dict[str, float], ac_bus: str) -> tuple[str, dict[str, Any]]:
    """Gas bus + supply generator + gas carrier (reuses an existing gas bus and its supplier)."""
    ef = P["fuel_gas_co2"]
    ctx.carrier("gas", co2_emissions=ef)
    gas_bus = _find_bus(ctx, spec.get("gasBus"), ("gas", "natural gas", "ch4"))
    price = num(spec.get("gasPrice"), P["fuel_gas_price"]) if spec.get("gasPrice") not in (None, "") else P["fuel_gas_price"]
    info: dict[str, Any] = {"gasPrice": price, "gasCo2": ef, "created": []}
    if gas_bus is None:
        gas_bus = ctx.bus("gas", "gas", like=ac_bus)
        info["created"].append(gas_bus)
    has_supply = any(str(g.get("bus")) == gas_bus and str(g.get("carrier") or "").lower() == "gas" for g in ctx.model.get("generators") or [])
    if not has_supply:
        ctx.add("generators", {"name": ctx.nm("gas_supply"), "bus": gas_bus, "carrier": "gas", "p_nom_extendable": True,
                               "capital_cost": 0, "marginal_cost": round(price, 6)}, "gas supply", fuelPrice=price)
    elif spec.get("gasPrice") not in (None, ""):
        ctx.warnings.append(f"Gas bus {gas_bus!r} already has a gas supplier: its price is kept, the plant's gasPrice is not used.")
    return gas_bus, info


# ── CCGT / OCGT: gas -> electricity Link ─────────────────────────────────────────


def build_gas_turbine(kind: str, spec: dict[str, Any], ctx: Ctx, ac_bus: str, r: float) -> dict[str, Any]:
    """CCGT or OCGT as a Link from the gas bus to the AC bus (a committable Link when asked and fixed in size)."""
    P = _turbine_params(spec, kind)
    eta = P["efficiency"]
    ext, p_el, p_max = _size(spec)
    gas_bus, info = _gas_supply(ctx, spec, P, ac_bus)
    carrier = TURBINES[kind]
    ctx.carrier(carrier)
    link: dict[str, Any] = {
        "name": ctx.nm(), "bus0": gas_bus, "bus1": ac_bus, "carrier": carrier, "efficiency": round(eta, 8),
        **_cost(P, r, P["capex"] * 1000.0 * eta, horizon_years(ctx.model)), "marginal_cost": round(P["vom"] * eta, 6), "lifetime": P["lifetime"],
    }
    if ext:
        link.update({"p_nom_extendable": True, "p_nom": 0.0})
        if p_max:
            link["p_nom_max"] = round(p_max / eta, 6)
    else:
        link["p_nom"] = round(p_el / eta, 6)
    link.update(uc_fields(P, p_el, bool(spec.get("committable")), ext, ctx.warnings))
    extras = uc_extras(ctx, spec, "links", link, P, p_el, eta, eta)
    ctx.add("links", link, f"{carrier} turbine", **extras)
    add_time_units(ctx, "links", link["name"], P, bool(link.get("committable")), ext, spec, link.get("p_min_pu"))
    return {"main": {"sheet": "links", "name": link["name"]}, "parameters": P, "efficiency": eta, "gasBus": gas_bus,
            "fuel": info, "turbineCarrier": carrier, "capacityMwEl": None if ext else p_el, "feeders": None,
            "powerSeries": ("links", "p1"), "fuelSeries": ("links", "p0"), "committable": bool(link.get("committable")), **extras}


# ── simple co-firing: one Generator with a blend carrier ─────────────────────────


def blend_inputs(spec: dict[str, Any], P: dict[str, float]) -> dict[str, Any]:
    """H2 share in both bases and the LHV constants used (spec ``h2Share`` in ``h2ShareUnit``)."""
    K = tech.constants()
    lh, lg = K["h2_lhv_mj_per_nm3"], K["ch4_lhv_mj_per_nm3"]
    unit = str(spec.get("h2ShareUnit") or "energy").lower()
    if unit not in cf.UNITS:
        raise PlantError(f"h2ShareUnit must be one of {cf.UNITS}, got {spec.get('h2ShareUnit')!r}.")
    raw = num(spec.get("h2Share"))
    try:
        s = cf.share_to_energy(raw, unit, lh, lg)
    except ValueError as exc:
        raise PlantError(str(exc)) from exc
    return {"energyShare": s, "volShare": cf.energy_to_vol_share(s, lh, lg), "input": raw, "unit": unit, "lhvMjPerNm3": {"H2": lh, "CH4": lg}}


def build_cofiring_simple(kind: str, spec: dict[str, Any], ctx: Ctx, ac_bus: str, r: float) -> dict[str, Any]:
    """One Generator burning a fixed gas / H2 blend (see the module docstring for the cost and emission factors)."""
    P = _turbine_params(spec, kind)
    b = blend_inputs(spec, P)
    s = b["energyShare"]
    eta, cap_factor, derate = _derated(spec, P, s, ctx.warnings)
    price_h2 = num(spec.get("h2Price"), P["fuel_h2_price"]) if spec.get("h2Price") not in (None, "") else P["fuel_h2_price"]
    price_gas = num(spec.get("gasPrice"), P["fuel_gas_price"]) if spec.get("gasPrice") not in (None, "") else P["fuel_gas_price"]
    ef_g = P["fuel_gas_co2"]
    ext, p_el, p_max = _size(spec)
    carrier = f"{ctx.pid} blend"
    co2 = round((1.0 - s) * ef_g + s * P["fuel_h2_co2"], 8)
    ctx.carrier(carrier, co2_emissions=co2)
    mc = ((1.0 - s) * price_gas + s * price_h2) / eta + P["vom"]
    gen: dict[str, Any] = {
        "name": ctx.nm(), "bus": ac_bus, "carrier": carrier, "efficiency": round(eta, 8), "marginal_cost": round(mc, 6),
        **_cost(P, r, P["capex"] * 1000.0, horizon_years(ctx.model)), "lifetime": P["lifetime"],
    }
    if ext:
        gen.update({"p_nom_extendable": True, "p_nom": 0.0})
        if p_max:
            gen["p_nom_max"] = round(p_max * cap_factor, 6)
    else:
        gen["p_nom"] = round(p_el * cap_factor, 6)
    gen.update(uc_fields(P, p_el * cap_factor, bool(spec.get("committable")), ext, ctx.warnings))
    extras = uc_extras(ctx, spec, "generators", gen, P, p_el * cap_factor, eta, P["efficiency"],
                       fuel_price=(1.0 - s) * price_gas + s * price_h2)
    ctx.add("generators", gen, f"{TURBINES[kind]} gas + H2 generator", **extras)
    add_time_units(ctx, "generators", gen["name"], P, bool(gen.get("committable")), ext, spec, gen.get("p_min_pu"))
    return {**extras, "main": {"sheet": "generators", "name": gen["name"]}, "parameters": P, "efficiency": eta, "turbineCarrier": TURBINES[kind],
            "blend": {**b, "carrier": carrier, "carrierCo2": co2, "marginalCost": mc, "gasPrice": price_gas, "h2Price": price_h2,
                      "gasCo2": ef_g, "formula": "mc = ((1-s)*c_gas + s*c_h2)/eta + VOM; co2 = (1-s)*e_gas"},
            "derate": derate, "capacityMwEl": None if ext else p_el * cap_factor, "feeders": None,
            "powerSeries": ("generators", "p"), "fuelSeries": None, "committable": bool(gen.get("committable"))}


# ── fuel-network co-firing: gas + H2 buses -> turbine fuel bus -> turbine Link ───


def build_cofiring_network(kind: str, spec: dict[str, Any], ctx: Ctx, ac_bus: str, r: float) -> dict[str, Any]:
    """Gas bus and H2 bus feed a turbine-fuel bus through Links (efficiency 1, LHV basis); the turbine runs fuel bus -> AC."""
    P = _turbine_params(spec, kind)
    K = tech.constants()
    blend = _blend_spec(spec)
    ref_share = 0.0
    if blend["maxShare"] is not None:
        ref_share = cf.share_to_energy(blend["maxShare"], blend["unit"], K["h2_lhv_mj_per_nm3"], K["ch4_lhv_mj_per_nm3"])
    eta, cap_factor, derate = _derated(spec, P, ref_share, ctx.warnings)
    if derate["applied"] and blend["maxShare"] is None:
        ctx.warnings.append("The H2 derate is applied at the maximum blend share, but no maximum share is set: it has no effect.")
    ext, p_el, p_max = _size(spec)
    gas_bus, ginfo = _gas_supply(ctx, spec, P, ac_bus)
    price_h2 = num(spec.get("h2Price"), P["fuel_h2_price"]) if spec.get("h2Price") not in (None, "") else P["fuel_h2_price"]
    h2_bus = _find_bus(ctx, spec.get("h2Bus"), ()) if spec.get("h2Bus") else None
    ctx.carrier("H2", co2_emissions=P["fuel_h2_co2"])
    h2_created = False
    if h2_bus is None:
        h2_bus = ctx.bus("h2", "H2", like=ac_bus)
        h2_created = True
        ctx.add("generators", {"name": ctx.nm("h2_supply"), "bus": h2_bus, "carrier": "H2", "p_nom_extendable": True,
                               "capital_cost": 0, "marginal_cost": round(price_h2, 6)}, "H2 supply", fuelPrice=price_h2)
    else:
        feeds = any(str(g.get("bus")) == h2_bus for g in ctx.model.get("generators") or []) or any(
            h2_bus in {str(x.get(c)) for c in ("bus1", "bus2", "bus3")} for x in [*(ctx.model.get("links") or []), *(ctx.model.get("processes") or [])])
        if not feeds:
            ctx.warnings.append(f"H2 bus {h2_bus!r} has no generator, Link or Process delivering into it: the turbine can only burn gas. "
                                "Add a supply or a P2X chain on that bus.")
    fuel_bus = ctx.bus("fuel", "turbine fuel", like=ac_bus)
    free = {"p_nom_extendable": True, "p_nom": 0.0, "capital_cost": 0}
    gas_feed = ctx.add("links", {"name": ctx.nm("gas_feed"), "bus0": gas_bus, "bus1": fuel_bus, "carrier": "gas feed", "efficiency": 1.0, **free}, "gas feeder")
    h2_feed = ctx.add("links", {"name": ctx.nm("h2_feed"), "bus0": h2_bus, "bus1": fuel_bus, "carrier": "H2 feed", "efficiency": 1.0, **free}, "H2 feeder")
    ctx.carrier("gas feed")
    ctx.carrier("H2 feed")
    carrier = TURBINES[kind]
    ctx.carrier(carrier)
    link: dict[str, Any] = {
        "name": ctx.nm(), "bus0": fuel_bus, "bus1": ac_bus, "carrier": carrier, "efficiency": round(eta, 8),
        **_cost(P, r, P["capex"] * 1000.0 * eta, horizon_years(ctx.model)), "marginal_cost": round(P["vom"] * eta, 6), "lifetime": P["lifetime"],
    }
    if ext:
        link.update({"p_nom_extendable": True, "p_nom": 0.0})
        if p_max:
            link["p_nom_max"] = round(p_max * cap_factor / eta, 6)
    else:
        link["p_nom"] = round(p_el * cap_factor / eta, 6)
    link.update(uc_fields(P, p_el * cap_factor, bool(spec.get("committable")), ext, ctx.warnings))
    extras = uc_extras(ctx, spec, "links", link, P, p_el * cap_factor, eta, P["efficiency"])
    ctx.add("links", link, f"{carrier} turbine (fuel bus -> AC)", **extras)
    add_time_units(ctx, "links", link["name"], P, bool(link.get("committable")), ext, spec, link.get("p_min_pu"))
    return {**extras, "main": {"sheet": "links", "name": link["name"]}, "parameters": P, "efficiency": eta, "turbineCarrier": carrier,
            "gasBus": gas_bus, "h2Bus": h2_bus, "fuelBus": fuel_bus, "h2BusCreated": h2_created, "fuel": {**ginfo, "h2Price": price_h2},
            "feeders": {"gas": gas_feed["name"], "h2": h2_feed["name"]}, "blend": blend,
            "lhvMjPerNm3": {"H2": K["h2_lhv_mj_per_nm3"], "CH4": K["ch4_lhv_mj_per_nm3"]}, "derate": derate,
            "capacityMwEl": None if ext else p_el * cap_factor, "powerSeries": ("links", "p1"), "fuelSeries": ("links", "p0"),
            "committable": bool(link.get("committable"))}


def _blend_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Blend limits stored with a fuel-network plant (``blendMin`` / ``blendMax`` fractions, ``blendUnit``, ``blendScope``)."""
    lo = spec.get("blendMin")
    hi = spec.get("blendMax")
    try:
        return cf._block({"minShare": lo, "maxShare": hi, "unit": spec.get("blendUnit"), "scope": spec.get("blendScope")})
    except ValueError as exc:
        raise PlantError(str(exc)) from exc
