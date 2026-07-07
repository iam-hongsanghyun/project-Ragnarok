"""Download & refine real public data into CLIMADA-ready catalog entries.

This is the platform's *ingestion* layer: turn a listed data source into a
``Hazard`` the physical runners consume via the local catalog, with no manual
file handling. Two refiners are wired:

  - ``ingest_dataapi``  — a CLIMADA Data API hazard (tropical cyclone, river
    flood, wildfire, earthquake) cached to HDF5 for offline / reproducible runs.
  - ``ingest_aqueduct`` — WRI Aqueduct flood return-period GeoTIFFs, read over
    GDAL ``/vsicurl`` for ONLY the portfolio's bounding box (no multi-GB
    download), assembled into a CLIMADA flood ``Hazard`` where each return
    period is one event and the event frequency is the incremental exceedance
    probability ``1/RP_i − 1/RP_{i+1}`` (so AAI is the proper lower-sum integral
    of the exceedance curve and ``calc_freq_curve`` reconstructs the return
    periods).

The catalog key ``(peril, climate_scenario, region)`` is computed the SAME way
the runners compute it (``region`` = single-country ISO3 of the asset points,
else ``"global"``), so an ingested hazard is found by the matching runner with
no extra configuration. Runs in the CLIMADA conda env only.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from physical_risk_worker import catalog
from physical_risk_worker._params import (
    RF_SCENARIO_MAP as _RF_SCENARIO_MAP,
)
from physical_risk_worker._params import (
    RF_YEAR_RANGES as _RF_YEAR_RANGES,
)
from physical_risk_worker._params import (
    TC_REF_YEARS as _TC_REF_YEARS,
)
from physical_risk_worker._params import (
    nearest as _nearest,
)

# --- Aqueduct Floods v2 (WRI, CC-BY 4.0) ---------------------------------------
_AQ_BASE = "http://wri-projects.s3.amazonaws.com/AqueductFloodTool/download/v2"
# Return periods (years) published for riverine flood; each is one event layer.
_AQ_RIVER_RPS = (5, 10, 25, 50, 100, 250, 500, 1000)
# One representative GCM keeps the fetch deterministic (full ensemble is large).
_AQ_GCM = "00000NorESM1-M"
_AQ_FUTURE_YEARS = (2030, 2050, 2080)
# Platform climate scenario -> Aqueduct emissions scenario (only 4p5 / 8p5 exist).
_AQ_SCENARIO = {"rcp26": "rcp4p5", "rcp45": "rcp4p5", "rcp60": "rcp8p5", "rcp85": "rcp8p5"}
# Coastal flood (inuncoast_*): return periods + subsidence/sea-level-rise tokens.
_AQ_COAST_RPS = (2, 5, 10, 25, 50, 100, 250, 500, 1000)
_AQ_COAST_SUBSIDENCE = "wtsub"  # with subsidence (more conservative than nosub)
_AQ_COAST_SLR = "0"  # sea-level-rise scenario token (0 = 50th-percentile central estimate)

# DEM mosaic decimation cap: 30 m GLO-30 over a portfolio bbox is millions of cells,
# which makes the bathtub-surge model run out of memory. Cap the larger dimension to
# this many pixels (the resolution at which surge ran comfortably).
_DEM_MAX_PIXELS = 250
# IBTrACS observed-track window for synthetic TC generation — a recent-climatology
# decade. Override per-run via request["ibtracs_year_range"] = [start, end].
_IBTRACS_YEAR_RANGE = (2010, 2021)

# CLIMADA Data API future windows (_TC_REF_YEARS / _RF_*) and _nearest are shared
# with physical.py via physical_risk_worker._params (single source of truth).


def _region_for_points(points: list[list[float]]) -> str:
    """Single-country ISO3 of the asset points, else ``"global"`` (mirrors the runners)."""
    import numpy as np
    from climada.util import coordinates as u_coord

    lats = [float(p[0]) for p in points]
    lons = [float(p[1]) for p in points]
    codes = [int(c) for c in u_coord.get_country_code(np.array(lats), np.array(lons))]
    iso: set[str | None] = set()
    for c in codes:
        iso.add(u_coord.country_to_iso([c], "alpha3")[0] if c != 0 else None)
    real = {c for c in iso if c}
    return next(iter(real)) if len(real) == 1 and None not in iso else "global"


def _bbox(
    points: list[list[float]], pad: float, max_span: float
) -> tuple[float, float, float, float]:
    """Padded lon/lat bounding box of the asset points, clipped to ``max_span`` degrees."""
    lats = [float(p[0]) for p in points]
    lons = [float(p[1]) for p in points]
    minlon, maxlon = min(lons) - pad, max(lons) + pad
    minlat, maxlat = min(lats) - pad, max(lats) + pad
    # Clip an over-wide box around its centre so a sparse portfolio can't pull a global read.
    clon, clat = (minlon + maxlon) / 2, (minlat + maxlat) / 2
    if maxlon - minlon > max_span:
        minlon, maxlon = clon - max_span / 2, clon + max_span / 2
    if maxlat - minlat > max_span:
        minlat, maxlat = clat - max_span / 2, clat + max_span / 2
    return (minlon, minlat, maxlon, maxlat)


# --- Aqueduct refiner ----------------------------------------------------------


def _aq_river_layers(scenario: str, year: int) -> tuple[str, list[tuple[int, str]]]:
    """Return ``(label, [(rp, url), ...])`` for the chosen scenario/year."""
    if scenario == "historical":
        label = "historical (WATCH 1980)"
        urls = [
            (rp, f"{_AQ_BASE}/inunriver_historical_000000000WATCH_1980_rp{rp:05d}.tif")
            for rp in _AQ_RIVER_RPS
        ]
        return label, urls
    aq_scen = _AQ_SCENARIO.get(scenario, "rcp8p5")
    yr = _nearest(_AQ_FUTURE_YEARS, year)
    label = f"{aq_scen} {_AQ_GCM} {yr}"
    urls = [
        (rp, f"{_AQ_BASE}/inunriver_{aq_scen}_{_AQ_GCM}_{yr}_rp{rp:05d}.tif")
        for rp in _AQ_RIVER_RPS
    ]
    return label, urls


def _aq_coast_layers(scenario: str, year: int) -> tuple[str, list[tuple[int, str]]]:
    """Return ``(label, [(rp, url), ...])`` for Aqueduct coastal inundation (inuncoast_*)."""
    sub, slr = _AQ_COAST_SUBSIDENCE, _AQ_COAST_SLR
    if scenario == "historical":
        urls = [
            (rp, f"{_AQ_BASE}/inuncoast_historical_{sub}_hist_rp{rp:04d}_{slr}.tif")
            for rp in _AQ_COAST_RPS
        ]
        return f"historical {sub}", urls
    aq_scen = _AQ_SCENARIO.get(scenario, "rcp8p5")
    yr = _nearest(_AQ_FUTURE_YEARS, year)
    urls = [
        (rp, f"{_AQ_BASE}/inuncoast_{aq_scen}_{sub}_{yr}_rp{rp:04d}_{slr}.tif")
        for rp in _AQ_COAST_RPS
    ]
    return f"{aq_scen} {sub} {yr}", urls


def _incremental_frequency(rps: list[int]):  # type: ignore[no-untyped-def]
    """Event frequency = incremental exceedance probability ``1/rp_i − 1/rp_{i+1}``."""
    import numpy as np

    inv = 1.0 / np.array(sorted(rps), dtype=float)
    freq = inv.copy()
    freq[:-1] = inv[:-1] - inv[1:]  # largest RP keeps its full 1/rp mass
    return freq


# Aqueduct flood peril -> (CLIMADA haz_type, layer-plan function).
_AQ_FLOOD = {
    "river_flood": ("RF", _aq_river_layers),
    "coastal_flood": ("CF", _aq_coast_layers),
}


def _read_aqueduct_rp_layers(  # type: ignore[no-untyped-def]
    layers: list[tuple[int, str]], bbox: tuple[float, float, float, float]
):
    """Read return-period GeoTIFFs over a bbox; return ``(lat, lon, rows, used_rps)``.

    Each layer is read over ``/vsicurl`` for the bbox only (no full download); a
    missing/unreachable RP layer is skipped rather than aborting the ingest.
    """
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds

    minlon, minlat, maxlon, maxlat = bbox
    lat = lon = None
    rows: list[Any] = []
    used_rps: list[int] = []
    for rp, url in layers:
        try:
            with rasterio.open("/vsicurl/" + url) as ds:
                win = from_bounds(minlon, minlat, maxlon, maxlat, ds.transform)
                win = win.round_offsets().round_lengths()
                arr = ds.read(1, window=win).astype(float)
                if lat is None:
                    wt = ds.window_transform(win)
                    nrows, ncols = arr.shape
                    xs = wt.c + (np.arange(ncols) + 0.5) * wt.a
                    ys = wt.f + (np.arange(nrows) + 0.5) * wt.e
                    lon_g, lat_g = np.meshgrid(xs, ys)
                    lon, lat = lon_g.ravel(), lat_g.ravel()
                nd = ds.nodata
            flat = arr.ravel()
            if nd is not None:
                flat[flat == nd] = 0.0
            flat[~np.isfinite(flat)] = 0.0
            flat[flat < 0] = 0.0
        except Exception:  # a missing RP layer should not abort the whole ingest
            continue
        rows.append(flat)
        used_rps.append(rp)
    return lat, lon, rows, used_rps


def ingest_aqueduct(request: dict[str, Any]) -> dict[str, Any]:
    """Build a CLIMADA flood ``Hazard`` (riverine or coastal) from Aqueduct RP GeoTIFFs."""
    import numpy as np
    from climada.hazard import Hazard
    from scipy import sparse

    from physical_risk_worker.hazard_convert import _centroids

    points = request["points"]
    scenario = request["scenario"]
    year = int(request["year"])
    peril = request.get("peril", "river_flood")
    pad = float(request.get("pad", 0.5))
    max_span = float(request.get("max_span", 8.0))
    if not points:
        raise ValueError("aqueduct ingest needs portfolio asset points to bound the download")
    if peril not in _AQ_FLOOD:
        raise ValueError(f"aqueduct ingest does not support peril '{peril}'")
    haz_type, layers_fn = _AQ_FLOOD[peril]

    region = _region_for_points(points)
    label, layers = layers_fn(scenario, year)
    lat, lon, rows, used_rps = _read_aqueduct_rp_layers(layers, _bbox(points, pad, max_span))
    if len(used_rps) < 2 or lat is None:
        raise ValueError(f"Aqueduct returned no usable {peril} layers for bbox/{label}")

    order = np.argsort(used_rps)
    rps_sorted = [used_rps[i] for i in order]
    intensity = np.vstack([rows[i] for i in order])
    freq = _incremental_frequency(rps_sorted)
    n_ev = len(rps_sorted)

    haz = Hazard(
        haz_type=haz_type,
        units="m",
        centroids=_centroids(lat, lon),
        event_id=np.arange(1, n_ev + 1),
        event_name=[f"rp{rp}" for rp in rps_sorted],
        date=np.full(n_ev, int(f"{year if scenario != 'historical' else 1980}0701")),
        frequency=freq,
        intensity=sparse.csr_matrix(intensity),
        fraction=sparse.csr_matrix((intensity > 0).astype(float)),
    )
    haz.check()

    db = catalog.catalog_dir()
    peril_dir = db / peril
    peril_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{haz_type}_{scenario}_{region}_{year}.hdf5"
    haz.write_hdf5(str(peril_dir / fname))
    return {
        "peril": peril,
        "haz_type": haz_type,
        "climate_scenario": scenario,
        "region": region,
        "year": year,
        "units": "m",
        "file": f"{peril}/{fname}",
        "n_events": int(haz.size),
        "n_centroids": int(haz.centroids.size),
        "source": f"WRI Aqueduct Floods v2 ({peril}, {label}, RPs {rps_sorted})",
        "license": "CC-BY 4.0",
    }


# --- CLIMADA Data API refiner --------------------------------------------------


class _DataApiPlan(NamedTuple):
    """How to fetch a Data-API hazard and which keys to file it under in the catalog."""

    data_type: str
    properties: dict[str, str]
    catalog_scenario: str  # scenario key the matching runner looks up
    catalog_year: int  # year key the matching runner looks up
    src_scenario: str  # the Data-API-side scenario (for the provenance label)
    country_only: bool  # True => single-country fetch only (no global fallback)


def _dataapi_plan(peril: str, scenario: str, year: int, region: str) -> _DataApiPlan:
    """Map a platform ``(peril, scenario, year, region)`` to a Data-API fetch + catalog keys.

    Pure (no CLIMADA / network), so the mapping is unit-testable. ``catalog_scenario`` /
    ``catalog_year`` are the keys the matching physical runner looks up — for the
    geophysical / observed perils these are fixed (wildfire → ``historical``/2020,
    earthquake → ``observed``/2020), independent of the requested climate scenario.
    """
    if peril == "tropical_cyclone":
        ref_year = _nearest(_TC_REF_YEARS, year)
        props = {
            "event_type": "synthetic",
            "model_name": "random_walk",
            "climate_scenario": scenario,
            "ref_year": str(ref_year),
        }
        return _DataApiPlan("tropical_cyclone", props, scenario, ref_year, scenario, False)
    if peril == "river_flood":
        rf_scen = _RF_SCENARIO_MAP.get(scenario, "rcp60")
        year_range = next(
            (r for r in _RF_YEAR_RANGES if int(r[:4]) <= year <= int(r[5:])), "2030_2050"
        )
        props = {"climate_scenario": rf_scen, "year_range": year_range}
        return _DataApiPlan("river_flood", props, scenario, int(year_range[5:]), rf_scen, False)
    if peril == "wildfire":
        if region == "global":
            raise ValueError(
                "wildfire ingest needs a single-country portfolio (global set too large)"
            )
        props = {"spatial_coverage": "country", "country_iso3alpha": region}
        return _DataApiPlan("wildfire", props, "historical", 2020, "historical", True)
    if peril == "earthquake":
        if region == "global":
            raise ValueError(
                "earthquake ingest needs a single-country portfolio (global set too large)"
            )
        props = {
            "spatial_coverage": "country",
            "country_iso3alpha": region,
            "event_type": "observed",
        }
        return _DataApiPlan("earthquake", props, "observed", 2020, "observed", True)
    raise ValueError(f"Data API ingest does not support peril '{peril}'")


def ingest_dataapi(request: dict[str, Any]) -> dict[str, Any]:
    """Cache a CLIMADA Data API hazard (TC / river flood / wildfire / earthquake) to the catalog."""
    from climada.util.api_client import Client

    points = request["points"]
    peril = request["peril"]
    region = _region_for_points(points)
    plan = _dataapi_plan(peril, request["scenario"], int(request["year"]), region)
    client = Client()
    if plan.country_only:
        haz = client.get_hazard(plan.data_type, properties=dict(plan.properties))
    else:
        haz = _fetch_country_or_global(client, plan.data_type, dict(plan.properties), region)

    db = catalog.catalog_dir()
    peril_dir = db / peril
    peril_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{haz.haz_type}_{plan.catalog_scenario}_{region}_{plan.catalog_year}.hdf5"
    haz.write_hdf5(str(peril_dir / fname))
    return {
        "peril": peril,
        "haz_type": haz.haz_type,
        "climate_scenario": plan.catalog_scenario,
        "region": region,
        "year": plan.catalog_year,
        "units": haz.units,
        "file": f"{peril}/{fname}",
        "n_events": int(haz.size),
        "n_centroids": int(haz.centroids.size),
        "source": f"CLIMADA Data API ({peril}, {plan.src_scenario}, cached)",
        "license": "per CLIMADA Data API",
    }


def _fetch_country_or_global(client: Any, data_type: str, props: dict[str, str], region: str):  # type: ignore[no-untyped-def]
    """Fetch a country-coverage hazard if the region is known, else the global set."""
    if region != "global":
        try:
            return client.get_hazard(
                data_type,
                properties={**props, "spatial_coverage": "country", "country_iso3alpha": region},
            )
        except Exception:
            pass
    return client.get_hazard(data_type, properties={**props, "spatial_coverage": "global"})


# --- Copernicus DEM refiner (topography for TC storm surge) ---------------------

_COPDEM_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"


def _copdem_tile_url(lat_sw: int, lon_sw: int) -> str:
    """Copernicus DEM GLO-30 COG URL for the 1°×1° tile with the given SW corner."""
    ns, ew = ("N" if lat_sw >= 0 else "S"), ("E" if lon_sw >= 0 else "W")
    name = f"Copernicus_DSM_COG_10_{ns}{abs(lat_sw):02d}_00_{ew}{abs(lon_sw):03d}_00_DEM"
    return f"{_COPDEM_BASE}/{name}/{name}.tif"


def ingest_copernicus_dem(request: dict[str, Any]) -> dict[str, Any]:
    """Mosaic Copernicus DEM GLO-30 tiles over the portfolio bbox → a local GeoTIFF for surge."""
    import math

    import rasterio
    from rasterio.merge import merge

    points = request["points"]
    if not points:
        raise ValueError("DEM ingest needs portfolio asset points to bound the download")
    pad = float(request.get("pad", 0.2))
    max_span = float(request.get("max_span", 3.0))
    minlon, minlat, maxlon, maxlat = _bbox(points, pad, max_span)
    region = _region_for_points(points)

    tiles = [
        (la, lo)
        for la in range(math.floor(minlat), math.floor(maxlat) + 1)
        for lo in range(math.floor(minlon), math.floor(maxlon) + 1)
    ]
    if len(tiles) > 9:
        raise ValueError(f"DEM bbox spans {len(tiles)} tiles — portfolio too large for surge DEM")
    srcs = []
    for la, lo in tiles:
        try:
            srcs.append(rasterio.open("/vsicurl/" + _copdem_tile_url(la, lo)))
        except Exception:  # a missing/ocean tile should not abort the mosaic
            continue
    if not srcs:
        raise ValueError("no Copernicus DEM tiles available for the portfolio bbox")
    mosaic, transform = merge(srcs, bounds=(minlon, minlat, maxlon, maxlat))
    for s in srcs:
        s.close()

    # Decimate to ~asset-appropriate resolution: 30 m GLO-30 over a portfolio bbox is
    # millions of cells, which makes the bathtub-surge model run out of memory. Cap the
    # larger dimension to ~250 px (the resolution at which surge ran comfortably).
    from rasterio import Affine

    max_dim = max(int(mosaic.shape[-2]), int(mosaic.shape[-1]))
    stride = max(1, max_dim // _DEM_MAX_PIXELS)
    if stride > 1:
        mosaic = mosaic[:, ::stride, ::stride]
        transform = transform * Affine.scale(float(stride))

    dem_dir = catalog.catalog_dir() / "dem"
    dem_dir.mkdir(parents=True, exist_ok=True)
    out = dem_dir / "portfolio_dem.tif"
    h, w = int(mosaic.shape[-2]), int(mosaic.shape[-1])
    with rasterio.open(
        out,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=1,
        dtype=mosaic.dtype,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(mosaic[0], 1)
    return {
        "peril": "tc_surge",
        "source": "Copernicus DEM GLO-30 (AWS open data)",
        "file": "dem/portfolio_dem.tif",
        "region": region,
        "detail": f"DEM mosaic {w}×{h} over {region} bbox written for TC surge",
    }


# --- TCTracks refiner (generate a TC wind hazard from IBTrACS) -----------------


def _synth_tctracks(request: dict[str, Any]):  # type: ignore[no-untyped-def]
    """IBTrACS observed tracks (+ synthetic perturbation) + portfolio-bbox centroids.

    Shared by the TCTracks (wind) and TCRain ingesters. Returns ``(tracks, centroids,
    region, nb_synth)``. Bounded (recent years, few synthetic tracks, coarse grid) for
    tractability; needs network (IBTrACS download).
    """
    from climada.hazard import Centroids, TCTracks

    points = request["points"]
    if not points:
        raise ValueError("TC-tracks ingest needs portfolio asset points to bound the hazard")
    region = _region_for_points(points)
    nb_synth = int(request.get("nb_synth_tracks", 2))
    basin = request.get("basin")  # optional 2-letter basin (e.g. "WP", "NA")
    yr0, yr1 = tuple(request.get("ibtracs_year_range") or _IBTRACS_YEAR_RANGE)

    tracks = TCTracks.from_ibtracs_netcdf(
        year_range=(int(yr0), int(yr1)), basin=basin, estimate_missing=True
    )
    if tracks.size == 0:
        raise ValueError(f"no IBTrACS tracks for basin={basin} {yr0}–{yr1}")
    tracks.equal_timestep()
    if nb_synth > 0:
        tracks.calc_perturbed_trajectories(nb_synth_tracks=nb_synth)

    minlon, minlat, maxlon, maxlat = _bbox(points, pad=1.0, max_span=6.0)
    cent = Centroids.from_pnt_bounds((minlon, minlat, maxlon, maxlat), res=0.1)
    return tracks, cent, region, nb_synth


def ingest_tctracks(request: dict[str, Any]) -> dict[str, Any]:
    """Generate a tropical-cyclone wind hazard from IBTrACS (+ synthetic perturbation).

    Builds the platform its own TC hazard set (no Data-API dependency) over the portfolio
    bbox and files it under the TC catalog key so the TC runner picks it up. Bounded
    (recent years, few synthetic tracks, coarse centroids) for tractability; needs network
    (IBTrACS download).
    """
    from climada.hazard import TropCyclone

    scenario = request["scenario"]
    year = int(request["year"])
    tracks, cent, region, nb_synth = _synth_tctracks(request)
    tc = TropCyclone.from_tracks(tracks, centroids=cent)

    ref_year = _nearest(_TC_REF_YEARS, year)
    db = catalog.catalog_dir()
    peril_dir = db / "tropical_cyclone"
    peril_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{tc.haz_type}_{scenario}_{region}_{ref_year}.hdf5"
    tc.write_hdf5(str(peril_dir / fname))
    return {
        "peril": "tropical_cyclone",
        "haz_type": tc.haz_type,
        "climate_scenario": scenario,
        "region": region,
        "year": ref_year,
        "units": tc.units,
        "file": f"tropical_cyclone/{fname}",
        "n_events": int(tc.size),
        "n_centroids": int(tc.centroids.size),
        "source": f"IBTrACS synthetic tracks (TCTracks, {nb_synth}× perturbed)",
        "license": "IBTrACS (US public domain)",
    }


def ingest_tcrain(request: dict[str, Any]) -> dict[str, Any]:
    """Generate a tropical-cyclone *rainfall* hazard (climada_petals ``TCRain``, R-CLIPER).

    Reuses the IBTrACS-track pipeline, then derives rainfall (mm) via the analytic R-CLIPER
    model — a real physical rainfall hazard rather than the indicative catalog ramp. Files
    it under the ``tc_rain`` catalog key (haz_type ``TR``, mm) so the existing tc_rain runner
    picks it up automatically. Needs network (IBTrACS download).
    """
    from climada_petals.hazard import TCRain

    scenario = request["scenario"]
    year = int(request["year"])
    tracks, cent, region, nb_synth = _synth_tctracks(request)
    rain = TCRain.from_tracks(tracks, centroids=cent, model="R-CLIPER")

    ref_year = _nearest(_TC_REF_YEARS, year)
    db = catalog.catalog_dir()
    peril_dir = db / "tc_rain"
    peril_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{rain.haz_type}_{scenario}_{region}_{ref_year}.hdf5"
    rain.write_hdf5(str(peril_dir / fname))
    return {
        "peril": "tc_rain",
        "haz_type": rain.haz_type,
        "climate_scenario": scenario,
        "region": region,
        "year": ref_year,
        "units": rain.units,
        "file": f"tc_rain/{fname}",
        "n_events": int(rain.size),
        "n_centroids": int(rain.centroids.size),
        "source": f"IBTrACS synthetic tracks → TCRain R-CLIPER ({nb_synth}× perturbed)",
        "license": "IBTrACS (US public domain)",
    }


# --- dispatch ------------------------------------------------------------------

_REFINERS = {
    "dataapi": ingest_dataapi,
    "aqueduct": ingest_aqueduct,
    "copdem": ingest_copernicus_dem,
    "tctracks": ingest_tctracks,
    "tcrain": ingest_tcrain,
}


def run_ingest(request: dict[str, Any]) -> dict[str, Any]:
    """Dispatch an ingest request, register hazard entries in the catalog, and report it."""
    source = request.get("source", "")
    refiner = _REFINERS.get(source)
    if refiner is None:
        return {"status": "error", "source": source, "detail": f"unknown ingest source '{source}'"}
    entry = refiner(request)
    if "n_events" in entry:  # hazard entries go in the catalog manifest; DEM/topo do not
        catalog.register(entry)
        detail = (
            f"Ingested {entry['peril']} → local catalog "
            f"({entry['n_events']} events × {entry['n_centroids']} centroids, "
            f"{entry['climate_scenario']} {entry['region']} {entry.get('year')})."
        )
    else:
        detail = entry.get("detail", f"Ingested {source}.")
    return {
        "status": "ok",
        "source": source,
        "peril": entry.get("peril", ""),
        "entry": entry,
        "detail": detail,
    }
