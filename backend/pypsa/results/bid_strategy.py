"""Bid-strategy simulator (Tier 2) — does bidding above cost pay off?

A price-taker bids at marginal cost. A firm with market power bids *above* cost:
if it is pivotal (needed to meet load), raising its offer lifts the clearing
price on all its output; if it is not, it just loses dispatch. This simulates a
user-chosen markup: raise the selected owner's offers, re-clear the whole
market, and compare the owner's profit to the price-taker baseline.

Profit is always evaluated at the owner's *true* marginal cost — the markup is
only the offer used for clearing. A positive delta means the markup pays off
(the firm has market power); a negative delta means the market is competitive
enough that withholding backfires.
"""
from __future__ import annotations

import logging
from typing import Any

import pypsa

_log = logging.getLogger("pypsa.solver")


def _owner_generators(model: dict[str, list[dict[str, Any]]], owner: str, column: str) -> list[str]:
    want = owner.strip()
    return [
        str(r.get("name", "")).strip()
        for r in model.get("generators", []) or []
        if str(r.get("name", "")).strip() and str(r.get(column, "")).strip() == want
    ]


def _profit(network: pypsa.Network, gens: list[str], mc_true: dict[str, float]) -> dict[str, float]:
    """Owner profit / energy / revenue at the network's clearing prices."""
    mp = network.buses_t.marginal_price
    w = network.snapshot_weightings["objective"]
    energy = revenue = cost = 0.0
    for g in gens:
        if g not in network.generators_t.p.columns:
            continue
        bus = str(network.generators.at[g, "bus"])
        p = network.generators_t.p[g]
        e = float((p * w).sum())
        energy += e
        cost += float(mc_true.get(g, 0.0) * (p * w).sum())
        if bus in mp.columns:
            revenue += float((p * mp[bus] * w).sum())
    return {
        "profit": round(revenue - cost, 2),
        "revenue": round(revenue, 2),
        "energyMWh": round(energy, 2),
        "capturePrice": round(revenue / energy, 2) if energy > 1e-9 else None,
    }


def build_bid_strategy(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    *,
    owner: str,
    owner_column: str,
    markup_type: str,
    markup: float,
    currency: str,
    solver_options: dict[str, Any] | None = None,
    io_api: str = "direct",
) -> dict[str, Any] | None:
    """Compare an owner's profit under a markup strategy vs the price-taker baseline.

    Returns ``None`` when there is nothing to simulate (unsolved network, no
    prices, owner has no generators) or the strategic re-solve fails.
    """
    if not getattr(network, "is_solved", False):
        return None
    mp = network.buses_t.marginal_price
    if mp is None or mp.empty:
        return None
    column = (owner_column or "owner").strip() or "owner"
    gens = [g for g in _owner_generators(model, owner, column) if g in network.generators.index]
    if not gens:
        return None

    w = network.snapshot_weightings["objective"]
    mc_true = {g: float(network.generators.at[g, "marginal_cost"]) for g in gens}
    baseline = _profit(network, gens, mc_true)
    sys_price_base = round(float((mp.mean(axis=1) * w).sum() / w.sum()), 2)

    # Strategic re-solve: raise the owner's offers by the markup and re-clear.
    try:
        if network.model is not None:
            network.model.solver_model = None
    except Exception:  # noqa: BLE001
        pass
    try:
        work = network.copy()
        for g in gens:
            base_mc = mc_true[g]
            offer = base_mc * (1.0 + markup) if markup_type == "percent" else base_mc + markup
            work.generators.at[g, "marginal_cost"] = offer
        result = work.optimize(
            solver_name="highs",
            solver_options=solver_options or {},
            io_api=io_api,
            include_objective_constant=False,
        )
    except Exception as exc:  # noqa: BLE001 — never sink the run over the extra solve
        _log.warning("bid-strategy re-solve failed for owner %r: %s", owner, exc)
        return None
    status = str(result[0]) if isinstance(result, tuple) else str(result)
    if status not in ("ok", "optimal"):
        _log.warning("bid-strategy re-solve non-optimal for owner %r: %s", owner, status)
        return None

    strategic = _profit(work, gens, mc_true)  # profit at TRUE cost, new clearing
    wmp = work.buses_t.marginal_price
    sys_price_strat = round(float((wmp.mean(axis=1) * w).sum() / w.sum()), 2) if not wmp.empty else None

    delta = round(strategic["profit"] - baseline["profit"], 2)
    _log.info(
        "bid-strategy: owner=%r markup=%s%s Δprofit=%.1f", owner, markup, markup_type, delta,
    )
    return {
        "owner": owner,
        "markupType": markup_type,
        "markup": markup,
        "currency": currency,
        "generatorCount": len(gens),
        "baseline": baseline,
        "strategic": strategic,
        "deltaProfit": delta,
        "systemAvgPrice": {"baseline": sys_price_base, "strategic": sys_price_strat},
    }
