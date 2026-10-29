"""Temporal and operations module tools (core cleanup steps 4 and 5).

Thin wrappers over ``/api/time-units*``, ``/api/model/*`` and ``/api/transform/sample``; nothing here imports ``backend.app``.
Each write is a visible workbook step: the tool says what it changed.

* ``get_time_units``              - read-only: the ``RAGNAROK_TimeUnits`` rows (ramps / UC times in hours or per hour).
* ``preview_time_units``          - read-only: the per-snapshot values a run with these options would write for PyPSA.
* ``set_time_units``              - WRITE (cheap): upsert rows (e.g. min_up_time 4 hours, ramp_limit_up 0.02 per_minute).
* ``set_weightings_from_spacing`` - WRITE (gated, confirm=true): fill the snapshot weightings from the timestamp spacing.
* ``sample_workbook``             - WRITE (gated, confirm=true): test-run sampling written into the workbook.
* ``make_noncyclic_for_rolling``  - WRITE (gated, confirm=true): cyclic storage flags false (rolling refuses cyclic storage).
* ``relax_maintenance``           - WRITE (gated, confirm=true): maintainable = false (Force-LP refuses maintainable units).
* ``get_demand_response``         - read-only: the ``dr_*`` rows the demand-response module would write, and those it wrote.
* ``apply_demand_response``       - WRITE (gated, confirm=true): write those rows into the workbook (a disabled config removes them).
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
    "The ramp and unit-commitment times of the working model, as stated by the user (sheet RAGNAROK_TimeUnits): component generators | links | processes, name, "
    "attribute (ramp_limit_up / _down / _start_up / _shut_down in per_hour or per_minute, a fraction of p_nom; min_up_time / min_down_time / up_time_before / "
    "down_time_before in hours or minutes) and value. PyPSA counts these per SNAPSHOT; the run converts them with the weights it uses."))
async def get_time_units() -> Any:
    client = get_client()
    return await client._get("/api/time-units", {"session_id": client.session_id})


@mcp.tool(annotations=_RO, description=(
    "What a run with these options would write for PyPSA from the time-units rows: per row the stated value, the step in hours (smallest stores weighting) and the "
    "per-snapshot value (ramp = min(1, rate/h x step), blank when >= 1; times = ceil(hours / step)). options may carry rampConfig, samplingConfig, rollingConfig, snapshot window."))
async def preview_time_units(scenario: dict[str, Any] | None = None, options: dict[str, Any] | None = None) -> Any:
    return await _post("/api/time-units/preview", {"scenario": scenario, "options": options})


@mcp.tool(annotations=_EDIT, description=(
    "Set ramp rates and minimum up / down times (hours, minutes, per minute) of generators, links and CCGT units. Upsert rows of RAGNAROK_TimeUnits: each {component, name, attribute, value, unit}. Examples: {component: 'links', name: 'ccgt', attribute: 'min_up_time', value: 4, unit: 'hours'}, "
    "{component: 'generators', name: 'gas1', attribute: 'ramp_limit_up', value: 0.02, unit: 'per_minute'}. replace=true replaces the whole sheet. The conversion to PyPSA's "
    "per-snapshot values happens at solve time with the run's weights."))
async def set_time_units(rows: list[dict[str, Any]], replace: bool = False, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Write {len(rows)} time-unit row(s) (replace={replace}).", {"rows": rows, "replace": replace})
    return await _post("/api/time-units/set", {"rows": rows, "replace": replace})


@mcp.tool(annotations=_MUT, description=(
    "Fill objective / stores / generators of the snapshots sheet from the timestamp spacing (each snapshot weighs the gap to the next; irregular spacing and investment "
    "periods handled). Use it when check_model reports weighting_spacing (a 4-hourly model carries weight 4, or PyPSA books a quarter of the energy). Applied on confirm."))
async def set_weightings_from_spacing(confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        return _preview("Write the snapshot weightings from the timestamp spacing.", {})
    return await _post("/api/model/set-weightings-from-spacing", {})


@mcp.tool(annotations=_MUT, description=(
    "Representative-day sampling for a fast test run, written into the workbook: the sampled snapshots, their weightings (objective/generators = window hours / kept hours, stores unchanged) and "
    "the (averaged) series replace the working model. options.samplingConfig = {enabled: true, mode: count|gap|average, blockSize, blockCount, gapSnapshots, "
    "scaleStartUpCosts} plus an optional snapshotStart/snapshotCount window. Applied on confirm."))
async def sample_workbook(options: dict[str, Any], confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        return _preview("Replace the working model with its sampled test-run version.", {"options": options})
    resp = await _post("/api/transform/sample", {"options": options})
    await get_client().save_model(resp["model"])
    return {"status": "applied", "before": resp.get("before"), "after": resp.get("after"), "factor": resp.get("factor"), "notes": resp.get("notes")}


@mcp.tool(annotations=_MUT, description=(
    "Rolling horizon refuses cyclic storage (each window starts from the previous window's end state). This writes cyclic_state_of_charge / "
    "cyclic_state_of_charge_per_period / e_cyclic / e_cyclic_per_period = false into the working model and lists what changed. Applied on confirm."))
async def make_noncyclic_for_rolling(confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        return _preview("Set every cyclic storage flag to false.", {})
    return await _post("/api/model/make-noncyclic", {})


@mcp.tool(annotations=_MUT, description=(
    "Force-LP is PyPSA's linearized unit commitment and cannot relax scheduled maintenance (no native switch), so a Force-LP run with maintainable units is refused. "
    "This writes maintainable = false on every generator / link / process and lists what changed. Applied on confirm."))
async def relax_maintenance(confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        return _preview("Set maintainable = false on every component.", {})
    return await _post("/api/model/relax-maintenance", {})


_DR_CONFIG = (
    "config = options.demandResponseConfig: {enabled, shiftFraction (0-1 of each load's peak), maxShiftHours, elasticEnabled, elasticFraction, wtpMax, "
    "loads (names; empty = all)}. "
)


@mcp.tool(annotations=_RO, description=(
    "Demand response as workbook rows: what the module would write for a config (shiftable load: bus dr_<load>, link drlink_<load> from the parent bus with "
    "p_nom = peak + buffer, cyclic store drstore_<load> with e_nom = buffer x hours, the load moved onto dr_<load>; price-elastic: generators "
    "load_shedding_elastic_<load>_<k> with a stepped willingness to pay) and the dr_* rows the workbook already has. " + _DR_CONFIG + "Read-only."))
async def get_demand_response(config: dict[str, Any] | None = None, pathway_config: dict[str, Any] | None = None) -> Any:
    return await _post("/api/demand-response/preview", {"config": config, "pathwayConfig": pathway_config})


@mcp.tool(annotations=_MUT, description=(
    "Write the demand-response module's rows into the working model (buses / links / stores / loads / generators / carriers), replacing its previous dr_* "
    "rows; the run then builds what the workbook holds. A config with enabled and elasticEnabled false removes the rows (loads back on their bus). "
    + _DR_CONFIG + "Without confirm=true it returns the preview."))
async def apply_demand_response(config: dict[str, Any] | None = None, pathway_config: dict[str, Any] | None = None, confirm: bool = False) -> Any:
    body = {"config": config, "pathwayConfig": pathway_config}
    if _needs_confirm(cheap=False) and not confirm:
        prev = await _post("/api/demand-response/preview", body)
        return _preview("Write the demand-response rows into the model.", prev)
    return await _post("/api/demand-response/apply", body)


# Tool areas (see catalogue.py).
declare_areas({
    "get_time_units": "time_ops",
    "preview_time_units": "time_ops",
    "set_time_units": "time_ops",
    "set_weightings_from_spacing": "time_ops",
    "sample_workbook": "transforms",
    "make_noncyclic_for_rolling": "time_ops",
    "relax_maintenance": "time_ops",
    "get_demand_response": "policy",
    "apply_demand_response": "policy",
})
