"""Run-spec tools: saved scenarios, the carbon library and the DSL sheet (WA3-WA6).

Registered on the shared ``mcp`` object from :mod:`backend.mcp.server` (one import
line at the end of that file). Thin wrappers over the REST API via
:class:`RagnarokClient`; the preset -> run-body logic lives in the backend
(``backend/app/scenario_presets.py``), so the browser's batch runner and these tools
build identical runs.

Tools (read-only unless noted):

* ``list_scenarios``     - saved presets, the carbon library, the DSL sheet status.
* ``describe_scenario``  - one preset in full plus the exact run body it resolves to.
* ``submit_scenario``    - WRITE/GATE: solve one saved scenario (queues, optionally waits).
* ``submit_scenarios``   - WRITE/GATE: queue several (or all) saved scenarios as a batch.
* ``save_scenario``      - WRITE: create or update a preset (fields merge over the stored one).
* ``set_active_scenario`` / ``delete_scenario`` - WRITE: pick or remove a preset.
* ``set_custom_dsl``     - WRITE: replace the model's custom-constraint DSL sheet.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from mcp.types import ToolAnnotations

from .catalogue import declare_areas
from .server import _MUT, _RO, _needs_confirm, _preview, get_client, mcp, submit_solve

_SUBMIT = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)

_DONE = ("done", "error", "cancelled")


def _carbon_row(profile: dict[str, Any]) -> dict[str, Any]:
    years = [r.get("year") for r in profile.get("schedule") or []]
    return {"id": profile.get("id"), "name": profile.get("name"), "years": years}


@mcp.tool(
    annotations=_RO,
    description="List the model's saved scenario presets (id, label, window, carbon price, enabled study modes, constraint count, model overrides), its carbon-schedule library, and the status of its custom-constraint DSL sheet. Pass an id to submit_scenario / submit_scenarios to run one. 'unreadable' lists scenario rows the browser would silently drop, with the reason.",
)
async def list_scenarios() -> Any:
    client = get_client()
    catalog = await client.list_scenarios()
    library = await client.list_carbon_schedules()
    dsl = await client.get_custom_dsl()
    return {
        **catalog,
        "carbonSchedules": [_carbon_row(p) for p in library.get("schedules", [])],
        "dsl": {
            "sheet": dsl.get("sheet"),
            "lineCount": len(dsl.get("lines", [])),
            "errors": dsl.get("errors", []),
            "generatorCarriers": dsl.get("generatorCarriers", []),
            "note": "The DSL sheet is shared by every scenario and applies when a run carries no constraintSpecs/customDsl of its own.",
        },
    }


@mcp.tool(
    annotations=_RO,
    description="One saved scenario in full (every preset field) and the exact {scenario, options} run body submit_scenario would send. Optional carbon_schedule_id swaps in a library profile; options_patch replaces top-level options keys (see describe_run_options). Does not queue anything.",
)
async def describe_scenario(
    scenario_id: str,
    carbon_schedule_id: str | None = None,
    options_patch: dict[str, Any] | None = None,
) -> Any:
    client = get_client()
    preset = await client.get_scenario(scenario_id)
    body = await client.resolve_scenario(
        scenario_id, carbon_schedule_id=carbon_schedule_id, options_patch=options_patch
    )
    return {**preset, "runBody": {"scenario": body["scenario"], "options": body["options"]}}


async def _resolve(
    scenario_id: str,
    carbon_schedule_id: str | None,
    options_patch: dict[str, Any] | None,
    solver_options: dict[str, Any] | None,
    run_label: str | None,
) -> dict[str, Any]:
    return await get_client().resolve_scenario(
        scenario_id,
        ui_options=solver_options,
        carbon_schedule_id=carbon_schedule_id,
        options_patch=options_patch,
        run_label=run_label,
    )


@mcp.tool(
    annotations=_SUBMIT,
    description="Solve ONE saved scenario exactly as the web UI's scenario run would (preset + the model's DSL sheet + solver defaults) - no hand-built options. Submits to the queue (minutes of compute). carbon_schedule_id: use a carbon-library profile instead of the preset's schedule. options_patch: top-level options keys to replace (validated against describe_run_options). solver_options: filename/solverType/solverThreads/solveAcceptance/objectiveAutoScale/currencySymbol/dateFormat. wait/timeout_s/confirm behave like submit_solve.",
)
async def submit_scenario(
    scenario_id: str,
    carbon_schedule_id: str | None = None,
    options_patch: dict[str, Any] | None = None,
    solver_options: dict[str, Any] | None = None,
    wait: bool = True,
    timeout_s: int = 600,
    confirm: bool = False,
) -> Any:
    body = await _resolve(scenario_id, carbon_schedule_id, options_patch, solver_options, None)
    result = await submit_solve(
        scenario=body["scenario"],
        options=body["options"],
        wait=wait,
        timeout_s=timeout_s,
        confirm=confirm,
    )
    if isinstance(result, dict) and result.get("status") != "preview":
        result = {"scenarioId": scenario_id, "scenarioLabel": body.get("scenarioLabel"), **result}
    return result


def distinct_run_labels(labels: list[str]) -> list[str]:
    """The browser's ``runLabelFor``: a repeated label becomes ``label #2``, ``label #3``."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for label in labels:
        seen[label] = seen.get(label, 0) + 1
        out.append(label if seen[label] == 1 else f"{label} #{seen[label]}")
    return out


@mcp.tool(
    annotations=_SUBMIT,
    description="Queue SEVERAL saved scenarios as a batch (scenario_ids=None or [] runs ALL saved scenarios), one queue job each with a distinct run label, like the UI's 'run scenarios'. Every scenario is resolved and checked first; if any fails, NOTHING is queued. Queue concurrency is global (see the queue tools). wait=false (default) returns the job ids; wait=true polls until all finish or timeout_s, then returns each job's status and run name (read results with get_analytics / compare tools).",
)
async def submit_scenarios(
    scenario_ids: list[str] | None = None,
    carbon_schedule_id: str | None = None,
    options_patch: dict[str, Any] | None = None,
    solver_options: dict[str, Any] | None = None,
    wait: bool = False,
    timeout_s: int = 1800,
    confirm: bool = False,
) -> Any:
    client = get_client()
    catalog = await client.list_scenarios()
    saved = catalog.get("scenarios", [])
    ids = list(scenario_ids or [])
    if not ids:
        ids = [s["id"] for s in saved]
    if not ids:
        return {
            "status": "nothing-to-run",
            "hint": "The model has no saved scenarios (list_scenarios). Use submit_solve for a one-off run.",
        }
    labels_by_id = {s["id"]: s["label"] for s in saved}
    unknown = [i for i in ids if i not in labels_by_id]
    if unknown:
        known = ", ".join(f'"{i}"' for i in labels_by_id) or "none saved"
        raise ValueError(f'unknown scenario id(s) {", ".join(unknown)}; saved scenarios: {known}')
    run_labels = distinct_run_labels([labels_by_id[i] for i in ids])
    bodies = [
        await _resolve(i, carbon_schedule_id, options_patch, solver_options, label)
        for i, label in zip(ids, run_labels, strict=True)
    ]
    # Run the same checks submit would (model validator + pre-run guards) on every
    # body first, so one bad scenario means NOTHING is queued.
    rejected: list[str] = []
    for scenario_id, body in zip(ids, bodies, strict=True):
        report = await client.validate_run(body["scenario"], body["options"])
        if not report.get("valid", True):
            shown = "; ".join(str(e) for e in (report.get("errors") or [])[:3])
            rejected.append(f'"{scenario_id}": {shown}')
    if rejected:
        raise ValueError("nothing was queued; these scenarios would be refused: " + " | ".join(rejected))
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Queue {len(bodies)} scenario solve(s) (minutes of compute each).",
            {"scenarios": [{"id": i, "runLabel": label} for i, label in zip(ids, run_labels, strict=True)]},
        )
    jobs: list[dict[str, Any]] = []
    for scenario_id, label, body in zip(ids, run_labels, bodies, strict=True):
        try:
            submitted = await client.submit_solve(body["scenario"], body["options"])
            jobs.append({"scenarioId": scenario_id, "runLabel": label, "jobId": submitted.get("id"), "queueStatus": submitted.get("status")})
        except Exception as exc:  # noqa: BLE001 - report which one failed, keep the queued ones
            jobs.append({"scenarioId": scenario_id, "runLabel": label, "error": str(exc)})
    queued = [j for j in jobs if j.get("jobId")]
    out: dict[str, Any] = {
        "status": "submitted" if len(queued) == len(jobs) else "partially-submitted",
        "queued": len(queued),
        "total": len(jobs),
        "jobs": jobs,
        "hint": "Poll get_queue; each finished job's run appears in History (get_analytics(run)).",
    }
    if not wait or not queued:
        return out
    deadline = time.monotonic() + max(1, timeout_s)
    pending = {j["jobId"]: j for j in queued}
    while pending and time.monotonic() < deadline:
        await asyncio.sleep(2.0)
        queue = await client.get_queue()
        for item in queue.get("jobs", []):
            job = pending.get(item.get("id"))
            if job is not None and item.get("status") in _DONE:
                job["status"] = item.get("status")
                job["runName"] = item.get("runName")
                if item.get("error"):
                    job["error"] = item.get("error")
                pending.pop(item["id"])
    out["status"] = "done" if not pending else "running"
    out["stillRunning"] = [j["jobId"] for j in pending.values()]
    return out


_EDIT = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


@mcp.tool(
    annotations=_EDIT,
    description=(
        "Create or update a saved scenario preset — the same record the Scenarios panel in the web UI edits. "
        "'fields' merge over the stored preset (a config block such as pathwayConfig replaces the stored block "
        "whole); a new id starts from the defaults. Allowed fields: label, notes, snapshotStart, snapshotEnd, "
        "snapshotWeight (must stay 1: resolution is the workbook's, see temporal_cluster), carbonPrice, carbonPriceSchedule, discountRate, forceLp, enableLoadShedding, "
        "loadSheddingCost, ownerColumn, constraints, modelOverrides and every *Config block — see "
        "describe_run_options(key='scenario') / (key='options.<block>') for their fields. activate=true makes it "
        "the model's active scenario. Run it with submit_scenario."
    ),
)
async def save_scenario(
    scenario_id: str,
    fields: dict[str, Any] | None = None,
    activate: bool = False,
    confirm: bool = False,
) -> Any:
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(
            f"Save scenario {scenario_id!r}{' and make it active' if activate else ''}.",
            {"scenario_id": scenario_id, "fields": fields or {}, "activate": activate},
        )
    return await get_client().save_scenario(scenario_id, fields or {}, activate=activate)


@mcp.tool(
    annotations=_EDIT,
    description="Make a saved scenario the model's active one (the preset the web UI loads its run controls from).",
)
async def set_active_scenario(scenario_id: str, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Make scenario {scenario_id!r} active.", {"scenario_id": scenario_id})
    return await get_client().activate_scenario(scenario_id)


@mcp.tool(
    annotations=_MUT,
    description="Remove a saved scenario preset from the model (stored runs are untouched). Re-call with confirm=true to apply.",
)
async def delete_scenario(scenario_id: str, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"Delete scenario {scenario_id!r}.", {"scenario_id": scenario_id})
    return await get_client().delete_scenario(scenario_id)


@mcp.tool(
    annotations=_EDIT,
    description=(
        "Add custom constraints, e.g. a CO2 emissions cap or a generation limit per carrier: replace the model's custom-constraint DSL sheet (RAGNAROK_CustomDSL) — one constraint per line, e.g. "
        "'gen(\"gas\") <= 120' or 'emissions() <= 5000'. Lines are parsed with the solver's own parser and the "
        "save is refused if any line does not parse (allow_errors=true saves anyway; such a sheet then blocks "
        "runs that use it). An empty text clears the sheet. The sheet applies to runs that carry no "
        "constraintSpecs/customDsl of their own."
    ),
)
async def set_custom_dsl(text: str, allow_errors: bool = False, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=True) and not confirm:
        return _preview("Replace the custom-constraint DSL sheet.", {"text": text, "allow_errors": allow_errors})
    return await get_client().set_custom_dsl(text, allow_errors=allow_errors)


# Tool areas (see catalogue.py).
declare_areas({
    "list_scenarios": "run",
    "describe_scenario": "run",
    "submit_scenario": "run",
    "submit_scenarios": "run",
    "save_scenario": "run",
    "set_active_scenario": "run",
    "delete_scenario": "run",
    "set_custom_dsl": "policy",
})
