"""Calibrate an impact-function parameter against observed losses (EM-DAT).

Fits the Emanuel tropical-cyclone ``v_half`` to historical EM-DAT losses for the
portfolio's country by minimising squared error between modelled and observed annual
losses (``climada.util.calibrate.ScipyMinimizeOptimizer`` over present-day TC hazard).

EM-DAT is login-gated and non-commercial; drop the CSV in and set ``CLIMATERISK_EMDAT_PATH``.
When it is absent this degrades with a clear, actionable error. Worker (CLIMADA) env only.
"""

from __future__ import annotations

import os
from typing import Any


def compute_calibration(request: dict[str, Any]) -> dict[str, Any]:
    """Calibrate TC ``v_half`` to EM-DAT observed losses for the portfolio's country."""
    assets: list[dict[str, Any]] = request["assets"]
    if not assets:
        return {"status": "error", "detail": "portfolio has no assets"}

    emdat = os.environ.get("CLIMATERISK_EMDAT_PATH")
    if not emdat or not os.path.isfile(emdat):
        return {
            "status": "error",
            "detail": (
                "calibration needs an EM-DAT disaster-loss CSV (login-gated, non-commercial). "
                "Download EM-DAT and set CLIMATERISK_EMDAT_PATH (Data tab → EM-DAT)."
            ),
        }

    try:
        import numpy as np
        from climada.engine import ImpactCalc
        from climada.engine.impact_data import emdat_to_impact
        from climada.entity import ImpactFuncSet
        from climada.entity.impact_funcs.trop_cyclone import ImpfTropCyclone

        from physical_risk_worker.cost_benefit import _tc_hazard
        from physical_risk_worker.physical import (
            _build_exposures,
            _per_asset_iso3,
            _single_country_iso3,
        )
    except Exception as exc:
        return {"status": "error", "detail": f"calibration engine unavailable: {exc}"}

    iso3 = _single_country_iso3(
        _per_asset_iso3([a["lat"] for a in assets], [a["lon"] for a in assets])
    )
    if iso3 is None:
        return {
            "status": "error",
            "detail": "calibration needs a single-country portfolio (EM-DAT is by-country).",
        }

    try:
        import datetime

        # Observed losses from EM-DAT for this country / peril (total over the record).
        obs = emdat_to_impact(emdat, "TC", countries=[iso3])
        imp_emdat = obs[0] if obs else None
        at_event = np.asarray(getattr(imp_emdat, "at_event", []), dtype=float)
        observed = float(np.nansum(at_event)) if at_event.size else 0.0
        if observed <= 0:
            return {
                "status": "error",
                "detail": f"no EM-DAT tropical-cyclone losses found for {iso3}.",
            }

        # Annualise over the calendar-year span the EM-DAT record covers — NOT the
        # event count (the present-day hazard set holds thousands of synthetic events,
        # so dividing by it would yield a per-event, not per-year, loss).
        dates = np.asarray(getattr(imp_emdat, "date", []), dtype=float)
        event_years = [datetime.date.fromordinal(int(d)).year for d in dates if d > 0]
        n_years = max(1, max(event_years) - min(event_years) + 1) if event_years else 1

        # Present-day hazard + exposure; fit v_half so modelled AAI matches observed.
        impf_ids = [1] * len(assets)
        exp, _ = _build_exposures(assets, "impf_TC", impf_ids)
        haz = _tc_hazard(iso3, "None", None)

        def modelled_aai(v_half: float) -> float:
            impf_set = ImpactFuncSet([ImpfTropCyclone.from_emanuel_usa(impf_id=1, v_half=v_half)])
            return float(ImpactCalc(exp, impf_set, haz).impact(assign_centroids=True).aai_agg)

        target = observed / n_years  # observed annual-average loss
        from scipy.optimize import minimize_scalar

        initial = float(assets[0].get("tc_v_half", 84.7))
        res = minimize_scalar(
            lambda v: (modelled_aai(v) - target) ** 2,
            bounds=(25.7, 200.0),
            method="bounded",
        )
        calibrated = float(res.x)
        return {
            "status": "ok",
            "peril": "tropical_cyclone",
            "country": iso3,
            "param": "v_half",
            "initial": initial,
            "calibrated": calibrated,
            "observed_annual_loss": target,
            "detail": (
                f"{iso3} TC v_half calibrated to EM-DAT (observed ~{target:,.0f}/yr): "
                f"{initial:.1f} → {calibrated:.1f} m/s"
            ),
        }
    except Exception as exc:
        return {
            "status": "error",
            "detail": f"calibration failed: {type(exc).__name__}: {str(exc)[:160]}",
        }
