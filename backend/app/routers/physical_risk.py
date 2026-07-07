"""``/api/physical-risk/*`` — native physical-climate-risk capability.

A faithful port of the user's standalone ``climaterisk`` orchestration into
Ragnarok. Transition (NGFS carbon cost) and finance (climate risk premium) are
REAL ported math; the worker-gated run kinds (physical, uncertainty,
cost-benefit, supply-chain, calibration, forecast) run against a deterministic
STUB engine until the conda CLIMADA worker is attached (see
:mod:`backend.app.physical_risk.engine`).

Endpoints::

    POST /api/physical-risk/seed-from-model         -> Portfolio (from the live model)
    GET  /api/physical-risk/session/{sid}           -> Portfolio
    PUT  /api/physical-risk/session/{sid}           -> Portfolio (full-model sync)
    GET  /api/physical-risk/libraries               -> Libraries (vendored methodology data)
    POST /api/physical-risk/session/{sid}/run       -> Run (queued; body.kind selects the analysis;
                                                        executes async on a background thread)
    GET  /api/physical-risk/session/{sid}/run/{rid} -> Run (+ result when done; pure status read)
    POST /api/physical-risk/session/{sid}/transition -> TransitionResult (synchronous, REAL)
    POST /api/physical-risk/session/{sid}/finance   -> FinanceResult (synchronous, REAL)
    GET  /api/physical-risk/session/{sid}/report    -> JSON report bundle
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import model_store
from ..physical_risk.entities import (
    RUN_KINDS,
    MeasureSpec,
    PhysicalRunOutput,
    Portfolio,
    Run,
    Scenario,
)
from ..physical_risk.finance import FinanceResult, compute_finance
from ..physical_risk.libraries import libraries_payload, load_libraries
from ..physical_risk.seed import portfolio_from_model
from ..physical_risk.store import store
from ..physical_risk.transition import TransitionResult, compute_transition_risk

router = APIRouter(prefix="/api/physical-risk", tags=["physical-risk"])

# Default value-per-MW used when a unit has no ``capital_cost`` — a placeholder
# order-of-magnitude for a generic power asset, overridable per seed request.
_DEFAULT_VALUE_PER_MW = 1_000_000.0
_DEFAULT_CURRENCY = "USD"

# Report keys per run kind (camelCase JSON contract).
_REPORT_KIND_KEYS: dict[str, str] = {
    "physical": "physical",
    "uncertainty": "uncertainty",
    "cost-benefit": "costBenefit",
    "supply-chain": "supplyChain",
    "calibration": "calibration",
    "forecast": "forecast",
}


class SeedRequest(BaseModel):
    """Optional overrides for ``POST /seed-from-model``."""

    defaultValuePerMw: float = _DEFAULT_VALUE_PER_MW
    currency: str = _DEFAULT_CURRENCY
    sessionId: str = "default"


class RunRequest(BaseModel):
    """Body for ``POST /session/{sid}/run`` — ``kind`` selects the analysis.

    Kind-specific parameters (ignored by the other kinds): ``nSamples`` (uncertainty),
    ``measures`` + ``peril`` + ``discountRate`` (cost-benefit), ``mriotType`` +
    ``mriotYear`` (supply-chain). ``perils``/``scenario`` default to the portfolio's
    stored scenario config, except the physical kind which keeps the Phase-0 contract
    (explicit non-empty ``perils`` required).
    """

    kind: str = "physical"
    perils: list[str] = []
    scenario: Scenario | None = None
    nSamples: int = Field(default=50, description="Monte-Carlo samples (clamped to 10..200).")
    measures: list[MeasureSpec] = Field(default_factory=list)
    peril: str | None = Field(default=None, description="Cost-benefit peril override.")
    discountRate: float | None = Field(default=None, ge=0.0, le=1.0)
    mriotType: str = "WIOD16"
    mriotYear: int = 2010


class TransitionRequest(BaseModel):
    """Optional overrides for ``POST /session/{sid}/transition``."""

    scenario: str | None = Field(default=None, description="NGFS scenario id override.")
    discountRate: float | None = Field(default=None, ge=0.0, le=1.0)


class FinanceRequest(BaseModel):
    """Body for ``POST /session/{sid}/finance``."""

    runId: str = Field(description="A completed physical run whose AAI stresses the cashflow.")
    transitionCost: float = Field(
        default=0.0, ge=0.0, description="Annual transition carbon cost to add to the stress."
    )


@router.post("/seed-from-model", response_model=Portfolio)
def seed_from_model(body: SeedRequest | None = None) -> Portfolio:
    """Build a portfolio from the current Ragnarok model and open a session."""
    req = body or SeedRequest()
    model = model_store.load_full_model(req.sessionId, static_only=True)
    if not model:
        raise HTTPException(status_code=400, detail="No working model loaded in this session.")
    portfolio, _notes = portfolio_from_model(
        model,
        default_value_per_mw=req.defaultValuePerMw,
        currency=req.currency,
    )
    if not portfolio.assets:
        raise HTTPException(
            status_code=400,
            detail="No placeable generators or storage units (need a bus with x/y coordinates).",
        )
    return store.create_session(portfolio)


@router.get("/session/{sid}", response_model=Portfolio)
def get_session(sid: str) -> Portfolio:
    """Return the portfolio for a physical-risk session, or 404 if unknown."""
    portfolio = store.get_session(sid)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="physical-risk session not found")
    return portfolio


@router.put("/session/{sid}", response_model=Portfolio)
def save_session(sid: str, portfolio: Portfolio) -> Portfolio:
    """Replace the stored portfolio for a session (full-model sync). 404 if unknown."""
    saved = store.save_session(sid, portfolio)
    if saved is None:
        raise HTTPException(status_code=404, detail="physical-risk session not found")
    return saved


@router.get("/libraries")
def libraries() -> dict[str, Any]:
    """The vendored methodology libraries, camelCased for the frontend.

    Keys: ``perils, scenarios, sectors, vulnerabilityClasses, impactFunctions,
    ngfsScenarios, financeChannels, dataSources`` (finance reference framework at
    ``financeChannels.reference``).
    """
    return libraries_payload()


@router.post("/session/{sid}/run", response_model=Run)
def submit_run(sid: str, body: RunRequest) -> Run:
    """Submit an analysis run for the session's portfolio (``kind`` selects it)."""
    if body.kind not in RUN_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown run kind '{body.kind}' (expected one of {', '.join(RUN_KINDS)})",
        )
    portfolio = store.get_session(sid)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="physical-risk session not found")
    if not portfolio.assets:
        raise HTTPException(status_code=400, detail="portfolio has no assets")

    perils = list(body.perils)
    if body.kind == "physical":
        if not perils:  # Phase-0 contract: the physical kind requires an explicit selection
            raise HTTPException(status_code=400, detail="no perils selected")
    elif not perils:
        perils = list(portfolio.scenario.perils)

    scenario = body.scenario or Scenario(
        rcp=portfolio.scenario.climate, horizon=portfolio.scenario.horizonYear
    )
    options: dict[str, Any] = {
        "nSamples": max(10, min(body.nSamples, 200)),
        "measures": body.measures,
        "peril": body.peril,
        "discountRate": (
            body.discountRate
            if body.discountRate is not None
            else portfolio.scenario.discountRate
        ),
        "mriotType": body.mriotType,
        "mriotYear": body.mriotYear,
    }
    run = store.submit_run(sid, body.kind, perils, scenario, options)
    if run is None:  # session vanished between the checks above and submit
        raise HTTPException(status_code=404, detail="physical-risk session not found")
    return run


@router.get("/session/{sid}/run/{rid}", response_model=Run)
def get_run(sid: str, rid: str) -> Run:
    """Poll a run — a pure status read; execution happens on a background thread.

    Stub runs are near-instant (submit grace-joins them), so they are typically
    already 'done' by the first poll; real CLIMADA runs report queued/running
    until the worker finishes.
    """
    run = store.poll_run(rid, session_id=sid)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("/session/{sid}/transition", response_model=TransitionResult)
def run_transition(sid: str, body: TransitionRequest | None = None) -> TransitionResult:
    """Compute the portfolio's transition (carbon-cost) risk — synchronous, REAL math."""
    portfolio = store.get_session(sid)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="physical-risk session not found")
    req = body or TransitionRequest()
    return compute_transition_risk(
        portfolio, scenario=req.scenario, discount_rate=req.discountRate
    )


@router.post("/session/{sid}/finance", response_model=FinanceResult)
def run_finance(sid: str, body: FinanceRequest) -> FinanceResult:
    """Climate Risk Premium for a completed physical run — synchronous, REAL math.

    Cashflow -> NPV/IRR/DSCR -> rating -> CRP, baseline vs climate-stressed. Mirrors
    climaterisk's finance route validations.
    """
    portfolio = store.get_session(sid)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="physical-risk session not found")
    run = store.poll_run(body.runId, session_id=sid)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status != "done" or not isinstance(run.result, PhysicalRunOutput):
        raise HTTPException(
            status_code=400, detail="finance needs a completed run of kind 'physical'"
        )
    prof = portfolio.scenario.financialProfile
    is_power = prof is not None and prof.financialModel == "power_gen"
    if prof is None or not prof.capex:
        raise HTTPException(
            status_code=400,
            detail="set a financial profile (CAPEX) on the portfolio scenario first",
        )
    if is_power and not (
        prof.capacityMw and prof.powerPrice and (prof.capacityFactor or prof.plantFuel)
    ):
        raise HTTPException(
            status_code=400,
            detail="power-generation model needs capacity (MW), price (per MWh) and a "
            "capacity factor (or fuel type)",
        )
    if not is_power and not prof.annualEbitda:
        raise HTTPException(
            status_code=400,
            detail="set a financial profile (CAPEX + annual EBITDA) on the portfolio "
            "scenario first",
        )
    libs = load_libraries()
    return compute_finance(
        portfolio,
        run.result,
        body.transitionCost,
        libs["finance_reference"],
        libs["finance_channels"],
    )


@router.get("/session/{sid}/report")
def report(sid: str) -> dict[str, Any]:
    """JSON report bundle: portfolio + latest done result per run kind + transition/finance.

    Transition is recomputed synchronously (as climaterisk's report route does). Finance is
    included when the portfolio carries a CAPEX-bearing financial profile AND a physical run
    has completed; its transition stress is the transition total at the horizon year.
    """
    portfolio = store.get_session(sid)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="physical-risk session not found")

    latest = store.latest_results(sid)
    results: dict[str, Any] = {key: None for key in _REPORT_KIND_KEYS.values()}
    for kind, result in latest.items():
        results[_REPORT_KIND_KEYS.get(kind, kind)] = result

    transition = compute_transition_risk(portfolio)

    finance = None
    prof = portfolio.scenario.financialProfile
    physical = latest.get("physical")
    if prof is not None and prof.capex and isinstance(physical, PhysicalRunOutput):
        horizon = portfolio.scenario.horizonYear
        transition_cost = 0.0
        if horizon in transition.years:
            transition_cost = transition.totalCostByYear[transition.years.index(horizon)]
        libs = load_libraries()
        finance = compute_finance(
            portfolio,
            physical,
            transition_cost,
            libs["finance_reference"],
            libs["finance_channels"],
        )

    currency = portfolio.assets[0].currency if portfolio.assets else _DEFAULT_CURRENCY
    return {
        "sessionId": sid,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "portfolio": portfolio,
        "summary": {
            "assetCount": len(portfolio.assets),
            "totalValue": round(sum(a.value for a in portfolio.assets), 2),
            "currency": currency,
        },
        "results": results,
        "transition": transition,
        "finance": finance,
    }
