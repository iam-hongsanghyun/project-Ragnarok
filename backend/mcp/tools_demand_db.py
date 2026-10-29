"""Self-hosted hourly demand database tools (D2).

Registered on the shared ``mcp`` object from :mod:`backend.mcp.server` (one import line at the
end of that file). Thin wrappers over the REST API via :class:`RagnarokClient`; nothing here
imports ``backend.app``.

The database is an offline snapshot (Open Power System Data EU load to 2020-09, EIA-930 US
balancing authorities, ENTSO-E where a token was used at refresh time) built by
``python -m backend.app.importers.demand_db.refresh``. All series are MW, UTC, hour-beginning.

Tools:

* ``list_demand_db``   - read-only: what the snapshot holds (series, years, licences, definitions).
* ``get_demand_db_slice`` - read-only: one series for a year window (+ stats; values capped).
* ``import_demand_db`` - WRITE (gated): put a series into the working model as a Load + hourly
                         ``loads-p_set`` + snapshots, through the normal importer.
"""

from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

from .catalogue import declare_areas
from .server import _needs_confirm, _preview, _RO, get_client, mcp

_MAX_VALUES = 2000  # inline hourly values returned at most; stats always cover the full window


@mcp.tool(
    annotations=_RO,
    description=(
        "What the self-hosted hourly demand database holds: per series (key 'source/area', e.g. "
        "'opsd/DE', 'eia930/ERCO') the country, years, coverage, row count, retrieved date, licence and "
        "attribution, plus what each source measures. Units MW, time zone UTC, timestamps hour-beginning. "
        "Offline snapshot: refreshed with `python -m backend.app.importers.demand_db.refresh`, never by "
        "this tool. Empty 'slices' means no snapshot has been built yet."
    ),
)
async def list_demand_db() -> Any:
    return await get_client().demand_db_coverage()


@mcp.tool(
    annotations=_RO,
    description=(
        "Hourly load of one series from the self-hosted demand database for year_from..year_to (UTC years, "
        "max 12). Give 'series' ('opsd/DE', see list_demand_db) or 'country' (ISO-3, picks the best national "
        "series). Returns stats over the full window (hours, TWh, peak/mean/min MW), the definition and licence, "
        "and up to max_values hourly values (default 2000; set 0 for stats only). MW, UTC, hour-beginning."
    ),
)
async def get_demand_db_slice(
    series: str | None = None,
    country: str | None = None,
    year_from: int = 2019,
    year_to: int | None = None,
    max_values: int = _MAX_VALUES,
) -> Any:
    out = await get_client().demand_db_slice(series, country, year_from, year_to)
    n = len(out.get("load_mw", []))
    cap = max(0, int(max_values))
    if n > cap:
        out["timestamps"] = out["timestamps"][:cap]
        out["load_mw"] = out["load_mw"][:cap]
        out["truncated"] = {"returned": cap, "total": n, "hint": "import_demand_db brings the whole window into the model"}
    return out


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
    description=(
        "Import one series from the self-hosted demand database into the working model: a national bus, a Load "
        "and an hourly loads-p_set series over the chosen UTC years, with the snapshot axis (merged like the "
        "GUI's Add to workbook). country_iso is the map country (ISO-3, e.g. 'DEU'); series defaults to 'auto' "
        "(best national series for that country) or pass 'opsd/DE', 'eia930/ERCO'. Reads the local snapshot only - "
        "no network, no API key. Applied to the session on confirm."
    ),
)
async def import_demand_db(
    country_iso: str,
    year_from: int = 2019,
    year_to: int | None = None,
    series: str = "auto",
    fill_gaps: bool = True,
    confirm: bool = False,
) -> Any:
    filters = {
        "series": series,
        "year_from": year_from,
        "year_to": year_from if year_to is None else year_to,
        "fill_gaps": fill_gaps,
    }
    client = get_client()
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Import demand series {series!r} for {country_iso.upper()} {filters['year_from']}-{filters['year_to']} "
            "from the local demand database (replaces/merges the load and snapshots).",
            {"country_iso": country_iso, "dataset_ids": ["demand_db"], "filters": filters},
        )
    resp = await client.import_dataset(country_iso, ["demand_db"], filters)
    await client.apply_fragment(resp["fragment"])
    return {
        "status": "applied",
        "dataset_ids": resp.get("dataset_ids"),
        "country_iso": resp.get("country_iso"),
        "preview": resp.get("preview"),
    }


# Tool areas (see catalogue.py).
declare_areas({
    "list_demand_db": "data",
    "get_demand_db_slice": "data",
    "import_demand_db": "data",
})
