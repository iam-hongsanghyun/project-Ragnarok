"""PyPSA-native file I/O and grid-model importers (P18, P41, P42, P43).

* ``POST /api/import/pypsa-excel``    -- PyPSA Excel workbook -> model (``import_from_excel``)
* ``POST /api/import/pypsa-csv``      -- zip of a PyPSA CSV folder -> model
* ``POST /api/import/matpower``       -- MATPOWER ``.m`` / ``.mat`` case -> model
* ``POST /api/import/pandapower``     -- pandapower JSON net -> model (optional dependency)
* ``POST /api/export/pypsa-excel``    -- working model -> PyPSA Excel (``export_to_excel``)
* ``POST /api/export/pypsa-csv``      -- working model -> zip of a CSV folder
* ``POST /api/transform/seasonal-rating`` -- ``Lines.apply_seasonal_rating`` as a transform

Export bodies are a ``RunPayload`` (same as ``/api/export/netcdf``); the options
``exportStandardTypes`` / ``netcdfCompression`` / ``netcdfFloat32`` are read here
and by the netCDF/HDF5 exporters.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .. import model_store
from ...pypsa.network import pandapower_env, pypsa_io
from ..models import RunPayload
from ..run_options_reference import RunOption, register_options

router = APIRouter(tags=["pypsa-io"])

_EXPORT_READER = "backend/pypsa/network/pypsa_io.py (export options), backend/app/main.py (netCDF/HDF5 export)"
register_options(
    [
        RunOption(
            "options.exportStandardTypes", "boolean",
            "Write PyPSA's standard line/transformer types into the exported file (all four export formats).",
            False, reader=_EXPORT_READER, source="api", group="export",
        ),
        RunOption(
            "options.netcdfCompression", "boolean | integer | object",
            "netCDF compression: true = zlib level 4, an integer 1-9 = that zlib level, or an "
            "xarray encoding dict such as {\"zlib\": true, \"complevel\": 5}.",
            None, reader=_EXPORT_READER, source="api", group="export",
        ),
        RunOption(
            "options.netcdfFloat32", "boolean",
            "Store netCDF floats as float32 (smaller file, ~7 significant digits).",
            False, reader=_EXPORT_READER, source="api", group="export",
        ),
    ]
)


async def _import(builder, data: bytes, label: str) -> Any:
    try:
        network = await asyncio.to_thread(builder, data)
        model = await asyncio.to_thread(pypsa_io.model_from_network, network)
    except pandapower_env.PandapowerSettingUp as exc:
        # 202, not an error: the isolated pandapower env is being built (first use, ~1 min).
        # The model is untouched; the client retries the same request.
        return JSONResponse(
            status_code=202,
            content={
                "detail": str(exc),
                "status": "setting_up",
                "retryAfterSeconds": exc.retry_after_s,
                "pandapowerSetup": exc.status,
            },
            headers={"Retry-After": str(exc.retry_after_s)},
        )
    except pypsa_io.PandapowerUnavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"{label} import failed: {exc}") from exc
    return {"model": model}


@router.post("/api/import/pypsa-excel")
async def import_pypsa_excel(file: UploadFile, skipTime: bool = Query(False)) -> dict[str, Any]:
    """Import a PyPSA-native Excel workbook through ``Network.import_from_excel``."""
    data = await file.read()
    return await _import(lambda d: pypsa_io.network_from_excel(d, skip_time=skipTime), data, "PyPSA Excel")


@router.post("/api/import/pypsa-csv")
async def import_pypsa_csv(file: UploadFile, skipTime: bool = Query(False)) -> dict[str, Any]:
    """Import a zip of a PyPSA CSV folder through ``Network.import_from_csv_folder``."""
    data = await file.read()
    return await _import(lambda d: pypsa_io.network_from_csv_zip(d, skip_time=skipTime), data, "PyPSA CSV")


@router.post("/api/import/matpower")
async def import_matpower(
    file: UploadFile, overwriteZeroSNom: float | None = Query(None)
) -> dict[str, Any]:
    """Import a MATPOWER ``.m``/``.mat`` case via ``Network.import_from_pypower_ppc``."""
    data = await file.read()
    name = file.filename or "case.m"
    return await _import(
        lambda d: pypsa_io.network_from_matpower(d, name, overwrite_zero_s_nom=overwriteZeroSNom),
        data,
        "MATPOWER",
    )


@router.post("/api/import/pandapower")
async def import_pandapower(
    file: UploadFile,
    extraLineData: bool = Query(False),
    usePandapowerIndex: bool = Query(False),
) -> dict[str, Any]:
    """Import a pandapower JSON net via ``Network.import_from_pandapower_net``.

    The first call builds the isolated pandapower environment in the background and
    answers 202 ``{"status": "setting_up", "retryAfterSeconds": N}``; retry the same
    request after N seconds. 501 means setup failed or is disabled (``detail`` says
    why and names the log).
    """
    data = await file.read()
    return await _import(
        lambda d: pypsa_io.network_from_pandapower_json(
            d.decode("utf-8", errors="replace"),
            extra_line_data=extraLineData,
            use_pandapower_index=usePandapowerIndex,
        ),
        data,
        "pandapower",
    )


@router.get("/api/import/pypsa-io/capabilities")
async def pypsa_io_capabilities() -> dict[str, Any]:
    """Which PyPSA-native import/export paths this backend offers."""
    return {
        "import": ["pypsa-excel", "pypsa-csv", "matpower", "pandapower"],
        "export": ["netcdf", "hdf5", "pypsa-excel", "pypsa-csv"],
        "pandapowerInstalled": pypsa_io.pandapower_available(),
        "pandapowerSetup": pandapower_env.status(),
        "exportOptions": ["exportStandardTypes", "netcdfCompression", "netcdfFloat32"],
    }


async def _export(payload: RunPayload, fmt: str) -> Response:
    from .. import main as _main

    try:
        network = await asyncio.to_thread(_main._model_payload_to_network, payload)
        data, media, filename = await asyncio.to_thread(
            pypsa_io.export_network_bytes, network, fmt, payload.options or {}
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"{fmt} export failed: {exc}") from exc
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/export/pypsa-excel")
async def export_pypsa_excel(payload: RunPayload) -> Response:
    """Return the model as a PyPSA-native Excel workbook (``Network.export_to_excel``)."""
    return await _export(payload, "excel")


@router.post("/api/export/pypsa-csv")
async def export_pypsa_csv(payload: RunPayload) -> Response:
    """Return the model as a zip of a PyPSA CSV folder (``Network.export_to_csv_folder``)."""
    return await _export(payload, "csv")


class SeasonalRatingRequest(BaseModel):
    sessionId: str
    # {line: {"summer": MVA, "winter": MVA}}
    ratings: dict[str, dict[str, float]]
    summerMonths: list[int] | None = None  # default NH 4..9; SH e.g. [10,11,12,1,2,3]
    compose: bool = True


@router.post("/api/transform/seasonal-rating")
async def seasonal_rating(req: SeasonalRatingRequest) -> dict[str, Any]:
    """Write ``lines-s_max_pu`` from per-line summer/winter ratings (PyPSA ``apply_seasonal_rating``)."""
    model = model_store.load_full_model(req.sessionId)
    if not model:
        raise HTTPException(status_code=400, detail="No working model in this session.")
    try:
        return await asyncio.to_thread(
            pypsa_io.seasonal_rating_transform,
            model, req.ratings, req.summerMonths, req.compose,
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip("'\"")) from exc
