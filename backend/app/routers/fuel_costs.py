"""Fuel-costs module: the run-time option switch, the pre-run preview and the edits of its input sheets.

* ``GET  /api/fuel-costs/inputs`` - what the module will read: per carrier the price (series statistics or the flat value),
  the VOM rows and the scenario price rows. Read-only.
* ``POST /api/fuel-costs/price/set`` / ``price/remove`` - a carrier's price as a constant (``carriers.fuel_cost_thermal``) or a
  series (a column of ``RAGNAROK_FuelPrices``), optionally in the fuel's native unit ($/MMBtu, $/tonne, $/bbl).
* ``POST /api/fuel-costs/vom/set`` / ``vom/remove`` - one ``RAGNAROK_VariableOM`` row (a unit by name, or every unit of a carrier).
* ``POST /api/fuel-costs/scenario-price/set`` / ``scenario-price/remove`` - one ``RAGNAROK_FuelPriceScenarios`` row.
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
from ..fuel_costs import edit as fuel_edit
from ..run_options_reference import RunOption, register_options
from ..stochastic.scenarios import apply_scenarios, parse_stochastic_config

router = APIRouter(tags=["fuel-costs"])

register_options([
    RunOption("options.fuelCosts", "object", "Fuel-costs module switch. Inputs: model sheets RAGNAROK_FuelPrices (snapshot + one currency/MWh_thermal "
              "column per fuel carrier), RAGNAROK_VariableOM (component, name | carrier, vom in currency/MWh_el) and the carriers column "
              "fuel_cost_thermal (a constant price). At run time marginal_cost = fuel price / efficiency + VOM is written as a time series "
              "(Link with a priced supply Generator on bus0: fuel on the supplier, VOM x efficiency on the Link). Carbon is not in it. Stochastic runs: per-scenario prices from RAGNAROK_FuelPriceScenarios (scenario, carrier, snapshot, price | multiplier) or stochastic override rows (sheet carriers, attribute fuel_price).", None,
              None, None, "backend/app/fuel_costs", "api", "fuelCosts"),
    RunOption("options.fuelCosts.enabled", "boolean", "false leaves every marginal_cost as the workbook states it. Absent: on exactly when the model has "
              "a price sheet, a VOM sheet or a carrier fuel_cost_thermal (a model with none is untouched).", None,
              None, None, "backend/app/fuel_costs/inputs.py (is_enabled)", "api", "fuelCosts"),
])


class FuelCostsPreview(BaseModel):
    sessionId: str = "default"
    carbonPrice: float = 0.0
    carbonPriceSchedule: list[dict[str, Any]] | None = None
    #: ``options.stochasticConfig``: when enabled, the response adds ``scenarios`` (each scenario's own series).
    stochasticConfig: dict[str, Any] | None = None


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
    out = {**fuel_costs.preview(net, plan), "inputs": inputs}
    stoch = parse_stochastic_config(body.stochasticConfig)
    if stoch.enabled:
        # the same path a run takes: expand to scenarios, apply their overrides, then plan each scenario
        snet, _ = build_components(model, {})
        carbon_pricing.set_plan(snet, carbon_pricing.parse_carbon_price_config(body.carbonPrice, body.carbonPriceSchedule))
        apply_scenarios(snet, stoch)
        plans = fuel_costs.build_stochastic_plans(snet, model, stoch)
        out["scenarios"] = fuel_costs.stochastic_preview(snet, plans, {s.name: s.weight for s in stoch.scenarios})
    return out


# ── edits of the input sheets (validated with the module's own readers; 400 on bad input) ────────────────

_ALL_ROWS = 10_000_000


def _static_model(session_id: str) -> dict[str, Any]:
    model = model_store.load_full_model(session_id, static_only=True)
    if not model:
        raise HTTPException(status_code=400, detail=f"No model loaded in session {session_id!r}.")
    return model


def _price_rows(session_id: str) -> list[dict[str, Any]]:
    page = model_store.get_sheet_page(session_id, fuel_costs.SHEET_PRICES, 0, _ALL_ROWS)
    return [dict(r) for r in (page or {}).get("rows") or [] if isinstance(r, dict)]


def _write_static(session_id: str, sheet: str, rows: list[dict[str, Any]]) -> None:
    if model_store.merge_static_model(session_id, {sheet: rows}) is None:
        raise HTTPException(status_code=400, detail=f"No model loaded in session {session_id!r}.")


class PricePoint(BaseModel):
    snapshot: str
    price: float


class FuelPriceSet(BaseModel):
    sessionId: str = "default"
    carrier: str
    price: float | None = None          # a constant, in `unit`
    series: list[PricePoint] | None = None  # or one price per snapshot, in `unit`
    unit: str = "MWh_th"                # MWh_th, or the fuel's native unit (gas MMBtu, coal / biomass tonne, oil bbl)
    merge: bool = False                 # series only: overwrite just the given snapshots instead of replacing the column


class FuelPriceRemove(BaseModel):
    sessionId: str = "default"
    carrier: str


@router.get("/api/fuel-costs/inputs")
def fuel_costs_inputs(session_id: str = "default") -> dict[str, Any]:
    model = _static_model(session_id)
    model[fuel_costs.SHEET_PRICES] = _price_rows(session_id)
    return fuel_edit.inputs_summary(model)


@router.post("/api/fuel-costs/price/set")
def fuel_price_set(body: FuelPriceSet) -> dict[str, Any]:
    if (body.price is None) == (body.series is None):
        raise HTTPException(status_code=400, detail="give exactly one of price (a constant) or series (a list of {snapshot, price}).")
    model = _static_model(body.sessionId)
    carrier = fuel_edit.check_carrier(model, body.carrier)
    prices = _price_rows(body.sessionId)
    if body.series is not None:
        rows, info = fuel_edit.set_price_series(model, prices, carrier, [p.model_dump() for p in body.series], body.unit, body.merge)
        model_store.merge_series_sheets(body.sessionId, {fuel_costs.SHEET_PRICES: rows})
        return {"carrier": carrier, "kind": "series", "unit": body.unit, "sheet": fuel_costs.SHEET_PRICES, **info,
                "note": "A series supersedes the carrier's flat fuel_cost_thermal (kept, unused)."}
    thermal = fuel_edit.convert_price(carrier, body.price, body.unit)
    carriers_rows = fuel_edit.set_flat_price(model, prices, carrier, thermal)
    _write_static(body.sessionId, "carriers", carriers_rows)
    return {"carrier": carrier, "kind": "constant", "unit": body.unit, "thermalPrice": thermal, "priceUnit": "currency/MWh_thermal",
            "sheet": f"carriers.{fuel_costs.FLAT_COLUMN}"}


@router.post("/api/fuel-costs/price/remove")
def fuel_price_remove(body: FuelPriceRemove) -> dict[str, Any]:
    model = _static_model(body.sessionId)
    carrier = body.carrier.strip()
    prices = _price_rows(body.sessionId)
    new_prices, carriers_rows, removed = fuel_edit.remove_price(model, prices, carrier)
    if removed["series"]:
        model_store.merge_series_sheets(body.sessionId, {fuel_costs.SHEET_PRICES: new_prices})
    if carriers_rows is not None:
        _write_static(body.sessionId, "carriers", carriers_rows)
    return {"carrier": carrier, "removed": removed, "sheetRows": len(new_prices)}


class VomSet(BaseModel):
    sessionId: str = "default"
    component: str                      # Generator | Link
    name: str | None = None             # one unit ...
    carrier: str | None = None          # ... or every unit of a carrier
    vom: float                          # currency per MWh of electric output, >= 0


class VomRemove(BaseModel):
    sessionId: str = "default"
    component: str
    name: str | None = None
    carrier: str | None = None


@router.post("/api/fuel-costs/vom/set")
def vom_set(body: VomSet) -> dict[str, Any]:
    rows = fuel_edit.set_vom(_static_model(body.sessionId), body.component, body.name, body.carrier, body.vom)
    _write_static(body.sessionId, fuel_costs.SHEET_VOM, rows)
    return {"rows": rows, "sheet": fuel_costs.SHEET_VOM, "unit": "currency/MWh_el"}


@router.post("/api/fuel-costs/vom/remove")
def vom_remove(body: VomRemove) -> dict[str, Any]:
    rows = fuel_edit.remove_vom(_static_model(body.sessionId), body.component, body.name, body.carrier)
    _write_static(body.sessionId, fuel_costs.SHEET_VOM, rows)
    return {"rows": rows, "sheet": fuel_costs.SHEET_VOM}


class ScenarioPriceSet(BaseModel):
    sessionId: str = "default"
    scenario: str
    carrier: str
    snapshot: str | None = None         # blank = every snapshot
    price: float | None = None          # replaces the price, in `unit`
    multiplier: float | None = None     # scales the price (>= 0); price is applied first
    unit: str = "MWh_th"


class ScenarioPriceRemove(BaseModel):
    sessionId: str = "default"
    scenario: str
    carrier: str
    snapshot: str | None = None


@router.post("/api/fuel-costs/scenario-price/set")
def scenario_price_set(body: ScenarioPriceSet) -> dict[str, Any]:
    rows = fuel_edit.set_scenario_price(_static_model(body.sessionId), body.scenario, body.carrier, body.snapshot,
                                        body.price, body.multiplier, body.unit)
    _write_static(body.sessionId, fuel_costs.SHEET_PRICE_SCENARIOS, rows)
    return {"rows": rows, "sheet": fuel_costs.SHEET_PRICE_SCENARIOS}


@router.post("/api/fuel-costs/scenario-price/remove")
def scenario_price_remove(body: ScenarioPriceRemove) -> dict[str, Any]:
    rows = fuel_edit.remove_scenario_price(_static_model(body.sessionId), body.scenario, body.carrier, body.snapshot)
    _write_static(body.sessionId, fuel_costs.SHEET_PRICE_SCENARIOS, rows)
    return {"rows": rows, "sheet": fuel_costs.SHEET_PRICE_SCENARIOS}
