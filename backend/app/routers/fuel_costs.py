"""Fuel-costs module: the run-time option switch and the pre-run preview.

* ``POST /api/fuel-costs/preview`` - per Generator / Link the marginal-cost series a run would send (fuel price / efficiency
  + VOM), with the fuel / VOM / carbon split, without solving. Carbon is read from the carbon-pricing module for the
  optional ``carbonPrice`` / ``carbonPriceSchedule`` (it is an objective term, not part of the marginal cost). Read-only.

The inputs are the model sheets ``RAGNAROK_FuelPrices`` (temporal, one column per fuel carrier, currency/MWh_thermal),
``RAGNAROK_VariableOM`` (static rows, currency/MWh_el) and the carriers column ``fuel_cost_thermal`` (a constant price).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...pypsa.network import build_components
from .. import carbon_pricing, fuel_costs, model_store
from ..run_options_reference import RunOption, register_options

router = APIRouter(tags=["fuel-costs"])

register_options([
    RunOption("options.fuelCosts", "object", "Fuel-costs module switch. Inputs: model sheets RAGNAROK_FuelPrices (snapshot + one currency/MWh_thermal "
              "column per fuel carrier), RAGNAROK_VariableOM (component, name | carrier, vom in currency/MWh_el) and the carriers column "
              "fuel_cost_thermal (a constant price). At run time marginal_cost = fuel price / efficiency + VOM is written as a time series "
              "(Link with a priced supply Generator on bus0: fuel on the supplier, VOM x efficiency on the Link). Carbon is not in it.", None,
              None, None, "backend/app/fuel_costs", "api", "fuelCosts"),
    RunOption("options.fuelCosts.enabled", "boolean", "false leaves every marginal_cost as the workbook states it. Absent: on exactly when the model has "
              "a price sheet, a VOM sheet or a carrier fuel_cost_thermal (a model with none is untouched).", None,
              None, None, "backend/app/fuel_costs/inputs.py (is_enabled)", "api", "fuelCosts"),
])


class FuelCostsPreview(BaseModel):
    sessionId: str = "default"
    carbonPrice: float = 0.0
    carbonPriceSchedule: list[dict[str, Any]] | None = None


@router.post("/api/fuel-costs/preview")
def fuel_costs_preview(body: FuelCostsPreview) -> dict[str, Any]:
    model = model_store.load_full_model(body.sessionId)
    if not model:
        raise HTTPException(status_code=400, detail=f"No model loaded in session {body.sessionId!r}.")
    inputs = {"priceSheet": fuel_costs.SHEET_PRICES, "vomSheet": fuel_costs.SHEET_VOM, "flatColumn": f"carriers.{fuel_costs.FLAT_COLUMN}"}
    if not fuel_costs.has_inputs(model):
        return {"active": False, "carbonPriceActive": False, "units": [], "priceSources": {}, "inputs": inputs, "smp": fuel_costs.SMP_REFERENCE,
                "notes": ["The model has no fuel-cost input: add RAGNAROK_FuelPrices, RAGNAROK_VariableOM or a carriers fuel_cost_thermal, and a run writes marginal costs from them."],
                "basis": "no input: every marginal_cost stays as the workbook states it"}
    net, _ = build_components(model, {})
    carbon_pricing.set_plan(net, carbon_pricing.parse_carbon_price_config(body.carbonPrice, body.carbonPriceSchedule))
    plan = fuel_costs.build_plan(net, model)
    return {**fuel_costs.preview(net, plan), "inputs": inputs}
