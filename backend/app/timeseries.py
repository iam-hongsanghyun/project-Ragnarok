"""Shared time-series windowing + downsampling for the thin-client API.

Both the working-model session store (:mod:`session_store`) and the stored-run
results (:mod:`run_store`) serve time-series the same way: the client asks for a
row window ``[start, end)`` and a maximum number of points, and the server slices
and reduces server-side so the browser only ever receives what it draws.

Centralising the maths here keeps the two call sites identical and gives the
downsampling one well-tested home.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

# Candidate index columns for a time-series sheet, in priority order. A series
# row is ``{<index>: <timestamp>, <assetA>: value, …}``.
INDEX_KEYS = ("snapshot", "name", "datetime", "period")

Agg = Literal["mean", "point", "max", "min"]
VALID_AGG = ("mean", "point", "max", "min")


def series_index_col(columns: list[str]) -> str:
    """Return the index (time-axis) column among ``columns``."""
    for key in INDEX_KEYS:
        if key in columns:
            return key
    return columns[0] if columns else "snapshot"


def df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame → JSON-safe list of row dicts (NaN/NaT → None)."""
    return df.replace({np.nan: None}).to_dict(orient="records")


TransformOp = Literal["set", "scale", "offset", "shift", "interpolate", "clip", "grow"]
VALID_TRANSFORMS = ("set", "scale", "offset", "shift", "interpolate", "clip", "grow")


def transform_rows(
    rows: list[dict[str, Any]],
    index_col: str,
    op: TransformOp,
    *,
    columns: list[str] | None = None,
    value: float = 0.0,
    factor: float = 1.0,
    delta: float = 0.0,
    shift: int = 0,
    wrap: bool = True,
    min_value: float | None = None,
    max_value: float | None = None,
    growth_pct: float = 0.0,
) -> list[dict[str, Any]]:
    """Apply a bulk transform to the value columns of wide series ``rows`` (T1).

    ``rows`` are ``{index_col: <ts>, <asset>: <value>, …}``. Only the value
    columns are touched (all columns except ``index_col``, optionally restricted
    to ``columns``); the timestamp column is preserved. Non-numeric cells coerce
    to NaN → ``None``.

    Ops:
        set         ``v → value`` for EVERY cell in the selected columns
                    (blanks included — a "set" overwrites, unlike scale/offset)
        scale       ``v → v · factor``
        offset      ``v → v + delta``
        shift       roll each column by ``shift`` steps; ``wrap`` cyclically (no
                    gaps, reversible) or edge-fill the exposed end
        interpolate linear-fill blank/None/NaN cells (edge → nearest neighbour)
        clip        bound to ``[min_value, max_value]``
        grow        ramp-scale for a demand-growth forecast: the first snapshot is
                    unchanged and the last is scaled by ``1 + growth_pct/100``,
                    linearly in between

    Algorithm (shift): ``out[i] = in[(i - shift) mod N]`` when ``wrap`` else
    ``out[i] = in[i - shift]`` with the exposed end held at the nearest value.
    Algorithm (grow): ``out[i] = in[i] · (1 + (growth_pct/100)·i/(N-1))``.
    """
    if not rows:
        return rows
    df = pd.DataFrame(rows)
    value_cols = [c for c in df.columns if c != index_col]
    if columns:
        wanted = set(columns)
        value_cols = [c for c in value_cols if c in wanted]
    if not value_cols:
        return rows

    num = df[value_cols].apply(pd.to_numeric, errors="coerce")

    if op == "set":
        # Overwrite every selected cell with the constant — blanks included, so a
        # "set p_set = 7" fills the whole series (a scale/offset can't touch NaN).
        num = num.copy()
        num[:] = float(value)
    elif op == "scale":
        num = num * float(factor)
    elif op == "offset":
        num = num + float(delta)
    elif op == "shift":
        k = int(shift)
        if wrap:
            num = pd.DataFrame(
                {c: np.roll(num[c].to_numpy(dtype=float), k) for c in value_cols},
                index=num.index,
            )
        else:
            num = num.shift(k).ffill().bfill()
    elif op == "interpolate":
        num = num.interpolate(method="linear", limit_direction="both")
    elif op == "clip":
        lo = None if min_value is None else float(min_value)
        hi = None if max_value is None else float(max_value)
        num = num.clip(lower=lo, upper=hi)
    elif op == "grow":
        n = len(num)
        if n > 1:
            ramp = 1.0 + (float(growth_pct) / 100.0) * (np.arange(n) / (n - 1))
            num = num.mul(pd.Series(ramp, index=num.index), axis=0)
    else:
        raise ValueError(f"unknown transform op {op!r}")

    out = df.copy()
    for c in value_cols:
        out[c] = num[c]
    return out.replace({np.nan: None}).to_dict(orient="records")


def generate_snapshots(start: str, end: str, step_hours: float = 1.0) -> list[str]:
    """Snapshot timestamps for ``[start, end]`` at ``step_hours`` (T1 retarget).

    Returns ``"YYYY-MM-DD HH:MM"`` strings (the app's canonical snapshot form).
    """
    step = max(step_hours, 1e-6)
    # pandas freq wants an integer-ish alias; minutes keep sub-hourly steps exact.
    freq = f"{int(round(step * 60))}min"
    idx = pd.date_range(start=start, end=end, freq=freq)
    return [ts.strftime("%Y-%m-%d %H:%M") for ts in idx]


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


def year_of(value: Any) -> int | None:
    """Calendar year of a snapshot value, or None if unparseable."""
    try:
        return int(pd.Timestamp(str(value)).year)
    except Exception:  # noqa: BLE001
        return None


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


def downsample(df: pd.DataFrame, max_points: int, agg: Agg, index_col: str) -> pd.DataFrame:
    """Reduce ``df`` to at most ``max_points`` rows using ``agg``.

    Algorithm:
        Split the N rows into ``min(N, max_points)`` contiguous buckets
        (``numpy.array_split``). Each bucket yields one output row, labelled by
        the bucket's first index value:
          * ``mean`` — arithmetic mean of each numeric column over the bucket
          * ``max`` / ``min`` — extremum of each numeric column over the bucket
          * ``point`` — the bucket's first row verbatim (decimation)
        ASCII: out[k] = reduce(rows[bucket_k]); buckets partition [0, N).

    Non-numeric value cells coerce to NaN under mean/max/min (not meaningful to
    aggregate); ``point`` preserves them.
    """
    n = len(df)
    if max_points <= 0 or n <= max_points:
        return df.reset_index(drop=True)

    value_cols = [c for c in df.columns if c != index_col]
    buckets = np.array_split(np.arange(n), max_points)
    out_rows: list[dict[str, Any]] = []
    for bucket in buckets:
        if len(bucket) == 0:
            continue
        sub = df.iloc[bucket]
        first = sub.iloc[0]
        row: dict[str, Any] = {index_col: first[index_col]}
        if agg == "point":
            for col in value_cols:
                row[col] = first[col]
        else:
            for col in value_cols:
                numeric = pd.to_numeric(sub[col], errors="coerce")
                if agg == "mean":
                    value = numeric.mean()
                elif agg == "max":
                    value = numeric.max()
                else:  # min
                    value = numeric.min()
                row[col] = None if pd.isna(value) else float(value)
        out_rows.append(row)
    return pd.DataFrame(out_rows)


def slice_and_reduce(
    df: pd.DataFrame,
    *,
    start: int,
    end: int | None,
    max_points: int,
    agg: str,
    index_col: str,
) -> dict[str, Any]:
    """Window ``df`` to ``[start, end)`` then downsample to ``max_points``.

    Returns ``{indexCol, total, window:{start,end}, returned, agg, columns, rows}``.
    Column selection (pushdown) is the caller's job — do it at the Parquet read so
    only needed columns are loaded.
    """
    if agg not in VALID_AGG:
        agg = "mean"
    max_points = max(1, int(max_points))
    total = len(df)
    start = max(0, int(start))
    end = total if end is None else min(total, int(end))
    if end < start:
        end = start
    window = df.iloc[start:end]
    reduced = downsample(window, max_points, agg, index_col)  # type: ignore[arg-type]
    return {
        "indexCol": index_col,
        "total": total,
        "window": {"start": start, "end": end},
        "returned": len(reduced),
        "agg": agg,
        "columns": [str(c) for c in reduced.columns],
        "rows": df_to_records(reduced),
    }
