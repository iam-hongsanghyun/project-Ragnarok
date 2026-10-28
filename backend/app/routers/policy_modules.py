"""Carbon-pricing and annual-budgets modules: what they send PyPSA, previewed, and the budget sheet edited.

* ``POST /api/carbon-price/preview`` - per emitting generator the adder the module's objective term charges
  (price x co2_emissions / efficiency), for a scalar or scheduled price. Read-only.
* ``GET  /api/annual-budgets`` - the RAGNAROK_AnnualBudgets rows of the session.
* ``POST /api/annual-budgets/preview`` - the horizon values the module would write for the workbook's own horizon.
* ``POST /api/annual-budgets/set`` - add / replace one row (annual value).
* ``POST /api/annual-budgets/apply`` - write the horizon values into the component rows (visible in the workbook).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...pypsa.network import build_components
from .. import annual_budgets, carbon_pricing, model_store
from ..run_options_reference import RunOption, register_options

router = APIRouter(tags=["policy-modules"])

register_options([
    RunOption("options.carbonPricing", "object", "Carbon-pricing module switch. The price itself is scenario.carbonPrice / options.carbonPriceSchedule.", None,
              None, None, "backend/app/carbon_pricing", "api", "carbonPricing"),
    RunOption("options.carbonPricing.enabled", "boolean", "false keeps the price inputs but sends PyPSA no carbon term (compare a run with and without the price).", True,
              None, None, "backend/app/carbon_pricing/config.py (config_from_run)", "api", "carbonPricing"),
    RunOption("options.annualBudgets", "object", "Annual-budgets module switch. The annual values live in the model sheet RAGNAROK_AnnualBudgets "
              "(component, name, attribute, annual); the module writes annual x sum(w)/8760 into e_sum_min/e_sum_max and the GlobalConstraint constant.", None,
              None, None, "backend/app/annual_budgets", "api", "annualBudgets"),
    RunOption("options.annualBudgets.enabled", "boolean", "false leaves e_sum / constant as the workbook states them (no horizon value written).", True,
              None, None, "backend/pypsa/network/__init__.py (build_network)", "api", "annualBudgets"),
])


def _model(session_id: str) -> dict[str, Any]:
    model = model_store.load_full_model(session_id)
    if not model:
        raise HTTPException(status_code=400, detail=f"No model loaded in session {session_id!r}.")
    return model


class CarbonPreview(BaseModel):
    sessionId: str = "default"
    carbonPrice: float = 0.0
    carbonPriceSchedule: list[dict[str, Any]] | None = None


@router.post("/api/carbon-price/preview")
def carbon_preview(body: CarbonPreview) -> dict[str, Any]:
    model = _model(body.sessionId)
    cfg = carbon_pricing.parse_carbon_price_config(body.carbonPrice, body.carbonPriceSchedule)
    net, _ = build_components(model, {})
    carbon_pricing.set_plan(net, cfg)
    adder = carbon_pricing.adder_frame(net)
    ef = carbon_pricing.emission_factors(net)
    rows = []
    for col in adder.columns:
        name = str(col[-1] if isinstance(col, tuple) else col)
        rows.append({"generator": name, "carrier": str(net.generators.at[name, "carrier"]), "co2PerMWhFuel": float(ef[name]),
                     "adderMean": float(adder[col].mean()), "adderMax": float(adder[col].max())})
    prices = carbon_pricing.price_series(cfg, net.snapshots)
    return {"active": cfg.is_active, "priceMin": float(prices.min()) if len(prices) else 0.0,
            "priceMax": float(prices.max()) if len(prices) else 0.0, "generators": rows,
            "basis": "objective += price x co2_emissions / efficiency x output; marginal_cost is not changed"}


@router.get("/api/annual-budgets")
def budgets_get(session_id: str = "default") -> dict[str, Any]:
    model = _model(session_id)
    try:
        rows = annual_budgets.read_rows(model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"sheet": annual_budgets.SHEET, "rows": [r.__dict__ for r in rows]}


class BudgetPreview(BaseModel):
    sessionId: str = "default"
    pathwayConfig: dict[str, Any] | None = None


def _table(model: dict[str, Any], pathway: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[str]]:
    net, _ = build_components(model, {"pathwayConfig": pathway} if pathway else {})
    notes: list[str] = []
    try:
        table = annual_budgets.apply_to_network(net, model, notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return table, notes


@router.post("/api/annual-budgets/preview")
def budgets_preview(body: BudgetPreview) -> dict[str, Any]:
    table, notes = _table(_model(body.sessionId), body.pathwayConfig)
    return {"table": table, "notes": notes}


class BudgetSet(BaseModel):
    sessionId: str = "default"
    component: str
    name: str
    attribute: str
    annual: float


@router.post("/api/annual-budgets/set")
def budgets_set(body: BudgetSet) -> dict[str, Any]:
    model = _model(body.sessionId)
    rows = [dict(r) for r in model.get(annual_budgets.SHEET) or [] if isinstance(r, dict)]
    key = (body.component, body.name, body.attribute)
    rows = [r for r in rows if (r.get("component"), r.get("name"), r.get("attribute")) != key]
    rows.append({"component": body.component, "name": body.name, "attribute": body.attribute, "annual": body.annual})
    try:
        annual_budgets.read_rows({annual_budgets.SHEET: rows})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    model_store.merge_static_model(body.sessionId, {annual_budgets.SHEET: rows})
    return {"rows": rows}


@router.post("/api/annual-budgets/apply")
def budgets_apply(body: BudgetPreview) -> dict[str, Any]:
    model = _model(body.sessionId)
    table, notes = _table(model, body.pathwayConfig)
    out = annual_budgets.apply_to_workbook(model, table)
    changed = {t["component"]: out[t["component"]] for t in table}
    if changed:
        model_store.merge_static_model(body.sessionId, changed)
    return {"table": table, "notes": notes, "sheetsWritten": sorted(changed)}
