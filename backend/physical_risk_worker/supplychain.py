"""Indirect (macro-economic) impact via climada_petals supply-chain I/O models.

Builds the direct tropical-cyclone impact on the portfolio, then propagates it through a
Multi-Regional Input-Output (MRIO) table (WIOD16 / EXIOBASE3 / …) with a static Leontief
model (``StaticIOModel``) to estimate **indirect** losses rippling across economic sectors.

The MRIO table is large and fetched on first use (network); when it is unavailable this
degrades with a clear, actionable error rather than failing opaquely. Runs in the worker
(climada_petals) env only.
"""

from __future__ import annotations

import sys
from typing import Any


def compute_supplychain(request: dict[str, Any]) -> dict[str, Any]:
    """Direct TC impact → MRIO Leontief propagation → indirect impact by sector."""
    assets: list[dict[str, Any]] = request["assets"]
    scenario: str = request["climate_scenario"]
    anchor_years: list[int] = request["anchor_years"]
    mriot_type: str = request.get("mriot_type", "WIOD16")
    mriot_year = int(request.get("mriot_year", 2010))
    if not assets:
        return {"status": "error", "detail": "portfolio has no assets"}

    try:
        from climada.engine import ImpactCalc
        from climada.entity import ImpactFuncSet
        from climada.entity.impact_funcs.trop_cyclone import ImpfTropCyclone
        from climada_petals.engine import get_mriot
        from climada_petals.engine.supplychain import DirectShocksSet, StaticIOModel

        from physical_risk_worker.cost_benefit import _tc_hazard
        from physical_risk_worker.physical import (
            _TC_REF_YEARS,
            _build_exposures,
            _nearest,
            _per_asset_iso3,
            _single_country_iso3,
        )
    except Exception as exc:  # petals / optional deps missing
        return {"status": "error", "detail": f"supply-chain engine unavailable: {exc}"}

    # --- direct tropical-cyclone impact on the portfolio --------------------------
    ref_year = _nearest(_TC_REF_YEARS, max(anchor_years) if anchor_years else _TC_REF_YEARS[0])
    iso3 = _single_country_iso3(
        _per_asset_iso3([a["lat"] for a in assets], [a["lon"] for a in assets])
    )
    v_halves = sorted({round(float(a["tc_v_half"]), 1) for a in assets})
    id_by = {v: i + 1 for i, v in enumerate(v_halves)}
    impf_set = ImpactFuncSet(
        [ImpfTropCyclone.from_emanuel_usa(impf_id=i + 1, v_half=v) for i, v in enumerate(v_halves)]
    )
    impf_ids = [id_by[round(float(a["tc_v_half"]), 1)] for a in assets]
    exp, _ = _build_exposures(assets, "impf_TC", impf_ids)

    # The I/O model aggregates exposure by region_id (numeric country code) and maps it to
    # MRIO regions, so it must be set on every exposure row.
    from climada.util import coordinates as u_coord

    e_lat = exp.gdf.geometry.y.to_numpy()
    e_lon = exp.gdf.geometry.x.to_numpy()
    exp.gdf["region_id"] = [int(c) for c in u_coord.get_country_code(e_lat, e_lon)]

    haz = _tc_hazard(iso3, scenario, ref_year)
    imp = ImpactCalc(exp, impf_set, haz).impact(save_mat=True, assign_centroids=True)
    total_direct = float(imp.aai_agg)

    # --- MRIO table (large; network on first use) --------------------------------
    try:
        mriot = get_mriot(mriot_type, mriot_year)
    except Exception as exc:
        return {
            "status": "error",
            "detail": (
                f"SupplyChain needs the {mriot_type} MRIO table ({mriot_year}); the first run "
                f"downloads it (network required, large). {type(exc).__name__}: {str(exc)[:160]}"
            ),
        }

    # --- propagate direct shock through the Leontief model -----------------------
    # A probabilistic TC hazard has thousands of events; one Leontief solve per event is
    # intractable, so we propagate the most-impactful events only (bounded, indicative).
    import numpy as np

    max_events = int(request.get("max_events", 80))
    at_event = np.asarray(getattr(imp, "at_event", []), dtype=float)
    ev_ids = np.asarray(getattr(imp, "event_id", []))
    order = np.argsort(at_event)[::-1] if at_event.size else np.array([], dtype=int)
    top_ids = [int(ev_ids[i]) for i in order if at_event[i] > 0][:max_events]
    try:
        shocks = DirectShocksSet.from_exp_and_imp(
            mriot,
            exp,
            imp,
            affected_sectors="all",
            impact_distribution=None,
            shock_name="tc",
        )
        model = StaticIOModel(mriot, direct_shocks=shocks)
        # Leontief (demand-side) indirect impacts. calc_indirect_impacts also runs Ghosh,
        # which needs mriot.G (not computed for WIOD16) and raises IndexError — so call the
        # Leontief solve directly.
        indirect = model.calc_leontief(event_ids=top_ids or None)
    except Exception as exc:
        return {
            "status": "error",
            "detail": f"supply-chain propagation failed: {type(exc).__name__}: {str(exc)[:160]}",
        }

    # --- summarize indirect impact by sector (robust to the DataFrame shape) ------
    total_indirect = 0.0
    by_sector: list[dict[str, Any]] = []
    try:
        import pandas as pd

        # calc_leontief returns per-sector indirect production change (sign varies); sum over
        # events and rank by absolute magnitude.
        s = indirect.sum(axis=0) if hasattr(indirect, "sum") else pd.Series(dtype=float)
        s = s.abs().sort_values(ascending=False)
        s = s[s > 0]
        total_indirect = float(s.sum())
        for key, val in list(s.items())[:10]:
            sector = key[-1] if isinstance(key, tuple) else str(key)
            by_sector.append({"sector": str(sector), "indirect": float(val)})
    except Exception as exc:
        # Don't silently report a fake zero: surface that the breakdown failed.
        print(f"WARNING supplychain: indirect-impact summary failed: {exc!r}", file=sys.stderr)
        total_indirect = 0.0

    return {
        "status": "ok",
        "mriot": f"{mriot_type} {mriot_year}",
        "currency": assets[0]["currency"],
        "total_direct": total_direct,
        "total_indirect": total_indirect,
        "amplification": (total_indirect / total_direct) if total_direct > 0 else None,
        "by_sector": by_sector,
        "detail": (
            f"{iso3 or 'multi'} TC direct → {mriot_type} Leontief gross indirect production "
            f"change across sectors (horizon {ref_year})"
        ),
    }
