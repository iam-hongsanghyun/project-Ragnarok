"""Convert a standardized hazard observation grid into a CLIMADA-ready Hazard.

A *standardized grid* is the common on-ramp for any real peril source: a set of
grid cells (lat/lon) plus per-cell annual observations of a hazard intensity. This
is exactly the shape produced by an ingestion pipeline (download → clip → annual
slices), e.g. burn severity per cell-year for wildfire, flood depth per cell-year,
etc. The mapping to CLIMADA is faithful and lossless:

    grid cell      -> centroid
    analysis year  -> event
    intensity      -> intensity[event, centroid]
    1 / n_years    -> event frequency
    (per-cell exceedance frequency then equals the pipeline's annual exceedance
     probability — the same event-frequency model.)

Grid schema (plain dict / JSON)::

    {
      "peril": "wildfire", "haz_type": "WF", "units": "severity",
      "climate_scenario": "historical", "region": "AUS", "year": 2020,
      "source": "...", "license": "...",
      "cells": [{"cell_id": "c0", "lat": -33.5, "lon": 150.5}, ...],
      "observations": [{"cell_id": "c0", "year": 2001, "intensity": 0.0, "valid": true}, ...]
    }
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from climada.hazard import Centroids, Hazard
from scipy import sparse

REQUIRED_KEYS = (
    "peril",
    "haz_type",
    "units",
    "climate_scenario",
    "region",
    "cells",
    "observations",
)


def _centroids(lat: np.ndarray, lon: np.ndarray) -> Centroids:
    try:
        return Centroids(lat=lat, lon=lon)
    except TypeError:  # older signature
        return Centroids.from_lat_lon(lat, lon)


def grid_to_hazard(grid: dict[str, Any]) -> Hazard:
    """Build a CLIMADA ``Hazard`` from a standardized observation grid (see module docs)."""
    missing = [k for k in REQUIRED_KEYS if k not in grid]
    if missing:
        raise ValueError(f"standardized grid missing keys: {missing}")

    cells = grid["cells"]
    if not cells:
        raise ValueError("standardized grid has no cells")
    cell_index = {c["cell_id"]: i for i, c in enumerate(cells)}
    lat = np.array([float(c["lat"]) for c in cells])
    lon = np.array([float(c["lon"]) for c in cells])

    valid_years = sorted({int(o["year"]) for o in grid["observations"] if o.get("valid", True)})
    if not valid_years:
        raise ValueError("standardized grid has no valid observation years")
    year_index = {y: i for i, y in enumerate(valid_years)}

    intensity = np.zeros((len(valid_years), len(cells)))
    for o in grid["observations"]:
        if not o.get("valid", True):
            continue
        ci = cell_index.get(o["cell_id"])
        if ci is None:
            continue
        intensity[year_index[int(o["year"])], ci] = float(o.get("intensity", 0.0) or 0.0)

    n_ev = len(valid_years)
    haz = Hazard(
        haz_type=grid["haz_type"],
        units=grid["units"],
        centroids=_centroids(lat, lon),
        event_id=np.arange(1, n_ev + 1),
        event_name=[str(y) for y in valid_years],
        date=np.array([int(f"{y}0701") for y in valid_years]),
        frequency=np.full(n_ev, 1.0 / n_ev),
        intensity=sparse.csr_matrix(intensity),
        fraction=sparse.csr_matrix((intensity > 0).astype(float)),
    )
    haz.check()
    return haz


def hazard_filename(grid: dict[str, Any]) -> str:
    """Catalog file name: ``<haz_type>_<scenario>_<region>_<year>.hdf5``."""
    year = grid.get("year", "na")
    return f"{grid['haz_type']}_{grid['climate_scenario']}_{grid['region']}_{year}.hdf5"


def convert_grid_to_catalog(grid: dict[str, Any], hazard_db_dir: Path) -> dict[str, Any]:
    """Convert a grid, write its HDF5 under ``hazard_db_dir``, and return a catalog entry."""
    haz = grid_to_hazard(grid)
    peril_dir = hazard_db_dir / grid["peril"]
    peril_dir.mkdir(parents=True, exist_ok=True)
    fname = hazard_filename(grid)
    haz.write_hdf5(str(peril_dir / fname))
    return {
        "peril": grid["peril"],
        "haz_type": grid["haz_type"],
        "climate_scenario": grid["climate_scenario"],
        "region": grid["region"],
        "year": grid.get("year"),
        "units": grid["units"],
        "file": f"{grid['peril']}/{fname}",
        "n_events": int(haz.size),
        "n_centroids": int(haz.centroids.size),
        "source": grid.get("source", "unknown"),
        "license": grid.get("license", "unknown"),
    }
