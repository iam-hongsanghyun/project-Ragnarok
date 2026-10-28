"""Demand module: growth and retargeting of a demand series onto another horizon.

PyPSA takes the loads as authored. This module is what turns "this year's profile" into "the profile for the
study year" *before* the model is sent to PyPSA, and writes the result into the workbook as visible rows:

* :func:`retarget_rows` - reindex a wide series onto new snapshots (tile / pad / truncate);
* :func:`shift_snapshot_year` - move a snapshot's year (29 Feb falls back to 28 Feb);
* :func:`growth_factor` - compound or linear growth over a number of years;
* :func:`estimate_growth_factor` - a trend fitted on the series' own annual totals (log-linear OLS, ARIMA, Prophet).

The session endpoints (``/api/session/...``) call these; ``app.timeseries`` re-exports them for older imports.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def retarget_rows(
    rows: list[dict[str, Any]],
    index_col: str,
    new_snapshots: list[str],
    fill: str = "tile",
) -> list[dict[str, Any]]:
    """Reindex wide series ``rows`` onto ``new_snapshots`` positionally (T1).

    Each new snapshot takes the source row at the same position; when the new
    window is longer, ``tile`` cycles the source (reuse a base year to fill future
    years) and ``pad`` repeats the last row. Shorter windows truncate. The value
    columns carry over; the index column is set to the new snapshot.
    """
    out: list[dict[str, Any]] = []
    n_src = len(rows)
    for i, snap in enumerate(new_snapshots):
        row: dict[str, Any] = {}
        if n_src:
            if i < n_src:
                src = rows[i]
            elif fill == "pad":
                src = rows[-1]
            else:  # tile
                src = rows[i % n_src]
            row = {k: v for k, v in src.items() if k != index_col}
        row[index_col] = snap
        out.append(row)
    return out




def shift_snapshot_year(s: str, delta: int) -> str:
    """Shift a snapshot's year by ``delta``, preserving month/day/hour.

    Feb 29 in a source year that lands on a non-leap target falls back to Feb 28.
    Unparseable values pass through unchanged.
    """
    try:
        ts = pd.Timestamp(s)
    except Exception:  # noqa: BLE001
        return s
    try:
        return ts.replace(year=ts.year + delta).strftime("%Y-%m-%d %H:%M")
    except ValueError:  # e.g. 29 Feb → 28 Feb
        return ts.replace(year=ts.year + delta, day=28).strftime("%Y-%m-%d %H:%M")


def growth_factor(growth_pct: float, delta_years: int, method: str = "cagr") -> float:
    """Multiplicative growth over ``delta_years`` (T1 forecast).

    ``cagr``: ``(1 + g)^Δ`` (compound); ``linear``: ``1 + g·Δ``.
    """
    g = float(growth_pct) / 100.0
    if method == "linear":
        return 1.0 + g * delta_years
    return (1.0 + g) ** delta_years


# ── Statistical multi-year forecast (T1 "finalise": ARIMA / Prophet / trend) ──
STAT_METHODS = ("regression", "arima", "prophet")


def annual_totals(rows_by_sheet: dict[str, list[dict[str, Any]]]) -> dict[int, float]:
    """Sum the numeric values of the given series sheets per calendar year.

    ``rows_by_sheet`` maps a series-sheet name to its wide rows; the year is read
    from each row's index (snapshot) column. Used to fit a demand-growth trend.
    """
    totals: dict[int, float] = {}
    for rows in rows_by_sheet.values():
        if not rows:
            continue
        from backend.app.timeseries import series_index_col  # lazy: timeseries re-exports this module
        index_col = series_index_col(list(rows[0].keys()))
        for r in rows:
            try:
                year = pd.Timestamp(str(r.get(index_col))).year
            except Exception:  # noqa: BLE001
                continue
            s = sum(
                float(v) for k, v in r.items()
                if k != index_col and isinstance(v, (int, float)) and not isinstance(v, bool)
            )
            totals[year] = totals.get(year, 0.0) + s
    return totals


def estimate_growth_factor(
    rows_by_sheet: dict[str, list[dict[str, Any]]],
    from_year: int,
    to_year: int,
    method: str,
) -> tuple[float, str]:
    """Fit a demand-growth trend on the series' annual totals and project the
    multiplicative factor from ``from_year`` to ``to_year`` (T1 forecast).

    ``regression`` = log-linear OLS (keyless), ``arima`` = statsmodels
    ARIMA(1,1,0), ``prophet`` = Prophet — all on the annual totals. Needs ≥3
    distinct years of history; raises :class:`ValueError` otherwise (the caller
    turns that into a 400 pointing the user at CAGR/linear).

    Algorithm:
        $$ f = \\hat{y}(t_\\text{to}) \\,/\\, \\hat{y}(t_\\text{from}) $$
        ASCII: factor = projected_total(to_year) / baseline_total(from_year).
    """
    totals = annual_totals(rows_by_sheet)
    years = sorted(totals)
    if len(years) < 3:
        raise ValueError(
            f"'{method}' needs at least 3 years of history in the demand series "
            f"(found {len(years)}). Import more years, or use CAGR/linear with a growth %."
        )
    x = np.asarray(years, dtype=float)
    y = np.asarray([totals[yr] for yr in years], dtype=float)
    base = float(totals.get(from_year) or y[0]) or 1e-9

    if method == "regression":
        mask = y > 0
        slope, intercept = np.polyfit(x[mask], np.log(y[mask]), 1)
        proj = float(np.exp(intercept + slope * to_year))
        proj_from = float(np.exp(intercept + slope * from_year))
        factor = proj / max(proj_from, 1e-9)
        note = f"log-linear trend ≈ {(np.exp(slope) - 1) * 100:.1f} %/yr"
    elif method == "arima":
        import warnings

        from statsmodels.tsa.arima.model import ARIMA

        ser = pd.Series(y, index=pd.PeriodIndex([pd.Period(int(yr), freq="Y") for yr in years], freq="Y"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # non-stationary starts / small-sample notes
            fit = ARIMA(ser, order=(1, 1, 0)).fit()
            if to_year > years[-1]:
                proj = float(fit.forecast(steps=to_year - years[-1]).iloc[-1])
            else:
                proj = float(totals.get(to_year, y[-1]))
        factor = proj / base
        note = "ARIMA(1,1,0) on annual totals"
    elif method == "prophet":
        import logging

        logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
        from prophet import Prophet

        df = pd.DataFrame({"ds": pd.to_datetime([f"{yr}-01-01" for yr in years]), "y": y})
        m = Prophet(yearly_seasonality=False, weekly_seasonality=False, daily_seasonality=False)
        m.fit(df)
        pred = m.predict(pd.DataFrame({"ds": pd.to_datetime([f"{to_year}-01-01"])}))
        factor = float(pred["yhat"].iloc[0]) / base
        note = "Prophet on annual totals"
    else:
        raise ValueError(f"unknown forecast method: {method!r}")
    return max(factor, 0.0), note


