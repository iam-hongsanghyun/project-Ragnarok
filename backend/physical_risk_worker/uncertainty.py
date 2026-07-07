"""Uncertainty + Sobol sensitivity for physical risk (CLIMADA ``ImpactCalc`` + SALib).

Propagates three input uncertainties through repeated impact calculations:
  - exposure value   (× U[0.8, 1.2])
  - vulnerability    (Emanuel ``v_half`` × U[0.9, 1.1])
  - hazard frequency (× U[0.85, 1.15])

Sampling is a Saltelli design (SALib — the same engine CLIMADA's ``unsequa`` uses), so
the variance decomposition yields proper **Sobol** indices: first-order ``S1`` (each
input's own contribution to AAI variance) and total-order ``ST`` (its contribution
including interactions). Returns the AAI distribution (mean/std/percentiles) too. TC-first.

Model evaluations = base_N × (num_inputs + 2); base_N is capped for tractability.
"""

from __future__ import annotations

from typing import Any

from physical_risk_worker.cost_benefit import _tc_hazard  # reuse TC hazard resolver (catalog-first)
from physical_risk_worker.physical import (
    _TC_REF_YEARS,
    _nearest,
    _per_asset_iso3,
    _single_country_iso3,
)

_PROBLEM = {
    "num_vars": 3,
    "names": ["exposure_value", "vulnerability", "hazard_frequency"],
    "bounds": [[0.8, 1.2], [0.9, 1.1], [0.85, 1.15]],
}


def compute_uncertainty(request: dict[str, Any]) -> dict[str, Any]:
    """Run a Sobol AAI uncertainty + sensitivity analysis."""
    import numpy as np
    import pandas as pd
    from climada.engine import ImpactCalc
    from climada.entity import Exposures, ImpactFuncSet
    from climada.entity.impact_funcs.trop_cyclone import ImpfTropCyclone
    from SALib.analyze import sobol as sobol_analyze
    from SALib.sample import sobol as sobol_sample

    assets: list[dict[str, Any]] = request["assets"]
    scenario: str = request["climate_scenario"]
    anchor_years: list[int] = request["anchor_years"]
    if not assets:
        return {"status": "error", "detail": "portfolio has no assets"}

    # base_N drives the Saltelli design; cap evals = base_N*(D+2) for tractability.
    base_n = max(8, min(int(request.get("n_samples", 16)), 64))
    ref_year = _nearest(_TC_REF_YEARS, max(anchor_years) if anchor_years else _TC_REF_YEARS[0])
    iso3 = _single_country_iso3(
        _per_asset_iso3([a["lat"] for a in assets], [a["lon"] for a in assets])
    )
    haz = _tc_hazard(iso3, scenario, ref_year)

    # Present-day baseline hazard for the climate-change delta (best-effort: Data API / cache).
    present_haz = None
    try:
        from climada.util.api_client import Client

        from physical_risk_worker._dataapi import resilient_get_hazard

        client = Client()
        base_props = {
            "event_type": "synthetic",
            "model_name": "random_walk",
            "climate_scenario": "None",
        }
        if iso3 is not None:
            try:
                present_haz = resilient_get_hazard(
                    client,
                    "tropical_cyclone",
                    properties={
                        **base_props,
                        "spatial_coverage": "country",
                        "country_iso3alpha": iso3,
                    },
                )
            except Exception:
                present_haz = None
        if present_haz is None:
            present_haz = resilient_get_hazard(
                client, "tropical_cyclone", properties={**base_props, "spatial_coverage": "global"}
            )
    except Exception:
        present_haz = None

    lats = [float(a["lat"]) for a in assets]
    lons = [float(a["lon"]) for a in assets]
    base_values = np.array([float(a["value"]) for a in assets])
    base_vhalf = np.array([float(a["tc_v_half"]) for a in assets])

    def evaluate(fv: float, fh: float, ff: float) -> float:
        scaled = base_vhalf * fh
        uniq = sorted({round(v, 1) for v in scaled})
        id_by = {v: i + 1 for i, v in enumerate(uniq)}
        impf_set = ImpactFuncSet(
            [ImpfTropCyclone.from_emanuel_usa(impf_id=i + 1, v_half=v) for i, v in enumerate(uniq)]
        )
        exp = Exposures(
            pd.DataFrame(
                {
                    "latitude": lats,
                    "longitude": lons,
                    "value": base_values * fv,
                    "impf_TC": [id_by[round(v, 1)] for v in scaled],
                }
            )
        )
        imp = ImpactCalc(exp, impf_set, haz).impact(assign_centroids=True)
        return float(imp.aai_agg) * ff  # frequency scales AAI linearly

    param_values = sobol_sample.sample(_PROBLEM, base_n, calc_second_order=False)
    Y = np.array([evaluate(float(r[0]), float(r[1]), float(r[2])) for r in param_values])

    Si = sobol_analyze.analyze(_PROBLEM, Y, calc_second_order=False, print_to_console=False)
    names = _PROBLEM["names"]
    s1 = {n: float(max(0.0, v)) for n, v in zip(names, Si["S1"], strict=False)}
    st = {n: float(max(0.0, v)) for n, v in zip(names, Si["ST"], strict=False)}

    # Climate-change delta: the future AAI distribution vs the present-day baseline AAI
    # (CalcDeltaImpact-style). Present is computed once at the base (unscaled) inputs.
    present_aai: float | None = None
    if present_haz is not None:
        try:
            uniq = sorted({round(v, 1) for v in base_vhalf})
            idb = {v: i + 1 for i, v in enumerate(uniq)}
            base_impf = ImpactFuncSet(
                [
                    ImpfTropCyclone.from_emanuel_usa(impf_id=i + 1, v_half=v)
                    for i, v in enumerate(uniq)
                ]
            )
            base_exp = Exposures(
                pd.DataFrame(
                    {
                        "latitude": lats,
                        "longitude": lons,
                        "value": base_values,
                        "impf_TC": [idb[round(v, 1)] for v in base_vhalf],
                    }
                )
            )
            present_aai = float(
                ImpactCalc(base_exp, base_impf, present_haz).impact(assign_centroids=True).aai_agg
            )
        except Exception:
            present_aai = None
    delta = (Y - present_aai) if present_aai is not None else None

    return {
        "status": "ok",
        "peril": "tropical_cyclone",
        "future_year": ref_year,
        "n_samples": len(Y),
        "currency": assets[0]["currency"],
        "aai_mean": float(Y.mean()),
        "aai_std": float(Y.std()),
        "aai_p5": float(np.percentile(Y, 5)),
        "aai_p50": float(np.percentile(Y, 50)),
        "aai_p95": float(np.percentile(Y, 95)),
        "distribution": [float(x) for x in np.sort(Y)],
        "sensitivity": st,  # headline = total-order (back-compatible with the existing UI bars)
        "sensitivity_s1": s1,
        "sensitivity_st": st,
        "sensitivity_method": "sobol",
        "present_aai": present_aai,
        "delta_mean": float(np.mean(delta)) if delta is not None else None,
        "delta_p5": float(np.percentile(delta, 5)) if delta is not None else None,
        "delta_p95": float(np.percentile(delta, 95)) if delta is not None else None,
        "detail": (
            f"{iso3 or 'global'} TC; Sobol variance decomposition "
            f"({len(Y)} model evals, base N={base_n}), horizon {ref_year}"
        ),
    }
