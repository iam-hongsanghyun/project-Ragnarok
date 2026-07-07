"""Render a local-catalog hazard's intensity field to a georeferenced color PNG.

This is the *input preview* layer: it shows the raw hazard footprint (wind m/s, flood
depth m, MMI, rain mm, …) as a color-scale raster on the map, BEFORE any impact
calculation — so a user can see whether their assets fall inside the hazard, and what a
run will act on. No ImpactCalc, no exposure: just the hazard's per-centroid maximum
intensity gridded onto a regular raster and colour-mapped. Worker (CLIMADA) env only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Cap the rendered raster so the PNG stays small and gridding stays fast.
_GRID_PX = 220
# Per-peril display colours are uniform (turbo); the legend carries the units instead.
_COLORMAP = "turbo"


def compute_hazard_preview(request: dict[str, Any]) -> dict[str, Any]:
    """Render the chosen catalog hazard to ``<run_dir>/preview.png`` + return its metadata.

    Request: ``peril``, ``scenario``, ``region``, ``year`` (the exact catalog key the UI
    picked) and ``out_dir`` (the run directory). Returns bbox + value range + unit for the
    map overlay + legend, or a graceful error when the hazard is not in the local catalog.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib as mpl
    import numpy as np
    from PIL import Image
    from scipy.interpolate import griddata

    from physical_risk_worker import catalog

    peril = request["peril"]
    scenario = request.get("scenario", "historical")
    region = request.get("region", "global")
    year = request.get("year")
    out_dir = Path(request["out_dir"])

    haz = catalog.load_hazard(peril, scenario, region, year)
    if haz is None:
        return {
            "status": "error",
            "peril": peril,
            "detail": (
                f"{peril} has no local hazard for {region} ({scenario}). "
                "Ingest it first (Data tab → Fetch & ingest), then preview."
            ),
        }

    lat = np.asarray(haz.centroids.lat, dtype=float)
    lon = np.asarray(haz.centroids.lon, dtype=float)
    inten = np.asarray(haz.intensity.max(axis=0).todense()).ravel().astype(float)
    if lat.size == 0 or float(np.nanmax(inten)) <= 0:
        return {"status": "error", "peril": peril, "detail": f"{peril} hazard has no intensity."}

    # Grid the irregular centroids onto a regular raster over the hazard bbox.
    aspect = max((lat.max() - lat.min()) / max(lon.max() - lon.min(), 1e-6), 1e-6)
    width = _GRID_PX
    height = int(np.clip(round(_GRID_PX * aspect), 40, _GRID_PX * 2))
    gx = np.linspace(lon.min(), lon.max(), width)
    gy = np.linspace(lat.min(), lat.max(), height)
    grid = griddata((lon, lat), inten, tuple(np.meshgrid(gx, gy)), method="linear")

    vmax = float(np.nanpercentile(inten, 99)) or float(np.nanmax(inten))
    norm = mpl.colors.Normalize(vmin=0.0, vmax=vmax)
    rgba = mpl.colormaps[_COLORMAP](norm(grid))
    rgba[..., 3] = np.where(np.isnan(grid) | (grid <= 0), 0.0, 0.78)  # transparent where no hazard
    # PNG origin is top-left; leaflet imageOverlay expects north-up → flip rows.
    img = Image.fromarray((rgba[::-1] * 255).astype("uint8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    img.save(out_dir / "preview.png")

    return {
        "status": "ok",
        "peril": peril,
        "scenario": scenario,
        "region": region,
        "year": year,
        "unit": str(getattr(haz, "units", "") or ""),
        "vmin": 0.0,
        "vmax": round(vmax, 3),
        "colormap": _COLORMAP,
        # leaflet LatLngBounds order: [[south, west], [north, east]]
        "bounds": [[float(lat.min()), float(lon.min())], [float(lat.max()), float(lon.max())]],
        "n_centroids": int(lat.size),
        "image": "preview.png",
        "detail": f"{peril} {scenario} {region}: peak intensity field ({haz.units}).",
    }
