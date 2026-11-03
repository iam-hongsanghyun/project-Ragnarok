"""Which unit pays which fuel, and the marginal-cost series the module writes for it.

A fuel price (currency/MWh_thermal, a series per carrier) becomes a unit's time-varying ``marginal_cost`` at run
time; the workbook is not rewritten. Carbon is NOT part of it: the carbon-pricing module adds it to the objective.

Algorithm:
    For a Generator :math:`g` of a priced carrier :math:`c` (electric efficiency :math:`\\eta_{g,t}`, fuel price
    :math:`\\pi^{f}_{c,t}`, variable O&M :math:`v_g`)

    $$ mc_{g,t} = \\frac{\\pi^{f}_{c,t}}{\\eta_{g,t}} + v_g \\qquad [\\text{currency}/\\mathrm{MWh_{el}}] $$

    ASCII: mc[g,t] = fuel[c,t] / eta[g,t] + vom[g]

    A Link :math:`l` converts fuel at ``bus0`` (MW_th, ``p0``) into electricity at ``bus1`` (:math:`p_1 = -\\eta_{l,t}\\,p_0`
    in MW_el). PyPSA's Link ``marginal_cost`` is per MW of ``p0``, so the electric cost
    :math:`\\pi^{f}/\\eta + v` is split between the Link and the fuel supply:

    $$ mc^{link}_{l,t} = v_l\\,\\eta_{l,t}, \\quad mc^{supply}_{s,t} = \\pi^{f}_{c,t}
       \\qquad\\text{(a priced supply Generator } s \\text{ on } bus0\\text{)} $$
    $$ mc^{link}_{l,t} = \\pi^{f}_{c,t} + v_l\\,\\eta_{l,t} \\qquad\\text{(no supply Generator on } bus0\\text{)} $$

    ASCII: link mc = vom*eta (+ fuel if bus0 has no priced supply generator); supplier mc = fuel.
    Per MWh_el both are fuel/eta + vom.

    Symbols: :math:`\\pi^{f}` fuel price (currency/MWh_th); :math:`\\eta` electric efficiency (MWh_el per MWh_th,
    dimensionless, > 0); :math:`v` variable O&M (currency/MWh_el); :math:`mc` marginal cost (currency per MWh of the
    unit's own output: MWh_el for a Generator, MWh_th of ``p0`` for a Link).

The Link convention (one home for it):

* A Link is a FUEL CONVERTER when its ``bus0`` carrier is not an electricity carrier
  (``""``, ``ac``, ``dc``, ``electricity``, ``elec``, ``power`` - the plants module's convention). A Link on an
  electricity ``bus0`` (battery charger, interconnector, HVDC) is never priced, only given a VOM when a row names it.
* Its fuel supplier is every Generator on ``bus0`` whose carrier has a price (the composites' ``gas supply`` /
  ``H2 supply`` generators). The Link's fuel carrier is that carrier; with several carriers on ``bus0`` the bus
  carrier decides, else the Link is ambiguous and left as the workbook has it (reported).
* Without a priced supplier the fuel carrier is the carrier of ``bus0`` (else the Link's own carrier) and the fuel
  is priced on the Link itself.
* Multi-output Links (``efficiency2`` ...) keep the VOM on the electric output: ``bus1`` and its efficiency.
* A supplied Link with no ``RAGNAROK_VariableOM`` row keeps its own static ``marginal_cost`` as its VOM
  (``v = mc / eta``, reported as source ``workbook``): its fuel is on the supplier, so that value is non-fuel cost
  (the plants catalogue writes ``vom x eta`` there). A Generator has no such fallback: its static value may hold fuel.
* A Generator on a fuel (non-electricity) bus is a SUPPLIER: priced per MWh_th, efficiency 1 when blank.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import pypsa
from fastapi import HTTPException

from .inputs import (
    PriceSet,
    VomTable,
    price_set,
    priced_carriers,
    read_price_scenarios,
    read_vom,
    scenario_prices,
    stochastic_price_changes,
)

#: Bus carriers that mean electricity (mirrors ``backend/app/plants/thermal._AC``).
ELECTRIC_BUS_CARRIERS = frozenset({"", "ac", "dc", "electricity", "elec", "power"})
GENERATOR, LINK = "Generator", "Link"
#: Roles of a unit.
ROLE_GENERATOR, ROLE_SUPPLIER = "generator", "supplier"
ROLE_LINK_SUPPLIED, ROLE_LINK_DIRECT, ROLE_VOM_ONLY = "link-supplied", "link-direct", "vom-only"
_MAX_NOTE_UNITS = 25


def _rows(model: dict[str, Any] | None, sheet: str) -> list[dict[str, Any]]:
    return [r for r in ((model or {}).get(sheet) or []) if isinstance(r, dict) and str(r.get("name") or "").strip()]


def _num(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _text(value: Any) -> str:
    return "" if value is None or (isinstance(value, float) and math.isnan(value)) else str(value).strip()


def is_electric_bus_carrier(carrier: str) -> bool:
    return carrier.strip().lower() in ELECTRIC_BUS_CARRIERS


@dataclass(frozen=True)
class UnitSpec:
    """One unit the module prices, from the workbook rows (no network needed)."""

    component: str            # "Generator" | "Link"
    name: str
    carrier: str              # the unit's own carrier
    role: str
    fuel_carrier: str | None  # the carrier whose price applies
    suppliers: tuple[str, ...]  # link-supplied: the supply Generators priced for it
    needs_eta: bool           # a positive efficiency must be stated
    eta_problem: str | None   # why the stated efficiency is unusable (None = fine)
    vom: float                # currency/MWh_el (0 when no row)
    vom_source: str           # "name" | "carrier" | "workbook" | "none"
    skip: str | None = None   # why the module leaves it as the workbook has it


def _series_columns(model: dict[str, Any], sheet: str) -> set[str]:
    """Names with at least one value in a series sheet (``generators-efficiency``)."""
    out: set[str] = set()
    for r in (model.get(sheet) or []):
        if not isinstance(r, dict):
            continue
        for k, v in r.items():
            if k != "snapshot" and _num(v) is not None:
                out.add(str(k))
    return out


def _curve_names(model: dict[str, Any], sheet: str) -> set[str]:
    return {str(r.get("name")) for r in (model.get(sheet) or []) if isinstance(r, dict) and r.get("name")}


def resolve_units(model: dict[str, Any], vom: VomTable | None = None, priced: set[str] | None = None) -> list[UnitSpec]:
    """Classify every Generator and Link of the workbook (the module's Link convention is in the module docstring).

    A unit is listed when it has a fuel price to apply or a variable O&M row. Pure on the sheet rows, so the
    ``guard`` hook can run it before any network is built.
    """
    vom = vom if vom is not None else read_vom(model)
    priced = priced if priced is not None else priced_carriers(model)
    bus_carrier = {str(b["name"]): _text(b.get("carrier")) for b in _rows(model, "buses")}
    gen_eta_series = _series_columns(model, "generators-efficiency")
    link_eta_series = _series_columns(model, "links-efficiency")
    pw_gen = _curve_names(model, "generators-marginal_cost-pw")
    pw_link = _curve_names(model, "links-marginal_cost-pw") | _curve_names(model, "links-efficiency-pw")

    def is_fuel_bus(bus: str) -> bool:
        return not is_electric_bus_carrier(bus_carrier.get(bus, ""))

    gens = _rows(model, "generators")
    suppliers_at: dict[str, list[tuple[str, str]]] = {}
    for g in gens:
        carrier, bus = _text(g.get("carrier")), _text(g.get("bus"))
        if carrier in priced and is_fuel_bus(bus):
            suppliers_at.setdefault(bus, []).append((str(g["name"]), carrier))

    def eta_check(row: dict[str, Any], series: set[str], *, blank_ok: bool) -> tuple[bool, str | None]:
        """``(needs_eta, problem)``: a stated efficiency must be > 0; blank is a problem unless a series or ``blank_ok``."""
        name = str(row["name"])
        if name in series:
            return True, None
        eta = _num(row.get("efficiency"))
        if eta is None:
            return (not blank_ok), (None if blank_ok else "efficiency is blank (PyPSA would silently use 1)")
        if eta <= 0:
            return True, f"efficiency {eta:g} is not > 0"
        return True, None

    out: list[UnitSpec] = []
    for g in gens:
        name, carrier, bus = str(g["name"]), _text(g.get("carrier")), _text(g.get("bus"))
        v, vsrc = vom.lookup(GENERATOR, name, carrier)
        is_priced = carrier in priced
        if not is_priced and v is None:
            continue
        skip = None
        if name in pw_gen:
            skip = "piecewise marginal_cost curve (its own cost curve is kept)"
        elif (_num(g.get("stand_by_cost")) or 0.0) > 0:
            skip = "part-load generator (stand_by_cost with an incremental marginal_cost: its fuel price is inside its curve)"
        if is_priced and is_fuel_bus(bus):
            role = ROLE_SUPPLIER
            needs, problem = eta_check(g, gen_eta_series, blank_ok=True)  # a supplier with no efficiency stated is 1
        elif is_priced:
            role = ROLE_GENERATOR
            needs, problem = eta_check(g, gen_eta_series, blank_ok=False)
        else:
            role, needs, problem = ROLE_VOM_ONLY, False, None
        out.append(UnitSpec(GENERATOR, name, carrier, role, carrier if is_priced else None, (), needs, problem,
                            float(v or 0.0), vsrc, skip))

    for ln in _rows(model, "links"):
        name, carrier, bus0 = str(ln["name"]), _text(ln.get("carrier")), _text(ln.get("bus0"))
        v, vsrc = vom.lookup(LINK, name, carrier)
        fuel_carrier: str | None = None
        suppliers: tuple[str, ...] = ()
        role = ROLE_VOM_ONLY
        skip = None
        if is_fuel_bus(bus0):
            at_bus = suppliers_at.get(bus0, [])
            carriers_here = sorted({c for _, c in at_bus})
            if carriers_here:
                bus_c = bus_carrier.get(bus0, "")
                if bus_c in carriers_here:
                    fuel_carrier = bus_c
                elif len(carriers_here) == 1:
                    fuel_carrier = carriers_here[0]
                else:
                    skip = f"bus0 {bus0!r} has supply generators of several priced carriers ({', '.join(carriers_here)}): ambiguous fuel"
                if fuel_carrier is not None:
                    role = ROLE_LINK_SUPPLIED
                    suppliers = tuple(n for n, c in at_bus if c == fuel_carrier)
            elif bus_carrier.get(bus0, "") in priced:
                fuel_carrier, role = bus_carrier[bus0], ROLE_LINK_DIRECT
            elif carrier in priced:
                fuel_carrier, role = carrier, ROLE_LINK_DIRECT
        if fuel_carrier is None and v is None and skip is None:
            continue
        if skip is None and name in pw_link:
            skip = "piecewise efficiency / marginal_cost curve (its own cost curve is kept)"
        elif skip is None and (_num(ln.get("stand_by_cost")) or 0.0) > 0:
            skip = "part-load link (stand_by_cost: its fuel price is inside its curve)"
        needs, problem = eta_check(ln, link_eta_series, blank_ok=False)
        if v is None and role == ROLE_LINK_SUPPLIED:
            # The fuel is on the supplier, so the Link's own static marginal_cost is its non-fuel cost per MWh_th
            # (the plants catalogue writes vom x eta there): keep it as the VOM rather than dropping it to 0.
            mc0, eta0 = _num(ln.get("marginal_cost")), _num(ln.get("efficiency"))
            if mc0 and eta0 and eta0 > 0:
                v, vsrc = mc0 / eta0, "workbook"
        out.append(UnitSpec(LINK, name, carrier, role, fuel_carrier, suppliers, needs, problem, float(v or 0.0), vsrc, skip))
    return out


def efficiency_problems(units: list[UnitSpec]) -> list[str]:
    """Human-readable lines for every unit that is priced (or carries a VOM) with an unusable efficiency.

    Skipped units are not priced, so they are not a problem. A priced Generator, and every Link, needs a stated
    efficiency > 0: dividing the fuel price by a silent 1 understates the fuel cost.
    """
    return [f"{u.component} {u.name}: {u.eta_problem}" for u in units if u.eta_problem and u.skip is None]


def raise_on_efficiency_problems(units: list[UnitSpec]) -> None:
    problems = efficiency_problems(units)
    if problems:
        shown = "; ".join(problems[:8]) + (f"; ... and {len(problems) - 8} more" if len(problems) > 8 else "")
        raise HTTPException(
            status_code=400,
            detail=(
                f"Fuel costs: {shown}. A priced unit's marginal cost is fuel price / efficiency + VOM, so it needs a stated "
                "efficiency > 0 (Generator / Link `efficiency`, or a `<list>-efficiency` series). Fix the rows, or turn the "
                "module off with options.fuelCosts.enabled = false."
            ),
        )


# ── the plan on a network ───────────────────────────────────────────────────────────

@dataclass
class AppliedUnit:
    """A unit with the series the module computed for it."""

    spec: UnitSpec
    eta: pd.Series                   # electric efficiency on the snapshots (1 for a supplier with none stated)
    fuel: pd.Series | None           # fuel price on the snapshots (NaN = none); None when the unit has no fuel carrier
    mc_old: pd.Series                # the workbook's marginal cost on the snapshots (per MWh of the unit's own flow)
    mc_new: pd.Series                # what the module writes
    status: str                      # "applied" | "unpriced" | "skipped"
    reason: str = ""
    unpriced_snapshots: int = 0      # snapshots with a fuel carrier but no price

    @property
    def changed(self) -> bool:
        return self.status == "applied"


@dataclass
class FuelPlan:
    """Everything the module decided for one network."""

    units: list[AppliedUnit]
    prices: PriceSet
    notes: list[str] = field(default_factory=list)

    def get(self, component: str, name: str) -> AppliedUnit | None:
        for u in self.units:
            if u.spec.component == component and u.spec.name == name:
                return u
        return None


def _dense(network: pypsa.Network, component: str, attr: str) -> pd.DataFrame:
    return network.get_switchable_as_dense(component, attr).astype(float)


def _apply_specs(
    specs: list[UnitSpec],
    snaps: pd.Index,
    prices: pd.DataFrame,
    eta_dense: dict[str, pd.DataFrame],
    mc_dense: dict[str, pd.DataFrame],
    present: dict[str, set[str]],
    scenario: str = "",
) -> tuple[list[AppliedUnit], list[str]]:
    """The per-unit rule on plain (one scenario, or none) frames: ``(units, problems)``."""
    units: list[AppliedUnit] = []
    problems: list[str] = []
    where = f" in scenario '{scenario}'" if scenario else ""
    for s in specs:
        if s.name not in present[s.component]:
            continue
        eta = eta_dense[s.component][s.name]
        mc_old = mc_dense[s.component][s.name]
        fuel = prices[s.fuel_carrier] if s.fuel_carrier is not None and s.fuel_carrier in prices.columns else None
        if s.skip is not None:
            units.append(AppliedUnit(s, eta, fuel, mc_old, mc_old.copy(), "skipped", s.skip))
            continue
        if s.needs_eta and not bool(((eta > 0) & np.isfinite(eta)).all()):
            problems.append(f"{s.component} {s.name}: efficiency is <= 0 or blank on a modelled snapshot{where}")
            continue
        if s.role != ROLE_VOM_ONLY and (fuel is None or fuel.notna().sum() == 0):
            why = f"no price for carrier '{s.fuel_carrier}' on any modelled snapshot" if s.fuel_carrier else "no fuel carrier"
            units.append(AppliedUnit(s, eta, fuel, mc_old, mc_old.copy(), "unpriced", why, len(mc_old)))
            continue
        if s.role in (ROLE_GENERATOR, ROLE_SUPPLIER):
            assert fuel is not None
            mc_new = fuel.div(eta).add(s.vom).where(fuel.notna(), mc_old)
        elif s.role == ROLE_LINK_SUPPLIED:
            mc_new = eta * s.vom                      # the fuel is priced on the supply Generator
        elif s.role == ROLE_LINK_DIRECT:
            assert fuel is not None
            mc_new = fuel.add(eta * s.vom).where(fuel.notna(), mc_old)
        elif s.component == GENERATOR:                # VOM only: marginal cost = VOM
            mc_new = pd.Series(s.vom, index=snaps, dtype=float)
        else:                                         # VOM only on a Link: per MW of p0
            mc_new = eta * s.vom
        n_unpriced = int(fuel.isna().sum()) if fuel is not None and s.role != ROLE_VOM_ONLY else 0
        units.append(AppliedUnit(s, eta, fuel, mc_old, mc_new.astype(float), "applied", "", n_unpriced))
    return units, problems


def build_plan(network: pypsa.Network, model: dict[str, Any], currency: str = "") -> FuelPlan:
    """Decide every unit's marginal-cost series for a non-stochastic ``network`` (nothing is written; see :func:`apply_plan`).

    Args:
        network: the built network (its snapshots are the run's window).
        model: the workbook sheets (the inputs and the unit rows are read from them).
        currency: symbol for the notes.

    Raises:
        HTTPException: 400 - an unusable efficiency on a priced unit (stated, or a series that is <= 0 / NaN on a
            modelled snapshot); a malformed input sheet; a stochastic network (use :func:`build_stochastic_plans`).
    """
    if getattr(network, "has_scenarios", False):
        raise HTTPException(status_code=500, detail="build_plan is for a deterministic network; use build_stochastic_plans.")
    snaps = network.snapshots
    vom = read_vom(model)
    prices = price_set(model, snaps)
    priced = priced_carriers(model)
    specs = resolve_units(model, vom, priced)
    raise_on_efficiency_problems(specs)

    eta_dense = {GENERATOR: _dense(network, GENERATOR, "efficiency"), LINK: _dense(network, LINK, "efficiency")}
    mc_dense = {GENERATOR: _dense(network, GENERATOR, "marginal_cost"), LINK: _dense(network, LINK, "marginal_cost")}
    present = {GENERATOR: set(network.generators.index), LINK: set(network.links.index)}
    units, problems = _apply_specs(specs, snaps, prices.frame, eta_dense, mc_dense, present)
    if problems:
        raise HTTPException(status_code=400, detail="Fuel costs: " + "; ".join(problems[:8]))

    plan = FuelPlan(units, prices)
    plan.notes = describe(plan, currency)
    return plan


def build_stochastic_plans(network: pypsa.Network, model: dict[str, Any], config: Any, currency: str = "") -> dict[str, FuelPlan]:
    """One :class:`FuelPlan` per scenario of a stochastic network, computed AFTER the scenario overrides were applied.

    Scenario ``S`` sees its own fuel prices (the base series, then the ``RAGNAROK_FuelPriceScenarios`` rows of ``S``, then the
    ``carriers.fuel_price`` override rows of ``S``), its own efficiency (static or series, after its overrides) and its own
    workbook marginal cost where the module leaves a unit alone. ``config`` is the parsed ``StochasticConfig``.

    Raises:
        HTTPException: 400 - as :func:`build_plan`, naming the scenario; a ``marginal_cost`` override of a unit the module prices.
    """
    snaps = network.snapshots
    vom = read_vom(model)
    base = price_set(model, snaps)
    priced = priced_carriers(model)
    specs = resolve_units(model, vom, priced)
    raise_on_efficiency_problems(specs)
    raise_on_marginal_cost_overrides(config, specs)
    changes = read_price_scenarios(model) + stochastic_price_changes(config)
    eta_all = {GENERATOR: _dense(network, GENERATOR, "efficiency"), LINK: _dense(network, LINK, "efficiency")}
    mc_all = {GENERATOR: _dense(network, GENERATOR, "marginal_cost"), LINK: _dense(network, LINK, "marginal_cost")}
    present = {GENERATOR: {str(n[-1]) for n in network.generators.index}, LINK: {str(n[-1]) for n in network.links.index}}

    def of_scenario(frames: dict[str, pd.DataFrame], name: str) -> dict[str, pd.DataFrame]:
        return {c: f.xs(name, level="scenario", axis=1) for c, f in frames.items()}

    plans: dict[str, FuelPlan] = {}
    problems: list[str] = []
    for k, sc in enumerate(config.scenarios):
        frame = scenario_prices(base.frame, changes, sc.name)
        source = dict(base.source)
        source.update({c: "scenario" for c in frame.columns if c not in base.frame.columns})
        units, probs = _apply_specs(specs, snaps, frame, of_scenario(eta_all, sc.name), of_scenario(mc_all, sc.name), present, sc.name)
        problems += probs
        plan = FuelPlan(units, PriceSet(frame, source))
        notes = describe(plan, currency, label=sc.name)
        plan.notes = notes if k == 0 else [n for n in notes if "overrode marginal_cost" in n]
        plans[sc.name] = plan
    if problems:
        raise HTTPException(status_code=400, detail="Fuel costs: " + "; ".join(problems[:8]))
    return plans


def marginal_cost_overrides(config: Any, specs: list[UnitSpec]) -> list[str]:
    """Stochastic override rows that set ``marginal_cost`` of a unit the module prices (it writes that value itself)."""
    hits: list[str] = []
    if config is None or not getattr(config, "enabled", False):
        return hits
    kind = {"generators": GENERATOR, "links": LINK}
    for sc in config.scenarios:
        for ov in sc.overrides:
            comp = kind.get(ov.sheet)
            if comp is None or ov.attribute != "marginal_cost":
                continue
            for u in specs:
                if u.component != comp or u.skip is not None:
                    continue
                if (ov.scope_type == "all" or (ov.scope_type == "name" and u.name == ov.scope_value)
                        or (ov.scope_type == "carrier" and u.carrier == ov.scope_value)):
                    scope = "all rows" if ov.scope_type == "all" else f"{ov.scope_type} {ov.scope_value}"
                    hits.append(f"scenario '{sc.name}' overrides {ov.sheet}.marginal_cost ({scope}, {ov.operation} {ov.value:g}), which hits {u.component} {u.name}")
                    break
    return hits


def raise_on_marginal_cost_overrides(config: Any, specs: list[UnitSpec]) -> None:
    hits = marginal_cost_overrides(config, specs)
    if hits:
        raise HTTPException(
            status_code=400,
            detail=(
                "Fuel costs: " + "; ".join(hits[:6]) + ". The fuel-costs module writes the marginal cost of those units "
                "(fuel / efficiency + VOM), so a marginal_cost override would scale the VOM too or be overwritten. "
                "Change the fuel price instead (override sheet carriers, attribute fuel_price, or RAGNAROK_FuelPriceScenarios), "
                "or `efficiency` (honoured), or turn the module off with options.fuelCosts.enabled = false."
            ),
        )


def apply_plan(network: pypsa.Network, plan: FuelPlan) -> int:
    """Write the plan's series into ``generators_t.marginal_cost`` / ``links_t.marginal_cost``. Returns the unit count."""
    n = 0
    for u in plan.units:
        if not u.changed:
            continue
        frame = network.generators_t.marginal_cost if u.spec.component == GENERATOR else network.links_t.marginal_cost
        frame[u.spec.name] = u.mc_new.to_numpy(dtype=float)
        n += 1
    return n


def apply_stochastic_plans(network: pypsa.Network, plans: dict[str, FuelPlan]) -> int:
    """Write every scenario's series as ``(scenario, name)`` columns of ``generators_t`` / ``links_t`` ``marginal_cost``."""
    n = 0
    for scenario, plan in plans.items():
        for u in plan.units:
            if not u.changed:
                continue
            frame = network.generators_t.marginal_cost if u.spec.component == GENERATOR else network.links_t.marginal_cost
            frame[(scenario, u.spec.name)] = u.mc_new.to_numpy(dtype=float)
            n += 1
    return n


def _mean(s: pd.Series) -> float:
    return float(s.mean()) if len(s) else float("nan")


def describe(plan: FuelPlan, currency: str = "", label: str = "") -> list[str]:
    """The run notes: what was overridden (old -> new mean), what was left alone and why."""
    cur = f" {currency}" if currency else ""
    tag = f"[scenario {label}] " if label else ""
    applied = [u for u in plan.units if u.changed]
    notes: list[str] = []
    if not plan.units:
        return notes
    src = ", ".join(f"{c} ({k})" for c, k in sorted(plan.prices.source.items())) or "none"
    notes.append(
        f"{tag}Fuel costs: marginal cost = fuel price / efficiency + VOM written for {len(applied)} unit(s) at run time "
        f"(carbon is not in it: the carbon-pricing module adds it to the objective). Price sources: {src}."
    )
    lines = [
        f"{u.spec.component} {u.spec.name} [{u.spec.role}]: {_mean(u.mc_old):.4g} -> {_mean(u.mc_new):.4g}{cur}/MWh"
        for u in applied
    ]
    if lines:
        shown = lines[:_MAX_NOTE_UNITS]
        more = f" ... and {len(lines) - len(shown)} more" if len(lines) > len(shown) else ""
        notes.append(f"{tag}Fuel costs overrode marginal_cost (mean, old -> new): " + "; ".join(shown) + more + ".")
    for u in plan.units:
        if u.status == "skipped" or u.status == "unpriced":
            notes.append(f"{tag}Fuel costs: {u.spec.component} {u.spec.name} left as the workbook has it - {u.reason}.")
        elif u.unpriced_snapshots:
            notes.append(
                f"{tag}Fuel costs: {u.spec.component} {u.spec.name}: no price for '{u.spec.fuel_carrier}' on "
                f"{u.unpriced_snapshots} of {len(u.mc_new)} snapshot(s); the workbook's marginal cost stands there."
            )
    no_vom = [u.spec.name for u in applied if u.spec.vom_source == "none" and u.spec.role not in (ROLE_VOM_ONLY, ROLE_SUPPLIER)]
    if no_vom:
        shown_names = ", ".join(no_vom[:_MAX_NOTE_UNITS]) + (f" ... and {len(no_vom) - _MAX_NOTE_UNITS} more" if len(no_vom) > _MAX_NOTE_UNITS else "")
        notes.append(f"{tag}Fuel costs: no RAGNAROK_VariableOM row for {len(no_vom)} priced unit(s), VOM taken as 0: {shown_names}.")
    return notes
