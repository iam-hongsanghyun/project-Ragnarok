"""Price-formation view (Tier 0) — why is the price what it is?

The system marginal price is set, hour by hour, by the most expensive unit that
has to run. That in turn is driven by how much *residual* demand is left after
the zero-marginal-cost variable renewables (wind, solar, …) have been used —
low renewables ⇒ higher residual demand ⇒ a pricier unit sets the price.

This surfaces that relationship directly: per snapshot it reports the price, the
demand, the residual demand (demand − variable renewables), the renewable share,
and the carrier of the price-setting generator (the most expensive dispatched
unit). No re-optimisation — read straight off the solved network.

Variable renewables are identified structurally, by a time-varying ``p_max_pu``
(weather-driven availability), so the split needs no carrier-name assumptions.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pypsa

_log = logging.getLogger("pypsa.solver")

_DISPATCH_EPS = 1e-3  # MW below which a generator is treated as off


def build_price_formation(network: pypsa.Network, *, currency: str) -> dict[str, Any] | None:
    """Per-snapshot price / residual-demand / marginal-carrier table.

    Returns ``None`` when the run has no marginal prices (a non-LP run) or no
    generators — there is no price to explain.
    """
    mp = network.buses_t.marginal_price
    if mp is None or mp.empty or network.generators.empty:
        return None
    gen_p = network.generators_t.p
    if gen_p is None or gen_p.empty:
        return None

    price = mp.mean(axis=1)  # system price per snapshot (mean nodal price)

    # Demand per snapshot: the served load (fall back to the set profile).
    if not network.loads_t.p.empty:
        demand = network.loads_t.p.sum(axis=1)
    elif not network.loads_t.p_set.empty:
        demand = network.loads_t.p_set.sum(axis=1)
    else:
        demand = pd.Series(0.0, index=network.snapshots)

    # Variable renewables: generators with a time-varying availability profile.
    vre_gens = [g for g in network.generators.index if g in network.generators_t.p_max_pu.columns]
    vre_gen = gen_p[vre_gens].sum(axis=1) if vre_gens else pd.Series(0.0, index=network.snapshots)
    total_gen = gen_p.sum(axis=1)
    residual = demand - vre_gen
    share = (vre_gen / total_gen).where(total_gen > _DISPATCH_EPS, 0.0)

    # Price-setting carrier: among generators actually running each snapshot, the
    # one with the highest effective marginal cost (the marginal unit in a
    # merit-order dispatch). marginal_cost already carries any carbon adder.
    mc = network.get_switchable_as_dense("Generator", "marginal_cost")
    mc_running = mc.where(gen_p > _DISPATCH_EPS)  # NaN where the unit is off
    # idxmax(axis=1) raises on all-NaN rows (a snapshot with nothing running, e.g.
    # a window served entirely by storage) in modern pandas — guard per row.
    marg_gen = mc_running.apply(lambda r: r.idxmax() if r.notna().any() else None, axis=1)
    carrier = network.generators["carrier"]

    weights = network.snapshot_weightings["objective"]

    rows: list[dict[str, Any]] = []
    marginal_hours: dict[str, float] = {}
    for ts in network.snapshots:
        g = marg_gen.get(ts)
        marg_carrier = str(carrier.get(g, "")) if isinstance(g, str) else ""
        w = float(weights.get(ts, 1.0))
        if marg_carrier:
            marginal_hours[marg_carrier] = marginal_hours.get(marg_carrier, 0.0) + w
        rows.append({
            "snapshot": str(ts),
            "price": round(float(price.get(ts, 0.0)), 2),
            "demand": round(float(demand.get(ts, 0.0)), 1),
            "residualDemand": round(float(residual.get(ts, 0.0)), 1),
            "renewableShare": round(float(share.get(ts, 0.0)), 4),
            "marginalCarrier": marg_carrier,
        })

    # Summary per price-setting carrier: hours marginal + average price then.
    price_sum: dict[str, float] = {}
    for r in rows:
        c = r["marginalCarrier"]
        if c:
            price_sum[c] = price_sum.get(c, 0.0) + r["price"]
    counts: dict[str, int] = {}
    for r in rows:
        if r["marginalCarrier"]:
            counts[r["marginalCarrier"]] = counts.get(r["marginalCarrier"], 0) + 1
    total_w = sum(marginal_hours.values()) or 1.0
    summary = [
        {
            "carrier": c,
            "hours": round(h, 1),
            "shareOfHours": round(h / total_w, 4),
            "avgPrice": round(price_sum.get(c, 0.0) / counts.get(c, 1), 2),
        }
        for c, h in sorted(marginal_hours.items(), key=lambda kv: kv[1], reverse=True)
    ]

    _log.info("price formation: %d snapshots, %d price-setting carriers", len(rows), len(summary))
    return {
        "currency": currency,
        "series": rows,
        "marginalSummary": summary,
    }
