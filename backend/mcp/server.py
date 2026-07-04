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
    "act on one shared working session, visible live in the Ragnarok web UI."
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
    description="Driver-based demand forecast — evolves the hourly SHAPE, not just the level, from population/GDP growth + electrified heat/EV additions.",
)
async def driver_forecast(
    from_year: int,
    to_year: int,
    pop_growth_pct: float = 0.0,
    gdp_growth_pct: float = 0.0,
    gdp_elasticity: float = 0.5,
    heat_added_gwh: float = 0.0,
    ev_added_gwh: float = 0.0,
    confirm: bool = False,
) -> Any:
    client = get_client()
    args = {
        "popGrowthPct": pop_growth_pct,
        "gdpGrowthPct": gdp_growth_pct,
        "gdpElasticity": gdp_elasticity,
        "heatAddedGWh": heat_added_gwh,
        "evAddedGWh": ev_added_gwh,
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
    description="Reshape per-region demand from an EV fleet's daily movement (home overnight, work daytime). Applies to the demand series sheet.",
)
async def ev_reshape_demand(
    fleet_size: float,
    kwh_per_vehicle_day: float = 7.0,
    home_charging_share: float = 0.7,
    sheet: str = "loads-p_set",
    confirm: bool = False,
) -> Any:
    client = get_client()
    args = {
        "kwhPerVehicleDay": kwh_per_vehicle_day,
        "homeChargingShare": home_charging_share,
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
    description="Cluster/reduce the network to fewer buses (method: modularity|kmeans) or merge buses sharing a column value (group_by_column, e.g. 'country'). Applied to the session on confirm.",
)
async def cluster_network(
    n_clusters: int = 0,
    method: str = "modularity",
    group_by_column: str | None = None,
    aggregate_components: list[str] | None = None,
    confirm: bool = False,
) -> Any:
    client = get_client()
    args: dict[str, Any] = {
        "method": method,
        "groupByColumn": group_by_column,
        "aggregateComponents": aggregate_components,
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


# ══════════════════════════════════════════════════════════════════════════════
# Data-in / transforms — GATE (live network + persist). Not cheap.
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, openWorldHint=True
    ),
    description="Fetch weather-derived capacity-factor profiles for the model's existing solar/wind fleet (keyless Open-Meteo) and attach them. Applied to the session on confirm.",
)
async def attach_renewable_profiles(
    date_from: str = "2019-01-01",
    date_to: str = "2019-01-31",
    performance_ratio: float = 0.9,
    utc_offset: int = 0,
    solar_carriers: list[str] | None = None,
    wind_carriers: list[str] | None = None,
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
    }
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Attach renewable profiles {date_from}..{date_to} (fetches live weather).",
            args,
        )
    resp = await client.attach_renewable_profiles(**args)
    await client.merge_sheets(resp["sheets"])
    return {
        "status": "applied",
        "attached": resp.get("attached"),
        "skipped": resp.get("skipped"),
        "sites": resp.get("sites"),
        "failedSites": resp.get("failedSites"),
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
    await client.merge_sheets(resp["sheets"])
    return {
        "status": "applied",
        "attached": resp.get("attached"),
        "skipped": resp.get("skipped"),
        "sites": resp.get("sites"),
        "failedSites": resp.get("failedSites"),
        "notes": resp.get("notes"),
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
