"""Company module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.app import module_hooks as mh

MODULE = "company"
_MODES = "rolling horizon, stochastic, security-constrained, sampled-block, power-flow, or contingency modes."


def _guard_asset_swap(ctx: mh.RunContext) -> None:
    # Asset-swap re-solves the whole system with a carrier swapped, so it needs the plain optimise path.
    if bool((ctx.options.get("assetSwapConfig") or {}).get("enabled", False)) and ctx.incompatible_modes:
        raise HTTPException(status_code=400, detail=f"Asset-swap what-if cannot be combined with {_MODES}")


def _guard_ess(ctx: mh.RunContext) -> None:
    # The ESS business case prices arbitrage against the base LMP, so it needs the plain optimise path.
    if bool((ctx.options.get("essConfig") or {}).get("enabled", False)) and ctx.incompatible_modes:
        raise HTTPException(status_code=400, detail=f"ESS business case cannot be combined with {_MODES}")


def _asset_swap(ctx: mh.RunContext) -> dict[str, Any]:
    """Retire a carrier, add a replacement (fixed 1:1, or LP-sized), re-solve, report the before-vs-after delta."""
    cfg = ctx.options.get("assetSwapConfig") or {}
    if not bool(cfg.get("enabled", False)):
        return {"assetSwap": None}
    from backend.pypsa.network import build_network

    from .asset_swap import build_asset_swap

    return {"assetSwap": build_asset_swap(
        ctx.network,
        ctx.model,
        ctx.scenario,
        ctx.options,
        build_network,
        remove_filters=cfg.get("removeFilters") or None,
        remove_carrier=str(cfg.get("removeCarrier", "") or ""),
        add_carrier=str(cfg.get("addCarrier", "") or ""),
        add_capital_cost=float(cfg.get("addCapitalCost", 0.0) or 0.0),
        add_marginal_cost=float(cfg.get("addMarginalCost", 0.0) or 0.0),
        replace_ratio=float(cfg.get("replaceRatio", 1.0) or 1.0),
        size_replacement=bool(cfg.get("sizeReplacement", False)),
        add_storage_mw=float(cfg.get("addStorageMW", 0.0) or 0.0),
        add_storage_hours=float(cfg.get("addStorageHours", 4.0) or 4.0),
        add_storage_capex_per_mw=float(cfg.get("addStorageCapexPerMW", 0.0) or 0.0),
        currency=ctx.currency,
        emissions_factors=ctx.emissions_factors,
        solver_options=ctx.solver_options or {},
        io_api=ctx.io_api,
    )}


def _ess(ctx: mh.RunContext) -> dict[str, Any]:
    """Size sweep of a price-taker battery (DW3)."""
    cfg = ctx.options.get("essConfig") or {}
    if not bool(cfg.get("enabled", False)):
        return {"essBusinessCase": None}
    from .ess import build_ess_business_case, ess_cost_kwargs

    return {"essBusinessCase": build_ess_business_case(
        ctx.network,
        bus=str(cfg.get("bus", "") or ""),
        max_hours=float(cfg.get("maxHours", 4.0) or 4.0),
        capital_cost_per_mw=float(cfg.get("capitalCostPerMW", 0.0) or 0.0),
        min_size_mw=float(cfg.get("minSizeMW", 0.0) or 0.0),
        max_size_mw=float(cfg.get("maxSizeMW", 0.0) or 0.0),
        steps=int(cfg.get("steps", 6) or 6),
        round_trip_efficiency=float(cfg.get("roundTripEfficiency", 0.9) or 0.9),
        discount_rate=float(ctx.scenario.get("discountRate", 0.0) or 0.0),
        currency=ctx.currency,
        solver_options=ctx.solver_options or {},
        io_api=ctx.io_api,
        **ess_cost_kwargs(cfg),
    )}


def _company_breakdown(ctx: mh.RunContext) -> dict[str, Any]:
    """Per-company KPIs whenever assets carry an owner tag (F1); reads only solved dataframes."""
    from .company import build_company_breakdown

    return {"companies": build_company_breakdown(
        ctx.network, ctx.model,
        owner_column=ctx.owner_column, currency=ctx.currency, emissions_factors=ctx.emissions_factors,
    )}


def _company_finance(ctx: mh.RunContext) -> dict[str, Any]:
    """Company-level financial model (F2): NPV / IRR / payback / DSCR per owner."""
    from .finance import build_company_finance

    return {"companyFinance": build_company_finance(
        ctx.network, ctx.model,
        owner_column=ctx.owner_column,
        discount_rate=float(ctx.scenario.get("discountRate", 0.0) or 0.0),
        currency=ctx.currency,
        debt=ctx.options.get("financeConfig") or None,
    )}


def _company_statement(ctx: mh.RunContext) -> dict[str, Any]:
    """Consolidated per-company annual P&L (revenue -> carbon/fuel -> margin -> EBIT -> net)."""
    from .company_statement import build_company_statement

    return {"companyStatement": build_company_statement(
        ctx.network, ctx.model,
        owner_column=ctx.owner_column,
        currency=ctx.currency,
        emissions_factors=ctx.emissions_factors,
        debt=ctx.options.get("financeConfig") or None,
    )}


mh.register("guard", "asset-swap", _guard_asset_swap, module=MODULE, order=30)
mh.register("guard", "ess", _guard_ess, module=MODULE, order=40)
mh.register("study", "asset-swap", _asset_swap, module=MODULE, order=120, payload_keys=("assetSwap",))
mh.register("study", "ess", _ess, module=MODULE, order=130, payload_keys=("essBusinessCase",))
mh.register("study", "company-breakdown", _company_breakdown, module=MODULE, order=140, payload_keys=("companies",))
mh.register("study", "company-finance", _company_finance, module=MODULE, order=170, payload_keys=("companyFinance",))
mh.register("study", "company-statement", _company_statement, module=MODULE, order=190,
            payload_keys=("companyStatement",))
