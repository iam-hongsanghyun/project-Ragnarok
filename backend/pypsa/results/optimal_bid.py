"""Optimal-bid finder (Tier 3a) — Ragnarok's best-response markup.

Tier 2 asks "what if I bid this markup?". This asks "what markup should I bid?"
— it sweeps the owner's markup, re-clears the market at each level, and reports
the profit-maximising bid against the competitive fringe. This is the
single-firm best response (the firm faces a fixed residual-demand curve); it is
NOT a full multi-firm equilibrium.

Each swept markup is one re-clear on a copy of the solved optimum, so cost grows
with the number of steps — the step count is capped.
"""
from __future__ import annotations

import logging
from typing import Any

import pypsa

from .bid_strategy import _apply_offer, _owner_generators, _profit, _true_marginal_cost

_log = logging.getLogger("pypsa.solver")

_MAX_STEPS = 20


def _system_avg_price(network: pypsa.Network) -> float | None:
    mp = network.buses_t.marginal_price
    if mp is None or mp.empty:
        return None
    w = network.snapshot_weightings["objective"]
    denom = float(w.sum()) or 1.0
    return round(float((mp.mean(axis=1) * w).sum() / denom), 2)


def build_optimal_bid(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    *,
    owner: str,
    owner_column: str,
    markup_type: str,
    max_markup: float,
    steps: int,
    currency: str,
    solver_options: dict[str, Any] | None = None,
    io_api: str = "direct",
) -> dict[str, Any] | None:
    """Sweep the owner's markup and return the profit-maximising bid + curve.

    Returns ``None`` when there is nothing to optimise (unsolved network, no
    prices, owner has no generators).
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

    mc_true = _true_marginal_cost(network, gens)
    n_steps = max(1, min(int(steps or 8), _MAX_STEPS))
    max_markup = max(0.0, float(max_markup))

    # Markup 0 (bid at cost = price-taker) is the base network's own solution.
    base = _profit(network, gens, mc_true)
    curve: list[dict[str, Any]] = [{
        "markup": 0.0,
        "profit": base["profit"],
        "energyMWh": base["energyMWh"],
        "systemAvgPrice": _system_avg_price(network),
    }]

    try:
        if network.model is not None:
            network.model.solver_model = None
    except Exception:  # noqa: BLE001
        pass

    for i in range(1, n_steps + 1):
        markup = max_markup * i / n_steps
        try:
            work = network.copy()
            _apply_offer(work, gens, mc_true, markup_type, markup)
            result = work.optimize(
                solver_name="highs",
                solver_options=solver_options or {},
                io_api=io_api,
                include_objective_constant=False,
            )
        except Exception as exc:  # noqa: BLE001 — skip a failed point, keep the sweep
            _log.warning("optimal-bid step markup=%s failed: %s", markup, exc)
            continue
        status = str(result[0]) if isinstance(result, tuple) else str(result)
        if status not in ("ok", "optimal"):
            continue
        p = _profit(work, gens, mc_true)
        curve.append({
            "markup": round(markup, 4),
            "profit": p["profit"],
            "energyMWh": p["energyMWh"],
            "systemAvgPrice": _system_avg_price(work),
        })

    best = max(curve, key=lambda c: c["profit"])
    _log.info(
        "optimal-bid: owner=%r best markup=%s profit=%.1f (%d points)",
        owner, best["markup"], best["profit"], len(curve),
    )
    return {
        "owner": owner,
        "markupType": markup_type,
        "currency": currency,
        "generatorCount": len(gens),
        "baselineProfit": base["profit"],
        "optimalMarkup": best["markup"],
        "optimalProfit": best["profit"],
        "deltaProfit": round(best["profit"] - base["profit"], 2),
        "curve": curve,
    }
