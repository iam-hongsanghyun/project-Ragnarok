"""Modeled-exposure run — gridded country exposure × any physical peril.

Builds a gridded asset-value exposure for a country (LitPop population × nightlights by
default, or another source from :mod:`physical_risk_worker.exposures` — BlackMarble,
GDP2Asset, a population/value raster), then computes the impact of the *chosen* peril on
it. A modeled grid is just a (large) set of point assets, so it flows through the exact
same per-peril runners as a hand-built portfolio — every peril, yearsets and the
return-period curve come for free. Gated/large exposure data degrades with an actionable
message rather than failing opaquely.
"""

from __future__ import annotations

from typing import Any

# Default vulnerability for modeled grid cells (residential class — mirrors
# assets/libraries/impact_functions.json so a modeled run matches a residential portfolio).
_DEFAULT_VULN: dict[str, Any] = {
    "tc_v_half": 74.7,
    "wf_max_mdd": 0.40,
    "flood_depth_m": [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    "flood_mdr": [0.0, 0.25, 0.40, 0.60, 0.75, 0.85, 0.92, 0.95],
    "eq_mmi": [5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
    "eq_mdr": [0.0, 0.03, 0.10, 0.30, 0.55, 0.85],
}


def _grid_to_assets(exp: Any, currency: str) -> list[dict[str, Any]]:
    """Turn a CLIMADA Exposures grid into the asset-dict list the peril runners consume."""
    import numpy as np

    gdf = exp.gdf
    if "geometry" in gdf and hasattr(gdf["geometry"], "x"):
        lat = gdf["geometry"].y.to_numpy()
        lon = gdf["geometry"].x.to_numpy()
    else:
        lat = gdf["latitude"].to_numpy()
        lon = gdf["longitude"].to_numpy()
    val = np.asarray(gdf["value"], dtype=float)
    return [
        {
            "id": f"cell_{i}",
            "lat": float(lat[i]),
            "lon": float(lon[i]),
            "value": float(val[i]),
            "currency": currency,
            **_DEFAULT_VULN,
        }
        for i in range(len(val))
    ]


def compute_litpop_exposure(request: dict[str, Any]) -> dict[str, Any]:
    """Build a modeled country exposure and compute the chosen peril's impact on it.

    ``exposure_source`` selects the builder (litpop | blackmarble | gdp | raster | …) and
    ``peril`` (default tropical_cyclone) selects which physical peril runs on the grid.
    """
    import numpy as np

    from physical_risk_worker.exposures import EXPOSURE_SOURCES, ExposureUnavailable, build_exposure
    from physical_risk_worker.physical import _RUNNERS, _interpret_result

    country = request.get("country")
    if not country:
        return {"status": "error", "detail": "no country (ISO3) specified for modeled exposure"}
    source = str(request.get("exposure_source", "litpop"))
    source_label = EXPOSURE_SOURCES.get(source, {}).get("label", source)
    peril = str(request.get("peril", "tropical_cyclone"))
    scenario = request["climate_scenario"]
    anchor = request["anchor_years"]
    options = request.get("options", {})

    runner = _RUNNERS.get(peril)
    if runner is None:
        return {
            "status": "error",
            "detail": f"peril '{peril}' is not supported for modeled exposure",
        }

    try:
        exp = build_exposure(source, country, res_arcsec=300)
    except ExposureUnavailable as exc:
        return {"status": "error", "source": source, "detail": exc.detail}

    currency = exp.value_unit or "USD"
    total_value = float(np.nansum(np.asarray(exp.gdf["value"], dtype=float)))
    grid_assets = _grid_to_assets(exp, currency)
    if not grid_assets:
        return {"status": "error", "source": source, "detail": "modeled exposure produced no cells"}

    # Run the chosen peril on the modeled grid via the shared runner (impf + hazard +
    # freq-curve + yearset identical to a hand-built portfolio).
    res = runner(grid_assets, scenario, anchor, options)
    if res.get("status") != "ok":
        return {"status": "error", "source": source, "peril": peril, "detail": res.get("detail")}

    # Top cells by expected annual impact → a tractable map layer.
    per_asset = res.get("per_asset", [])
    ranked = sorted(per_asset, key=lambda p: p.get("eai", 0.0), reverse=True)[:250]
    per_point = [
        {"lat": p["lat"], "lon": p["lon"], "eai": float(p["eai"])}
        for p in ranked
        if p.get("eai", 0) > 0
    ]
    return {
        "status": "ok",
        "interpretation": _interpret_result(res),
        "country": country,
        "exposure_source": source,
        "source_label": source_label,
        "peril": peril,
        "future_year": res.get("target_year"),
        "total_value": total_value,
        "aai_agg": float(res.get("aai_agg", 0.0)),
        "n_points": len(grid_assets),
        "per_point": per_point,
        "currency": currency,
        "result_kind": res.get("result_kind", "monetary"),
        "metric_unit": res.get("metric_unit"),
        "yearset": res.get("yearset"),
        "warn_levels": res.get("warn_levels"),
        "freq_curve": res.get("freq_curve"),
        "detail": f"{source_label} {country}: {len(grid_assets)} cells × {peril}",
    }
