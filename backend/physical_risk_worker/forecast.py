"""Operational tropical-cyclone forecast impact (climada_petals TCForecast → Impact).

Fetches the latest ECMWF ensemble TC tracks, builds a wind hazard at the portfolio
centroids, and computes the forecast impact. ECMWF tracks exist only while a TC is
active, so off-season / no-network this degrades with a clear message (the normal,
expected behaviour). Worker (CLIMADA) env only.
"""

from __future__ import annotations

from typing import Any


def compute_forecast(request: dict[str, Any]) -> dict[str, Any]:
    """Latest ECMWF ensemble TC forecast → impact on the portfolio."""
    assets: list[dict[str, Any]] = request["assets"]
    if not assets:
        return {"status": "error", "detail": "portfolio has no assets"}

    try:
        import numpy as np
        from climada.engine import ImpactCalc
        from climada.entity import ImpactFuncSet
        from climada.entity.impact_funcs.trop_cyclone import ImpfTropCyclone
        from climada.hazard import Centroids, TropCyclone
        from climada_petals.hazard import TCForecast

        from physical_risk_worker.physical import (
            _build_exposures,
            _eai_by_asset,
            _per_asset_iso3,
        )
    except Exception as exc:
        return {"status": "error", "detail": f"forecast engine unavailable: {exc}"}

    try:
        tf = TCForecast()
        tf.fetch_ecmwf()
    except Exception as exc:
        return {
            "status": "error",
            "detail": (
                "ECMWF forecast feed unavailable (operational live feed — active TCs only). "
                f"{type(exc).__name__}: {str(exc)[:140]}"
            ),
        }

    n_tracks = len(getattr(tf, "data", []) or [])
    if n_tracks == 0:
        return {
            "status": "ok",
            "peril": "tropical_cyclone",
            "n_tracks": 0,
            "total_impact": 0.0,
            "per_asset": [],
            "detail": "No active TC tracks in the latest ECMWF forecast (off-season / none active)",
        }

    try:
        lats = [float(a["lat"]) for a in assets]
        lons = [float(a["lon"]) for a in assets]
        try:
            cent = Centroids(lat=np.array(lats), lon=np.array(lons))
        except TypeError:
            cent = Centroids.from_lat_lon(np.array(lats), np.array(lons))
        tc = TropCyclone.from_tracks(tf, centroids=cent)

        v_halves = sorted({round(float(a["tc_v_half"]), 1) for a in assets})
        id_by = {v: i + 1 for i, v in enumerate(v_halves)}
        impf_set = ImpactFuncSet(
            [
                ImpfTropCyclone.from_emanuel_usa(impf_id=i + 1, v_half=v)
                for i, v in enumerate(v_halves)
            ]
        )
        impf_ids = [id_by[round(float(a["tc_v_half"]), 1)] for a in assets]
        exp, src_idx = _build_exposures(assets, "impf_TC", impf_ids)
        imp = ImpactCalc(exp, impf_set, tc).impact(assign_centroids=True)
        eai = _eai_by_asset(imp, src_idx, len(assets))
        iso3s = _per_asset_iso3(lats, lons)
        return {
            "status": "ok",
            "peril": "tropical_cyclone",
            "n_tracks": n_tracks,
            "total_impact": float(imp.aai_agg),
            "per_asset": [
                {
                    "id": a["id"],
                    "lat": a["lat"],
                    "lon": a["lon"],
                    "eai": eai[i],
                    "country": iso3s[i],
                }
                for i, a in enumerate(assets)
            ],
            "detail": f"ECMWF ensemble forecast: {n_tracks} member tracks over the portfolio.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "detail": f"forecast impact failed: {type(exc).__name__}: {str(exc)[:140]}",
        }
