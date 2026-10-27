"""Analysis tools: server-side results the UI computed only in the browser (WA7)
and the Forge/Build helpers (WA8).

Registered on the shared ``mcp`` object from :mod:`backend.mcp.server` (one import
line at the end of that file). Thin wrappers over the REST API via
:class:`RagnarokClient`; the maths lives in ``backend/app/results_derived.py`` and
``backend/app/forge_helpers.py``, so the UI and these tools return the same numbers.

Read-only:

* ``compare_runs``       - cross-run comparison matrix data (Analytics -> Comparison).
* ``get_kpis``           - the KPI strip of a run (cost, dispatch, prices, peak, load factor, renewables).
* ``compare_companies``  - per-company capacity / energy / revenue / emissions / NPV / IRR / margin.
* ``get_asset_details``  - per-asset summaries, and series for named assets.
* ``list_conversions``   - the sector-coupling conversion templates.

Write (gated like ``forge_query``: without ``confirm=true`` they return a real dry-run preview):

* ``snap_to_buses``      - connect components with x/y to their nearest bus.
* ``adjust_values``      - bulk multiply / add / set one attribute; returns a baseline for revert.
* ``revert_adjustments`` - restore the originals from that baseline.
* ``add_conversion``     - add a conversion technology (Link + carrier bus + carriers + fuel supply).
* ``merge_fragment``     - merge an importer / siting / PyPSA-Earth fragment into the working model.
"""

from __future__ import annotations

from typing import Any

from .server import _MUT, _RO, _autonomy, _needs_confirm, get_client, mcp


def _gated_preview(preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "preview",
        "autonomy": _autonomy(),
        "confirmHint": "Re-invoke with confirm=true to apply.",
        **preview,
    }


# ══ read-only ══════════════════════════════════════════════════════════════════
@mcp.tool(
    annotations=_RO,
    description=(
        "Side-by-side comparison of 2-5 stored runs - the Analytics -> Comparison matrix as data. "
        "'topics' picks columns of detail: kpi (summary KPIs with the generator/storage capacity split), "
        "generation-mix, installed-capacity (solved p_nom_opt by carrier), cost, emissions, capacity "
        "(expansion installed vs optimised), generation-time (carrier dispatch series, strided to <=600 points). "
        "Default kpi + generation-mix. Cite these figures rather than recomputing them."
    ),
)
async def compare_runs(run_names: list[str], topics: list[str] | None = None) -> Any:
    return await get_client().compare_runs(run_names, topics)


@mcp.tool(
    annotations=_RO,
    description=(
        "The KPI strip of a stored run: total cost, dispatch MWh, average/min/max price, peak load MW, "
        "load factor, renewable share % (zero-emission carriers excluding nuclear and storage), emissions, "
        "snapshot count and weight. Numbers match the Analytics KPI card."
    ),
)
async def get_kpis(run_name: str, currency: str | None = None) -> Any:
    return await get_client().get_kpis(run_name, currency)


@mcp.tool(
    annotations=_RO,
    description=(
        "Company comparison for a stored run: the per-owner breakdown (capacity, energy, revenue, emissions), "
        "project finance (NPV, IRR, payback) and P&L (net margin) joined by company and ranked by 'sort_by' "
        "(npv, netMargin, irr, revenue, capacityMW, emissionsTonnes; default the first available). Needs "
        "owner-tagged assets (see the run's ownerColumn option)."
    ),
)
async def compare_companies(run_name: str, sort_by: str | None = None) -> Any:
    return await get_client().compare_companies(run_name, sort_by)


@mcp.tool(
    annotations=_RO,
    description=(
        "Per-asset details of a stored run. kind is one of generators, buses, storageUnits, stores, branches, "
        "processes, shuntImpedances (default all). Without 'names' it returns each asset's summary (energy, "
        "operating cost, emissions, ratings, peaks); with 'names' (or series=true) it also returns the "
        "per-snapshot series. 'period' selects one investment period of a pathway run. Paginated "
        "{items, total, offset, limit}."
    ),
)
async def get_asset_details(
    run_name: str,
    kind: str | None = None,
    names: list[str] | None = None,
    series: bool = False,
    period: int | None = None,
    currency: str | None = None,
    offset: int = 0,
    limit: int = 200,
) -> Any:
    return await get_client().get_asset_details(
        run_name, kind=kind, names=",".join(names) if names else None, series=series or None,
        period=period, currency=currency, offset=offset, limit=limit,
    )


@mcp.tool(
    annotations=_RO,
    description=(
        "The sector-coupling conversion templates (CCGT, OCGT, CHP, electrolyser, fuel cell, heat pump, resistive "
        "heater, gas boiler, methanation) with efficiency, capital cost and fuel assumptions, plus the default "
        "anchor bus of the working model. Use with add_conversion."
    ),
)
async def list_conversions() -> Any:
    return await get_client().list_conversions()


# ══ write (gated) ══════════════════════════════════════════════════════════════
@mcp.tool(
    annotations=_MUT,
    description=(
        "Forge spatial snap: set bus / bus0 / bus1 of every row on 'sheet' that carries x/y (x0/y0, x1/y1 for "
        "branches) to its nearest bus within 'buffer_km' (great-circle). Components beyond the buffer are left "
        "unchanged and listed under 'outside'. Without confirm=true returns the dry-run result (assigned, "
        "outside, noCoords) without writing; confirm=true writes the sheet."
    ),
)
async def snap_to_buses(sheet: str, buffer_km: float = 50.0, confirm: bool = False) -> Any:
    client = get_client()
    gated = _needs_confirm(cheap=False) and not confirm
    res = await client.forge_snap(sheet=sheet, bufferKm=buffer_km, apply=not gated)
    if gated:
        res.pop("rows", None)  # the preview is the counts, not the whole sheet
        return _gated_preview(res)
    res.pop("rows", None)
    return res


_ADJUSTMENT_DOC = (
    "'adjustments' is a list of {sheet, attribute, action: multiply|add|set, amount, filters: [{column, value}]} "
    "(filters are ANDed equality matches; multiply amount is a percent, 100 = unchanged)."
)


@mcp.tool(
    annotations=_MUT,
    description=(
        "Forge bulk adjust: " + _ADJUSTMENT_DOC + " Later adjustments see earlier ones. multiply/add skip rows "
        "whose attribute is not numeric; set always writes. Returns {changed, perAdjustment, baseline}; keep "
        "'baseline' to undo with revert_adjustments (it holds the ORIGINAL values, first touch wins). Without "
        "confirm=true returns the dry-run counts only."
    ),
)
async def adjust_values(
    adjustments: list[dict[str, Any]], baseline: dict[str, Any] | None = None, confirm: bool = False,
) -> Any:
    gated = _needs_confirm(cheap=False) and not confirm
    res = await get_client().forge_adjust(
        {"adjustments": adjustments, "baseline": baseline or {}, "apply": not gated}
    )
    res["sheets"] = {name: len(rows) for name, rows in (res.get("sheets") or {}).items()}  # counts, not rows
    return _gated_preview(res) if gated else res


@mcp.tool(
    annotations=_MUT,
    description=(
        "Undo adjust_values: restore the cells targeted by 'adjustments' to their ORIGINAL value from 'baseline' "
        "(a cell that was absent originally is removed). " + _ADJUSTMENT_DOC + " Idempotent. Without confirm=true "
        "returns the dry-run count."
    ),
)
async def revert_adjustments(
    adjustments: list[dict[str, Any]], baseline: dict[str, Any], confirm: bool = False,
) -> Any:
    gated = _needs_confirm(cheap=False) and not confirm
    res = await get_client().forge_adjust(
        {"adjustments": adjustments, "baseline": baseline, "apply": not gated}, revert=True
    )
    res["sheets"] = {name: len(rows) for name, rows in (res.get("sheets") or {}).items()}
    return _gated_preview(res) if gated else res


@mcp.tool(
    annotations=_MUT,
    description=(
        "Build: add one conversion technology to the working model - the Link plus any missing carrier bus, carriers "
        "and (for gas-fed templates) a fuel-supply generator, reusing existing ones. 'template_id' from "
        "list_conversions; 'anchor_bus' is the electricity bus (default: first electricity bus); p_nom is MW of "
        "input capacity unless extendable=true (the solver sizes it, template capital cost). Without confirm=true "
        "returns the fragment that would be merged."
    ),
)
async def add_conversion(
    template_id: str,
    anchor_bus: str | None = None,
    name: str | None = None,
    p_nom: float = 100.0,
    extendable: bool = False,
    confirm: bool = False,
) -> Any:
    gated = _needs_confirm(cheap=False) and not confirm
    res = await get_client().build_conversion(
        templateId=template_id, anchorBus=anchor_bus, name=name, pNom=p_nom,
        extendable=extendable, apply=not gated,
    )
    return _gated_preview(res) if gated else res


@mcp.tool(
    annotations=_MUT,
    description=(
        "Merge a WorkbookFragment (from import_dataset, siting_scan or PyPSA-Earth) into the working model with the "
        "GUI's 'Add to workbook' rules: rows are appended with name dedupe (never a whole-sheet replace), carriers "
        "are unioned (existing values win; a fuel-price fragment overwrites and re-prices generators), snapshots are "
        "unioned and temporal sheets widened, provenance recorded. Without confirm=true returns the row counts the "
        "merge would produce."
    ),
)
async def merge_fragment(fragment: dict[str, Any], confirm: bool = False) -> Any:
    gated = _needs_confirm(cheap=False) and not confirm
    res = await get_client().merge_fragment(fragment, apply=not gated)
    res.pop("model", None)  # counts, not the merged model
    return _gated_preview(res) if gated else res
