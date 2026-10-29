"""Build plant tools: a plant-type catalogue, add / edit / remove one plant as a unit, and results grouped by plant.

Registered on the shared ``mcp`` object from :mod:`backend.mcp.server` (one import line at the end of that file). Thin
wrappers over ``/api/build/plant*`` through the :class:`RagnarokClient`; nothing here imports ``backend.app``.

Tools:

* ``list_plant_types`` - read-only: the plant types (generator, bess, ccgt, ocgt, cofiring_simple, cofiring_network, p2x),
  their fields with defaults and units, and the technology data sources.
* ``add_plant``        - WRITE (gated, confirm=true): build a plant (bus + capacity + a few fields) into the working model.
* ``edit_plant``       - WRITE (gated, confirm=true): re-derive a plant's components from its stored spec plus a patch.
* ``remove_plant``     - WRITE (gated, confirm=true): delete all of a plant's components and nothing else.
* ``get_plant_results``- read-only: results of a stored run grouped by plant (generation, capacity factor, fuel, H2 share, avoided CO2, starts).

The H2 blend-share limits of the fuel-network plants are a run option (``options.cofiringConfig``): pass it to ``submit_solve``;
``describe_run_options(key="options.cofiringConfig")`` documents every field. The existing ``add_conversion`` tool is unchanged.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .catalogue import declare_areas
from .server import _MUT, _RO, _needs_confirm, _preview, get_client, mcp


async def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    client = get_client()
    return await client._post(path, {"sessionId": client.session_id, **body})


def _trim(res: dict[str, Any]) -> dict[str, Any]:
    keep = ("applied", "plantId", "type", "rowCounts", "removed", "kept", "summary", "warnings", "spec")
    return {k: res.get(k) for k in keep if k in res}


@mcp.tool(
    annotations=_RO,
    description=(
        "List the plant types add_plant accepts (CCGT, OCGT gas turbine, BESS battery, generator, gas + hydrogen co-firing, P2X) with fields, defaults and units. Plant types Build can add as ONE unit: generator, bess (battery StorageUnit), ccgt, ocgt (gas turbines with DEA / technology-data cost, "
        "efficiency, minimum load, start-up cost and unit commitment when committable, plus opt-in advanced fields for a committable unit of fixed size: minLoadEfficiency (part-load efficiency: no-load fuel + incremental heat rate), startCostHot / startCostWarm / startCostCold with startWarmAfterHours / startColdAfterHours (start cost by offline time, run through a plants-module constraint) and startUpMinutes / shutDownMinutes (PyPSA ramp_limit_start_up / _shut_down); the ramp rate (per minute) and the minimum up / down times (hours) are written to RAGNAROK_TimeUnits and converted for the run's snapshot weights at solve time, see get_time_units), cofiring_simple (one generator burning a fixed gas / H2 blend: "
        "cost and CO2 factor from the share), cofiring_network (gas bus + H2 bus -> fuel bus -> turbine, blend limited by options.cofiringConfig or the plant's "
        "blendMin / blendMax) and p2x (electrolyser chain). Each entry lists its fields (key, label, unit, default, advanced) and defaults. Every plant needs a bus and a "
        "capacity (pNom MW, or extendable=true); the rest defaults from the technology data (value, unit, source, verified flag: file | derived | literature | assumption)."
    ),
)
async def list_plant_types(include_technologies: bool = False) -> Any:
    client = get_client()
    out = await client._get("/api/build/plant/types")
    if include_technologies:
        out["technologies"] = await client._get("/api/build/plant/technologies")
    return out


@mcp.tool(
    annotations=_MUT,
    description=(
        "Add a CCGT, OCGT gas turbine (가스터빈), BESS battery (배터리), plain generator, gas + hydrogen co-firing or P2X plant to the model as one unit, with part-load, ramp and start-up characteristics. type (see list_plant_types), bus, capacity and the type's fields in a flat spec, e.g. "
        "{'plantId': 'unit1', 'bus': 'grid', 'pNom': 400, 'committable': true} for a ccgt, or {'pNom': 400, 'committable': true, 'minLoadEfficiency': 0.52, 'startCostWarm': 90, 'startWarmAfterHours': 8, 'startCostCold': 130, 'startColdAfterHours': 48} for a ccgt with part-load efficiency and hot / warm / cold start costs (the preview lists the derived values), or {'turbine': 'ccgt', 'h2Share': 0.3, 'h2ShareUnit': 'vol'} for cofiring_simple, "
        "or {'turbine': 'ccgt', 'blendMax': 0.3, 'blendUnit': 'vol', 'blendScope': 'hourly'} for cofiring_network. Every component it creates carries the plant id in its "
        "`plant` column. Without confirm=true it returns the preview of what would be merged."
    ),
)
async def add_plant(type: str, spec: dict[str, Any] | None = None, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        prev = await _post("/api/build/plant", {"type": type, "spec": spec or {}, "apply": False})
        return _preview(f"Add a {type} plant to the working model.", _trim(prev))
    return _trim(await _post("/api/build/plant", {"type": type, "spec": spec or {}, "apply": True}))


@mcp.tool(
    annotations=_MUT,
    description=(
        "Edit a CCGT / OCGT / BESS battery / co-firing plant (change capacity, bus, efficiency, hydrogen share). 'spec' is a patch laid over the plant's stored spec, and ALL its components are re-derived (old rows removed, new ones merged); buses and "
        "carriers other components use are kept. A plant imported without a registry row cannot be edited (remove it and add it again). Without confirm=true it "
        "returns the preview."
    ),
)
async def edit_plant(plant_id: str, spec: dict[str, Any], confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        prev = await _post("/api/build/plant/edit", {"plantId": plant_id, "spec": spec, "apply": False})
        return _preview(f"Re-derive plant {plant_id!r} with the given changes.", _trim(prev))
    return _trim(await _post("/api/build/plant/edit", {"plantId": plant_id, "spec": spec, "apply": True}))


@mcp.tool(
    annotations=_MUT,
    description=(
        "Remove a CCGT / OCGT / BESS battery / co-firing plant. Deletes every component carrying its plant id (generators, links, processes, stores, loads, the registry row and the buses / carriers only "
        "it uses) and nothing else; a bus or carrier another component still references is kept and released from the plant. Without confirm=true it returns the preview."
    ),
)
async def remove_plant(plant_id: str, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        prev = await _post("/api/build/plant/delete", {"plantId": plant_id, "apply": False})
        return _preview(f"Remove plant {plant_id!r} and its components.", _trim(prev))
    return _trim(await _post("/api/build/plant/delete", {"plantId": plant_id, "apply": True}))


@mcp.tool(
    annotations=_RO,
    description=(
        "Results of a stored run grouped by plant id (server-side groupby): per plant the generation, capacity factor, full-load hours, starts (solved for committable units), "
        "operating / fixed / total cost (plus startCosts: starts by hot / warm / cold and what they cost, and standByCost, for a plant that uses those fields), revenue at the bus price and, for gas turbines and co-firing, the gas and H2 fuel use, the H2 share per hour (energy % and vol % "
        "equivalent), the CO2 emitted and the CO2 avoided against the same dispatch on 100 % gas; BESS charge / discharge and cycles; P2X LCOH. plant_id narrows to one. "
        "Per-snapshot series are omitted unless include_series=true."
    ),
)
async def get_plant_results(run_name: str, plant_id: str | None = None, period: int | None = None, include_series: bool = False) -> Any:
    res = await get_client()._get(
        f"/api/build/plant/results/{quote(run_name, safe='')}", {"plant": plant_id, "period": period, "include_series": str(bool(include_series)).lower()})
    if not include_series and isinstance(res, dict):
        res["seriesHint"] = "Per-snapshot series omitted; call with include_series=true to get them."
    return res


# Tool areas (see catalogue.py).
declare_areas({
    "list_plant_types": "composites",
    "add_plant": "composites",
    "edit_plant": "composites",
    "remove_plant": "composites",
    "get_plant_results": "composites",
})
