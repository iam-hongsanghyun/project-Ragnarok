"""Carbon-pricing and annual-budgets module tools.

Thin wrappers over ``/api/carbon-price/*``, ``/api/annual-budgets/*`` and the scenario presets; nothing here imports ``backend.app``.

* ``get_carbon_price``   - read-only: the module's per-generator adder for a price / schedule on the working model.
* ``get_fuel_costs``     - read-only: the fuel-costs module's per-unit marginal-cost series (fuel / efficiency + VOM) with the fuel / VOM / carbon split.
* ``get_fuel_inputs``    - read-only: what the module will read (prices per carrier, VOM rows, scenario price rows).
* ``set_fuel_price`` / ``set_vom`` / ``set_fuel_price_scenario`` - WRITE (cheap, gated by autonomy): set or remove one input of the fuel-costs module.
* ``set_carbon_price``   - WRITE (cheap, gated by autonomy): the scenario preset's carbonPrice / carbonPriceSchedule.
* ``get_annual_budgets`` - read-only: the budget rows and the horizon values the module would write.
* ``set_annual_budget``  - WRITE (cheap): add / replace one annual budget row.
* ``apply_annual_budgets`` - WRITE (gated, confirm=true): write the horizon values into the component rows.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .catalogue import declare_areas
from .server import _MUT, _RO, _needs_confirm, _preview, get_client, mcp
from .tools_runspec import _EDIT


async def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    client = get_client()
    return await client._post(path, {"sessionId": client.session_id, **body})


@mcp.tool(annotations=_RO, description=(
    "What the carbon-pricing module sends PyPSA for a price: per emitting generator the carbon cost per MWh (price x co2_emissions / efficiency), "
    "added to the OBJECTIVE (marginal_cost is not changed). price = flat currency/tCO2; schedule = [{year, price}]."))
async def get_carbon_price(price: float = 0.0, schedule: list[dict[str, Any]] | None = None) -> Any:
    return await _post("/api/carbon-price/preview", {"carbonPrice": price, "carbonPriceSchedule": schedule})


@mcp.tool(annotations=_RO, description=(
    "What the fuel-costs module would send PyPSA, without solving: per Generator / Link the marginal-cost series fuel price / efficiency + VOM "
    "(fuel prices: sheet RAGNAROK_FuelPrices, one currency/MWh_thermal column per carrier, or carriers.fuel_cost_thermal as a constant; VOM: sheet RAGNAROK_VariableOM, "
    "currency/MWh_el), with the fuel / VOM / carbon split per MWh_el. A Link burning a fuel with a priced supply Generator on bus0 carries VOM x efficiency; the fuel is priced on the supplier. "
    "Carbon is an objective term, not in marginal_cost: pass price (currency/tCO2) to see it in the breakdown. A priced unit without efficiency is a 400. "
    "The system marginal price is an output of the solve, not an input. stochastic_config (options.stochasticConfig) adds each scenario's own series: scenario fuel prices from "
    "RAGNAROK_FuelPriceScenarios or override rows (sheet carriers, attribute fuel_price), efficiency overrides honoured, marginal_cost overrides of priced units refused."))
async def get_fuel_costs(price: float = 0.0, schedule: list[dict[str, Any]] | None = None, stochastic_config: dict[str, Any] | None = None) -> Any:
    return await _post("/api/fuel-costs/preview", {"carbonPrice": price, "carbonPriceSchedule": schedule, "stochasticConfig": stochastic_config})


@mcp.tool(annotations=_RO, description=(
    "What the fuel-costs module will read from the working model (연료 가격 입력 확인), without computing anything: per carrier its fuel price (a series: count / first / last / min / max / mean of RAGNAROK_FuelPrices, "
    "currency/MWh_thermal; or a flat carriers.fuel_cost_thermal), the VOM rows (RAGNAROK_VariableOM, currency/MWh_el), the per-scenario price rows (RAGNAROK_FuelPriceScenarios) and each fuel's native price unit "
    "(gas MMBtu, coal / biomass tonne, oil bbl). Read this before set_fuel_price / set_vom / set_fuel_price_scenario; get_fuel_costs shows the resulting marginal costs."))
async def get_fuel_inputs() -> Any:
    client = get_client()
    return await client._get("/api/fuel-costs/inputs", {"session_id": client.session_id})


_SERIES_POINTS_SHOWN = 3


def _series_digest(series: list[dict[str, Any]]) -> dict[str, Any]:
    """A series in a preview: the count and the first points, never the whole 8760."""
    return {"points": len(series), "first": series[:_SERIES_POINTS_SHOWN], "last": series[-1:] if len(series) > _SERIES_POINTS_SHOWN else []}


@mcp.tool(annotations=_EDIT, description=(
    "Set (or remove) a carrier's fuel price (연료 가격, 가스 가격 시계열, gas / coal / oil / biomass price) for the fuel-costs module: at run time each unit's marginal_cost becomes fuel price / efficiency + VOM. "
    "Give exactly one of price (a constant, written to carriers.fuel_cost_thermal) or series = [{snapshot, price}] (one price per snapshot, written to a column of the temporal sheet RAGNAROK_FuelPrices; "
    "snapshots must be on the model's axis, e.g. '2030-01-01 00:00'). unit: 'MWh_th' (default, currency per MWh of fuel heat) or the fuel's native unit converted with the fuel-price importer's factors "
    "(gas 'MMBtu' x3.412142, coal / biomass 'tonne', oil 'bbl'; get_fuel_inputs lists them). series replaces the carrier's column (snapshots not given = no price); merge=true overwrites only the given snapshots. "
    "A series beats a constant, so a constant for a carrier that has a series is refused: remove=true first. remove=true deletes the carrier's price (column and constant). "
    "Needs a carrier that exists in the model; efficiency is required on priced units. Check with get_fuel_costs."))
async def set_fuel_price(
    carrier: str,
    price: float | None = None,
    series: list[dict[str, Any]] | None = None,
    unit: str = "MWh_th",
    merge: bool = False,
    remove: bool = False,
    confirm: bool = False,
) -> Any:
    if remove:
        body: dict[str, Any] = {"carrier": carrier}
        path, effect = "/api/fuel-costs/price/remove", f"Remove the fuel price of carrier {carrier!r}."
        shown: dict[str, Any] = body
    else:
        if (price is None) == (series is None):
            return {"error": "give exactly one of price (a constant) or series (a list of {snapshot, price}), or remove=true."}
        body = {"carrier": carrier, "unit": unit, "merge": merge, **({"price": price} if price is not None else {"series": series})}
        path = "/api/fuel-costs/price/set"
        effect = f"Set the fuel price of carrier {carrier!r}" + (f" to {price:g} per {unit}." if price is not None else f" from a series of {len(series or [])} points.")
        shown = {**body, "series": _series_digest(series)} if series is not None else body
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(effect, shown)
    return await _post(path, body)


@mcp.tool(annotations=_EDIT, description=(
    "Set (or remove) one variable O&M row (VOM, 변동 운영비, currency per MWh of ELECTRIC output, >= 0) of the fuel-costs module, sheet RAGNAROK_VariableOM. component Generator | Link; give name (one unit) OR carrier "
    "(every unit of that carrier, a name row beats a carrier row), not both. A Link burning a fuel with a priced supply Generator on bus0 carries VOM x efficiency. remove=true deletes the row. "
    "The unit / carrier must exist in the model. Check with get_fuel_costs."))
async def set_vom(
    component: str,
    vom: float | None = None,
    name: str | None = None,
    carrier: str | None = None,
    remove: bool = False,
    confirm: bool = False,
) -> Any:
    target = {"component": component, **({"name": name} if name else {}), **({"carrier": carrier} if carrier else {})}
    if not remove and vom is None:
        return {"error": "give vom (currency per MWh of electric output, >= 0), or remove=true."}
    body = target if remove else {**target, "vom": vom}
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"{'Remove' if remove else 'Set'} the VOM of {component} {name or carrier!r}" + ("." if remove else f" to {vom:g}."), body)
    return await _post(f"/api/fuel-costs/vom/{'remove' if remove else 'set'}", body)


@mcp.tool(annotations=_EDIT, description=(
    "Set (or remove) how a STOCHASTIC scenario changes a carrier's fuel price (시나리오별 연료 가격: high / low gas), one row of RAGNAROK_FuelPriceScenarios: scenario (the name used in options.stochasticConfig), carrier, "
    "optional snapshot (blank = every snapshot), and price (replaces the price, in unit: MWh_th default or the fuel's native unit) and / or multiplier (scales it, >= 0; 1.3 = +30 %; price applies first). "
    "One row per (scenario, carrier, snapshot): setting it again replaces it; remove=true deletes it. Runs read it when options.stochasticConfig is enabled; get_fuel_costs(stochastic_config=...) previews each scenario."))
async def set_fuel_price_scenario(
    scenario: str,
    carrier: str,
    price: float | None = None,
    multiplier: float | None = None,
    snapshot: str | None = None,
    unit: str = "MWh_th",
    remove: bool = False,
    confirm: bool = False,
) -> Any:
    target = {"scenario": scenario, "carrier": carrier, **({"snapshot": snapshot} if snapshot else {})}
    if not remove and price is None and multiplier is None:
        return {"error": "give a price (replaces the carrier's price in that scenario) or a multiplier (scales it), or both; or remove=true."}
    body = target if remove else {**target, "unit": unit, **({"price": price} if price is not None else {}), **({"multiplier": multiplier} if multiplier is not None else {})}
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"{'Remove' if remove else 'Set'} the fuel price row of scenario {scenario!r}, carrier {carrier!r}.", body)
    return await _post(f"/api/fuel-costs/scenario-price/{'remove' if remove else 'set'}", body)


@mcp.tool(annotations=_EDIT, description=(
    "Set the carbon price (탄소 가격, CO2 price / tax, currency per tCO2) of a saved scenario preset (the module's input): price (currency/tCO2) and optionally a year -> price schedule that supersedes it. "
    "Runs read it on submit_scenario / submit_solve."))
async def set_carbon_price(scenario_id: str, price: float, schedule: list[dict[str, Any]] | None = None, confirm: bool = False) -> Any:
    fields: dict[str, Any] = {"carbonPrice": price}
    if schedule is not None:
        fields["carbonPriceSchedule"] = schedule
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Set the carbon price of scenario {scenario_id!r}.", {"scenario_id": scenario_id, "fields": fields})
    return await get_client().save_scenario(scenario_id, fields, activate=False)


@mcp.tool(annotations=_RO, description=(
    "The annual-budgets sheet (RAGNAROK_AnnualBudgets) and the horizon values the module writes for the model's own horizon: annual x sum(w)/8760 for e_sum_min / "
    "e_sum_max (generators) and the constant of a GlobalConstraint (primary_energy CO2 cap, operational_limit). Pathway: e_sum is one whole-horizon total; a "
    "global constraint with investment_period gets annual x period hours/8760 x years. Returns {rows (the sheet), table (horizon values), notes}. "
    "With run_name (a stored run) it returns instead what that run applied against what the solve achieved: per budget the annual figure, the horizon value, the achieved value read back from the network, "
    "the shadow price (dual) and whether it was binding (예산 달성 여부, 제약 구속)."))
async def get_annual_budgets(pathway_config: dict[str, Any] | None = None, run_name: str | None = None) -> Any:
    client = get_client()
    if run_name:
        return await client._get(f"/api/runs/{quote(run_name, safe='')}/annual-budgets")
    sheet = await client._get("/api/annual-budgets", {"session_id": client.session_id})
    preview = await _post("/api/annual-budgets/preview", {"pathwayConfig": pathway_config})
    return {"sheet": sheet.get("sheet"), "rows": sheet.get("rows", []), **preview}


@mcp.tool(annotations=_EDIT, description=(
    "Cap or floor the annual energy (TWh) or CO2 emissions of a generator or carrier (annual budget). Add or replace one annual budget: component generators | global_constraints, name, attribute e_sum_max | e_sum_min | constant, annual (per year, in the "
    "attribute's unit). The horizon value reaches PyPSA at run time; apply_annual_budgets writes it into the workbook rows."))
async def set_annual_budget(component: str, name: str, attribute: str, annual: float, confirm: bool = False) -> Any:
    body = {"component": component, "name": name, "attribute": attribute, "annual": annual}
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Set the annual budget {component}.{name}.{attribute} = {annual:g}/yr.", body)
    return await _post("/api/annual-budgets/set", body)


@mcp.tool(annotations=_MUT, description=(
    "Write the module's horizon values (annual x sum(w)/8760) into the e_sum / constant cells of the working model, so the workbook shows what PyPSA gets. "
    "Without confirm=true it returns the preview. Re-apply after the snapshots or the horizon change."))
async def apply_annual_budgets(pathway_config: dict[str, Any] | None = None, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        prev = await _post("/api/annual-budgets/preview", {"pathwayConfig": pathway_config})
        return _preview("Write the annual-budget horizon values into the model.", prev)
    return await _post("/api/annual-budgets/apply", {"pathwayConfig": pathway_config})


# Tool areas (see catalogue.py).
declare_areas({
    "get_carbon_price": "policy",
    "get_fuel_costs": "fuel_costs",
    "get_fuel_inputs": "fuel_costs",
    "set_fuel_price": "fuel_costs",
    "set_vom": "fuel_costs",
    "set_fuel_price_scenario": "fuel_costs",
    "set_carbon_price": "policy",
    "get_annual_budgets": "policy",
    "set_annual_budget": "policy",
    "apply_annual_budgets": "policy",
})
