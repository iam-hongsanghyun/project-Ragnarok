"""Strategic price-maker bidding (B4) — best-response over the simulated market.

An owner with market power doesn't take the price: its bids move the clearing
price. The bilevel (MPEC) formulation of that problem cannot be expressed in
PyPSA's single-level LP — but on a single-zone merit-order market the lower
level (clearing) is exactly what the B2 simulator computes, so the upper level
reduces to a **best-response search**: sweep the owner's strategy against the
simulator and take the profit-maximising level. With a rival owner, alternating
best responses (best-response dynamics) approximate a Nash equilibrium.

Strategies:
    markup    — bid = true marginal cost + adder (€/MWh; an adder rather than a
                multiplier so zero-cost units can act strategically too).
    withhold  — remove a fraction of every owned unit's capacity from the market
                (economic withholding).

Algorithm:
    $$ x^* = \\arg\\max_{x \\in \\text{grid}} \\; \\pi_{\\text{owner}}\\big(\\text{clear}(x)\\big) $$
    ASCII: for each candidate level x, simulate the market with the owner's
    strategy applied, sum the owner's unit profits, keep the argmax.

Profits are always measured at TRUE marginal cost (a marked-up bid changes the
price, not the cost). Consumer cost = total payment by load, so the price
impact of exercising market power is reported explicitly.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pypsa

from .simulation import run_market_simulation

_DEF_STEPS = 12
_DEF_MAX_ADDER = 100.0
_DEF_MAX_WITHHOLD = 0.5
_DEF_ROUNDS = 4

# The B2 simulation-config keys carried into the strategic baseline — the full
# market design (demand curve, storage thresholds, bid/withhold overrides) must
# survive, or a configured two-sided market is silently evaluated single-sided.
_SIM_KEYS = (
    "voll",
    "bids",
    "withheldMw",
    "chargeQuantile",
    "dischargeQuantile",
    "clearingModel",
    "demandElasticFraction",
    "demandWtp",
    "demandBids",
)


def _owner_units(
    model: dict[str, list[dict[str, Any]]], network: pypsa.Network, owner: str, column: str
) -> list[str]:
    """Owner's generators (from the workbook's owner column) present in the network."""
    want = owner.strip()
    in_net = {str(g) for g in network.generators.index}
    return [
        str(r.get("name", "")).strip()
        for r in model.get("generators", []) or []
        if str(r.get(column, "")).strip() == want and str(r.get("name", "")).strip() in in_net
    ]


def _strategy_config(
    base: dict[str, Any],
    strategy: str,
    level: float,
    units: list[str],
    mc: dict[str, float],
    p_nom: dict[str, float],
    other: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Simulation config with ``units`` playing ``strategy`` at ``level``.

    Overrides are layered: the user's base config (which may carry its own
    ``bids`` / ``withheldMw``), then ``other`` — the rival's current strategy
    in equilibrium rounds — then the owner's units at ``level``.
    """
    cfg = dict(base)
    bids = {**(base.get("bids") or {}), **((other or {}).get("bids") or {})}
    withheld = {**(base.get("withheldMw") or {}), **((other or {}).get("withheldMw") or {})}
    if strategy == "withhold":
        withheld.update({u: p_nom[u] * level for u in units})
    else:
        bids.update({u: mc[u] + level for u in units})
    if bids:
        cfg["bids"] = bids
    if withheld:
        cfg["withheldMw"] = withheld
    return cfg


def _owner_profit(sim: dict[str, Any], units: list[str]) -> float:
    return float(sum(u["profit"] for u in sim["units"] if u["name"] in units))


def _sweep(
    network: pypsa.Network,
    base: dict[str, Any],
    strategy: str,
    levels: np.ndarray,
    units: list[str],
    mc: dict[str, float],
    p_nom: dict[str, float],
    other: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    curve = []
    for level in levels:
        cfg = _strategy_config(base, strategy, float(level), units, mc, p_nom, other)
        sim = run_market_simulation(network, cfg)
        curve.append({
            "level": round(float(level), 4),
            "ownerProfit": round(_owner_profit(sim, units), 2),
            "avgPrice": sim["summary"]["avgPrice"],
            "consumerCost": sim["summary"]["totalCost"],
            "unservedMWh": sim["summary"]["unservedMWh"],
        })
    return curve


def build_strategic_bidding(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    *,
    config: dict[str, Any],
    sim_config: dict[str, Any],
    owner_column: str,
    currency: str,
) -> dict[str, Any] | None:
    """Best-response strategic bidding for ``config['owner']``; None if the
    owner has no generators in the network."""
    owner = str(config.get("owner") or "").strip()
    if not owner:
        return None
    units = _owner_units(model, network, owner, owner_column)
    if not units:
        return None

    strategy = "withhold" if str(config.get("strategy")) == "withhold" else "markup"
    steps = max(2, int(config.get("steps") or _DEF_STEPS))
    max_level = float(
        config.get("maxWithholdPct") or _DEF_MAX_WITHHOLD
    ) if strategy == "withhold" else float(config.get("maxAdder") or _DEF_MAX_ADDER)
    levels = np.linspace(0.0, max_level, steps + 1)

    # The simulated-market baseline the strategy is measured against: the user's
    # full B2 config with ONE deliberate override — uniform settlement
    # (strategic markup under pay-as-bid is a different game).
    base = {k: sim_config[k] for k in _SIM_KEYS if sim_config.get(k) is not None}
    base["pricing"] = "uniform"
    gens = network.generators
    mc = {str(g): float(gens.at[g, "marginal_cost"]) for g in gens.index}
    p_nom = {str(g): float(gens.at[g, "p_nom"]) for g in gens.index}

    baseline_sim = run_market_simulation(network, base)
    baseline = {
        "profit": round(_owner_profit(baseline_sim, units), 2),
        "avgPrice": baseline_sim["summary"]["avgPrice"],
        "consumerCost": baseline_sim["summary"]["totalCost"],
    }

    # Optional rival: alternating best responses (best-response dynamics).
    rival = str(config.get("rivalOwner") or "").strip()
    rival_units = _owner_units(model, network, rival, owner_column) if rival and rival != owner else []
    equilibrium: dict[str, Any] | None = None
    other_cfg: dict[str, Any] | None = None

    if rival_units:
        rounds = max(1, int(config.get("rounds") or _DEF_ROUNDS))
        owner_level = 0.0
        rival_level = 0.0
        history: list[dict[str, Any]] = []
        converged = False
        for rnd in range(1, rounds + 1):
            prev = (owner_level, rival_level)
            rival_now = _strategy_config({}, strategy, rival_level, rival_units, mc, p_nom)
            crv = _sweep(network, base, strategy, levels, units, mc, p_nom, rival_now)
            owner_level = max(crv, key=lambda r: r["ownerProfit"])["level"]
            owner_now = _strategy_config({}, strategy, owner_level, units, mc, p_nom)
            crv_r = _sweep(network, base, strategy, levels, rival_units, mc, p_nom, owner_now)
            rival_level = max(crv_r, key=lambda r: r["ownerProfit"])["level"]
            history.append({"round": rnd, "ownerLevel": owner_level, "rivalLevel": rival_level})
            if (owner_level, rival_level) == prev:
                converged = True
                break
        equilibrium = {
            "rivalOwner": rival, "rounds": history, "converged": converged,
            "ownerLevel": owner_level, "rivalLevel": rival_level,
        }
        other_cfg = _strategy_config({}, strategy, rival_level, rival_units, mc, p_nom)

    # The reported curve: the owner's final sweep (against the rival's
    # equilibrium strategy when there is one).
    curve = _sweep(network, base, strategy, levels, units, mc, p_nom, other_cfg)
    best = max(curve, key=lambda r: r["ownerProfit"])

    notes = [
        f"Best response over the simulated merit-order market ({len(curve)} strategy "
        f"levels, uniform settlement). Profits at true marginal cost.",
    ]
    if strategy == "withhold":
        notes.append("Strategy: economic withholding — a fraction of every owned unit's capacity is removed.")
    else:
        notes.append("Strategy: bid markup — a flat adder on every owned unit's bid.")
    if equilibrium:
        notes.append(
            f"Two-owner best-response dynamics vs {rival}: "
            + ("converged" if equilibrium["converged"] else "did NOT converge")
            + f" after {len(equilibrium['rounds'])} round(s)."
        )

    return {
        "owner": owner,
        "strategy": strategy,
        "currency": currency,
        "ownerUnits": units,
        "baseline": baseline,
        "curve": curve,
        "best": {
            **best,
            "profitUplift": round(best["ownerProfit"] - baseline["profit"], 2),
            "priceUplift": round(best["avgPrice"] - baseline["avgPrice"], 4),
            "consumerCostDelta": round(best["consumerCost"] - baseline["consumerCost"], 2),
        },
        "equilibrium": equilibrium,
        "notes": notes,
    }
