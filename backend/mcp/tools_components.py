"""Component-coverage tools: seasonal line ratings, maintenance, PyPSA-native I/O (P11, P18, P41-P43).

Registered on the shared ``mcp`` object from :mod:`backend.mcp.server` (one import
line at the end of that file). Thin wrappers over the REST API via
:class:`RagnarokClient`.

Tools:

* ``apply_seasonal_rating``  - WRITE/GATE: ``Lines.apply_seasonal_rating`` -> ``lines-s_max_pu``.
* ``set_maintenance``        - WRITE (cheap): maintainable / duration / events / pu on a
                               Generator, Link or Process.
* ``import_pypsa_native``    - WRITE/GATE: PyPSA Excel, CSV-folder zip, MATPOWER or pandapower file.
* ``export_pypsa_native``    - read-only export: PyPSA Excel or CSV-folder zip.
* ``pypsa_io_capabilities``  - read-only: which paths exist (is pandapower installed?).

netCDF / HDF5 export options go through the existing ``export_model`` tool's
``options`` argument: ``exportStandardTypes`` (bool), ``netcdfCompression``
(true | 1-9 | {"zlib": true, "complevel": n}), ``netcdfFloat32`` (bool).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .server import (
    _BUILD_ANN,
    _EXPORT_ANN,
    _MUT,
    _RO,
    _needs_confirm,
    _preview,
    _resolve_in,
    _resolve_out,
    get_client,
    mcp,
)

_SEASONAL_DOC = (
    "Write per-snapshot line limits (lines-s_max_pu) from summer/winter MVA ratings, via PyPSA's "
    "Lines.apply_seasonal_rating. ratings = {line: {summer: MVA, winter: MVA}}; s_nom is unchanged "
    "(the limit is rating / s_nom). summer_months defaults to the northern hemisphere 4-9; pass "
    "[10,11,12,1,2,3] for the southern. compose=true multiplies into an existing s_max_pu (keeps N-1 "
    "margins); false overwrites. Needs datetime snapshots. Replaces the working model on confirm."
)


@mcp.tool(annotations=_MUT, description=_SEASONAL_DOC)
async def apply_seasonal_rating(
    ratings: dict[str, dict[str, float]],
    summer_months: list[int] | None = None,
    compose: bool = True,
    confirm: bool = False,
) -> Any:
    client = get_client()
    args = {"ratings": ratings, "summerMonths": summer_months, "compose": compose}
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(f"Apply seasonal ratings to {len(ratings)} line(s).", args)
    resp = await client.seasonal_rating(**args)
    await client.save_model(resp["model"])
    return {
        "status": "applied",
        "lines": resp.get("lines"),
        "summerMonths": resp.get("summerMonths"),
        "compose": resp.get("compose"),
        "snapshots": resp.get("snapshots"),
    }


_MAINT_SHEETS = {"generator": "generators", "generators": "generators", "link": "links",
                 "links": "links", "process": "processes", "processes": "processes"}


@mcp.tool(
    annotations=_BUILD_ANN,
    description=(
        "Configure scheduled maintenance (PyPSA 1.3+) on a Generator, Link or Process. The solver then "
        "places maintenance events itself: maintenance_duration (hours per event), maintenance_events "
        "(count per horizon), maintenance_pu (fraction of capacity unavailable, 0-1). maintainable=false "
        "switches it off. Maintenance adds binaries (a MILP): set run option forceLp=true to relax it. "
        "Results: the 'maintenance' result block, and generators-maintenance / maintenance_start series; "
        "adequacy, outage Monte Carlo and ELCC derate by the solved schedule."
    ),
)
async def set_maintenance(
    component: str,
    name: str,
    maintainable: bool = True,
    maintenance_duration: float | None = None,
    maintenance_events: int | None = None,
    maintenance_pu: float | None = None,
    confirm: bool = False,
) -> Any:
    sheet = _MAINT_SHEETS.get(component.lower())
    if sheet is None:
        return {"error": "component must be Generator, Link or Process."}
    if maintenance_pu is not None and not 0.0 <= maintenance_pu <= 1.0:
        return {"error": "maintenance_pu must be in [0, 1]."}
    attrs: dict[str, Any] = {"maintainable": maintainable}
    for key, val in (
        ("maintenance_duration", maintenance_duration),
        ("maintenance_events", maintenance_events),
        ("maintenance_pu", maintenance_pu),
    ):
        if val is not None:
            attrs[key] = val
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Set maintenance on {component} {name!r}.", {"sheet": sheet, "name": name, "attributes": attrs})
    return await get_client().set_component(sheet, name, attrs)


_KIND_BY_SUFFIX = {".xlsx": "pypsa-excel", ".xls": "pypsa-excel", ".zip": "pypsa-csv",
                   ".m": "matpower", ".mat": "matpower", ".json": "pandapower"}


@mcp.tool(
    annotations=_MUT,
    description=(
        "Import a PyPSA-native or grid-model file INTO the working model through PyPSA's own importers. "
        "kind (inferred from the extension when omitted): 'pypsa-excel' (.xlsx, Network.import_from_excel), "
        "'pypsa-csv' (.zip of a PyPSA CSV folder), 'matpower' (.m or .mat case via import_from_pypower_ppc; "
        "overwrite_zero_s_nom replaces zero branch ratings), 'pandapower' (.json net; needs pandapower installed "
        "- see pypsa_io_capabilities). replace=true swaps the working model, false merges sheets over it. "
        "Gates like a model swap - re-call with confirm=true."
    ),
)
async def import_pypsa_native(
    path: str,
    kind: str | None = None,
    replace: bool = True,
    overwrite_zero_s_nom: float | None = None,
    skip_time: bool = False,
    confirm: bool = False,
) -> Any:
    src: Path = _resolve_in(path)
    kind = kind or _KIND_BY_SUFFIX.get(src.suffix.lower())
    if kind not in ("pypsa-excel", "pypsa-csv", "matpower", "pandapower"):
        return {"error": "kind must be pypsa-excel | pypsa-csv | matpower | pandapower (or use a .xlsx/.zip/.m/.mat/.json file)."}
    if not src.exists():
        return {"error": f"file not found: {src}"}
    if _needs_confirm(cheap=False) and not confirm:
        return _preview(
            f"Import {src.name} as {kind} ({'replace' if replace else 'merge'}).",
            {"path": str(src), "kind": kind, "replace": replace},
        )
    client = get_client()
    params: dict[str, Any] = {}
    if kind in ("pypsa-excel", "pypsa-csv") and skip_time:
        params["skipTime"] = "true"
    if kind == "matpower" and overwrite_zero_s_nom is not None:
        params["overwriteZeroSNom"] = overwrite_zero_s_nom
    model = await client.import_pypsa_file(kind, src.read_bytes(), src.name, params)
    if replace:
        await client.save_model(model)
    else:
        await client.merge_sheets(model)
    return {"status": "applied", "mode": "replace" if replace else "merge", "kind": kind,
            "sheets": sorted(model), "source": src.name}


@mcp.tool(
    annotations=_EXPORT_ANN,
    description=(
        "Export the CURRENT working model as a PyPSA-native Excel workbook (kind='excel', "
        "Network.export_to_excel) or a zip of a PyPSA CSV folder (kind='csv', export_to_csv_folder). "
        "export_standard_types=true also writes the line/transformer type catalogues so the file is self-contained. "
        "For netCDF/HDF5 use export_model (options exportStandardTypes, netcdfCompression, netcdfFloat32). "
        "Does not change the model."
    ),
)
async def export_pypsa_native(
    kind: str = "excel",
    dest: str | None = None,
    export_standard_types: bool = False,
    discount_rate: float | None = None,
) -> Any:
    ep = {"excel": "pypsa-excel", "xlsx": "pypsa-excel", "csv": "pypsa-csv", "zip": "pypsa-csv"}.get(kind.lower())
    if ep is None:
        return {"error": "kind must be excel | csv."}
    scenario = {"discountRate": discount_rate} if discount_rate is not None else None
    data, suggested = await get_client().export_pypsa_native(
        ep, scenario=scenario, options={"exportStandardTypes": export_standard_types}
    )
    out = _resolve_out(dest, suggested or ("ragnarok_pypsa_network.xlsx" if ep == "pypsa-excel" else "ragnarok_pypsa_csv.zip"))
    out.write_bytes(data)
    return {"status": "exported", "path": str(out), "bytes": len(data), "kind": kind}


@mcp.tool(
    annotations=_RO,
    description="Which PyPSA-native import/export paths the backend offers, the netCDF export option keys, and whether the optional pandapower library is installed.",
)
async def pypsa_io_capabilities() -> Any:
    return await get_client().pypsa_io_capabilities()
