"""``/api/procurement/*`` — power procurement portfolio optimizer (PP2).

A stateless endpoint over the CVaR-constrained instrument-mix optimizer
(:mod:`backend.app.procurement`). The browser posts the price series it already
holds (a completed run's system price, or an imported market-price series), a
contract volume, and a menu of hedging instruments; the server bootstraps price
scenarios and returns the optimal mix plus the cost-vs-risk efficient frontier.

Not tied to the solve path — procurement is a decision *on top of* prices, not
another optimisation of the network — which is why it is its own use-case
surface, not a solve-time option.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..procurement import generate_scenarios, optimize_portfolio

router = APIRouter(prefix="/api/procurement", tags=["procurement"])


class StressCase(BaseModel):
    label: str = ""
    multiplier: float = 1.0


class PpaInstrument(BaseModel):
    enabled: bool = False
    strike: float = 0.0
    maxMw: float = 0.0
    """Optional hourly capacity-factor profile (0–1); baseload (all 1s) if absent."""
    profile: list[float] | None = None


class ForwardInstrument(BaseModel):
    enabled: bool = False
    price: float = 0.0
    maxMw: float = 0.0


class RetailInstrument(BaseModel):
    enabled: bool = False
    price: float = 0.0


class OptimizeRequest(BaseModel):
    prices: list[float] = Field(..., description="Hourly reference price series (currency/MWh).")
    loadMw: float | list[float] = Field(..., description="Contract volume — a flat MW or an hourly series.")
    ppa: PpaInstrument = PpaInstrument()
    forward: ForwardInstrument = ForwardInstrument()
    retail: RetailInstrument = RetailInstrument()
    alpha: float = 0.95
    cvarBudget: float | None = None
    bootstrap: int = 200
    blockHours: int = 24
    stress: list[StressCase] = []
    frontierPoints: int = 8
    currency: str = "€"


@router.post("/optimize")
def optimize(req: OptimizeRequest) -> dict[str, Any]:
    """Optimal hedging mix + efficient frontier for the posted price series."""
    prices = np.asarray(req.prices, dtype=float)
    if prices.size < 2:
        raise HTTPException(422, "Need a price series of at least two points.")
    if not (0.5 <= req.alpha < 1.0):
        raise HTTPException(422, "alpha (CVaR tail level) must be in [0.5, 1).")

    T = prices.size
    if isinstance(req.loadMw, list):
        load = np.asarray(req.loadMw, dtype=float)
        if load.size < T:  # pad a short load profile with its own mean
            load = np.pad(load, (0, T - load.size), constant_values=float(load.mean() if load.size else 0.0))
        load = load[:T]
    else:
        load = np.full(T, float(req.loadMw))
    if float(load.sum()) <= 0:
        raise HTTPException(422, "Contract volume (load) must be positive.")

    scenarios, labels = generate_scenarios(
        prices,
        n_bootstrap=max(0, min(int(req.bootstrap), 1000)),
        block_hours=max(1, int(req.blockHours)),
        stress=[c.model_dump() for c in req.stress],
    )
    instruments = {
        "ppa": req.ppa.model_dump(),
        "forward": req.forward.model_dump(),
        "retail": req.retail.model_dump(),
    }
    result = optimize_portfolio(
        scenarios, load, instruments,
        alpha=float(req.alpha),
        cvar_budget=req.cvarBudget,
        frontier_points=max(2, min(int(req.frontierPoints), 24)),
    )
    result["currency"] = req.currency
    result["scenarioCount"] = int(scenarios.shape[0])
    result["horizonHours"] = int(T)
    result["stressLabels"] = [lbl for lbl in labels if lbl not in ("observed",) and not lbl.startswith("bootstrap_")]
    return result
