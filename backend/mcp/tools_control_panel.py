"""Control-panel module tools: switch PyPSA attributes (ramps, UC times, committable, ...) off for a filtered set of
components while the workbook keeps its values. Thin wrappers over ``/api/control-panel*``; nothing here imports
``backend.app``.

* ``get_control_switches``     - read-only: the project's rules, the components / columns / attributes, and what each rule selects.
* ``preview_control_switches`` - read-only: the same preview for a rule list that is not saved.
* ``get_column_values``        - read-only: the distinct values of a column of a component sheet (to build a filter).
* ``set_control_switches``     - WRITE (cheap): store the rule list in the project; the next run applies it.
"""
from __future__ import annotations

from typing import Any

from .catalogue import declare_areas
from .server import _RO, _needs_confirm, _preview, get_client, mcp
from .tools_runspec import _EDIT

_RULE = (
    "A rule = {id, component (generators | links | processes | storage_units | ...), attributes (PyPSA input attributes, or a group: "
    "ramps, ramp_up_down, ramp_start_shut, uc_times, unit_commitment, min_load), column (the filter column, e.g. carrier, or any "
    "column of the sheet), values (the column values it selects; [] = every row), on (true = leave the model as it is; false = the "
    "attributes of the selected rows take PyPSA's default in the run's copy: blank ramp, committable false, p_min_pu 0; their "
    "time-series column and RAGNAROK_TimeUnits rows are dropped), label}. The workbook values are never changed."
)


async def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    client = get_client()
    return await client._post(path, {"sessionId": client.session_id, **body})


@mcp.tool(annotations=_RO, description=(
    "The control panel: switch rules that turn constraints such as ramp limits off for a filtered set of components without "
    "deleting their values. Returns the project's rules, the attribute groups, each component sheet with its columns and input "
    "attributes, and per rule the rows it selects and what switching it off changes. " + _RULE))
async def get_control_switches() -> Any:
    client = get_client()
    return await client._get("/api/control-panel", {"session_id": client.session_id})


@mcp.tool(annotations=_RO, description=(
    "Preview a control-panel rule list without saving it: per rule the matched names and the cells, time-series columns and "
    "time-unit rows switching it off changes, and the notes a run would carry. " + _RULE))
async def preview_control_switches(rules: list[dict[str, Any]]) -> Any:
    return await _post("/api/control-panel/preview", {"rules": rules})


@mcp.tool(annotations=_RO, description=(
    "Distinct values of one column of a component sheet with their row counts, e.g. component='generators', column='carrier', "
    "to choose the values of a control-panel filter."))
async def get_column_values(component: str, column: str) -> Any:
    return await _post("/api/control-panel/values", {"component": component, "column": column})


@mcp.tool(annotations=_EDIT, description=(
    "Store the control-panel rule list in the project (replaces the list; open GUIs re-apply it). Each run then applies the rules "
    "switched off (on=false) to its own copy of the model and lists them in its notes. Example: switch every ramp off for coal and gas "
    "generators: [{id: 'r1', component: 'generators', attributes: ['ramps'], column: 'carrier', values: ['coal', 'gas'], on: false}]. "
    + _RULE))
async def set_control_switches(rules: list[dict[str, Any]], confirm: bool = False) -> Any:
    if _needs_confirm(cheap=True) and not confirm:
        prev = await _post("/api/control-panel/preview", {"rules": rules})
        return _preview(f"Store {len(rules)} control-panel rule(s) in the project.", prev)
    return await _post("/api/control-panel/set", {"rules": rules})


declare_areas({
    "get_control_switches": "time_ops",
    "preview_control_switches": "time_ops",
    "get_column_values": "time_ops",
    "set_control_switches": "time_ops",
})
