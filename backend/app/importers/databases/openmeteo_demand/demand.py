"""Temperature-driven synthetic hourly demand (I3-lite / hourly-demand database).

Measured hourly demand only exists for a few regions (ENTSO-E, EIA, KPG193). For
*any* location this builds a plausible hourly demand SHAPE from Open-Meteo
temperature — a flat base plus cooling (above a comfort temperature) and heating
(below it) response — then scales it to a target annual demand. It is a heuristic
(no weekday/holiday calendar, no sector detail), meant to give a runnable, weather-
consistent load profile where no measured series is available.

Algorithm:
    $$ s_t = b + k_c\\max(0, T_t - T_c) + k_h\\max(0, T_c - T_t) $$
    ASCII: shape[t] = base + cool*max(0, T-Tc) + heat*max(0, Tc-T)
    then p_set[t] = shape_normalised[t] · (annual_MWh / 8760)

Symbols: T_t temperature (°C), T_c comfort temperature (°C), b base fraction,
k_c/k_h cooling/heating sensitivity (per °C), p_set[t] load (MW).
"""
from __future__ import annotations

from collections.abc import Sequence

_HOURS_PER_YEAR = 8760.0


def demand_shape(
    temps: Sequence[float],
    base_fraction: float = 0.5,
    cool_coef: float = 0.03,
    heat_coef: float = 0.02,
    t_comfort: float = 18.0,
) -> list[float]:
    """Normalised hourly demand shape (mean ≈ 1) from temperature (°C)."""
    raw: list[float] = []
    for t in temps:
        try:
            temp = float(t)
        except (TypeError, ValueError):
            temp = t_comfort
        cdd = max(0.0, temp - t_comfort)
        hdd = max(0.0, t_comfort - temp)
        raw.append(max(0.0, base_fraction) + cool_coef * cdd + heat_coef * hdd)
    n = len(raw)
    total = sum(raw)
    if n == 0 or total <= 0:
        return [1.0] * n
    return [r * n / total for r in raw]  # rescale so the mean is 1


def scale_to_annual(shape: Sequence[float], annual_mwh: float) -> list[float]:
    """Scale a mean-1 shape to MW per hour so a full year totals ``annual_mwh``.

    Uses the mean-power basis (``annual_mwh / 8760``) so a partial window yields a
    consistent MW level rather than cramming a year into the window.
    """
    mean_power = float(annual_mwh) / _HOURS_PER_YEAR
    return [max(0.0, s * mean_power) for s in shape]
