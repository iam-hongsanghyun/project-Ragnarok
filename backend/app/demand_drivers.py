"""Driver-based demand forecast (I3) — a future demand series with an EVOLVED shape.

T1's forecast scales an existing series (same shape, bigger numbers). I3 derives
a *new* shape from exogenous drivers: macro growth (population + GDP) scales the
base profile, while electrification adds load components that follow their own
hourly patterns — heat (winter-peaking, morning/evening ridges) and EV charging
(overnight-peaking with a midday work bump). A decade out, the peak can move to
a winter evening even though the base shape was summer-peaking: exactly the
effect pathway studies need and uniform scaling cannot produce.

Algorithm (per snapshot t, per load column c):
    $$ d'_{c,t} = g \\cdot d_{c,t} + s_c\\,(H\\,h_t + E\\,e_t), \\quad
       g = (1+p)^{\\Delta}\\,(1+\\varepsilon\\,y)^{\\Delta} $$
    ASCII: new = macro_factor*base + share_c*(heat_MWh*heat_shape + ev_MWh*ev_shape)

Symbols: p = population growth [1/yr], y = GDP growth [1/yr], ε = demand-GDP
elasticity [-], Δ = toYear − fromYear [yr]; H, E = added heat / EV energy over
the modeled window [MWh], scaled from annual GWh by (window hours / 8760);
h_t, e_t = unit-sum hourly shapes; s_c = column c's share of base energy.

Shape templates (deterministic, documented):
    heat  h_t ∝ season_m · diurnal_h,  season_m = (1+cos(2π(m−1)/12))/2 (Jan=1,
          Jul=0), diurnal_h = 0.4 + 0.6·(morning 06–09 + evening 17–22 ridges)
    ev    e_t ∝ 1.0 overnight (22–06, home charging) + 0.5 midday (10–16, work)
          + 0.15 otherwise; season-flat.

Pure over list-of-row dicts (the session sheet shape); unit-tested analytically.
"""
from __future__ import annotations

import math
from typing import Any

from .timeseries import series_index_col, shift_snapshot_year

HOURS_PER_YEAR = 8760.0


def _month_hour(stamp: str) -> tuple[int, int]:
    """(month 1-12, hour 0-23) from an ISO-ish snapshot label; safe fallbacks."""
    try:
        month = int(stamp[5:7])
    except (ValueError, IndexError):
        month = 1
    hour = 0
    for sep in ("T", " "):
        if sep in stamp:
            try:
                hour = int(stamp.split(sep, 1)[1][:2])
            except (ValueError, IndexError):
                hour = 0
            break
    return max(1, min(12, month)), max(0, min(23, hour))


def heat_shape_weight(month: int, hour: int) -> float:
    """Unnormalised heat-electrification weight: winter-peaking seasonal factor
    times a morning/evening diurnal ridge."""
    season = (1.0 + math.cos(2.0 * math.pi * (month - 1) / 12.0)) / 2.0  # Jan=1, Jul=0
    diurnal = 0.4
    if 6 <= hour <= 9 or 17 <= hour <= 22:
        diurnal = 1.0
    return season * diurnal


def ev_shape_weight(hour: int) -> float:
    """Unnormalised EV-charging weight: overnight home charging + a work-hours
    bump; season-flat."""
    if hour >= 22 or hour < 6:
        return 1.0
    if 10 <= hour <= 16:
        return 0.5
    return 0.15


def driver_demand_forecast(
    rows: list[dict[str, Any]],
    *,
    from_year: int,
    to_year: int,
    pop_growth_pct: float = 0.0,
    gdp_growth_pct: float = 0.0,
    gdp_elasticity: float = 0.5,
    heat_added_gwh: float = 0.0,
    ev_added_gwh: float = 0.0,
    snapshot_weight: float = 1.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Forecast a demand sheet to ``to_year`` from drivers.

    Args:
        rows: The demand series rows (``loads-p_set`` shape).
        from_year / to_year: Base and target years (Δ may be 0 for shape-only).
        pop_growth_pct / gdp_growth_pct: Annual driver growth (%/yr).
        gdp_elasticity: Demand elasticity to GDP (0–1 typical).
        heat_added_gwh / ev_added_gwh: ANNUAL electrified heat / EV charging
            energy added by the target year (GWh/yr), window-scaled.
        snapshot_weight: Hours represented per row (aligns annual → window).

    Returns:
        ``(new_rows, meta)`` — snapshots re-dated to the target year, values
        reshaped; meta reports the factors and added energies actually applied.
    """
    if not rows:
        return [], {"macroFactor": 1.0, "heatAddedMwh": 0.0, "evAddedMwh": 0.0}
    index_col = series_index_col(list(rows[0].keys()))
    delta = int(to_year) - int(from_year)
    g = ((1.0 + pop_growth_pct / 100.0) ** delta) * ((1.0 + gdp_elasticity * gdp_growth_pct / 100.0) ** delta)

    # Per-column share of base energy — bigger loads absorb more electrification.
    cols = [c for c in rows[0].keys() if c != index_col]
    col_sums = {c: 0.0 for c in cols}
    for r in rows:
        for c in cols:
            try:
                col_sums[c] += float(r.get(c) or 0.0)
            except (TypeError, ValueError):
                pass
    total = sum(col_sums.values())
    shares = {c: (col_sums[c] / total if total > 0 else 1.0 / max(1, len(cols))) for c in cols}

    # Window-scaled added energy + unit-sum shapes over the actual snapshots.
    window_hours = len(rows) * max(snapshot_weight, 1e-9)
    window_share = window_hours / HOURS_PER_YEAR
    heat_mwh = heat_added_gwh * 1000.0 * window_share
    ev_mwh = ev_added_gwh * 1000.0 * window_share

    stamps = [str(r.get(index_col, "")) for r in rows]
    mh = [_month_hour(s) for s in stamps]
    heat_w = [heat_shape_weight(m, h) for m, h in mh]
    ev_w = [ev_shape_weight(h) for _, h in mh]
    heat_norm = sum(w * snapshot_weight for w in heat_w) or 1.0
    ev_norm = sum(w * snapshot_weight for w in ev_w) or 1.0

    new_rows: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        heat_mw = heat_mwh * heat_w[i] / (heat_norm * max(snapshot_weight, 1e-9)) if heat_mwh > 0 else 0.0
        ev_mw = ev_mwh * ev_w[i] / (ev_norm * max(snapshot_weight, 1e-9)) if ev_mwh > 0 else 0.0
        nr: dict[str, Any] = {index_col: shift_snapshot_year(stamps[i], delta)}
        for c in cols:
            try:
                base = float(r.get(c) or 0.0)
            except (TypeError, ValueError):
                base = 0.0
            nr[c] = round(base * g + shares[c] * (heat_mw + ev_mw), 6)
        new_rows.append(nr)

    return new_rows, {
        "macroFactor": round(g, 6),
        "heatAddedMwh": round(heat_mwh, 3),
        "evAddedMwh": round(ev_mwh, 3),
        "windowShareOfYear": round(window_share, 6),
        "columns": len(cols),
    }
