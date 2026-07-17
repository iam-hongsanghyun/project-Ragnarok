"""EV movement → per-region demand reshaping (M4, minimal first cut).

The user-scoped simplification of "EV energy physically moves between regions":
rather than modelling a migrating state of charge (a new component class), we
reshape each region's demand series BEFORE the solve. Vehicles charge where
they are: the home-charging share lands on each region's **home** share with an
overnight shape, the rest lands on the **work** share with a workday shape — so
home-heavy regions gain overnight load and work-heavy regions gain daytime
load. The energy follows the fleet's location by time of day, which is exactly
the region-to-region shift, without new PyPSA components.

Algorithm (per snapshot t, load column c):
    $$ d'_{c,t} = d_{c,t} + E \\left[ \\alpha\\,h_c\\,n_t + (1-\\alpha)\\,w_c\\,m_t \\right] $$
    ASCII: new = base + E*(alpha*home_share*night_shape + (1-alpha)*work_share*day_shape)

Symbols: E = fleet charging energy over the window [MWh] = vehicles ×
kWh/vehicle/day × window_days / 1000; α = home-charging share [-]; h_c, w_c =
region c's share of homes / workplaces (default: ∝ base energy); n_t, m_t =
unit-sum overnight (22–06) / workday (09–17) charging shapes.

Pure over the ``loads-p_set`` row shape; unit-tested analytically.
"""
from __future__ import annotations

from typing import Any

from .timeseries import series_index_col

HOURS_PER_DAY = 24.0


def _hour(stamp: str) -> int:
    for sep in ("T", " "):
        if sep in stamp:
            try:
                return max(0, min(23, int(stamp.split(sep, 1)[1][:2])))
            except (ValueError, IndexError):
                return 0
    return 0


def overnight_weight(hour: int) -> float:
    """Home charging: overnight plug-in (22:00–06:00), light shoulder."""
    return 1.0 if (hour >= 22 or hour < 6) else 0.1


def workday_weight(hour: int) -> float:
    """Workplace charging: office hours (09:00–17:00)."""
    return 1.0 if 9 <= hour <= 17 else 0.05


def ev_demand_adjustment(
    rows: list[dict[str, Any]],
    *,
    fleet_size: float,
    kwh_per_vehicle_day: float,
    home_charging_share: float = 0.7,
    home_shares: dict[str, float] | None = None,
    work_shares: dict[str, float] | None = None,
    snapshot_weight: float = 1.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Add the EV fleet's charging load onto the demand series, region-aware.

    Args:
        rows: ``loads-p_set`` rows.
        fleet_size: Number of vehicles.
        kwh_per_vehicle_day: Average charging energy per vehicle per day (kWh).
        home_charging_share: α — share of energy charged at home (0–1).
        home_shares / work_shares: Region (column) shares of homes / workplaces;
            each normalised over the demand columns. Default: ∝ base energy.
        snapshot_weight: Hours represented per row.

    Returns:
        ``(new_rows, meta)`` with the added energy split reported.
    """
    if not rows:
        return [], {"addedMwh": 0.0}
    index_col = series_index_col(list(rows[0].keys()))
    cols = [c for c in rows[0].keys() if c != index_col]

    # Default shares ∝ each column's base energy; user shares are normalised.
    def _norm(shares: dict[str, float] | None) -> dict[str, float]:
        if shares:
            picked = {c: max(0.0, float(shares.get(c, 0.0))) for c in cols}
        else:
            picked = {c: 0.0 for c in cols}
            for r in rows:
                for c in cols:
                    try:
                        picked[c] += float(r.get(c) or 0.0)
                    except (TypeError, ValueError):
                        pass
        total = sum(picked.values())
        if total <= 0:
            return {c: 1.0 / max(1, len(cols)) for c in cols}
        return {c: v / total for c, v in picked.items()}

    h_share = _norm(home_shares)
    w_share = _norm(work_shares)

    alpha = min(1.0, max(0.0, home_charging_share))
    window_hours = len(rows) * max(snapshot_weight, 1e-9)
    window_days = window_hours / HOURS_PER_DAY
    energy_mwh = fleet_size * kwh_per_vehicle_day * window_days / 1000.0

    hours = [_hour(str(r.get(index_col, ""))) for r in rows]
    night_w = [overnight_weight(h) for h in hours]
    day_w = [workday_weight(h) for h in hours]
    night_norm = sum(w * snapshot_weight for w in night_w) or 1.0
    day_norm = sum(w * snapshot_weight for w in day_w) or 1.0

    new_rows: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        # night_norm/day_norm already carry snapshot_weight (MWh per unit shape
        # weight), so dividing by them alone yields MW that integrate to energy_mwh.
        night_mw = energy_mwh * alpha * night_w[i] / night_norm
        day_mw = energy_mwh * (1.0 - alpha) * day_w[i] / day_norm
        nr: dict[str, Any] = {index_col: r.get(index_col)}
        for c in cols:
            try:
                base = float(r.get(c) or 0.0)
            except (TypeError, ValueError):
                base = 0.0
            nr[c] = round(base + h_share[c] * night_mw + w_share[c] * day_mw, 6)
        new_rows.append(nr)

    return new_rows, {
        "addedMwh": round(energy_mwh, 3),
        "homeMwh": round(energy_mwh * alpha, 3),
        "workMwh": round(energy_mwh * (1.0 - alpha), 3),
        "windowDays": round(window_days, 4),
        "columns": len(cols),
    }
