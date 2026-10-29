"""Carbon-pricing and annual-budgets module tools.

Thin wrappers over ``/api/carbon-price/*``, ``/api/annual-budgets/*`` and the scenario presets; nothing here imports ``backend.app``.

* ``get_carbon_price``   - read-only: the module's per-generator adder for a price / schedule on the working model.
* ``set_carbon_price``   - WRITE (cheap, gated by autonomy): the scenario preset's carbonPrice / carbonPriceSchedule.
* ``get_annual_budgets`` - read-only: the budget rows and the horizon values the module would write.
* ``set_annual_budget``  - WRITE (cheap): add / replace one annual budget row.
* ``apply_annual_budgets`` - WRITE (gated, confirm=true): write the horizon values into the component rows.
"""
from __future__ import annotations

from typing import Any

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
    "global constraint with investment_period gets annual x period hours/8760 x years."))
async def get_annual_budgets(pathway_config: dict[str, Any] | None = None) -> Any:
    return await _post("/api/annual-budgets/preview", {"pathwayConfig": pathway_config})


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
    "set_carbon_price": "policy",
    "get_annual_budgets": "policy",
    "set_annual_budget": "policy",
    "apply_annual_budgets": "policy",
})
