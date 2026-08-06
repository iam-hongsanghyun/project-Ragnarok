"""Bifrost MCP server — Ragnarok's tool catalog for any MCP-capable agent.

Read-only tools run freely. Mutating / expensive / live-network tools are
"GATE" tools: under the ``RAGNAROK_MCP_AUTONOMY`` guard they return a *preview*
unless called with ``confirm=true`` (see ``_needs_confirm``). Build/transform
tools that the API returns *without persisting* are applied back into the
session here, so their effect shows up live in the Ragnarok web UI.

Everything is a thin wrapper over the REST API via :class:`RagnarokClient`; this
module imports nothing from ``backend.app``.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .client import RagnarokClient

_INSTRUCTIONS = (
    "Drive a PyPSA power-system model in Ragnarok: introspect the loaded model, "
    "import/build data, edit and transform sheets, solve, and read results. "
    "Read-only tools are safe to call freely. Mutating tools (imports, edits, "
    "transforms, solves) may return a preview asking you to re-call with "
    "confirm=true — that is the human-in-the-loop guard, not an error. All tools "
    "act on one shared working session, visible live in the Ragnarok web UI.\n\n"
    "Solve-mode analytics: seven reliability/market studies (reserves, "
    "forced-outage Monte Carlo, ramping, correlated sampling, ELCC, "
    "convergence sampling, LMP decomposition) ride the same solve — call "
    "describe_analytics for their option keys, config fields and where each "
    "lands in get_analytics(run), then enable them via submit_solve's options.\n\n"
    "Physical risk: a separate climate-damage subsystem with its OWN "
    "server-minted session id. Workflow: physical_risk_seed (build a portfolio "
    "from the current model) -> optional physical_risk_set_scenario (perils, "
    "climate, horizon) -> physical_risk_run (polls to completion) -> "
    "physical_risk_transition / physical_risk_finance / physical_risk_report for "
    "the results. Every physical_risk_* tool defaults to the seeded session."
)

# ── shared client (created in lifespan; lazily in tests / introspection) ────────
_client: RagnarokClient | None = None


def get_client() -> RagnarokClient:
    global _client
    if _client is None:
        _client = RagnarokClient()
    return _client


@asynccontextmanager
async def _lifespan(_server: FastMCP):
    global _client
    _client = RagnarokClient()
    try:
        yield {}
    finally:
        await _client.aclose()
        _client = None


mcp = FastMCP("ragnarok", instructions=_INSTRUCTIONS, lifespan=_lifespan)

_RO = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
# Shared annotation for in-session mutating tools (edits, transforms, model
# swaps). Live-network and physical-risk tools keep their own inline annotations.
_MUT = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
)


# ── autonomy guard ──────────────────────────────────────────────────────────────
def _autonomy() -> str:
    lvl = os.environ.get("RAGNAROK_MCP_AUTONOMY", "guided").lower()
    return lvl if lvl in ("auto", "guided", "manual") else "guided"


def _needs_confirm(cheap: bool) -> bool:
    """Whether a GATE tool must be called with confirm=true first.

    auto → never; manual → always; guided (default) → only non-cheap tools
    (imports, transforms, solves) — cheap in-session edits run.
    """
    lvl = _autonomy()
    if lvl == "auto":
        return False
    if lvl == "manual":
        return True
    return not cheap  # guided


def _fragment_sheets(resp: dict[str, Any]) -> dict[str, Any]:
    """A build/transform response's sheets, INCLUDING its snapshot axis.

    The renewable-profile / hydro-inflow endpoints return ``snapshots`` (a list
    of labels) alongside ``sheets``; the GUI applies both. Dropping it leaves the
    new 8760-row profile spanning a window the ``snapshots`` sheet doesn't cover
    — a silent index mismatch at solve time.
    """
    sheets = dict(resp.get("sheets") or {})
    snapshots = resp.get("snapshots")
    if isinstance(snapshots, list) and snapshots:
        sheets["snapshots"] = [{"snapshot": s} for s in snapshots]
    return sheets


def _preview(effect: str, would_send: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "preview",
        "effect": effect,
        "wouldSend": would_send,
        "autonomy": _autonomy(),
        "confirmHint": "Re-invoke this tool with confirm=true to apply.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Introspect / read-only — safe to call freely
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool(
    annotations=_RO,
    description="List the data-import sources Ragnarok knows, with their per-country datasets and filters.",
)
async def list_importers() -> Any:
    return await get_client().list_importers()


@mcp.tool(
    annotations=_RO,
    description="Which upstream data sources are reachable right now. Optional comma-separated 'sources' to filter.",
)
async def source_health(sources: str | None = None) -> Any:
    return await get_client().source_health(sources)


@mcp.tool(
    annotations=_RO,
    description="What's loaded in the working session: buses, carriers, snapshot window, sheet list and sizes. Empty {} if nothing is loaded.",
)
async def get_world_state() -> Any:
    meta = await get_client().get_meta()
    return meta or {"loaded": False}


@mcp.tool(
    annotations=_RO,
    description="Return one page of a sheet's rows (static or time-series). Use offset/limit to page — never dump a whole 8760-row sheet.",
)
async def get_sheet_page(name: str, offset: int = 0, limit: int = 100) -> Any:
    return await get_client().get_sheet_page(name, offset=offset, limit=limit)


@mcp.tool(
    annotations=_RO,
    description="Derive a chart-ready series from a sheet, computed server-side. mode ∈ duration | daily_profile | grouped. duration/grouped need 'column'; grouped needs 'group_by'.",
)
async def derive_series(
    name: str,
    mode: str,
    column: str | None = None,
    columns: str | None = None,
    group_by: str | None = None,
    agg: str = "sum",
    max_points: int = 800,
) -> Any:
    return await get_client().derive_series(
        name,
        mode,
        column=column,
        columns=columns,
        groupBy=group_by,
        agg=agg,
        maxPoints=max_points,
    )


@mcp.tool(
    annotations=_RO,
    description="List stored solve runs (newest first) with their names and metadata.",
)
async def list_runs() -> Any:
    return await get_client().list_runs()


@mcp.tool(
    annotations=_RO,
    description="Full analytics for a stored run: summary, carrier mix, cost, emissions, adequacy. Cite these numbers in reports rather than composing figures.",
)
async def get_analytics(run_name: str) -> Any:
    return await get_client().get_analytics(run_name)


@mcp.tool(
    annotations=_RO,
    description="List the report perspectives (policy maker, investor, PPA buyer, lender, procurement) with their audience and section outline. A perspective defines which sections a report contains and the key question each answers.",
)
async def list_report_perspectives() -> Any:
    return await get_client().list_report_perspectives()


@mcp.tool(
    annotations=_RO,
    description="Assemble the deterministic report document for a stored run under a perspective (run_name may be 'latest'). Sections carry KPI, chart, table and templated-narrative blocks read verbatim from the stored solve payload. When authoring prose around a report, keep every figure exactly as this document states it — write narrative, never numbers.",
)
async def get_report(run_name: str, perspective: str) -> Any:
    return await get_client().get_report(run_name, perspective)


@mcp.tool(
    annotations=_RO,
    description="A specific derived metric for a stored run (e.g. dispatch_by_carrier, duration curve). Windowed + downsampled.",
)
async def get_derived(
    run_name: str,
    metric: str,
    start: int = 0,
    end: int | None = None,
    max_points: int | None = None,
) -> Any:
    params: dict[str, Any] = {"start": start}
    if end is not None:
        params["end"] = end
    if max_points is not None:
        params["maxPoints"] = max_points
    return await get_client().get_derived(run_name, metric, **params)


@mcp.tool(
    annotations=_RO,
    description="The solve queue: jobs with their status (queued/running/done/error) and concurrency settings. Use to watch a submitted solve.",
)
async def get_queue() -> Any:
    return await get_client().get_queue()


@mcp.tool(
    annotations=_RO,
    description="List every PyPSA component type Ragnarok supports (Bus, Generator, Line, Link, Transformer, StorageUnit, Store, Carrier, GlobalConstraint, …) with its sheet name and attribute count — the full registry, not a curated subset.",
)
async def list_components() -> Any:
    comps = (await get_client().get_config()).get("schema", {}).get("components", {})
    return [
        {
            "component": spec.get("component_name") or sheet,
            "sheet": sheet,
            "label": spec.get("label"),
            "attributes": len(spec.get("attributes", []) or []),
        }
        for sheet, spec in comps.items()
    ]


@mcp.tool(
    annotations=_RO,
    description="Describe a PyPSA component's full attribute schema (name, type, unit, default, required, description). Accepts a component name or sheet name (e.g. 'Generator' or 'generators'). Use before add_component/set_component to know valid attributes.",
)
async def describe_component(component: str) -> Any:
    client = get_client()
    sheet = await client.resolve_sheet(component)
    spec = (await client.get_config())["schema"]["components"][sheet]
    return {
        "component": spec.get("component_name") or sheet,
        "sheet": sheet,
        "label": spec.get("label"),
        "attributes": spec.get("attributes", []),
    }


@mcp.tool(
    annotations=_RO,
    description="All solve knobs available: backend capabilities (carbon price, multi-year pathway, rolling horizon, stochastic, SCLOPF, power flow, market simulation, MGA, …) and the simulation defaults. These are the keys you pass to submit_solve's scenario/options. For the seven reliability/market analytics (reserves, outage-MC, ramp, correlated sampling, ELCC, convergence, LMP decomposition) call describe_analytics.",
)
async def describe_run_options() -> Any:
    cfg = await get_client().get_config()
    return {
        "capabilities": cfg.get("capabilities"),
        "simulation_defaults": cfg.get("simulation_defaults"),
    }


@mcp.tool(
    annotations=_RO,
    description="List installed plugins and their ids/config. Run one with run_plugin_analysis (read-only analyze), run_plugin_transform (rewrite the model) or run_plugin_contribute (merge sheets/constraints).",
)
async def list_plugins() -> Any:
    return await get_client().list_plugins()


# ══════════════════════════════════════════════════════════════════════════════
# Tab-modules — a whole Ragnarok TAB, not a plugin (docs/module.md).
#
# A plugin is a small extension (importer / panel / analytics hook). A MODULE is
# big: its own tab, with the same reach a native tab has (read the model, submit
# solves, read analytics). Built-in modules (Data, Forge, Physical Risk, Siting,
# Post-analysis, Training) are compiled into the app and toggled in Settings →
# Modules; these tools manage the THIRD-PARTY ones, which live on the server
# under backend/data/modules/ so they belong to the project.
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool(
    annotations=_RO,
    description="List third-party tab-modules installed on the server: id, label, activity-bar order, whether the tab is shown, and the package's files. A tab-module is a whole tab (see install_tab_module); plugins are separate — use list_plugins.",
)
async def list_tab_modules() -> Any:
    modules = await get_client().list_tab_modules()
    # Drop file BODIES from the listing — a module's source can be large and an
    # agent listing modules wants the inventory, not the code.
    out = []
    for m in (modules or {}).get("modules", []):
        manifest = m.get("manifest") or {}
        out.append({
            "id": manifest.get("id"),
            "label": manifest.get("label"),
            "description": manifest.get("description"),
            "order": manifest.get("order"),
            "entry": manifest.get("entry"),
            "enabled": m.get("enabled"),
            "files": sorted((m.get("files") or {}).keys()),
            "installedAt": m.get("installedAt"),
        })
    return {"modules": out}


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    description=(
        "Install a third-party tab-module from a DIRECTORY on this machine — it becomes a new tab in the web UI. "
        "The directory needs `tabmodule.json` ({id, label, hint?, description?, order?, entry?}) and a CommonJS entry "
        "file exporting `mount(el, ctx)`; ctx gives {apiBase, sessionId}, i.e. the whole Ragnarok HTTP API, so the "
        "module can read the model, submit solves and read analytics like a native tab. Installing the same id again "
        "updates it in place and keeps its shown/hidden state. Ids that collide with a core tab or a built-in module "
        "are refused."
    ),
)
async def install_tab_module(path: str, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"Install the tab-module at {path} (adds a tab to the web UI).", {"path": path})
    installed = await get_client().install_tab_module(path)
    manifest = (installed or {}).get("manifest") or {}
    return {
        "status": "installed",
        "id": manifest.get("id"),
        "label": manifest.get("label"),
        "enabled": (installed or {}).get("enabled"),
        "files": sorted(((installed or {}).get("files") or {}).keys()),
        "hint": "The tab appears on the activity bar; reload the browser tab if it is already open.",
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    description="Show or hide an installed tab-module's tab. Persisted on the server, so it survives a browser cache clear or an app update. Does not uninstall anything.",
)
async def set_tab_module_enabled(module_id: str, enabled: bool, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(
            f"{'Show' if enabled else 'Hide'} the {module_id!r} tab.",
            {"module_id": module_id, "enabled": enabled},
        )
    return await get_client().set_tab_module_enabled(module_id, enabled)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
    description="Uninstall a third-party tab-module: deletes its package directory on the server and removes its tab. The model, settings, run history and results are untouched.",
)
async def remove_tab_module(module_id: str, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"Uninstall the tab-module {module_id!r} (deletes its files).", {"module_id": module_id})
    return await get_client().remove_tab_module(module_id)


# ── curated reference for the seven solve-mode reliability/market analytics ────
# submit_solve already passes arbitrary `options` through unchanged, so these
# ride the same solve — this tool is pure discovery: it tells an agent the
# analytics exist, the option key that enables each, its main config fields, and
# where its result lands in get_analytics(run). Field lists mirror the frontend
# TS config interfaces (lib/types/index.ts); kept concise, not exhaustive.
_ANALYTICS_REFERENCE: list[dict[str, Any]] = [
    {
        "optionKey": "reserveConfig",
        "resultKey": "reserve",
        "purpose": "Operating-reserve co-optimization — units keep headroom to cover a contingency; surfaces a reserve price alongside the energy price.",
        "config": {
            "enabled": "bool",
            "requirementType": "'fraction' | 'largestUnit' | 'both'",
            "fraction": "share of demand held as spinning reserve (0.1 = 10%)",
            "providers": "'all' | 'thermal' (thermal excludes variable renewables)",
            "reserveCost": "currency/MW added to the objective (usually 0)",
        },
    },
    {
        "optionKey": "outageMcConfig",
        "resultKey": "outageMc",
        "purpose": "Thermal forced-outage Monte Carlo — samples random up/down states (EFOR + repair time) across synthetic years; reports the LOLE / EUE distribution.",
        "config": {
            "enabled": "bool",
            "nMembers": "Monte-Carlo samples (synthetic years)",
            "seed": "int",
            "forcedOutageRate": "EFOR fallback when a generator has no explicit rate",
            "mttrHours": "mean time to repair, hours",
            "includeRenewableEnsemble": "bool",
            "physicalRiskUplift": "bool — raise each generator's FOR by its Physical Risk portfolio damage ratio before sampling",
            "physicalRiskSessionId": "Physical Risk session id to source the damage ratios from (see the physical_risk_* tools)",
        },
    },
    {
        "optionKey": "rampConfig",
        "resultKey": "ramp",
        "purpose": "Timestep-weighted ramp-rate limits — bounds how fast each unit's output can change between snapshots (|Δp| ≤ ramp% × p_nom × hours).",
        "config": {
            "enabled": "bool",
            "rampLimitUp": "max upward ramp, fraction of p_nom per hour (0.5 = 50%/h)",
            "rampLimitDown": "max downward ramp, fraction of p_nom per hour",
            "appliesTo": "'all' | 'thermal' (thermal excludes variable renewables)",
        },
    },
    {
        "optionKey": "correlatedSamplingConfig",
        "resultKey": "correlatedSampling",
        "purpose": "Correlated multi-driver Monte Carlo — a common weather stress pushes demand up while renewable output and hydro inflow drop together (cold-calm event).",
        "config": {
            "enabled": "bool",
            "nMembers": "Monte-Carlo samples (synthetic years)",
            "seed": "int",
            "loadSensitivity": "demand sensitivity to the common stress factor",
            "renewableSensitivity": "renewable-output sensitivity to the stress factor",
            "inflowSensitivity": "hydro-inflow sensitivity to the stress factor",
            "loadStd": "idiosyncratic demand noise, std dev",
            "renewableStd": "idiosyncratic renewable noise, std dev",
            "inflowStd": "idiosyncratic hydro-inflow noise, std dev",
        },
    },
    {
        "optionKey": "elccConfig",
        "resultKey": "elcc",
        "purpose": "Effective Load-Carrying Capability (capacity credit) — the firm MW each resource can replace at equal reliability (LOLE), by binary search on the outage-inclusive LOLE.",
        "config": {
            "enabled": "bool",
            "nMembers": "Monte-Carlo samples for the outage-inclusive LOLE",
            "seed": "int",
            "forcedOutageRate": "EFOR fallback when a generator has no explicit rate",
            "mttrHours": "mean time to repair, hours",
            "carriers": "carriers to evaluate; empty = auto (variable renewables + storage)",
        },
    },
    {
        "optionKey": "convergenceConfig",
        "resultKey": "convergenceSampling",
        "purpose": "Convergence-controlled sampling — draws the forced-outage Monte Carlo in batches until the target metric's standard error falls below a tolerance; optional maintenance placement.",
        "config": {
            "enabled": "bool",
            "targetMetric": "'eue' | 'lole'",
            "tolerance": "relative standard error at which sampling stops",
            "batchSize": "samples drawn per batch",
            "maxMembers": "hard cap on total samples even if not converged",
            "seed": "int",
            "forcedOutageRate": "EFOR fallback when a generator has no explicit rate",
            "mttrHours": "mean time to repair, hours",
            "maintenanceEnabled": "bool — schedule planned outages into low-load windows",
            "maintenanceWeeks": "length of each planned maintenance outage, weeks",
            "maintenanceCarriers": "carriers to schedule maintenance for; empty = auto",
        },
    },
    {
        "optionKey": "lmpDecompositionConfig",
        "resultKey": "lmpDecomposition",
        "purpose": "LMP decomposition — splits each bus's locational marginal price into energy vs congestion components and reports congestion rent per line/link. Post-process only; does not change the solve.",
        "config": {
            "enabled": "bool",
            "referenceMode": "'load-weighted' | 'min' | 'bus'",
            "referenceBus": "bus used as the energy-price reference (only when referenceMode == 'bus')",
        },
    },
]


@mcp.tool(
    annotations=_RO,
    description="The seven solve-mode reliability/market analytics (reserves, forced-outage Monte Carlo, ramping, correlated sampling, ELCC, convergence sampling, LMP decomposition): for each, the options.* key that enables it, its purpose, key config fields, and where its result lands in get_analytics(run). Enable them via submit_solve's options; no separate call.",
)
async def describe_analytics() -> Any:
    return {
        "note": (
            "Enable any of these by passing options.<optionKey> = {enabled: true, ...} "
            "to submit_solve, then read get_analytics(run).<resultKey>. submit_solve "
            "already forwards arbitrary options unchanged, so no extra step is needed."
        ),
        "analytics": _ANALYTICS_REFERENCE,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Model edits — GATE (mutating). edit_sheet is a "cheap" in-session edit.
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
    description="Edit a sheet in the working session. ops is a list applied in order: {op:'set',row,column,value}, {op:'addRow',values,index?}, {op:'deleteRows',rows:[...]}. Guarded when autonomy=manual.",
)
async def edit_sheet(
    name: str, ops: list[dict[str, Any]], confirm: bool = False
) -> Any:
    client = get_client()
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(
            f"Apply {len(ops)} edit op(s) to sheet {name!r}.",
            {"name": name, "ops": ops},
        )
    return await client.patch_sheet(name, ops)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ),
    description="Regenerate the snapshot index over [start,end] at step_hours and reindex every temporal sheet onto it. fill: 'tile' (cycle) or 'pad' (repeat last). Dates like '2030-01-01'.",
)
async def retarget_snapshots(
    start: str,
    end: str,
    step_hours: float = 1.0,
    fill: str = "tile",
    confirm: bool = False,
) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Retarget snapshots to [{start}, {end}] @ {step_hours}h (fill={fill}).",
            {"start": start, "end": end, "stepHours": step_hours, "fill": fill},
        )
    return await client.retarget_snapshots(start, end, step_hours, fill)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ),
    description="Project demand to a future year. method: cagr|linear (apply growth_pct) or regression|arima|prophet (fit trend, needs ≥3y history). grow_sheets defaults to demand.",
)
async def forecast_demand(
    from_year: int,
    to_year: int,
    growth_pct: float = 0.0,
    method: str = "cagr",
    grow_sheets: list[str] | None = None,
    confirm: bool = False,
) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Forecast demand {from_year}→{to_year} ({method}, {growth_pct}%).",
            {
                "fromYear": from_year,
                "toYear": to_year,
                "growthPct": growth_pct,
                "method": method,
                "growSheets": grow_sheets,
            },
        )
    return await client.forecast_demand(
        from_year, to_year, growthPct=growth_pct, method=method, growSheets=grow_sheets
    )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ),
    description="Driver-based demand forecast — evolves the hourly SHAPE, not just the level, from population/GDP growth + electrified heat/EV additions. grow_sheets lists the demand series sheets to evolve (default ['loads-p_set'] only — pass more for a multi-sheet demand model). snapshot_weight is hours per snapshot; set it on 3-hourly / typical-day models or the added heat/EV GWh is mis-scaled.",
)
async def driver_forecast(
    from_year: int,
    to_year: int,
    pop_growth_pct: float = 0.0,
    gdp_growth_pct: float = 0.0,
    gdp_elasticity: float = 0.5,
    heat_added_gwh: float = 0.0,
    ev_added_gwh: float = 0.0,
    grow_sheets: list[str] | None = None,
    snapshot_weight: float | None = None,
    confirm: bool = False,
) -> Any:
    client = get_client()
    args = {
        "popGrowthPct": pop_growth_pct,
        "gdpGrowthPct": gdp_growth_pct,
        "gdpElasticity": gdp_elasticity,
        "heatAddedGWh": heat_added_gwh,
        "evAddedGWh": ev_added_gwh,
        "growSheets": grow_sheets,
        "snapshotWeight": snapshot_weight,
    }
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Driver forecast {from_year}→{to_year}.",
            {"fromYear": from_year, "toYear": to_year, **args},
        )
    return await client.driver_forecast(from_year, to_year, **args)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ),
    description="Reshape per-region demand from an EV fleet's daily movement (home overnight, work daytime). home_shares / work_shares are {load_column: share} maps giving where the fleet sleeps vs works — that inter-region shift is the point of the tool, so pass them to move energy between regions (omit and the reshape only redistributes within each region by time of day). snapshot_weight is hours per snapshot (set it on 3-hourly / typical-day models, else the added GWh is mis-scaled). Applies to the demand series sheet.",
)
async def ev_reshape_demand(
    fleet_size: float,
    kwh_per_vehicle_day: float = 7.0,
    home_charging_share: float = 0.7,
    home_shares: dict[str, float] | None = None,
    work_shares: dict[str, float] | None = None,
    snapshot_weight: float | None = None,
    sheet: str = "loads-p_set",
    confirm: bool = False,
) -> Any:
    client = get_client()
    args = {
        "kwhPerVehicleDay": kwh_per_vehicle_day,
        "homeChargingShare": home_charging_share,
        "homeShares": home_shares,
        "workShares": work_shares,
        "snapshotWeight": snapshot_weight,
        "sheet": sheet,
    }
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Reshape {sheet!r} for an EV fleet of {fleet_size:g}.",
            {"fleetSize": fleet_size, **args},
        )
    return await client.ev_reshape_demand(fleet_size, **args)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ),
    description="Cluster/reduce the network to fewer buses (method: modularity|kmeans) or merge buses sharing a column value (group_by_column, e.g. 'country'). aggregate_components additionally merges one-port components by carrier per merged bus (e.g. ['Generator','StorageUnit','Load']). When buses/lines in a cluster disagree on an attribute, resolve_conflicts=true (default) merges them using conflict_strategy (mean|max|min|zero|default); set resolve_conflicts=false to fail instead and surface the disagreement. Applied to the session on confirm.",
)
async def cluster_network(
    n_clusters: int = 0,
    method: str = "modularity",
    group_by_column: str | None = None,
    aggregate_components: list[str] | None = None,
    resolve_conflicts: bool | None = None,
    conflict_strategy: str | None = None,
    confirm: bool = False,
) -> Any:
    client = get_client()
    args: dict[str, Any] = {
        "method": method,
        "groupByColumn": group_by_column,
        "aggregateComponents": aggregate_components,
        "resolveConflicts": resolve_conflicts,
        "conflictStrategy": conflict_strategy,
    }
    if _needs_confirm(cheap=False) and not confirm:
        eff = (
            f"Cluster by column {group_by_column!r}."
            if group_by_column
            else f"Cluster network to {n_clusters} buses ({method})."
        )
        return _preview(eff, {"nClusters": n_clusters, **args})
    resp = await client.cluster_network(n_clusters, **args)
    await client.save_model(
        resp["model"]
    )  # cluster returns a full reduced model → replace
    return {
        "status": "applied",
        "method": resp.get("method"),
        "before": resp.get("before"),
        "after": resp.get("after"),
        "resolvedConflicts": resp.get("resolvedConflicts"),
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ),
    description=(
        "Adjust a carrier's total capacity to a target (MW), distributed across that "
        "carrier's generators. method: 'proportional' (keep current ratios) | 'equal' | "
        "'custom' (per-generator MW in `shares`, must sum to target_mw). mode: 'cap' "
        "writes p_nom_max and marks units extendable — built capacity is bounded AT the "
        "target; 'fix' writes p_nom and marks units non-extendable — installed capacity "
        "EQUALS the target. Applied to the session on confirm."
    ),
)
async def adjust_carrier_capacity(
    carrier: str,
    target_mw: float,
    method: str = "proportional",
    mode: str = "cap",
    shares: dict[str, float] | None = None,
    confirm: bool = False,
) -> Any:
    client = get_client()
    args: dict[str, Any] = {
        "carrier": carrier,
        "targetMw": target_mw,
        "method": method,
        "mode": mode,
        "shares": shares,
    }
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Set {carrier!r} capacity to {target_mw:g} MW ({method}, mode={mode}).",
            args,
        )
    resp = await client.scale_carrier_capacity(**args)
    await client.save_model(resp["model"])  # transform returns a full model → replace
    return {
        "status": "applied",
        "carrier": carrier,
        "targetMw": target_mw,
        "method": resp.get("method"),
        "mode": resp.get("mode"),
        "before": resp.get("before"),
        "after": resp.get("after"),
        "perUnit": resp.get("perUnit"),
        "notes": resp.get("notes"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Build from primitives — GATE (cheap in-session edits). Ergonomic component
# constructors (pypsa-mcp-style) mapped to the shared Ragnarok session, so a
# model built here is persisted, visible live in the GUI, and solvable via the
# real queue with full analytics — one unified world.
# ══════════════════════════════════════════════════════════════════════════════
_BUILD_ANN = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, openWorldHint=False
)


def _row(fixed: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
    """Component row from the named fields (drop None) + any passthrough extras."""
    row = {k: v for k, v in fixed.items() if v is not None}
    if extra:
        row.update(extra)
    return row


@mcp.tool(
    annotations=_BUILD_ANN,
    description="Add a bus (node) to the working model. extra passes any other PyPSA bus attribute (e.g. v_mag_pu_set).",
)
async def add_bus(
    name: str,
    v_nom: float | None = None,
    x: float | None = None,
    y: float | None = None,
    carrier: str | None = None,
    extra: dict[str, Any] | None = None,
    confirm: bool = False,
) -> Any:
    row = _row(
        {"name": name, "v_nom": v_nom, "x": x, "y": y, "carrier": carrier}, extra
    )
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Add bus {name!r}.", {"sheet": "buses", "row": row})
    return await get_client().add_row("buses", row)


@mcp.tool(
    annotations=_BUILD_ANN,
    description="Add a generator on a bus. Set p_nom_extendable=true for capacity expansion. extra passes any other PyPSA generator attribute.",
)
async def add_generator(
    name: str,
    bus: str,
    carrier: str | None = None,
    p_nom: float | None = None,
    marginal_cost: float | None = None,
    p_nom_extendable: bool | None = None,
    capital_cost: float | None = None,
    efficiency: float | None = None,
    extra: dict[str, Any] | None = None,
    confirm: bool = False,
) -> Any:
    row = _row(
        {
            "name": name,
            "bus": bus,
            "carrier": carrier,
            "p_nom": p_nom,
            "marginal_cost": marginal_cost,
            "p_nom_extendable": p_nom_extendable,
            "capital_cost": capital_cost,
            "efficiency": efficiency,
        },
        extra,
    )
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(
            f"Add generator {name!r} on bus {bus!r}.",
            {"sheet": "generators", "row": row},
        )
    return await get_client().add_row("generators", row)


@mcp.tool(
    annotations=_BUILD_ANN,
    description="Add a load on a bus. p_set is the static demand (MW); use a loads-p_set time series for time-varying demand.",
)
async def add_load(
    name: str,
    bus: str,
    p_set: float | None = None,
    carrier: str | None = None,
    extra: dict[str, Any] | None = None,
    confirm: bool = False,
) -> Any:
    row = _row({"name": name, "bus": bus, "p_set": p_set, "carrier": carrier}, extra)
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(
            f"Add load {name!r} on bus {bus!r}.", {"sheet": "loads", "row": row}
        )
    return await get_client().add_row("loads", row)


@mcp.tool(
    annotations=_BUILD_ANN,
    description="Add an AC line between two buses (bus0, bus1). s_nom = rating (MVA); set s_nom_extendable=true to size it. extra passes r/x/length etc.",
)
async def add_line(
    name: str,
    bus0: str,
    bus1: str,
    s_nom: float | None = None,
    x: float | None = None,
    r: float | None = None,
    s_nom_extendable: bool | None = None,
    capital_cost: float | None = None,
    length: float | None = None,
    extra: dict[str, Any] | None = None,
    confirm: bool = False,
) -> Any:
    row = _row(
        {
            "name": name,
            "bus0": bus0,
            "bus1": bus1,
            "s_nom": s_nom,
            "x": x,
            "r": r,
            "s_nom_extendable": s_nom_extendable,
            "capital_cost": capital_cost,
            "length": length,
        },
        extra,
    )
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(
            f"Add line {name!r} ({bus0}–{bus1}).", {"sheet": "lines", "row": row}
        )
    return await get_client().add_row("lines", row)


@mcp.tool(
    annotations=_BUILD_ANN,
    description="Add a storage unit on a bus (battery, PHS, …). max_hours = energy/power ratio. extra passes efficiency_store/dispatch, standing_loss, etc.",
)
async def add_storage(
    name: str,
    bus: str,
    carrier: str | None = None,
    p_nom: float | None = None,
    max_hours: float | None = None,
    efficiency_store: float | None = None,
    efficiency_dispatch: float | None = None,
    capital_cost: float | None = None,
    p_nom_extendable: bool | None = None,
    extra: dict[str, Any] | None = None,
    confirm: bool = False,
) -> Any:
    row = _row(
        {
            "name": name,
            "bus": bus,
            "carrier": carrier,
            "p_nom": p_nom,
            "max_hours": max_hours,
            "efficiency_store": efficiency_store,
            "efficiency_dispatch": efficiency_dispatch,
            "capital_cost": capital_cost,
            "p_nom_extendable": p_nom_extendable,
        },
        extra,
    )
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(
            f"Add storage unit {name!r} on bus {bus!r}.",
            {"sheet": "storage_units", "row": row},
        )
    return await get_client().add_row("storage_units", row)


@mcp.tool(
    annotations=_BUILD_ANN,
    description="Set the model's snapshots (time steps) from an explicit list of timestamps, e.g. ['2030-01-01 00:00','2030-01-01 01:00']. Replaces the snapshots sheet. For a dated range + series reindexing use retarget_snapshots instead.",
)
async def set_snapshots(snapshots: list[str], confirm: bool = False) -> Any:
    rows = [{"snapshot": s} for s in snapshots]
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(
            f"Set {len(rows)} snapshot(s).", {"sheet": "snapshots", "count": len(rows)}
        )
    await get_client().merge_sheets({"snapshots": rows})
    return {"status": "applied", "snapshots": len(rows)}


# ── generic component CRUD — the full registry, any component + any attribute ──
@mcp.tool(
    annotations=_BUILD_ANN,
    description="Add ANY PyPSA component (generic constructor over the full registry). component = 'Generator'/'Link'/'Store'/'Transformer'/'Carrier'/… ; attributes = a dict of any valid attributes (see describe_component). For common types the typed add_* tools are handier.",
)
async def add_component(
    component: str,
    name: str,
    attributes: dict[str, Any] | None = None,
    confirm: bool = False,
) -> Any:
    client = get_client()
    sheet = await client.resolve_sheet(component)
    row = {"name": name, **(attributes or {})}
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Add {component} {name!r}.", {"sheet": sheet, "row": row})
    return await client.add_row(sheet, row)


@mcp.tool(
    annotations=_BUILD_ANN,
    description="Set attributes on an existing component (by name) — any component, any attributes. attributes = {attribute: value}.",
)
async def set_component(
    component: str, name: str, attributes: dict[str, Any], confirm: bool = False
) -> Any:
    client = get_client()
    sheet = await client.resolve_sheet(component)
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(
            f"Set {list(attributes)} on {component} {name!r}.",
            {"sheet": sheet, "name": name, "attributes": attributes},
        )
    return await client.set_component(sheet, name, attributes)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ),
    description="Remove components by name (any component type). names = list of names to delete.",
)
async def remove_component(
    component: str, names: list[str], confirm: bool = False
) -> Any:
    client = get_client()
    sheet = await client.resolve_sheet(component)
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Delete {len(names)} {component}(s): {names}.",
            {"sheet": sheet, "names": names},
        )
    return await client.delete_components(sheet, names)


@mcp.tool(
    annotations=_BUILD_ANN,
    description="Bulk-transform a time-series sheet (e.g. loads-p_set, generators-p_max_pu). op = set (value — overwrites every selected cell, blanks included) | scale (factor) | offset (delta) | shift (shift, wrap) | clip (min_value, max_value) | interpolate (fills gaps) | grow (growth_pct). Optional columns restricts to some assets.",
)
async def transform_series(
    sheet: str,
    op: str,
    value: float | None = None,
    factor: float | None = None,
    delta: float | None = None,
    shift: int | None = None,
    wrap: bool | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    growth_pct: float | None = None,
    columns: list[str] | None = None,
    confirm: bool = False,
) -> Any:
    if op == "set" and value is None:
        # The endpoint defaults value=0.0, so a missing value would silently
        # zero the whole series instead of erroring.
        return {"error": "op='set' requires 'value' (the constant to write)."}
    args = {
        "value": value,
        "factor": factor,
        "delta": delta,
        "shift": shift,
        "wrap": wrap,
        "minValue": min_value,
        "maxValue": max_value,
        "growthPct": growth_pct,
        "columns": columns,
    }
    if _needs_confirm(cheap=True) and not confirm:
        shown = {k: v for k, v in args.items() if v is not None}
        return _preview(
            f"Transform series {sheet!r} ({op}).", {"sheet": sheet, "op": op, **shown}
        )
    return await get_client().transform_series(sheet, op, **args)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ),
    description="Clear the working model in this session (start from an empty network). Destructive — wipes the loaded model.",
)
async def clear_session(confirm: bool = False) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            "Clear the working model (wipes the loaded network).",
            {"session": client.session_id},
        )
    return await client.clear_session()


# ══════════════════════════════════════════════════════════════════════════════
# Data-in / transforms — GATE (live network + persist). Not cheap.
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, openWorldHint=True
    ),
    description="Fetch weather-derived capacity-factor profiles for the model's existing solar/wind fleet and attach them, aligning the snapshot axis to the window. source ∈ open-meteo (default) | pvgis | nasa-power — all keyless; re-run with a second source to cross-validate a profile. Applied to the session on confirm.",
)
async def attach_renewable_profiles(
    date_from: str = "2019-01-01",
    date_to: str = "2019-01-31",
    performance_ratio: float = 0.9,
    utc_offset: int = 0,
    solar_carriers: list[str] | None = None,
    wind_carriers: list[str] | None = None,
    source: str | None = None,
    confirm: bool = False,
) -> Any:
    client = get_client()
    args = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "performanceRatio": performance_ratio,
        "utcOffset": utc_offset,
        "solarCarriers": solar_carriers,
        "windCarriers": wind_carriers,
        "source": source,
    }
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Attach renewable profiles {date_from}..{date_to} (fetches live weather).",
            args,
        )
    resp = await client.attach_renewable_profiles(**args)
    await client.merge_sheets(_fragment_sheets(resp))
    return {
        "status": "applied",
        "attached": resp.get("attached"),
        "skipped": resp.get("skipped"),
        "sites": resp.get("sites"),
        "failedSites": resp.get("failedSites"),
        "snapshotCount": len(resp.get("snapshots") or []),
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, openWorldHint=True
    ),
    description="Fetch GloFAS river-discharge-shaped inflow (keyless Open-Meteo Flood API) for the model's hydro storage units and attach it as storage_units-inflow. Applied to the session on confirm.",
)
async def attach_hydro_inflow(
    date_from: str = "2019-01-01",
    date_to: str = "2019-12-31",
    target_capacity_factor: float = 0.35,
    utc_offset: int = 0,
    hydro_carriers: list[str] | None = None,
    confirm: bool = False,
) -> Any:
    client = get_client()
    args = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "targetCapacityFactor": target_capacity_factor,
        "utcOffset": utc_offset,
        "hydroCarriers": hydro_carriers,
    }
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Attach hydro inflow {date_from}..{date_to} (fetches live discharge).",
            args,
        )
    resp = await client.attach_hydro_inflow(**args)
    await client.merge_sheets(_fragment_sheets(resp))
    return {
        "status": "applied",
        "attached": resp.get("attached"),
        "skipped": resp.get("skipped"),
        "sites": resp.get("sites"),
        "failedSites": resp.get("failedSites"),
        "notes": resp.get("notes"),
        "snapshotCount": len(resp.get("snapshots") or []),
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, openWorldHint=True
    ),
    description="Import one source's datasets for a country and merge them into the working model. country_iso like 'KR'; dataset_ids from list_importers. Applied to the session on confirm.",
)
async def import_dataset(
    country_iso: str,
    dataset_ids: list[str],
    filters: dict[str, Any] | None = None,
    confirm: bool = False,
) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Import {dataset_ids} for {country_iso} (fetches live data).",
            {
                "country_iso": country_iso,
                "dataset_ids": dataset_ids,
                "filters": filters or {},
            },
        )
    resp = await client.import_dataset(country_iso, dataset_ids, filters)
    await client.merge_sheets(resp["fragment"]["sheets"])
    return {
        "status": "applied",
        "source_id": resp.get("source_id"),
        "dataset_ids": resp.get("dataset_ids"),
        "country_iso": resp.get("country_iso"),
        "preview": resp.get("preview"),
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=True
    ),
    description="One-click: assemble a runnable model for a country from keyless global sources (OSM network, power plants, demand) and load it as the working model. iso3 like 'KOR'. Replaces the current model.",
)
async def one_click_model(iso3: str, confirm: bool = False) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Build & load a one-click model for {iso3.upper()} (replaces the working model, fetches live data).",
            {"iso3": iso3},
        )
    resp = await client.one_click_model(iso3)
    await client.save_model(resp["fragment"]["sheets"])  # fresh model → replace
    return {
        "status": "applied",
        "iso3": resp.get("iso3"),
        "label": resp.get("label"),
        "dataset_ids": resp.get("dataset_ids"),
        "preview": resp.get("preview"),
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=True
    ),
    description="Assemble a runnable workbook for a country + year from its starter-pack recipe and load it. iso3 like 'KOR', year like '2030'. Replaces the current model.",
)
async def build_starter_pack(iso3: str, year: str, confirm: bool = False) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Build & load the {iso3.upper()}/{year} starter pack (replaces the working model, fetches live data).",
            {"iso3": iso3, "year": year},
        )
    resp = await client.build_starter_pack(iso3, year)
    await client.save_model(resp["fragment"]["sheets"])
    return {
        "status": "applied",
        "iso3": resp.get("iso3"),
        "year": resp.get("year"),
        "label": resp.get("label"),
        "dataset_ids": resp.get("dataset_ids"),
        "preview": resp.get("preview"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Solve — GATE (minutes of compute). Submits to the queue (visible in the UI),
# waits for completion, and returns the resulting run's analytics.
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
    description="Solve the working model (submits to the queue — visible live in the web UI). scenario/options are the run config (carbon price, discount, solve mode…). With wait=true, blocks up to timeout_s then returns the run's analytics; else returns the job id to poll via get_queue.",
)
async def submit_solve(
    scenario: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    wait: bool = True,
    timeout_s: int = 600,
    confirm: bool = False,
) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            "Submit a solve (minutes of compute).",
            {"scenario": scenario or {}, "options": options or {}},
        )

    submitted = await client.submit_solve(scenario, options)
    job_id = submitted.get("id")
    if not wait:
        return {
            "status": "submitted",
            "jobId": job_id,
            "queueStatus": submitted.get("status"),
            "hint": "Poll get_queue for status; then get_analytics on the finished run.",
        }

    deadline = time.monotonic() + max(1, timeout_s)
    final: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        await asyncio.sleep(2.0)
        queue = await client.get_queue()
        job = next((j for j in queue.get("jobs", []) if j.get("id") == job_id), None)
        if job is None:
            continue
        if job.get("status") in ("done", "error", "cancelled"):
            final = job
            break

    if final is None:
        return {
            "status": "running",
            "jobId": job_id,
            "hint": f"Still solving after {timeout_s}s — poll get_queue, then get_analytics.",
        }
    if final.get("status") != "done":
        return {
            "status": final.get("status"),
            "jobId": job_id,
            "error": final.get("error"),
        }

    runs = (await client.list_runs()).get("runs", [])
    run_name = _newest_run_name(runs)
    if not run_name:
        return {
            "status": "done",
            "jobId": job_id,
            "note": "Solve finished but no run was found to report.",
        }
    analytics = await client.get_analytics(run_name)
    return {
        "status": "done",
        "jobId": job_id,
        "runName": run_name,
        "analytics": analytics,
    }


def _newest_run_name(runs: list[dict[str, Any]]) -> str | None:
    """Best-effort newest run: sort by a timestamp field if present, else take
    the first (the list endpoint returns newest-first)."""
    if not runs:
        return None
    for key in ("savedAt", "createdAt", "finishedAt", "timestamp", "mtime"):
        if all(key in r for r in runs):
            runs = sorted(runs, key=lambda r: r[key], reverse=True)
            break
    top = runs[0]
    return top.get("name") or top.get("runName") or top.get("label")


# ══════════════════════════════════════════════════════════════════════════════
# Pre-flight, deep reads, bulk edit, run/queue control, journal, plugins, master,
# procurement — the capabilities a human has in the GUI that the tool catalog was
# missing. Read tools flow freely; mutating ones gate like their peers.
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool(
    annotations=_RO,
    description="Validate the working model WITHOUT solving — a cheap structural check (missing buses, dangling references, bad snapshots). Run this before submit_solve to catch errors in one call instead of waiting minutes for a solve to fail.",
)
async def validate_model() -> Any:
    return await get_client().validate_case()


@mcp.tool(
    annotations=_RO,
    description=(
        "Answer 'is this the model I asked for?' by READING the model back. Returns a "
        "back-brief (component counts, load peak and energy, each generator's capacity "
        "and marginal cost, what is extendable, the snapshot span) plus findings for the "
        "traps that read as fine and are not: a temporal sheet misaligned to `snapshots` "
        "(uncovered hours solve as ZERO while the run reports Optimal), p_set pinning a "
        "generator, p_min_pu without unit commitment, extendable capacity with no capital "
        "cost, a non-finite lifetime, isolated buses, no load, load shedding present. "
        "Use it after building or changing a model and BEFORE reporting results — and "
        "quote the back-brief to the user rather than your own account of what you did, "
        "because the whole value is that this can disagree with your intent. Findings are "
        "observations, not errors: several are legitimate when deliberate."
    ),
)
async def check_model() -> Any:
    return await get_client().model_check()


@mcp.tool(
    annotations=_RO,
    description="Per-column statistics for an input sheet (count, nulls, min/max/mean/median/std/quartiles/histogram; top values for categoricals). Characterise a sheet without paging its raw rows into context. Optional comma-separated 'columns' to restrict.",
)
async def get_sheet_stats(name: str, columns: str | None = None) -> Any:
    return await get_client().get_sheet_stats(name, columns)


@mcp.tool(
    annotations=_RO,
    description="A windowed, downsampled slice of an INPUT time-series sheet in the working session (e.g. one asset's year of a demand or p_max_pu sheet). columns is comma-separated (omit for all); max_points caps returned points so an 8760-row sheet never enters context whole; agg is mean|min|max|sum. Prefer this over get_sheet_page for time-series.",
)
async def get_series_window(
    name: str,
    start: int = 0,
    end: int | None = None,
    columns: str | None = None,
    max_points: int | None = None,
    agg: str = "mean",
) -> Any:
    return await get_client().get_series_window(name, start, end, columns, max_points, agg)


@mcp.tool(
    annotations=_RO,
    description="A windowed, downsampled slice of a stored run's OUTPUT time-series sheet — per-generator dispatch, line loading, storage state-of-charge, per-bus LMPs, anything get_analytics/get_derived only aggregate. Use for asset-level questions after a solve ('was the battery ever empty?', 'which line was congested in week 3?'). columns comma-separated; max_points caps size; agg mean|min|max|sum.",
)
async def get_run_series(
    run_name: str,
    sheet: str,
    start: int = 0,
    end: int | None = None,
    columns: str | None = None,
    max_points: int | None = None,
    agg: str = "mean",
) -> Any:
    return await get_client().get_run_series(run_name, sheet, start, end, columns, max_points, agg)


@mcp.tool(
    annotations=_RO,
    description="The mutation journal — newest-first entries of every edit made to the session (by you or the user), with actor, kind and a summary. Read it to see what you changed. limit caps rows; before pages to older entries (id < before). Fetch a single entry's detailed diff with get_journal_diff.",
)
async def get_journal(limit: int = 50, before: int | None = None) -> Any:
    return await get_client().get_journal(limit, before)


@mcp.tool(
    annotations=_RO,
    description="The detailed before/after diff for one journal entry (cell-level or sheet-level). Use it to verify an edit landed as intended or to show the user exactly what changed.",
)
async def get_journal_diff(entry_id: int) -> Any:
    return await get_client().get_journal_diff(entry_id)


@mcp.tool(
    annotations=_RO,
    description="Metadata for the multi-year MASTER model stored in this session (its sheets and the calendar 'years' it spans), or {} if none is stored. The master is the multi-year superset a pathway solve derives each year's working model from. Pair with derive_from_master.",
)
async def get_master_meta() -> Any:
    return await get_client().get_master_meta()


@mcp.tool(
    annotations=_RO,
    description="Run an installed plugin's read-only analyze(result, config) hook and return its output — custom analyses, scenario comparisons. Pass 'runs' (stored-run names, max 12) for a cross-run/multiRun plugin. Enumerate plugins and their ids/config with list_plugins first. Does not change the model.",
)
async def run_plugin_analysis(
    plugin_id: str,
    config: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    runs: list[str] | None = None,
) -> Any:
    return await get_client().run_plugin_analyze(plugin_id, config, result, runs)


@mcp.tool(
    annotations=_RO,
    description="Optimise a power-procurement hedging mix: CVaR-constrained least-cost blend of PPA / forward / retail instruments over a price series, plus the cost-vs-risk efficient frontier. Stateless — supply prices (hourly currency/MWh; e.g. from get_run_series on a system-price sheet) and loadMw (flat MW or hourly series). Each instrument is a dict, e.g. ppa={'enabled':true,'strike':60,'maxMw':100}. alpha is the CVaR tail level in [0.5,1). Set cvar_budget to solve the actual CVaR-CONSTRAINED optimum (least expected cost subject to tail risk ≤ budget); omit it and you get the min-CVaR portfolio plus the frontier. bootstrap/block_hours control the block-bootstrap scenario generator (sample count and block length).",
)
async def optimize_procurement(
    prices: list[float],
    load_mw: float | list[float],
    ppa: dict[str, Any] | None = None,
    forward: dict[str, Any] | None = None,
    retail: dict[str, Any] | None = None,
    alpha: float = 0.95,
    cvar_budget: float | None = None,
    bootstrap: int | None = None,
    block_hours: int | None = None,
    stress: list[dict[str, Any]] | None = None,
    frontier_points: int = 8,
    currency: str = "€",
) -> Any:
    req: dict[str, Any] = {
        "prices": prices,
        "loadMw": load_mw,
        "alpha": alpha,
        "frontierPoints": frontier_points,
        "currency": currency,
    }
    for key, val in (
        ("cvarBudget", cvar_budget),
        ("bootstrap", bootstrap),
        ("blockHours", block_hours),
    ):
        if val is not None:
            req[key] = val
    for key, val in (("ppa", ppa), ("forward", forward), ("retail", retail), ("stress", stress)):
        if val is not None:
            req[key] = val
    return await get_client().optimize_procurement(req)


# ── mutating: bulk edit, model swaps, run/queue control (gated like peers) ─────
@mcp.tool(
    annotations=_MUT,
    description=(
        "Bulk conditional edit — Ragnarok's Forge Query & Edit. Select a component "
        "'target' sheet (e.g. 'generators') and an 'attribute' column; narrow rows "
        "with ANDed 'filters' (each {column, op in eq|ne|contains|in|gt|lt|ge|le, "
        "value or values, optional join {component, ref_column} for a one-hop link "
        "e.g. filter generators by their bus's country); then 'edit' "
        "{op in set|add|multiply|derive, amount, source_attr (derive), ...}. "
        "temporal=true edits the '{target}-{attribute}' time-series sheet instead. "
        "This is the ONLY way to do 'raise marginal_cost 20% on every coal generator' "
        "in one call. Without confirm=true it returns a real preview (match count + "
        "before/after sample + warnings); a non-empty 'warnings' means apply would fail. "
        "confirm=true applies it."
    ),
)
async def forge_query(
    target: str,
    attribute: str,
    edit: dict[str, Any],
    filters: list[dict[str, Any]] | None = None,
    temporal: bool = False,
    confirm: bool = False,
) -> Any:
    client = get_client()
    req = {"target": target, "attribute": attribute, "edit": edit,
           "filters": filters or [], "temporal": temporal}
    # The forge /preview endpoint IS the human-readable confirmation (real match
    # count + sample), so a gated call returns that instead of the generic stub.
    if _needs_confirm(cheap=False) and not confirm:
        preview = await client.forge_query(apply=False, req=req)
        return {"status": "preview", "autonomy": _autonomy(),
                "confirmHint": "Re-invoke with confirm=true to apply.", **preview}
    return await client.forge_query(apply=True, req=req)


@mcp.tool(
    annotations=_MUT,
    description="Load a stored run's input model back into the working session as the editable model — the History 'Import project' fast path. Use it to iterate on a past run ('take last month's run and add 2 GW of storage'). REPLACES the current working model. Guarded (it discards the current model).",
)
async def promote_run(run_name: str, confirm: bool = False) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"Replace the working model with stored run {run_name!r}.", {"run": run_name})
    return await client.promote_run(run_name)


@mcp.tool(
    annotations=_MUT,
    description="Derive this session's working model from its stored multi-year MASTER by keeping only selected 'years' and applying attribute 'filters' ([{sheet, column, values}]). mode 'deactivate' (default) marks excluded components inactive; 'remove' hard-deletes them. REPLACES the working model (get_master_meta first). This is the pathway-model assembly step.",
)
async def derive_from_master(
    years: list[int] | None = None,
    filters: list[dict[str, Any]] | None = None,
    mode: str = "deactivate",
    confirm: bool = False,
) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Derive the working model from the master (years={years}, mode={mode}).",
            {"years": years, "filters": filters, "mode": mode},
        )
    return await client.derive_from_master(years, filters, mode)


@mcp.tool(
    annotations=_MUT,
    description="Run an installed plugin's transform(model, config) hook, which rewrites the working model and persists it. A first-class model-edit path for site-specific plugins. Use run_plugin_analysis for the read-only analyze hook; run_plugin_contribute to MERGE a plugin's sheets/constraints instead of replacing.",
)
async def run_plugin_transform(
    plugin_id: str, config: dict[str, Any] | None = None, confirm: bool = False
) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"Run plugin transform {plugin_id!r} on the working model.", {"plugin": plugin_id, "config": config or {}})
    return await client.run_plugin_transform(plugin_id, config)


@mcp.tool(
    annotations=_MUT,
    description="Run an installed plugin's contribute(model, config) hook and MERGE its produced sheets + DSL constraints into the working model (additive, unlike transform which replaces).",
)
async def run_plugin_contribute(
    plugin_id: str, config: dict[str, Any] | None = None, confirm: bool = False
) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"Merge plugin contribution {plugin_id!r} into the model.", {"plugin": plugin_id, "config": config or {}})
    return await client.run_plugin_contribute(plugin_id, config)


@mcp.tool(
    annotations=_MUT,
    description="Undo a single journal entry by id (self-correct a bad edit). Blocked with a conflict if a LATER entry overlaps the same cells — undo the newer one first, or use revert_session. Find entry ids with get_journal.",
)
async def undo_journal_entry(entry_id: int, confirm: bool = False) -> Any:
    client = get_client()
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Undo journal entry {entry_id}.", {"entryId": entry_id})
    return await client.undo_journal_entry(entry_id)


@mcp.tool(
    annotations=_MUT,
    description="Revert the session to a past version by undoing EVERY entry newer than to_version (newest first). A bulk rollback — use get_journal to pick the target version. Heavier than undo_journal_entry.",
)
async def revert_session(to_version: int, confirm: bool = False) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"Revert the session to version {to_version} (undo everything newer).", {"toVersion": to_version})
    return await client.revert_session(to_version)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    description="Cancel a queued solve, or kill it if already running — a SAFETY action, never gated, so you can always stop a job you started. The queue row is kept (rerun_queue_item re-runs it); use delete_queue_item to remove it. item_id comes from get_queue.",
)
async def cancel_solve(item_id: str) -> Any:
    return await get_client().cancel_queue_item(item_id)


@mcp.tool(
    annotations=_MUT,
    description="Re-run a staged, finished or cancelled queue item in place — the SAME card flips back to queued and its retained model re-solves (no duplicate). Starts minutes of compute, so it is guarded. item_id from get_queue.",
)
async def rerun_queue_item(item_id: str, confirm: bool = False) -> Any:
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"Re-run queue item {item_id} (starts a solve).", {"itemId": item_id})
    return await client.rerun_queue_item(item_id)


@mcp.tool(
    annotations=_MUT,
    description="Delete a queue item and its retained model payload (prune the queue). Does NOT delete History entries from completed runs — use delete_run for those. item_id from get_queue.",
)
async def delete_queue_item(item_id: str, confirm: bool = False) -> Any:
    client = get_client()
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Delete queue item {item_id} and its payload.", {"itemId": item_id})
    return await client.delete_queue_item(item_id)


@mcp.tool(
    annotations=_MUT,
    description="Set the maximum number of concurrent solves (1 = serial). Clamped to the machine's CPU count. Lowering it never kills running jobs. Raise it to push your own queued work through faster.",
)
async def set_queue_concurrency(value: int, confirm: bool = False) -> Any:
    client = get_client()
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Set solve concurrency to {value}.", {"value": value})
    return await client.set_queue_concurrency(value)


@mcp.tool(
    annotations=_MUT,
    description="Rename a stored run (its file, identity and display labels together) — tidy the machine-named runs your solves produce. 409 if the new name is taken.",
)
async def rename_run(name: str, new_name: str, confirm: bool = False) -> Any:
    client = get_client()
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Rename run {name!r} to {new_name!r}.", {"name": name, "newName": new_name})
    return await client.rename_run(name, new_name)


@mcp.tool(
    annotations=_MUT,
    description="Delete a stored run from History (bundle + meta). Destructive and always gated — prune failed experiments only when you are sure. Use get_run_series / get_analytics to inspect a run before deleting.",
)
async def delete_run(name: str, confirm: bool = False) -> Any:
    client = get_client()
    # Always gate a permanent deletion, even at auto (mirrors ALWAYS_GATED intent).
    if not confirm:
        return _preview(f"Permanently delete stored run {name!r}.", {"name": name})
    return await client.delete_run(name)


# ══════════════════════════════════════════════════════════════════════════════
# File export / import — the workbook I/O family (xlsx · package · netCDF · HDF5 ·
# project). The GUI's Save/Export/Import buttons; the tool catalog previously had
# no way to get a file OUT of Ragnarok or load a PyPSA-native / project file IN.
# Files land on / are read from the MCP server process's filesystem (the embedded
# agent's sandboxed workdir; for a stdio client, the client machine). Set
# RAGNAROK_MCP_FILE_DIR to redirect the default directory.
# ══════════════════════════════════════════════════════════════════════════════
_FILE_DIR = Path(os.environ.get("RAGNAROK_MCP_FILE_DIR", ".")).expanduser()
# Exports write a local artefact but leave the Ragnarok model untouched — safe to
# run freely (classified read-only in the agent's approval policy).
_EXPORT_ANN = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


def _resolve_out(dest: str | None, default_name: str) -> Path:
    """Resolve an export destination path (relative → under _FILE_DIR); a
    directory (or trailing-slash) target gets default_name appended."""
    p = Path(dest).expanduser() if dest else _FILE_DIR / default_name
    if not p.is_absolute():
        p = _FILE_DIR / p
    if p.is_dir() or (dest is not None and dest.endswith(("/", os.sep))):
        p = p / default_name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_in(path: str) -> Path:
    """Resolve an import source path (relative → under _FILE_DIR)."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else _FILE_DIR / p


@mcp.tool(
    annotations=_EXPORT_ANN,
    description="Export a STORED run to a file on disk. kind='package' writes a re-importable Ragnarok Project .zip (canonical bundle + readable xlsx + this session's chat); kind='xlsx' writes just the workbook, with 'parts' a comma-separated subset of metadata,model,result. 'dest' overrides the output path (a directory or trailing / gets a default filename). Returns the written path and byte size. Does not change the model.",
)
async def export_run(
    run_name: str,
    kind: str = "package",
    parts: str = "metadata,model,result",
    dest: str | None = None,
) -> Any:
    kind = kind.lower()
    if kind not in ("xlsx", "package"):
        return {"error": "kind must be 'xlsx' or 'package'."}
    data, suggested = await get_client().download_run(
        run_name, kind=kind, parts=parts if kind == "xlsx" else None
    )
    default = suggested or f"{run_name}.{'zip' if kind == 'package' else 'xlsx'}"
    out = _resolve_out(dest, default)
    out.write_bytes(data)
    return {"status": "exported", "path": str(out), "bytes": len(data), "kind": kind, "run": run_name}


@mcp.tool(
    annotations=_EXPORT_ANN,
    description="Export the CURRENT working model to a file: format ∈ netcdf | hdf5 | project. netcdf/hdf5 write a PyPSA-native binary (shareable with any PyPSA tooling); project writes a re-importable Ragnarok Project .zip (pass the solved 'result' bundle to embed outputs, else inputs only). 'dest' overrides the path. netcdf/hdf5 build a pypsa.Network first, so they take the same scenario knobs a solve does: discount_rate (default 0.05) and carbon_price feed the derived capital/marginal costs baked into the file; 'options' passes any further solve option through. Returns the written path and byte size. Does not change the model.",
)
async def export_model(
    format: str = "netcdf",
    dest: str | None = None,
    result: dict[str, Any] | None = None,
    discount_rate: float | None = None,
    carbon_price: float | None = None,
    options: dict[str, Any] | None = None,
) -> Any:
    aliases = {
        "nc": "netcdf", "netcdf": "netcdf", "cdf": "netcdf",
        "h5": "hdf5", "hdf5": "hdf5",
        "project": "project", "zip": "project",
    }
    fmt = aliases.get(format.lower())
    if fmt is None:
        return {"error": "format must be netcdf | hdf5 | project."}
    scenario: dict[str, Any] = {}
    if discount_rate is not None:
        scenario["discountRate"] = discount_rate
    if carbon_price is not None:
        scenario["carbonPrice"] = carbon_price
    data, suggested = await get_client().export_model_file(
        fmt, result=result, scenario=scenario, options=options
    )
    default = {
        "netcdf": "ragnarok_network.nc",
        "hdf5": "ragnarok_network.h5",
        "project": "ragnarok_project.zip",
    }[fmt]
    out = _resolve_out(dest, suggested or default)
    out.write_bytes(data)
    return {"status": "exported", "path": str(out), "bytes": len(data), "format": fmt}


@mcp.tool(
    annotations=_MUT,
    description="Import a PyPSA-native netCDF (.nc) or HDF5 (.h5) file from disk INTO the working model (format inferred from the extension). replace=true swaps the whole working model; replace=false merges the imported sheets over it. This overwrites session state, so it gates like a model swap — re-call with confirm=true to apply.",
)
async def import_network(path: str, replace: bool = True, confirm: bool = False) -> Any:
    src = _resolve_in(path)
    suffix = src.suffix.lower()
    fmt = (
        "netcdf" if suffix in (".nc", ".netcdf", ".cdf")
        else "hdf5" if suffix in (".h5", ".hdf5", ".he5")
        else None
    )
    if fmt is None:
        return {"error": f"unrecognised extension {suffix!r}; expected .nc/.netcdf or .h5/.hdf5."}
    if not src.exists():
        return {"error": f"file not found: {src}"}
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Import {src.name} into the working model ({'replace' if replace else 'merge'}).",
            {"path": str(src), "format": fmt, "replace": replace},
        )
    client = get_client()
    model = await client.import_network_file(fmt, src.read_bytes(), src.name)
    if replace:
        await client.save_model(model)
    else:
        await client.merge_sheets(model)
    return {
        "status": "applied",
        "mode": "replace" if replace else "merge",
        "sheets": sorted(model),
        "source": src.name,
    }


@mcp.tool(
    annotations=_MUT,
    description="Import a Ragnarok Project .zip (or workbook .xlsx) from disk. persist=false loads it as the working model (like File→Open — no History entry, overwrites the current model); persist=true stores it as a History run instead (leaves the working model untouched, openable with full analytics). Gates like a model swap — re-call with confirm=true to apply.",
)
async def import_project(path: str, persist: bool = False, confirm: bool = False) -> Any:
    src = _resolve_in(path)
    if not src.exists():
        return {"error": f"file not found: {src}"}
    if _needs_confirm(cheap=False) and not confirm:
        effect = (
            f"Store {src.name} as a History run."
            if persist
            else f"Load {src.name} as the working model (overwrites the current model)."
        )
        return _preview(effect, {"path": str(src), "persist": persist})
    client = get_client()
    out = await client.import_project_file(src.read_bytes(), src.name, persist=persist)
    if persist:
        return {"status": "stored", "run": out.get("name"), "meta": out.get("meta")}
    model = out.get("model") or {}
    await client.save_model(model)
    return {"status": "loaded", "sheets": sorted(model), "filename": out.get("filename")}


# ══════════════════════════════════════════════════════════════════════════════
# Physical risk — climate-damage subsystem with its OWN server-minted session id
# (distinct from the model session). Seed a portfolio from the current model,
# tune its scenario, run the CLIMADA-backed (or deterministic-stub) analysis, and
# read transition / finance / report results. Non-destructive to the model: no
# tool here edits the working network, so they run without the confirm gate; the
# run tool is open-world since it may drive the real CLIMADA worker.
# ══════════════════════════════════════════════════════════════════════════════
# Side-effecting on the physical-risk store but NOT destructive to the model.
_PR_WRITE_ANN = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, openWorldHint=False
)
# The run may invoke the real CLIMADA worker (external compute) → open-world.
_PR_RUN_ANN = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, openWorldHint=True
)

_PR_NO_SESSION = {
    "error": "no physical-risk session — call physical_risk_seed first.",
    "hint": "physical_risk_seed builds a portfolio from the current model and caches its session id.",
}


def _pr_session(session_id: str | None) -> str | None:
    """Resolve a physical-risk session id: the arg, else the client's cached one."""
    return session_id or get_client().physical_risk_session_id


@mcp.tool(
    annotations=_RO,
    description="The physical-risk methodology libraries: perils, climate/NGFS scenarios, vulnerability classes, impact functions and finance reference — the ids you pass to physical_risk_set_scenario / physical_risk_run.",
)
async def physical_risk_libraries() -> Any:
    return await get_client().physical_risk_libraries()


@mcp.tool(
    annotations=_PR_WRITE_ANN,
    description="Seed a physical-risk portfolio from the CURRENT working model (one exposure per generator / storage unit with coordinates). Mints a physical-risk session, caches it for the other physical_risk_* tools, and returns the session id, asset count and a few sample assets. Non-destructive to the model.",
)
async def physical_risk_seed(
    default_value_per_mw: float | None = None, currency: str = "USD"
) -> Any:
    client = get_client()
    portfolio = await client.physical_risk_seed(
        default_value_per_mw=default_value_per_mw, currency=currency
    )
    assets = portfolio.get("assets", []) if isinstance(portfolio, dict) else []
    return {
        "sessionId": portfolio.get("sessionId") if isinstance(portfolio, dict) else None,
        "assetCount": len(assets),
        "sampleAssets": assets[:5],
        "notes": (
            "This physical-risk session is now the default for the other "
            "physical_risk_* tools. Set a scenario with physical_risk_set_scenario, "
            "then physical_risk_run."
        ),
    }


@mcp.tool(
    annotations=_RO,
    description="The physical-risk portfolio (assets + scenario config) for a session. Defaults to the seeded session.",
)
async def physical_risk_get_portfolio(session_id: str | None = None) -> Any:
    sid = _pr_session(session_id)
    if not sid:
        return _PR_NO_SESSION
    return await get_client().physical_risk_get_portfolio(sid)


@mcp.tool(
    annotations=_PR_WRITE_ANN,
    description="Update the portfolio's scenario in place: set any of perils (peril ids), climate (RCP/SSP id), horizon_year, sector. Reads the portfolio, patches only the provided fields, writes it back, and returns the updated scenario. Defaults to the seeded session.",
)
async def physical_risk_set_scenario(
    perils: list[str] | None = None,
    climate: str | None = None,
    horizon_year: int | None = None,
    sector: str | None = None,
    session_id: str | None = None,
) -> Any:
    sid = _pr_session(session_id)
    if not sid:
        return _PR_NO_SESSION
    client = get_client()
    portfolio = await client.physical_risk_get_portfolio(sid)
    if not isinstance(portfolio, dict):
        return {"error": "physical-risk session not found", "sessionId": sid}
    scenario = dict(portfolio.get("scenario") or {})
    if perils is not None:
        scenario["perils"] = perils
    if climate is not None:
        scenario["climate"] = climate
    if horizon_year is not None:
        scenario["horizonYear"] = horizon_year
    if sector is not None:
        scenario["sector"] = sector
    portfolio["scenario"] = scenario
    updated = await client.physical_risk_put_portfolio(sid, portfolio)
    return {
        "sessionId": sid,
        "scenario": updated.get("scenario") if isinstance(updated, dict) else scenario,
    }


@mcp.tool(
    annotations=_PR_RUN_ANN,
    description="Submit a physical-risk analysis (kind defaults to 'physical') for the seeded portfolio and POLL to completion up to poll_seconds. Uses the portfolio's scenario for climate/horizon; `perils` overrides the scenario perils. Returns the result when done, else {status:'running', runId, ...} to keep polling with physical_risk_get_run. May drive the real CLIMADA worker.",
)
async def physical_risk_run(
    kind: str = "physical",
    perils: list[str] | None = None,
    session_id: str | None = None,
    poll_seconds: float = 90.0,
) -> Any:
    sid = _pr_session(session_id)
    if not sid:
        return _PR_NO_SESSION
    client = get_client()
    portfolio = await client.physical_risk_get_portfolio(sid)
    if not isinstance(portfolio, dict):
        return {"error": "physical-risk session not found", "sessionId": sid}
    scenario_cfg = portfolio.get("scenario") or {}
    run_perils = perils if perils is not None else list(scenario_cfg.get("perils") or [])
    scenario = {
        "rcp": scenario_cfg.get("climate", "rcp45"),
        "horizon": scenario_cfg.get("horizonYear", 2050),
    }
    submitted = await client.physical_risk_submit_run(
        sid, kind, perils=run_perils, scenario=scenario
    )
    run_id = submitted.get("id") if isinstance(submitted, dict) else None
    if not run_id:
        return {"status": "error", "sessionId": sid, "detail": submitted}

    deadline = time.monotonic() + max(0.0, poll_seconds)
    run = submitted
    while True:
        status = run.get("status") if isinstance(run, dict) else None
        if status in ("done", "error"):
            break
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(2.0)
        run = await client.physical_risk_get_run(sid, run_id)

    status = run.get("status") if isinstance(run, dict) else None
    if status == "done":
        return {
            "status": "done",
            "runId": run_id,
            "sessionId": sid,
            "result": run.get("result"),
        }
    if status == "error":
        return {
            "status": "error",
            "runId": run_id,
            "sessionId": sid,
            "error": run.get("error"),
        }
    return {
        "status": "running",
        "runId": run_id,
        "sessionId": sid,
        "hint": "call physical_risk_get_run to keep polling",
    }


@mcp.tool(
    annotations=_RO,
    description="Poll one physical-risk run by id (a pure status read). Defaults to the seeded session. Use after physical_risk_run returns status 'running'.",
)
async def physical_risk_get_run(run_id: str, session_id: str | None = None) -> Any:
    sid = _pr_session(session_id)
    if not sid:
        return _PR_NO_SESSION
    return await get_client().physical_risk_get_run(sid, run_id)


@mcp.tool(
    annotations=_PR_WRITE_ANN,
    description="Compute the portfolio's transition (NGFS carbon-cost) risk — synchronous, real math. Defaults to the seeded session.",
)
async def physical_risk_transition(session_id: str | None = None) -> Any:
    sid = _pr_session(session_id)
    if not sid:
        return _PR_NO_SESSION
    return await get_client().physical_risk_transition(sid)


@mcp.tool(
    annotations=_PR_WRITE_ANN,
    description="Compute the Climate Risk Premium (finance) for a DONE physical run — needs a CAPEX-bearing financial profile on the portfolio scenario. Pass the run_id from physical_risk_run. Defaults to the seeded session.",
)
async def physical_risk_finance(run_id: str, session_id: str | None = None) -> Any:
    sid = _pr_session(session_id)
    if not sid:
        return _PR_NO_SESSION
    return await get_client().physical_risk_finance(sid, run_id)


@mcp.tool(
    annotations=_RO,
    description="The physical-risk report bundle for a session: portfolio, latest result per run kind, transition and (when available) finance. Defaults to the seeded session.",
)
async def physical_risk_report(session_id: str | None = None) -> Any:
    sid = _pr_session(session_id)
    if not sid:
        return _PR_NO_SESSION
    return await get_client().physical_risk_report(sid)
