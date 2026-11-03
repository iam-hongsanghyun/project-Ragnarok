"""The fuel-costs numbers: the cost breakdown per unit, the preview before a run and the ex-post results after it.

Per unit and snapshot the cost of one MWh of electric output splits into

* ``fuel``   - fuel price / efficiency (the module's own input),
* ``vom``    - the variable O&M row (the module's own input),
* ``carbon`` - the carbon-pricing module's objective term per MWh (``adder_frame``; for a Link it is the adder of the
  upstream fuel-supply Generator that burns the fuel, divided by the Link's efficiency),
* ``other``  - the workbook's own marginal cost on snapshots that carry no fuel price (left as stated),

and the unit's levelised cost over the horizon is

Algorithm:
    $$ \\mathrm{LCOE}_u = \\frac{K_u + F_u + \\sum_t w_t\\,q_{u,t}\\,\\big(c^{fuel}_{u,t} + v_u + c^{CO_2}_{u,t} + c^{other}_{u,t}\\big)}
        {\\sum_t w_t\\,q_{u,t}} $$

    ASCII: LCOE = (capex + fom + sum_t w*q*(fuel + vom + carbon + other)) / sum_t w*q

    :math:`K_u` + :math:`F_u` are PyPSA's own ``n.statistics.capex`` + ``n.statistics.fom`` over the modelled horizon
    (currency, via :func:`backend.pypsa.results.stat_metrics.fixed_cost_table`); :math:`w_t` the objective snapshot
    weighting times the investment-period objective weighting in a pathway run (h); :math:`q_{u,t}` the unit's electric
    output (MW: Generator ``p``, Link ``-p1``); the four :math:`c` in currency/MWh_el. A unit with no generation has no
    LCOE (``null``). A fuel-supply Generator is priced per MWh_th and its cost is carried by the Links that burn its fuel,
    so it has none. Carbon is read from the carbon-pricing module (``adder_frame``), never recomputed here.

The per-bus hourly system marginal price is NOT repeated: it is ``buses_t.marginal_price`` in the run results.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd
import pypsa

from .. import carbon_pricing
from .plan import (
    GENERATOR,
    LINK,
    ROLE_GENERATOR,
    ROLE_LINK_DIRECT,
    ROLE_LINK_SUPPLIED,
    ROLE_SUPPLIER,
    ROLE_VOM_ONLY,
    AppliedUnit,
    FuelPlan,
)

_TINY = 1e-9
SMP_REFERENCE = {
    "source": "buses_t.marginal_price",
    "note": "The system marginal price is an OUTPUT of the solve (per-bus hourly prices are in the run results); the module never writes it.",
}


def _r(x: Any, digits: int = 6) -> float | None:
    """JSON-safe number: ``None`` for NaN / inf."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, digits) if math.isfinite(v) else None


def _wmean(x: pd.Series, w: pd.Series, mask: pd.Series | None = None) -> float | None:
    """Weighted mean of ``x`` over ``mask`` (``None`` when the weight is zero)."""
    if mask is not None:
        x, w = x[mask], w[mask]
    tot = float(w.sum())
    return float((x * w).sum() / tot) if tot > _TINY else None


def _carbon_source(network: pypsa.Network, plan: FuelPlan, unit: AppliedUnit, adder: pd.DataFrame) -> str | None:
    """The generator whose carbon adder this unit pays: itself, or for a Link the emitting supplier on ``bus0``."""
    s = unit.spec
    if s.component == GENERATOR:
        return s.name if s.name in adder.columns else None
    for name in s.suppliers:
        if name in adder.columns:
            return name
    bus0 = str(network.links.at[s.name, "bus0"])
    gens = network.generators
    for name in gens.index[gens["bus"] == bus0]:
        if name in adder.columns:
            return str(name)
    return None


def components(network: pypsa.Network, plan: FuelPlan, unit: AppliedUnit, adder: pd.DataFrame) -> pd.DataFrame:
    """Per-snapshot cost of one MWh of the unit's output, columns ``fuel, vom, carbon, other, total`` and ``priced``.

    ``fuel`` is NaN where the unit has a fuel carrier but no price at that snapshot (``priced`` False); ``other`` then
    carries the workbook's marginal cost that stands there. ``total`` counts NaN as 0.
    """
    s, idx = unit.spec, unit.mc_new.index
    zero = pd.Series(0.0, index=idx)
    eta = unit.eta
    if s.role == ROLE_VOM_ONLY or unit.fuel is None:
        fuel = zero.copy()
        priced = pd.Series(True, index=idx)
    else:
        fuel = unit.fuel / eta
        priced = unit.fuel.notna()
    other = zero.copy()
    if unit.status == "applied" and not bool(priced.all()):
        if s.role in (ROLE_GENERATOR, ROLE_SUPPLIER):
            other = unit.mc_old.where(~priced, 0.0)
        elif s.role == ROLE_LINK_DIRECT:
            other = (unit.mc_old / eta).where(~priced, 0.0)
        elif s.role == ROLE_LINK_SUPPLIED:
            sup = next((plan.get(GENERATOR, n) for n in s.suppliers if plan.get(GENERATOR, n) is not None), None)
            if sup is not None:
                other = (sup.mc_old / eta).where(~priced, 0.0)
    src = _carbon_source(network, plan, unit, adder)
    carbon = adder[src].reindex(idx).fillna(0.0) if src is not None else zero.copy()
    if s.component == LINK:
        carbon = carbon / eta
    vom = pd.Series(s.vom, index=idx, dtype=float)
    out = pd.DataFrame({"fuel": fuel, "vom": vom, "carbon": carbon, "other": other})
    out["total"] = out["fuel"].fillna(0.0) + out["vom"] + out["carbon"] + out["other"]
    out["priced"] = priced
    return out


def _output_mw(network: pypsa.Network, unit: AppliedUnit) -> pd.Series:
    """The unit's output (MW): Generator ``p``; Link electric output ``-p1``; zero when it has no solution."""
    idx = unit.mc_new.index
    s = unit.spec
    if s.component == GENERATOR:
        frame = network.generators_t.p
        col = frame[s.name] if s.name in frame.columns else None
        return col.reindex(idx).fillna(0.0).astype(float) if col is not None else pd.Series(0.0, index=idx)
    frame = network.links_t.p1
    col = frame[s.name] if s.name in frame.columns else None
    return (-col).reindex(idx).fillna(0.0).astype(float) if col is not None else pd.Series(0.0, index=idx)


def _fixed_costs(network: pypsa.Network) -> pd.DataFrame:
    from ...pypsa.results.stat_metrics import fixed_cost_table

    try:
        return fixed_cost_table(network, ["Generator", "Link"])
    except Exception:  # noqa: BLE001 - an unsolved network has no statistics: no fixed cost to add
        return pd.DataFrame()


def _weights(network: pypsa.Network) -> pd.Series:
    snaps = network.snapshots
    pathway = isinstance(snaps, pd.MultiIndex) and "period" in (snaps.names or [])
    return carbon_pricing.objective_weights(network, snaps, multi_invest=pathway)


def unit_row(
    network: pypsa.Network,
    plan: FuelPlan,
    unit: AppliedUnit,
    adder: pd.DataFrame,
    weights: pd.Series,
    *,
    solved: bool,
    fixed: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """One unit's row of the preview (``solved=False``) or of the results (``solved=True``: adds dispatch-weighted
    components, generation and LCOE)."""
    s = unit.spec
    comp = components(network, plan, unit, adder)
    priced = comp["priced"]
    basis = "MWh_th" if s.role == ROLE_SUPPLIER else "MWh_el"
    cols = ("fuel", "vom", "carbon", "other", "total")
    row: dict[str, Any] = {
        "component": s.component, "name": s.name, "carrier": s.carrier, "role": s.role, "fuelCarrier": s.fuel_carrier,
        "suppliers": list(s.suppliers), "status": unit.status, "reason": unit.reason,
        "efficiencyMean": _r(unit.eta.mean()), "vom": _r(s.vom), "vomSource": s.vom_source,
        "snapshots": len(unit.mc_new), "pricedSnapshots": int(priced.sum()), "unpricedSnapshots": int(unit.unpriced_snapshots),
        "marginalCost": {
            "oldMean": _r(unit.mc_old.mean()), "newMean": _r(unit.mc_new.mean()),
            "newMin": _r(unit.mc_new.min()), "newMax": _r(unit.mc_new.max()),
            "basis": "per MWh of p0 (input)" if s.component == LINK else "per MWh of output",
        },
        "basis": basis,
        "timeMean": {c: _r(_wmean(comp[c].fillna(0.0), weights, priced)) for c in cols},
    }
    if not solved:
        return row
    q = _output_mw(network, unit)
    wq = weights * q
    row["dispatchWeighted"] = {c: _r(_wmean(comp[c].fillna(0.0), wq, priced)) for c in cols}
    generation = float(wq.sum())
    row["generationMwh"] = _r(generation, 3)
    row["lcoe"] = None
    if s.role == ROLE_SUPPLIER or generation <= _TINY:
        return row
    key = (s.component, s.name)
    fc = fixed.loc[key] if fixed is not None and not fixed.empty and key in fixed.index else None
    capex = float(fc["capex_horizon"]) if fc is not None else 0.0
    fom = float(fc["fom_horizon"]) if fc is not None else 0.0
    var = {c: float((comp[c].fillna(0.0) * wq).sum()) for c in ("fuel", "vom", "carbon", "other")}
    total = capex + fom + sum(var.values())
    row["lcoe"] = {
        "value": _r(total / generation), "capex": _r(capex / generation), "fom": _r(fom / generation),
        **{c: _r(v / generation) for c, v in var.items()},
        "basis": "currency per MWh_el over the horizon: (capex + fom + fuel + vom + carbon + other) / generation",
    }
    return row


def unit_rows(network: pypsa.Network, plan: FuelPlan, *, solved: bool) -> list[dict[str, Any]]:
    """Rows for every unit of the plan (carbon from the carbon-pricing plan recorded on ``network``)."""
    adder = carbon_pricing.adder_frame(network)
    weights = _weights(network)
    fixed = _fixed_costs(network) if solved else None
    return [unit_row(network, plan, u, adder, weights, solved=solved, fixed=fixed) for u in plan.units]


def preview(network: pypsa.Network, plan: FuelPlan) -> dict[str, Any]:
    """The pre-run summary: per unit the marginal-cost series the run would send, with the fuel / VOM / carbon split."""
    cfg = carbon_pricing.plan_of(network)
    return {
        "active": bool([u for u in plan.units if u.changed]),
        "carbonPriceActive": bool(cfg is not None and cfg.is_active),
        "units": unit_rows(network, plan, solved=False),
        "priceSources": dict(plan.prices.source),
        "notes": list(plan.notes),
        "smp": SMP_REFERENCE,
        "basis": "marginal_cost = fuel / efficiency + VOM (Link with a priced supplier: VOM x efficiency on the Link, fuel on the supplier); carbon is not in it, the carbon-pricing module adds it to the objective",
    }


def results(network: pypsa.Network, plan: FuelPlan, currency: str) -> dict[str, Any]:
    """The study payload ``fuelCosts``: per-unit breakdown, dispatch-weighted components and ex-post LCOE."""
    cfg = carbon_pricing.plan_of(network)
    return {
        "enabled": True,
        "currency": currency,
        "carbonPriceActive": bool(cfg is not None and cfg.is_active),
        "units": unit_rows(network, plan, solved=True),
        "priceSources": dict(plan.prices.source),
        "notes": list(plan.notes),
        "smp": SMP_REFERENCE,
        "weighting": "objective snapshot weighting (hours) x investment-period objective weighting (pathway)",
    }
