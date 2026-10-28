"""Market-studies module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from backend.app import module_hooks as mh

_log = logging.getLogger(__name__)
MODULE = "market-studies"

_MODES = "rolling horizon, stochastic, security-constrained, sampled-block, power-flow, or contingency modes."


def _refuse_with_core_modes(ctx: mh.RunContext, enabled: bool, label: str) -> None:
    if enabled and ctx.incompatible_modes:
        raise HTTPException(status_code=400, detail=f"{label} cannot be combined with {_MODES}")


# ── guards: these studies layer on the plain optimise path ───────────────────

def _guard_merchant(ctx: mh.RunContext) -> None:
    # Merchant mode needs the stage-1 optimum's LMPs, so it is incompatible with the modes that skip or
    # reshape that solve. (Pathway is allowed; a series price source bypasses the LMP.)
    _refuse_with_core_modes(ctx, bool((ctx.options.get("merchantConfig") or {}).get("enabled", False)),
                            "Merchant (price-taker) analysis")


def _guard_bid(ctx: mh.RunContext) -> None:
    # Bid-strategy re-clears the full market with modified offers, so like merchant it needs the plain path.
    _refuse_with_core_modes(ctx, bool((ctx.options.get("bidStrategyConfig") or {}).get("enabled", False)),
                            "Bid-strategy simulation")


def _bid_with_carbon_curve(ctx: mh.RunContext) -> None:
    """Strategic bidding re-solves a scratch copy that carries the carbon price in ``marginal_cost``, which a
    piecewise curve would ignore (the MGA half of this rule stays with the MGA core path)."""
    from backend.app import carbon_pricing

    plan = carbon_pricing.plan_of(ctx.network)
    if plan is None or not plan.is_active:
        return
    if bool((ctx.options.get("bidStrategyConfig") or {}).get("enabled", False)) and \
            ctx.network.components["generators"].has_piecewise("marginal_cost"):
        raise HTTPException(
            status_code=400,
            detail="A carbon price with a piecewise marginal_cost curve cannot be combined with MGA or strategic "
                   "bidding: those studies re-solve a copy with the price in marginal_cost, which a curve ignores.",
        )


# ── replace_solve: rule-based market simulation instead of an LP ─────────────

def _market_sim(ctx: mh.RunContext) -> dict[str, Any] | None:
    market_sim_cfg = ctx.options.get("marketSimConfig") or {}
    if not bool(market_sim_cfg.get("enabled", False)):
        return None
    from .simulation import run_market_sim_study

    return run_market_sim_study(
        ctx.network,
        market_sim_cfg,
        currency=ctx.currency,
        snapshot_count=ctx.snapshot_count,
        snapshot_weight=ctx.snapshot_weight,
        notes=ctx.notes,
        model=ctx.model,
        owner_column=ctx.owner_column,
    )


# ── studies (each reads the solved network; the base solution is never mutated) ──

def _merchant(ctx: mh.RunContext) -> dict[str, Any]:
    cfg = ctx.options.get("merchantConfig") or {}
    if not bool(cfg.get("enabled", False)):
        return {"merchant": None}
    from .merchant import build_merchant

    return {"merchant": build_merchant(
        ctx.network,
        ctx.model,
        owner=str(cfg.get("owner", "") or ""),
        owner_column=ctx.owner_column,
        price_source=str(cfg.get("priceSource", "lmp") or "lmp"),
        flat_price=float(cfg.get("flatPrice", 0.0) or 0.0),
        price_series=cfg.get("priceSeries") or None,
        currency=ctx.currency,
        solver_options=ctx.solver_options or {},
        io_api=ctx.io_api,
    )}


def _bid_strategy(ctx: mh.RunContext) -> dict[str, Any]:
    """Raise one owner's offers by a markup, re-clear the market, compare profit with the price-taker baseline."""
    cfg = ctx.options.get("bidStrategyConfig") or {}
    mode = str(cfg.get("mode", "fixed") or "fixed")
    if not bool(cfg.get("enabled", False)) or mode == "optimal":
        return {"bidStrategy": None}
    from .bid_strategy import build_bid_strategy

    return {"bidStrategy": build_bid_strategy(
        ctx.network,
        ctx.model,
        owner=str(cfg.get("owner", "") or ""),
        owner_column=ctx.owner_column,
        markup_type=str(cfg.get("markupType", "percent") or "percent"),
        markup=float(cfg.get("markup", 0.0) or 0.0),
        currency=ctx.currency,
        solver_options=ctx.solver_options or {},
        io_api=ctx.io_api,
    )}


def _optimal_bid(ctx: mh.RunContext) -> dict[str, Any]:
    """Sweep the markup for the profit-maximising bid."""
    cfg = ctx.options.get("bidStrategyConfig") or {}
    mode = str(cfg.get("mode", "fixed") or "fixed")
    if not bool(cfg.get("enabled", False)) or mode != "optimal":
        return {"optimalBid": None}
    from .optimal_bid import build_optimal_bid

    return {"optimalBid": build_optimal_bid(
        ctx.network,
        ctx.model,
        owner=str(cfg.get("owner", "") or ""),
        owner_column=ctx.owner_column,
        markup_type=str(cfg.get("markupType", "percent") or "percent"),
        max_markup=float(cfg.get("maxMarkup", 2.0) or 2.0),
        steps=int(cfg.get("steps", 8) or 8),
        currency=ctx.currency,
        solver_options=ctx.solver_options or {},
        io_api=ctx.io_api,
    )}


def _price_formation(ctx: mh.RunContext) -> dict[str, Any]:
    """Price vs residual demand and the marginal (price-setting) carrier each snapshot; None on non-LP runs."""
    from .price_formation import build_price_formation

    return {"priceFormation": build_price_formation(ctx.network, currency=ctx.currency)}


def _ppa(ctx: mh.RunContext) -> dict[str, Any]:
    """Value a fixed-price PPA against the LMP (PP1) and rank alternative contract shapes at the same strike (DW4)."""
    cfg = ctx.options.get("ppaConfig") or {}
    if not bool(cfg.get("enabled", False)):
        return {"ppa": None, "ppaExplorer": None}
    from .ppa import build_ppa
    from .ppa_explorer import build_ppa_explorer

    owner = str(cfg.get("owner", "") or "")
    flat_mw = float(cfg.get("flatMW", 0.0) or 0.0)
    strike = float(cfg.get("strikePrice", 0.0) or 0.0)
    ppa = build_ppa(
        ctx.network, ctx.model,
        owner=owner,
        owner_column=ctx.owner_column,
        volume_type=str(cfg.get("volumeType", "generation") or "generation"),
        flat_mw=flat_mw,
        strike_price=strike,
        currency=ctx.currency,
    )
    explorer = build_ppa_explorer(
        ctx.network, ctx.model,
        owner=owner,
        owner_column=ctx.owner_column,
        flat_mw=flat_mw,
        strike_price=strike,
        currency=ctx.currency,
    )
    return {"ppa": ppa, "ppaExplorer": explorer}


def _lmp_decomposition(ctx: mh.RunContext) -> dict[str, Any]:
    """Split solved nodal prices into an energy component and a per-bus congestion residual, plus the
    congestion rent per line/link. Never raises into the solve."""
    cfg = ctx.options.get("lmpDecompositionConfig") or {}
    if not bool(cfg.get("enabled")):
        return {"lmpDecomposition": None}
    from .lmp_decomposition import build_lmp_decomposition

    try:
        return {"lmpDecomposition": build_lmp_decomposition(ctx.network, ctx.options)}
    except Exception as exc:  # noqa: BLE001 - never sink the run over a reporting extra
        ctx.notes.append(f"LMP decomposition could not be computed: {exc}")
        _log.warning("lmp_decomposition failed: %s", exc)
        return {"lmpDecomposition": None}


mh.register("guard", "merchant", _guard_merchant, module=MODULE, order=10)
mh.register("guard", "bid-strategy", _guard_bid, module=MODULE, order=20)
mh.register("build_step", "bid-carbon-curve", _bid_with_carbon_curve, module=MODULE, order=100)
mh.register("replace_solve", "market-sim", _market_sim, module=MODULE, order=10)
mh.register("study", "merchant", _merchant, module=MODULE, order=100, payload_keys=("merchant",))
mh.register("study", "bid-strategy", _bid_strategy, module=MODULE, order=110, payload_keys=("bidStrategy",))
mh.register("study", "optimal-bid", _optimal_bid, module=MODULE, order=111, payload_keys=("optimalBid",))
mh.register("study", "price-formation", _price_formation, module=MODULE, order=150, payload_keys=("priceFormation",))
mh.register("study", "ppa", _ppa, module=MODULE, order=160, payload_keys=("ppa", "ppaExplorer"))
mh.register("study", "lmp-decomposition", _lmp_decomposition, module=MODULE, order=185,
            payload_keys=("lmpDecomposition",))
