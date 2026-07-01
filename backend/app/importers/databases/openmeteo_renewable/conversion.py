"""Weather → renewable capacity-factor conversion (I4).

Pure, offline-testable transforms from Open-Meteo hourly weather to per-hour
capacity factors usable directly as ``generators-p_max_pu`` values (∈ [0, 1]).

The models are deliberately first-order — enough to give a realistic *shape* and
plausible annual yield for a ``p_max_pu`` series, not a plant-engineering tool:

  • Solar — a plane-of-array proxy: CF ≈ global horizontal irradiance ÷ the
    1000 W/m² standard-test-condition irradiance, times a flat performance
    ratio. Ignores tilt, temperature derate, and spectral effects.
  • Wind — a generic turbine power curve on hub-height wind speed: zero below
    cut-in, a cubic ramp to rated, flat at rated→cut-out, zero above cut-out.

Both clip to [0, 1] so the output is always a valid availability factor.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

GHI_STC = 1000.0  # W/m² — irradiance at standard test conditions

# Default generic onshore-turbine power-curve break points (m/s).
WIND_CUT_IN = 3.0
WIND_RATED = 12.0
WIND_CUT_OUT = 25.0


def solar_cf(ghi_wm2: Sequence[float], performance_ratio: float = 0.9) -> list[float]:
    """Per-hour solar capacity factor from global horizontal irradiance (W/m²).

    Algorithm:
        $$ \\mathrm{CF} = \\mathrm{clip}\\!\\left(\\frac{\\mathrm{GHI}}{1000},\\,0,\\,1\\right)\\cdot \\eta $$
        ASCII: cf = clip(ghi / 1000, 0, 1) * performance_ratio

    Args:
        ghi_wm2: hourly global horizontal irradiance in W/m².
        performance_ratio: flat derate for inverter / soiling / temperature (η).
    """
    ghi = np.asarray(ghi_wm2, dtype=float)
    ghi = np.nan_to_num(ghi, nan=0.0)
    cf = np.clip(ghi / GHI_STC, 0.0, 1.0) * float(performance_ratio)
    return np.clip(cf, 0.0, 1.0).tolist()


def wind_cf(
    speed_ms: Sequence[float],
    cut_in: float = WIND_CUT_IN,
    rated: float = WIND_RATED,
    cut_out: float = WIND_CUT_OUT,
) -> list[float]:
    """Per-hour wind capacity factor from hub-height wind speed (m/s).

    Algorithm (simplified cubic power curve):
        cut_in ≤ v < rated : (v³ − cut_in³) / (rated³ − cut_in³)
        rated ≤ v ≤ cut_out: 1
        else               : 0
    """
    v = np.asarray(speed_ms, dtype=float)
    v = np.nan_to_num(v, nan=0.0)
    cf = np.zeros_like(v)
    denom = rated**3 - cut_in**3
    if denom > 0:
        ramp = (v >= cut_in) & (v < rated)
        cf[ramp] = (v[ramp] ** 3 - cut_in**3) / denom
    flat = (v >= rated) & (v <= cut_out)
    cf[flat] = 1.0
    return np.clip(cf, 0.0, 1.0).tolist()


def combined_ghi(
    shortwave: Sequence[float] | None,
    direct: Sequence[float] | None,
    diffuse: Sequence[float] | None,
) -> list[float]:
    """Per-hour global horizontal irradiance (W/m²) with a fallback chain.

    Open-Meteo's ERA5 archive sometimes leaves ``shortwave_radiation`` (total
    horizontal) null for recent periods while the components are present. Prefer
    it; else ``direct + diffuse``; else ``direct`` alone; else 0 — so a profile
    still lands rather than coming back empty.
    """
    sw, dr, df = shortwave or [], direct or [], diffuse or []
    n = max(len(sw), len(dr), len(df))

    def at(a: Sequence[float], i: int) -> float | None:
        return a[i] if i < len(a) else None

    out: list[float] = []
    for i in range(n):
        s, d, f = at(sw, i), at(dr, i), at(df, i)
        if s is not None:
            out.append(float(s))
        elif d is not None and f is not None:
            out.append(float(d) + float(f))
        elif d is not None:
            out.append(float(d))
        else:
            out.append(0.0)
    return out


def mean_cf(cf: Sequence[float]) -> float:
    """Mean capacity factor (the annual yield fraction), for previews."""
    arr = np.asarray(cf, dtype=float)
    return float(arr.mean()) if arr.size else 0.0
