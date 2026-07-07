"""``/api/physical-risk/*`` — native physical-climate-risk capability (Phase 0).

A faithful port of the user's standalone ``climaterisk`` orchestration into
Ragnarok, wired to a deterministic STUB engine (no CLIMADA / conda yet — see
:mod:`backend.app.physical_risk.engine`). The frontend seeds a portfolio from
the current Ragnarok model, edits the asset list, then submits + polls runs.

Endpoints::

    POST /api/physical-risk/seed-from-model   -> Portfolio (from the live model)
    GET  /api/physical-risk/session/{sid}     -> Portfolio
    PUT  /api/physical-risk/session/{sid}     -> Portfolio (full-model sync)
    GET  /api/physical-risk/libraries         -> {perils, vulnerabilityClasses}
    POST /api/physical-risk/session/{sid}/run -> Run (queued)
    GET  /api/physical-risk/session/{sid}/run/{rid} -> Run (+ result when done)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import model_store
from ..physical_risk.entities import Peril, Portfolio, Run, Scenario, VulnerabilityClass
from ..physical_risk.seed import portfolio_from_model
from ..physical_risk.store import store

router = APIRouter(prefix="/api/physical-risk", tags=["physical-risk"])

# Default value-per-MW used when a unit has no ``capital_cost`` — a placeholder
# order-of-magnitude for a generic power asset, overridable per seed request.
_DEFAULT_VALUE_PER_MW = 1_000_000.0
_DEFAULT_CURRENCY = "USD"

# Human-readable labels for the controlled vocabularies (libraries endpoint).
_PERIL_LABELS: dict[str, str] = {
    Peril.TROPICAL_CYCLONE.value: "Tropical cyclone",
    Peril.RIVER_FLOOD.value: "River flood",
    Peril.WILDFIRE.value: "Wildfire",
    Peril.EARTHQUAKE.value: "Earthquake",
    Peril.WINDSTORM.value: "Windstorm",
}
_VCLASS_LABELS: dict[str, str] = {
    VulnerabilityClass.THERMAL.value: "Thermal plant",
    VulnerabilityClass.RENEWABLE.value: "Renewable (wind / solar)",
    VulnerabilityClass.HYDRO.value: "Hydro",
    VulnerabilityClass.GRID.value: "Grid / storage",
    VulnerabilityClass.DEFAULT.value: "Generic",
}


class SeedRequest(BaseModel):
    """Optional overrides for ``POST /seed-from-model``."""

    defaultValuePerMw: float = _DEFAULT_VALUE_PER_MW
    currency: str = _DEFAULT_CURRENCY
    sessionId: str = "default"


class RunRequest(BaseModel):
    """Body for ``POST /session/{sid}/run``."""

    perils: list[str] = []
    scenario: Scenario = Scenario()


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
    """The controlled vocabularies the frontend picks from (perils + classes)."""
    return {
        "perils": [{"id": p.value, "label": _PERIL_LABELS[p.value]} for p in Peril],
        "vulnerabilityClasses": [
            {"id": v.value, "label": _VCLASS_LABELS[v.value]} for v in VulnerabilityClass
        ],
    }


@router.post("/session/{sid}/run", response_model=Run)
def submit_run(sid: str, body: RunRequest) -> Run:
    """Submit an analysis run for the session's portfolio."""
    portfolio = store.get_session(sid)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="physical-risk session not found")
    if not portfolio.assets:
        raise HTTPException(status_code=400, detail="portfolio has no assets")
    if not body.perils:
        raise HTTPException(status_code=400, detail="no perils selected")
    run = store.submit_run(sid, body.perils, body.scenario)
    if run is None:  # session vanished between the checks above and submit
        raise HTTPException(status_code=404, detail="physical-risk session not found")
    return run


@router.get("/session/{sid}/run/{rid}", response_model=Run)
def get_run(sid: str, rid: str) -> Run:
    """Poll a run; the stub engine finalises it to 'done' on the first poll."""
    run = store.poll_run(rid)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run
