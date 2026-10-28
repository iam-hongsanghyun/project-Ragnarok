"""Screening statistics — pure pandas / numpy / scipy functions (no I/O).

A statistical pre-screen of candidate solar and wind sites, and of the regions
they sit in, on their historical capacity-factor (CF) series, before the
expansion-based siting scan. Everything here takes a ``DataFrame`` (index =
timestamps, one column per site or region, values = CF in 0-1) and returns
arrays / frames; the dataset store and the HTTP layer sit in :mod:`.datasets`
and ``app/routers/screening.py``.

Regions enter in two ways: aggregated from sites (:func:`aggregate_regions`,
a weighted mean of the member sites' CF) or uploaded as a series of their own.
Either way a region is one more column, so every site statistic (correlation,
lag, clustering, portfolio metrics, optimiser) applies to regions unchanged;
:func:`within_between_correlation` and :func:`site_region_correlation` are the
statistics that need both levels.

Conventions
    * CF is dimensionless in [0, 1]; the aggregation to every basis is the mean.
    * Correlations are pairwise-complete; a constant series has no correlation
      and yields NaN (the HTTP layer turns NaN into ``null``).
    * "P90" is the *exceedance* convention of the energy industry: the output
      level exceeded in 90 % of the hours, i.e. the 10th percentile of the
      distribution; P10 is the 90th percentile.
"""
from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import (
    fcluster,
    leaves_list,
    linkage,
    optimal_leaf_ordering,
)
from scipy.optimize import linprog, minimize
from scipy.spatial.distance import squareform

BASES = ("hourly", "daily", "weekly", "monthly", "seasonal", "diurnal", "month_hour", "custom")
METHODS = ("pearson", "spearman")
Method = Literal["pearson", "spearman"]

_EARTH_RADIUS_KM = 6371.0

#: Meteorological seasons: month number -> label.
DEFAULT_SEASONS: dict[int, str] = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}

_EPS = 1e-12


# ── geometry ──────────────────────────────────────────────────────────────────


def haversine_matrix_km(lat: np.ndarray | list[float], lon: np.ndarray | list[float]) -> np.ndarray:
    """Pairwise great-circle distance matrix between WGS84 points, in km.

    Algorithm:
        $$ d_{ij} = 2R \\arcsin\\sqrt{\\sin^2\\tfrac{\\phi_j-\\phi_i}{2}
            + \\cos\\phi_i\\cos\\phi_j\\sin^2\\tfrac{\\lambda_j-\\lambda_i}{2}} $$
        ASCII: d_ij = 2*R*asin(sqrt(sin^2(dphi/2) + cos(phi_i)*cos(phi_j)*sin^2(dlam/2)))

    where $R$ = 6371 km (mean Earth radius), $\\phi$ latitude and $\\lambda$
    longitude in radians.

    Args:
        lat: latitudes in degrees, shape (n,).
        lon: longitudes in degrees, shape (n,).

    Returns:
        Symmetric (n, n) matrix in km with a zero diagonal.
    """
    phi = np.radians(np.asarray(lat, dtype=float))
    lam = np.radians(np.asarray(lon, dtype=float))
    dphi = phi[None, :] - phi[:, None]
    dlam = lam[None, :] - lam[:, None]
    a = np.sin(dphi / 2) ** 2 + np.cos(phi)[:, None] * np.cos(phi)[None, :] * np.sin(dlam / 2) ** 2
    d = 2 * _EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    np.fill_diagonal(d, 0.0)
    return d


# ── windowing and resampling ──────────────────────────────────────────────────


def filter_window(
    df: pd.DataFrame,
    start: str | None = None,
    end: str | None = None,
    months: list[int] | None = None,
    utc_offset_hours: float = 0.0,
) -> pd.DataFrame:
    """Shift the clock, then keep a date range and / or a set of calendar months.

    Args:
        df: frame indexed by UTC timestamps.
        start: first timestamp kept (inclusive, ISO date or datetime, analysis clock).
        end: last timestamp kept (a bare date keeps the whole day).
        months: calendar months (1-12) to keep, e.g. ``[6, 7, 8]`` for JJA only.
        utc_offset_hours: hours added to the UTC index before anything else
            (e.g. 9 for Korea) so diurnal and daily bases follow local time.
    """
    out = df
    if utc_offset_hours:
        out = out.copy()
        out.index = out.index + pd.Timedelta(hours=float(utc_offset_hours))
    if start:
        out = out[out.index >= pd.Timestamp(start)]
    if end:
        stamp = pd.Timestamp(end)
        if len(str(end).strip()) <= 10:  # a bare date: include that whole day
            stamp = stamp + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        out = out[out.index <= stamp]
    if months:
        out = out[out.index.month.isin([int(m) for m in months])]
    return out


def _season_start_months(season_map: dict[int, str]) -> dict[str, int]:
    """First calendar month of each season label (cyclically: the member whose predecessor is not a member)."""
    members: dict[str, set[int]] = {}
    for month, label in season_map.items():
        members.setdefault(label, set()).add(int(month))
    out: dict[str, int] = {}
    for label, months in members.items():
        starts = [m for m in sorted(months) if ((m - 2) % 12) + 1 not in months]
        out[label] = starts[0] if starts else 1
    return out


def season_keys(index: pd.DatetimeIndex, season_map: dict[int, str]) -> tuple[np.ndarray, np.ndarray]:
    """Season label and season-year of each timestamp.

    A season that wraps the year boundary (DJF) belongs to the year it *starts*
    in: Jan-Feb 2020 are part of ``DJF 2019``.

    Returns:
        ``(labels, season_years)``; months missing from ``season_map`` get label ``""``.
    """
    starts = _season_start_months(season_map)
    months = np.asarray(index.month)
    years = np.asarray(index.year)
    labels = np.array([season_map.get(int(m), "") for m in months], dtype=object)
    start_of = np.array([starts.get(str(lbl), 1) for lbl in labels])
    season_years = years - (months < start_of).astype(int)
    return labels, season_years


def resample_basis(
    df: pd.DataFrame,
    basis: str,
    *,
    rule: str | None = None,
    season_map: dict[int, str] | None = None,
) -> pd.DataFrame:
    """Aggregate hourly (raw) CF to the analysis basis; the aggregation is the mean.

    Algorithm:
        $$ \\bar{x}_k = \\frac{1}{|T_k|}\\sum_{t\\in T_k} x_t $$
        ASCII: xbar_k = sum(x_t for t in T_k) / |T_k|

    where $T_k$ is the set of source timestamps that fall in bucket $k$:

    * ``hourly``      - raw rows, no aggregation (the native step of the dataset).
    * ``daily`` / ``weekly`` / ``monthly`` - calendar buckets (``D`` / ``W`` / ``MS``).
    * ``seasonal``    - one row per season-year (``2019 DJF``), months mapped by
      ``season_map`` (default DJF/MAM/JJA/SON); months not in the map are dropped.
    * ``diurnal``     - 24 rows: the mean CF of each hour of day.
    * ``month_hour``  - 288 rows: mean CF of each (month, hour-of-day) cell.
    * ``custom``      - any pandas offset alias in ``rule`` (``"6h"``, ``"2W"``, ``"QS"``).

    Raises:
        ValueError: unknown basis, or ``custom`` without a valid ``rule``.
    """
    if basis not in BASES:
        raise ValueError(f"Unknown basis {basis!r}; one of {list(BASES)}.")
    if len(df) == 0:
        return df
    if basis == "hourly":
        return df
    if basis == "daily":
        return df.resample("D").mean().dropna(how="all")
    if basis == "weekly":
        return df.resample("W").mean().dropna(how="all")
    if basis == "monthly":
        return df.resample("MS").mean().dropna(how="all")
    if basis == "custom":
        if not rule:
            raise ValueError("basis 'custom' needs a pandas offset alias in `rule` (e.g. '6h', '2W', 'QS').")
        try:
            pd.tseries.frequencies.to_offset(rule)
        except ValueError as exc:
            raise ValueError(f"Invalid pandas offset alias {rule!r}.") from exc
        return df.resample(rule).mean().dropna(how="all")
    if basis == "diurnal":
        out = df.groupby(df.index.hour).mean()
        out.index.name = "hour"
        return out
    if basis == "month_hour":
        out = df.groupby([df.index.month, df.index.hour]).mean()
        out.index.names = ["month", "hour"]
        return out
    # seasonal
    smap = {int(k): str(v) for k, v in (season_map or DEFAULT_SEASONS).items()}
    labels, years = season_keys(df.index, smap)
    keep = labels != ""
    sub = df[keep]
    if len(sub) == 0:
        return sub
    out = sub.groupby([years[keep], labels[keep]], sort=False).mean()
    out.index = pd.Index([f"{int(y)} {s}" for y, s in out.index], name="season")
    return out


def index_labels(index: pd.Index) -> list[str]:
    """JSON-friendly labels for any basis index (timestamps, hours, (month, hour) pairs, seasons)."""
    if isinstance(index, pd.MultiIndex):
        return [f"{int(m):02d}-{int(h):02d}" for m, h in index]
    if isinstance(index, pd.DatetimeIndex):
        return [t.strftime("%Y-%m-%d %H:%M") for t in index]
    return [str(v) for v in index]


def anomalies(
    df: pd.DataFrame, *, by: Literal["month_hour", "hour"] = "month_hour", standardise: bool = False
) -> pd.DataFrame:
    """Hourly anomalies: CF minus its mean diurnal (and seasonal) cycle.

    Two solar sites look alike mostly because the sun rises and sets for both;
    removing the climatological cycle leaves the weather signal.

    Algorithm:
        $$ a_t = x_t - \\bar{x}_{c(t)} \\quad\\Big[\\;/\\ \\sigma_{c(t)}\\Big] $$
        ASCII: a_t = x_t - mean_c(t)   [ / std_c(t) ]

    where $c(t)$ is the cell of timestamp $t$: (month, hour-of-day) for
    ``by="month_hour"`` (removes diurnal *and* seasonal cycle) or hour-of-day
    only for ``by="hour"``; $\\bar x_c$, $\\sigma_c$ are the cell mean and
    standard deviation. With ``standardise`` the anomaly is in units of
    $\\sigma_c$ (cells with $\\sigma_c = 0$ give 0, e.g. night hours for solar).
    """
    keys: list[Any] = [df.index.month, df.index.hour] if by == "month_hour" else [df.index.hour]
    grp = df.groupby(keys)
    out = df - grp.transform("mean")
    if standardise:
        sd = grp.transform("std")
        out = (out / sd.where(sd > _EPS)).fillna(0.0)
    return out


# ── correlation ───────────────────────────────────────────────────────────────


def correlation_matrix(df: pd.DataFrame, method: str = "pearson") -> pd.DataFrame:
    """Pairwise correlation between the columns of ``df``.

    Algorithm:
        Pearson:  $$ r_{ij} = \\frac{\\sum_t (x_{it}-\\bar x_i)(x_{jt}-\\bar x_j)}
            {\\sqrt{\\sum_t (x_{it}-\\bar x_i)^2\\sum_t (x_{jt}-\\bar x_j)^2}} $$
        Spearman: $r^{s}_{ij}$ = Pearson correlation of the average ranks
        $\\mathrm{rank}(x_{it})$ (ties share the mean rank).
        ASCII: r_ij = cov(x_i, x_j) / (std(x_i) * std(x_j)); spearman = r of ranks

    Spearman is robust to the skew of CF distributions (many zeros for solar).
    A constant column has no correlation: its row and column are NaN.

    Raises:
        ValueError: unknown method.
    """
    if method not in METHODS:
        raise ValueError(f"Unknown method {method!r}; one of {list(METHODS)}.")
    return df.corr(method=method)


def reference_correlation(df: pd.DataFrame, reference: pd.Series, method: str = "pearson") -> pd.Series:
    """Correlation of every site column with one reference series (load or price).

    Both inputs must already be on the same basis; they are joined on their
    index (inner join) and each pair uses its complete observations.

    Algorithm:
        $$ r_{i,ref} = \\mathrm{corr}(x_{it}, y_t) $$ with $y_t$ the reference
        (MW or currency/MWh); ASCII: r_i = corr(x_i, y).

    Returns:
        Series indexed by site name; NaN where a series is constant or there is no overlap.
    """
    if method not in METHODS:
        raise ValueError(f"Unknown method {method!r}; one of {list(METHODS)}.")
    joined = df.join(reference.rename("__ref__"), how="inner")
    if len(joined) < 2:
        return pd.Series(np.nan, index=df.columns, dtype=float)
    return joined[list(df.columns)].corrwith(joined["__ref__"], method=method)


def correlation_vs_distance(corr: pd.DataFrame, lat: list[float], lon: list[float]) -> pd.DataFrame:
    """Upper-triangle site pairs with their distance and correlation.

    Args:
        corr: (n, n) correlation matrix, ordered like ``lat`` / ``lon``.
        lat, lon: site coordinates in degrees.

    Returns:
        Frame with columns ``a``, ``b``, ``km``, ``r``.
    """
    dist = haversine_matrix_km(lat, lon)
    names = list(corr.columns)
    iu, ju = np.triu_indices(len(names), k=1)
    return pd.DataFrame(
        {
            "a": [names[i] for i in iu],
            "b": [names[j] for j in ju],
            "km": dist[iu, ju],
            "r": corr.to_numpy()[iu, ju],
        }
    )


def lagged_cross_correlation(
    a: np.ndarray | pd.Series, b: np.ndarray | pd.Series, max_lag_steps: int
) -> tuple[np.ndarray, np.ndarray]:
    """Cross-correlation of two regular series at integer lags ``-N..N`` (weather fronts).

    Algorithm:
        $$ r_{ab}(k) = \\mathrm{corr}\\big(a_t,\\; b_{t+k}\\big),\\quad k=-N..N $$
        ASCII: r(k) = corr(a[t], b[t+k]) over the overlap of the two shifted series.

    A positive peak lag $k^*$ means $b$ repeats what $a$ did $k^*$ steps
    earlier (a front moving from $a$ to $b$). The series must be on a regular
    grid (positions equal time steps); NaN pairs are skipped.

    Args:
        a, b: equal-length 1-D arrays (CF).
        max_lag_steps: N, number of steps either side.

    Returns:
        ``(lags, r)`` — lags in steps (``-N..N``) and the correlation at each.
    """
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    n = len(x)
    if n != len(y):
        raise ValueError("lagged_cross_correlation needs equal-length series.")
    big_n = int(max(0, min(max_lag_steps, n - 3)))
    lags = np.arange(-big_n, big_n + 1)
    out = np.full(len(lags), np.nan)
    for idx, k in enumerate(lags):
        xs, ys = (x[: n - k], y[k:]) if k >= 0 else (x[-k:], y[: n + k])
        ok = np.isfinite(xs) & np.isfinite(ys)
        if ok.sum() < 3:
            continue
        xs, ys = xs[ok] - xs[ok].mean(), ys[ok] - ys[ok].mean()
        den = math.sqrt(float(xs @ xs) * float(ys @ ys))
        if den > _EPS:
            out[idx] = float(xs @ ys) / den
    return lags, out


# ── clustering ────────────────────────────────────────────────────────────────


def cluster_sites(
    corr: pd.DataFrame,
    *,
    k: int | None = None,
    threshold: float | None = None,
    method: str = "average",
) -> dict[str, Any]:
    """Hierarchical clustering of sites on the distance $1 - r$.

    Algorithm:
        $$ D_{ij} = 1 - r_{ij} \\in [0, 2] $$ then agglomerative linkage
        (``average`` = UPGMA by default) on $D$; clusters are the cut of the tree
        into ``k`` groups, or at cophenetic distance ``threshold``.
        ASCII: D_ij = 1 - r_ij; Z = linkage(D, method); labels = cut(Z, k | threshold)

    NaN correlations (constant series) are treated as uncorrelated ($D$ = 1).

    Returns:
        ``{"order": [...], "labels": {site: cluster}, "linkage": [[i, j, dist, n], ...],
        "nClusters": int}`` — ``order`` is the dendrogram leaf order (similar sites adjacent),
        clusters are numbered 1.. in that order.

    Raises:
        ValueError: neither/both of k and threshold, k out of range, unknown method.
    """
    names = [str(c) for c in corr.columns]
    n = len(names)
    if n == 0:
        raise ValueError("No sites to cluster.")
    if (k is None) == (threshold is None):
        raise ValueError("Give exactly one of k (number of clusters) or threshold (1 - r cut height).")
    if method not in ("average", "complete", "single", "ward"):
        raise ValueError(f"Unknown linkage {method!r}.")
    if n == 1:
        return {"order": names, "labels": {names[0]: 1}, "linkage": [], "nClusters": 1}
    dist = 1.0 - np.nan_to_num(corr.to_numpy(dtype=float), nan=0.0)
    dist = np.clip((dist + dist.T) / 2.0, 0.0, 2.0)
    np.fill_diagonal(dist, 0.0)
    z = linkage(squareform(dist, checks=False), method=method)
    z = optimal_leaf_ordering(z, squareform(dist, checks=False))
    order_idx = [int(i) for i in leaves_list(z)]
    if k is not None:
        if not 1 <= int(k) <= n:
            raise ValueError(f"k must be between 1 and {n}.")
        raw = fcluster(z, t=int(k), criterion="maxclust")
    else:
        raw = fcluster(z, t=float(threshold), criterion="distance")  # type: ignore[arg-type]
    renumber: dict[int, int] = {}
    for i in order_idx:
        renumber.setdefault(int(raw[i]), len(renumber) + 1)
    labels = {names[i]: renumber[int(raw[i])] for i in range(n)}
    return {
        "order": [names[i] for i in order_idx],
        "labels": labels,
        "linkage": [[int(r[0]), int(r[1]), float(r[2]), int(r[3])] for r in z],
        "nClusters": len(renumber),
    }


# ── portfolio ─────────────────────────────────────────────────────────────────


def normalise_weights(weights: dict[str, float], names: list[str]) -> np.ndarray:
    """Weights in the column order ``names``, scaled to sum to 1.

    Raises:
        ValueError: unknown site, negative weight or a non-positive total.
    """
    unknown = [s for s in weights if s not in names]
    if unknown:
        raise ValueError(f"Weights given for unknown site(s): {unknown}.")
    w = np.array([float(weights.get(n, 0.0)) for n in names])
    if np.any(w < 0):
        raise ValueError("Weights must be non-negative (long-only portfolio).")
    total = float(w.sum())
    if total <= 0:
        raise ValueError("Weights must sum to a positive number.")
    return w / total


def portfolio_series(df: pd.DataFrame, w: np.ndarray) -> pd.Series:
    """Combined output $y_t = \\sum_i w_i x_{it}$ (weights sum to 1, so $y$ is a CF in 0-1)."""
    return pd.Series(df.to_numpy(dtype=float) @ np.asarray(w, dtype=float), index=df.index, name="portfolio")


def portfolio_variance(w: np.ndarray, cov: np.ndarray) -> float:
    """Variance of the weighted sum.

    Algorithm:
        $$ \\sigma_p^2 = w^{\\top}\\Sigma\\,w $$
        ASCII: var_p = w' * Cov * w
        with $w$ the weights (sum 1) and $\\Sigma$ the site covariance matrix (CF^2).
        Uncorrelated equal-variance sites with equal weights give $\\sigma^2/n$.
    """
    w = np.asarray(w, dtype=float)
    return float(w @ np.asarray(cov, dtype=float) @ w)


def covariance_matrix(df: pd.DataFrame) -> np.ndarray:
    """Sample covariance (ddof = 1) of the site columns, always 2-D."""
    return np.atleast_2d(np.cov(df.to_numpy(dtype=float), rowvar=False, ddof=1))


def min_variance_weights_two_sites(sigma1: float, sigma2: float, rho: float) -> tuple[float, float]:
    """Analytic unconstrained minimum-variance weights of two sites.

    Algorithm:
        $$ w_1^{*} = \\frac{\\sigma_2^2 - \\rho\\sigma_1\\sigma_2}
            {\\sigma_1^2 + \\sigma_2^2 - 2\\rho\\sigma_1\\sigma_2},\\qquad w_2^{*} = 1 - w_1^{*} $$
        ASCII: w1 = (s2^2 - rho*s1*s2) / (s1^2 + s2^2 - 2*rho*s1*s2); w2 = 1 - w1

    where $\\sigma_i$ is the CF standard deviation of site $i$ and $\\rho$ their
    correlation. The result may leave [0, 1] (a short position); the long-only
    optimiser clips it to the boundary.
    """
    den = sigma1**2 + sigma2**2 - 2.0 * rho * sigma1 * sigma2
    if den <= 0:
        raise ValueError("Degenerate pair: identical, perfectly correlated risk has no unique minimum.")
    w1 = (sigma2**2 - rho * sigma1 * sigma2) / den
    return w1, 1.0 - w1


def _percentile_exceed(values: np.ndarray, p_exceed: float) -> float:
    """Level exceeded in ``p_exceed`` percent of the observations (P90 -> 10th percentile)."""
    return float(np.quantile(values, 1.0 - p_exceed / 100.0))


def _single_series_stats(x: np.ndarray, low_threshold: float, worst_n: int) -> dict[str, float | None]:
    mean = float(np.mean(x))
    std = float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
    order = np.argsort(x)[: max(1, min(worst_n, len(x)))]
    worst_mean = float(np.mean(x[order]))
    return {
        "meanCf": mean,
        "std": std,
        "cv": std / mean if mean > _EPS else None,
        "p10": _percentile_exceed(x, 10),
        "p50": _percentile_exceed(x, 50),
        "p90": _percentile_exceed(x, 90),
        "lowOutputShare": float(np.mean(x < low_threshold)),
        "worstNMeanCf": worst_mean,
        "worstNLossFrac": (1.0 - worst_mean / mean) if mean > _EPS else None,
    }


def portfolio_metrics(
    df: pd.DataFrame,
    weights: dict[str, float],
    *,
    low_threshold: float = 0.05,
    worst_n: int = 100,
) -> dict[str, Any]:
    """Complementarity metrics of a weighted portfolio of sites.

    Algorithm:
        With $y_t = \\sum_i w_i x_{it}$ (weights normalised to 1):

        * mean CF $\\bar y$ and coefficient of variation $CV = \\sigma_y / \\bar y$
        * P10 / P50 / P90 exceedance output: quantiles $q_{0.9}, q_{0.5}, q_{0.1}$ of $y$
        * low-output share $\\Pr(y_t < \\theta)$ for the threshold $\\theta$
        * coincident low-output probability of a pair $\\Pr(x_{it}<\\theta \\wedge x_{jt}<\\theta)$,
          reported next to the independent expectation $\\Pr(x_i<\\theta)\\Pr(x_j<\\theta)$
        * ramp correlation: Pearson correlation of the step changes
          $\\Delta x_{it} = x_{it} - x_{i,t-1}$ between sites
        * worst-N loss $L_N = 1 - \\bar y_{(N)} / \\bar y$, with $\\bar y_{(N)}$ the mean of
          the $N$ lowest values of $y$ (share of average output lost in the worst hours)
        * diversification ratio $\\sum_i w_i\\sigma_i / \\sigma_y \\ge 1$
        ASCII: y = X w; CV = std(y)/mean(y); P90 = quantile(y, 0.10);
        low = mean(y < thr); L_N = 1 - mean(lowest N of y)/mean(y)

    Args:
        df: hourly CF, columns = the sites in the portfolio.
        weights: ``{site: weight}``; normalised to sum 1.
        low_threshold: $\\theta$, CF below which an hour counts as low output.
        worst_n: N for the worst-hours loss.

    Returns:
        JSON-ready dict: ``weights``, ``portfolio``, ``perSite``, ``coincidentLow``,
        ``rampCorrelation``, ``nObs``.
    """
    clean = df.dropna()
    if len(clean) < 3:
        raise ValueError("Need at least 3 complete observations in the window.")
    names = [str(c) for c in clean.columns]
    w = normalise_weights(weights, names)
    keep = [i for i, v in enumerate(w) if v > 0]
    names_k = [names[i] for i in keep]
    wk = w[keep] / w[keep].sum()
    x = clean[names_k].to_numpy(dtype=float)
    y = x @ wk

    port = _single_series_stats(y, low_threshold, worst_n)
    sigmas = np.std(x, axis=0, ddof=1)
    port["diversificationRatio"] = float(wk @ sigmas / port["std"]) if port["std"] and port["std"] > _EPS else None
    steps = np.diff(y)
    port["rampStd"] = float(np.std(steps, ddof=1)) if len(steps) > 1 else 0.0
    port["maxRamp"] = float(np.max(np.abs(steps))) if len(steps) else 0.0

    per_site = []
    for j, name in enumerate(names_k):
        row = _single_series_stats(x[:, j], low_threshold, worst_n)
        row.update({"site": name, "weight": float(wk[j])})
        per_site.append(row)

    low = (x < low_threshold).astype(float)
    n_obs = len(x)
    both = (low.T @ low) / n_obs
    marg = low.mean(axis=0)
    ramp_corr = pd.DataFrame(np.diff(x, axis=0), columns=names_k).corr().to_numpy()
    return {
        "weights": {n: float(v) for n, v in zip(names_k, wk)},
        "portfolio": port,
        "perSite": per_site,
        "coincidentLow": {
            "sites": names_k,
            "matrix": both.tolist(),
            "independent": np.outer(marg, marg).tolist(),
        },
        "rampCorrelation": {"sites": names_k, "matrix": ramp_corr.tolist()},
        "nObs": int(n_obs),
        "lowThreshold": float(low_threshold),
        "worstN": int(min(worst_n, n_obs)),
    }


def duration_curve(series: pd.Series | np.ndarray, n_points: int = 200) -> dict[str, list[float]]:
    """Output duration curve: output sorted descending against the share of time it is exceeded.

    Algorithm:
        $$ y_{(1)} \\ge y_{(2)} \\ge \\dots \\ge y_{(T)},\\qquad p_m = 100\\,\\frac{m}{T} $$
        ASCII: sort y descending; x = 100 * rank / T [% of time]

    Down-sampled to at most ``n_points`` evenly spaced ranks (first and last kept).
    """
    y = np.sort(np.asarray(series, dtype=float))[::-1]
    t = len(y)
    if t == 0:
        return {"x": [], "y": []}
    idx = np.unique(np.linspace(0, t - 1, min(n_points, t)).round().astype(int))
    return {"x": [float(100.0 * (i + 1) / t) for i in idx], "y": [float(y[i]) for i in idx]}


def _bounds_and_constraints(
    names: list[str],
    max_weight: float,
    regions: dict[str, str] | None,
    region_caps: dict[str, float] | None,
) -> tuple[list[tuple[float, float]], list[dict[str, Any]], list[tuple[np.ndarray, float]]]:
    n = len(names)
    if max_weight * n < 1.0 - 1e-9:
        raise ValueError(f"max weight {max_weight:.3f} x {n} sites cannot reach a total of 1.")
    bounds = [(0.0, float(max_weight))] * n
    caps: list[tuple[np.ndarray, float]] = []
    for region, cap in (region_caps or {}).items():
        mask = np.array([1.0 if (regions or {}).get(s) == region else 0.0 for s in names])
        if mask.sum() > 0:
            caps.append((mask, float(cap)))
    cons: list[dict[str, Any]] = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0), "jac": lambda w: np.ones_like(w)}]
    for mask, cap in caps:
        cons.append({"type": "ineq", "fun": lambda w, m=mask, c=cap: c - float(m @ w), "jac": lambda w, m=mask: -m})
    return bounds, cons, caps


def _start_point(n: int, max_weight: float) -> np.ndarray:
    return np.full(n, min(1.0 / n, max_weight))


def _max_mean(mu: np.ndarray, bounds: list[tuple[float, float]], caps: list[tuple[np.ndarray, float]]) -> tuple[float, np.ndarray]:
    """Highest achievable mean CF under the weight bounds and region caps (an LP)."""
    a_ub = [m for m, _ in caps] or None
    b_ub = [c for _, c in caps] or None
    res = linprog(-mu, A_ub=np.array(a_ub) if a_ub else None, b_ub=np.array(b_ub) if b_ub else None,
                  A_eq=np.ones((1, len(mu))), b_eq=[1.0], bounds=bounds, method="highs")
    if not res.success:
        raise ValueError("The weight bounds and region caps leave no feasible portfolio.")
    return float(-res.fun), np.asarray(res.x)


def optimise_portfolio(
    df: pd.DataFrame,
    *,
    objective: Literal["min_variance", "max_mean"] = "min_variance",
    target_mean: float | None = None,
    variance_cap: float | None = None,
    max_weight: float = 1.0,
    regions: dict[str, str] | None = None,
    region_caps: dict[str, float] | None = None,
    frontier_points: int = 0,
) -> dict[str, Any]:
    """Long-only portfolio of sites: minimum variance, or maximum mean under a variance cap.

    Algorithm:
        $$ \\min_w\\; w^{\\top}\\Sigma w \\quad\\text{s.t.}\\quad \\mathbf 1^{\\top}w=1,\\;
            \\mu^{\\top}w \\ge \\mu^{*},\\; 0\\le w_i\\le w_{max},\\;
            \\textstyle\\sum_{i\\in r} w_i \\le c_r $$
        or
        $$ \\max_w\\; \\mu^{\\top}w \\quad\\text{s.t.}\\quad w^{\\top}\\Sigma w \\le v_{cap},\\; (\\text{same constraints}) $$
        ASCII: min w'Cov w  s.t. sum(w)=1, mu'w >= target, 0<=w<=wmax, sum_region(w)<=cap
               or max mu'w s.t. w'Cov w <= vcap.

    $\\mu$ is the vector of mean CF, $\\Sigma$ the sample covariance (CF^2),
    $\\mu^*$ the target mean CF, $v_{cap}$ the variance cap (CF^2),
    $c_r$ the share cap of region $r$. Solved with SLSQP; infeasible targets or
    caps are detected beforehand (an LP for the highest reachable mean, the
    unconstrained-target minimum variance) and raise a ``ValueError`` that
    states the reachable value.

    Args:
        df: hourly CF, columns = the candidate sites.
        objective: ``min_variance`` (optionally ``target_mean``) or ``max_mean``
            (needs ``variance_cap``).
        target_mean: minimum mean CF for ``min_variance``.
        variance_cap: maximum variance (CF^2) for ``max_mean``.
        max_weight: per-site weight ceiling.
        regions: ``{site: region}``; with ``region_caps`` ``{region: max total weight}``.
        frontier_points: when > 0, also return that many (mean, std) points of the
            efficient frontier between the minimum-variance and maximum-mean portfolios.

    Returns:
        ``{"weights": {site: w}, "meanCf", "std", "variance", "objective", "frontier": [...]}``.
    """
    clean = df.dropna()
    names = [str(c) for c in clean.columns]
    n = len(names)
    if n == 0 or len(clean) < 3:
        raise ValueError("Need at least one site and 3 complete observations.")
    mu = clean.mean().to_numpy(dtype=float)
    cov = covariance_matrix(clean)
    if n == 1:
        return {"weights": {names[0]: 1.0}, "meanCf": float(mu[0]), "std": math.sqrt(max(cov[0, 0], 0.0)),
                "variance": float(cov[0, 0]), "objective": objective, "frontier": []}
    bounds, cons0, caps = _bounds_and_constraints(names, max_weight, regions, region_caps)
    scale = 1.0 / max(float(np.max(np.diag(cov))), _EPS)

    def solve_min_var(target: float | None) -> np.ndarray:
        cons = list(cons0)
        if target is not None:
            cons.append({"type": "ineq", "fun": lambda w: float(mu @ w - target), "jac": lambda w: mu})
        res = minimize(
            lambda w: scale * float(w @ cov @ w), _start_point(n, max_weight), jac=lambda w: 2 * scale * (cov @ w),
            bounds=bounds, constraints=cons, method="SLSQP", options={"ftol": 1e-14, "maxiter": 1000},
        )
        w = np.clip(res.x, 0.0, None)
        if not res.success or abs(w.sum() - 1.0) > 1e-5:
            raise ValueError(f"Optimiser did not converge: {res.message}")
        return w / w.sum()

    best_mean, w_maxmean = _max_mean(mu, bounds, caps)
    if objective == "min_variance":
        if target_mean is not None and target_mean > best_mean + 1e-9:
            raise ValueError(f"Target mean CF {target_mean:.4f} exceeds the highest reachable {best_mean:.4f} under the caps.")
        w = solve_min_var(target_mean)
    elif objective == "max_mean":
        if variance_cap is None or variance_cap <= 0:
            raise ValueError("objective 'max_mean' needs a positive variance_cap.")
        w_min = solve_min_var(None)
        min_var = portfolio_variance(w_min, cov)
        if variance_cap < min_var * (1 - 1e-9):
            raise ValueError(f"Variance cap {variance_cap:.6g} is below the minimum achievable variance {min_var:.6g}.")
        if portfolio_variance(w_maxmean, cov) <= variance_cap:
            w = w_maxmean
        else:
            cons = list(cons0) + [{"type": "ineq", "fun": lambda w: scale * (variance_cap - float(w @ cov @ w)),
                                   "jac": lambda w: -2 * scale * (cov @ w)}]
            res = minimize(lambda w: -float(mu @ w), w_min, jac=lambda w: -mu, bounds=bounds, constraints=cons,
                           method="SLSQP", options={"ftol": 1e-14, "maxiter": 1000})
            w = np.clip(res.x, 0.0, None)
            if not res.success or abs(w.sum() - 1.0) > 1e-5:
                raise ValueError(f"Optimiser did not converge: {res.message}")
            w = w / w.sum()
    else:
        raise ValueError("objective must be 'min_variance' or 'max_mean'.")

    frontier: list[dict[str, float]] = []
    if frontier_points > 0:
        w0 = solve_min_var(None)
        lo = float(mu @ w0)
        for target in np.linspace(lo, best_mean, frontier_points):
            try:
                wf = solve_min_var(float(target))
            except ValueError:
                continue
            frontier.append({"meanCf": float(mu @ wf), "std": math.sqrt(max(portfolio_variance(wf, cov), 0.0))})
    var = portfolio_variance(w, cov)
    return {
        "weights": {nm: float(v) for nm, v in zip(names, w)},
        "meanCf": float(mu @ w),
        "std": math.sqrt(max(var, 0.0)),
        "variance": var,
        "objective": objective,
        "frontier": frontier,
    }


# ── profiles ──────────────────────────────────────────────────────────────────


def downsample_mean(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    """Reduce ``df`` to at most ``max_points`` rows by the mean of contiguous buckets (chart payloads)."""
    n = len(df)
    if max_points <= 0 or n <= max_points:
        return df
    buckets = np.array_split(np.arange(n), max_points)
    rows = [df.iloc[b].mean() for b in buckets if len(b)]
    out = pd.DataFrame(rows)
    out.index = pd.Index([df.index[b[0]] for b in buckets if len(b)])
    return out


# ── regions ───────────────────────────────────────────────────────────────────

WEIGHTINGS = ("equal", "capacity", "custom")
Weighting = Literal["equal", "capacity", "custom"]
_NO_REGION = ""


def aggregate_regions(
    df: pd.DataFrame,
    sites: list[dict[str, Any]],
    *,
    weighting: str = "equal",
    weights: dict[str, float] | None = None,
    by_technology: bool = False,
    technology: str | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
    """Region CF series as the weighted mean of the CF of the sites in each region.

    Algorithm:
        $$ X_{r,t} = \\frac{\\sum_{i\\in r} w_i\\,x_{it}}{\\sum_{i\\in r} w_i} $$
        with weights $w_i$: equal ($w_i=1$), capacity ($w_i = P_i$, installed MW of
        site $i$) or user supplied. $X_{r,t}$ is again a capacity factor in 0-1
        (a convex combination of CFs), and with capacity weights
        $\\sum_i P_i x_{it} / \\sum_i P_i$ is the region's energy output divided by
        its installed capacity. Region centroid: the weighted mean of the member
        coordinates $(\\sum w_i \\phi_i / \\sum w_i,\\ \\sum w_i \\lambda_i / \\sum w_i)$.
        ASCII: X_r(t) = sum_i(w_i * x_i(t)) / sum_i(w_i), i in region r

    A region made of one site repeated $k$ times is that site; identical sites
    give an identical region whatever the weights.

    Args:
        df: CF of the sites (index = timestamps, columns = site names).
        sites: site rows with ``name``, ``region``, ``technology``, ``lat``, ``lon``, ``capacityMw``.
        weighting: ``equal`` | ``capacity`` (every member needs a positive ``capacityMw``) | ``custom``
            (``weights`` = ``{site: w}``; a site not listed has weight 0).
        weights: user weights for ``custom``.
        by_technology: one column per (region, technology), named ``"<region> | <technology>"``.
        technology: keep only sites of this technology before grouping.

    Returns:
        ``(frame, regions, unassigned)`` - ``frame`` has one column per region; ``regions`` rows hold
        ``name, region, technology, nSites, members [{site, weight}] (weights normalised to sum 1),
        capacityMw, lat, lon, meanCf``; ``unassigned`` lists the sites with no region label (left out).

    Raises:
        ValueError: unknown weighting, a negative weight, a ``capacity`` member without capacity,
            a region whose weights sum to zero, or no region at all.
    """
    if weighting not in WEIGHTINGS:
        raise ValueError(f"Unknown weighting {weighting!r}; one of {list(WEIGHTINGS)}.")
    present = [s for s in sites if s["name"] in df.columns and (technology is None or s.get("technology") == technology)]
    unassigned = [s["name"] for s in present if not s.get("region")]
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in present:
        if not s.get("region"):
            continue
        key = f"{s['region']} | {s['technology']}" if by_technology else str(s["region"])
        groups.setdefault(key, []).append(s)
    if not groups:
        raise ValueError("No region to aggregate: the site table has no region labels for the chosen sites.")
    user = {str(k): float(v) for k, v in (weights or {}).items()}
    if any(v < 0 for v in user.values()):
        raise ValueError("Weights must be non-negative.")
    frame: dict[str, np.ndarray] = {}
    out: list[dict[str, Any]] = []
    for name, members in groups.items():
        if weighting == "equal":
            w = np.ones(len(members))
        elif weighting == "capacity":
            missing = [m["name"] for m in members if not (m.get("capacityMw") and m["capacityMw"] > 0)]
            if missing:
                raise ValueError(f"Capacity weighting needs a positive capacity_mw for every site; missing for {missing[:8]}.")
            w = np.array([float(m["capacityMw"]) for m in members])
        else:
            w = np.array([user.get(m["name"], 0.0) for m in members])
        if w.sum() <= 0:
            raise ValueError(f"Region {name!r} has weights summing to zero; give a positive weight to at least one of its sites.")
        share = w / w.sum()
        x = df[[m["name"] for m in members]].to_numpy(dtype=float) @ share
        frame[name] = x
        techs = {m["technology"] for m in members}
        caps = [m.get("capacityMw") for m in members]
        out.append({
            "name": name,
            "region": str(members[0]["region"]),
            "technology": next(iter(techs)) if len(techs) == 1 else "all",
            "nSites": len(members),
            "members": [{"site": m["name"], "weight": float(sh)} for m, sh in zip(members, share)],
            "capacityMw": float(sum(caps)) if all(c for c in caps) else None,
            "lat": float(share @ np.array([m["lat"] for m in members])),
            "lon": float(share @ np.array([m["lon"] for m in members])),
            "meanCf": float(np.mean(x)),
        })
    return pd.DataFrame(frame, index=df.index), out, unassigned


def pair_stats(values: np.ndarray | list[float]) -> dict[str, float | int | None]:
    """Distribution summary of a set of pairwise correlations (NaN dropped).

    Algorithm:
        mean $\\bar r = \\frac{1}{n}\\sum_k r_k$, median, sample standard deviation
        ($n-1$), minimum, maximum and the quartiles $q_{0.25}, q_{0.75}$ (linear
        interpolation), the five numbers of a box plot.
        ASCII: mean(r), median(r), std(r, ddof=1), min, q25, q75, max

    Returns:
        ``{n, mean, median, std, min, q1, q3, max}``; every statistic is ``None`` when ``n == 0``
        (and ``std`` when ``n == 1``).
    """
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    n = len(v)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "std": None, "min": None, "q1": None, "q3": None, "max": None}
    return {
        "n": int(n), "mean": float(v.mean()), "median": float(np.median(v)),
        "std": float(v.std(ddof=1)) if n > 1 else None,
        "min": float(v.min()), "q1": float(np.quantile(v, 0.25)), "q3": float(np.quantile(v, 0.75)), "max": float(v.max()),
    }


def within_between_correlation(corr: pd.DataFrame, group_of: dict[str, str]) -> dict[str, Any]:
    """Pairwise site correlations inside each region and across each region pair.

    Algorithm:
        With the site correlation matrix $r_{ij}$ and region labels $g(i)$:
        $$ W_g = \\{ r_{ij} : i<j,\\ g(i)=g(j)=g \\},\\qquad
           B_{gh} = \\{ r_{ij} : g(i)=g,\\ g(j)=h \\}\\ (g\\ne h) $$
        and for each set the mean, median and distribution (:func:`pair_stats`).
        Pooled: $\\bar r_W$ is the mean over all within-region pairs, $\\bar r_B$ over all
        between-region pairs, and the spread gain $\\Delta = \\bar r_W - \\bar r_B$.
        ASCII: W_g = {r_ij | g(i)=g(j)=g}; B_gh = {r_ij | g(i)=g, g(j)=h}; gain = mean(W) - mean(B)

    A positive $\\Delta$ says sites of one region move together more than sites of
    different regions, so spreading capacity across regions buys diversification;
    $\\Delta \\approx 0$ says region borders carry no information about co-movement.
    Plain (not Fisher-z) means of $r$. A region with one site has no within pair.

    Args:
        corr: (n, n) site correlation matrix.
        group_of: ``{site: region}``; sites without an entry are ignored.

    Returns:
        ``{"within": [{region, nSites, **stats}], "between": [{a, b, **stats}], "summary": {...}}``;
        ``summary`` holds ``withinMean, withinMedian, betweenMean, betweenMedian, gain, nWithinPairs,
        nBetweenPairs``.
    """
    names = [str(c) for c in corr.columns]
    r = corr.to_numpy(dtype=float)
    groups = list(dict.fromkeys(group_of[n] for n in names if n in group_of))
    idx = {g: [i for i, n in enumerate(names) if group_of.get(n) == g] for g in groups}
    within: list[dict[str, Any]] = []
    all_within: list[np.ndarray] = []
    for g in groups:
        ii = idx[g]
        sub = r[np.ix_(ii, ii)]
        vals = sub[np.triu_indices(len(ii), k=1)]
        all_within.append(vals)
        within.append({"region": g, "nSites": len(ii), **pair_stats(vals)})
    between: list[dict[str, Any]] = []
    all_between: list[np.ndarray] = []
    for a_i, a in enumerate(groups):
        for b in groups[a_i + 1:]:
            vals = r[np.ix_(idx[a], idx[b])].ravel()
            all_between.append(vals)
            between.append({"a": a, "b": b, **pair_stats(vals)})
    pooled_w = pair_stats(np.concatenate(all_within) if all_within else [])
    pooled_b = pair_stats(np.concatenate(all_between) if all_between else [])
    gain = pooled_w["mean"] - pooled_b["mean"] if pooled_w["mean"] is not None and pooled_b["mean"] is not None else None
    return {
        "within": within,
        "between": between,
        "summary": {
            "withinMean": pooled_w["mean"], "withinMedian": pooled_w["median"], "nWithinPairs": pooled_w["n"],
            "betweenMean": pooled_b["mean"], "betweenMedian": pooled_b["median"], "nBetweenPairs": pooled_b["n"],
            "gain": gain,
        },
    }


def _rank_if(df: pd.DataFrame | pd.Series, method: str) -> pd.DataFrame | pd.Series:
    return df.rank(method="average") if method == "spearman" else df


def site_region_correlation(
    df: pd.DataFrame,
    group_of: dict[str, str],
    weights: dict[str, float] | None = None,
    method: str = "pearson",
) -> dict[str, Any]:
    """Correlation of every site with its own region and with every other region.

    Algorithm:
        $$ r_{i,h} = \\mathrm{corr}\\big(x_i,\\ X_h\\big)\\quad (h \\ne g(i)),\\qquad
           r_{i,g(i)} = \\mathrm{corr}\\big(x_i,\\ X_{g(i)}^{(-i)}\\big),\\quad
           X_g^{(-i)} = \\frac{\\sum_{j\\in g, j\\ne i} w_j x_j}{\\sum_{j\\in g, j\\ne i} w_j} $$
        with $X_h$ the weighted region series. The own region is taken
        leave-one-out: the full region series contains $x_i$ itself and would
        correlate with it for free. A site is *odd* when its best other region
        beats its own: $\\max_{h\\ne g(i)} r_{i,h} > r_{i,g(i)}$.
        ASCII: r_ih = corr(x_i, X_h); own: corr(x_i, X_g without i); odd if max_h r_ih > own

    Because the weighted mean is linear, the series may be on any basis or
    anomaly transform (not the standardised anomaly, which is not linear).

    Args:
        df: site series on the analysis basis (columns = sites).
        group_of: ``{site: region}``.
        weights: ``{site: w}`` of the aggregation (default equal).
        method: ``pearson`` | ``spearman``.

    Returns:
        ``{sites, regions, regionOf, matrix (sites x regions, own = leave-one-out), own, bestOther
        {site: {region, r}}, behavesLike [{site, region, ownRegion, ownR, otherR, delta}]}``;
        a one-site region has ``own`` ``None``.
    """
    if method not in METHODS:
        raise ValueError(f"Unknown method {method!r}; one of {list(METHODS)}.")
    sites = [c for c in df.columns if c in group_of]
    regions = list(dict.fromkeys(group_of[s] for s in sites))
    w = {s: float((weights or {}).get(s, 1.0)) for s in sites}
    x = df[sites]
    region_series = pd.DataFrame({
        g: x[[s for s in sites if group_of[s] == g]].to_numpy(dtype=float) @ np.array([w[s] for s in sites if group_of[s] == g])
        / max(sum(w[s] for s in sites if group_of[s] == g), _EPS)
        for g in regions
    }, index=df.index)
    xr, rr = _rank_if(x, method), _rank_if(region_series, method)
    matrix = np.full((len(sites), len(regions)), np.nan)
    for j, g in enumerate(regions):
        matrix[:, j] = xr.corrwith(rr[g]).to_numpy(dtype=float)
    own: dict[str, float | None] = {}
    for i, s in enumerate(sites):
        g = group_of[s]
        mates = [m for m in sites if group_of[m] == g and m != s and w[m] > 0]
        if not mates:
            own[s] = None
            matrix[i, regions.index(g)] = np.nan
            continue
        loo = x[mates].to_numpy(dtype=float) @ np.array([w[m] for m in mates]) / sum(w[m] for m in mates)
        r = float(pd.Series(xr[s].to_numpy()).corr(pd.Series(_rank_if(pd.Series(loo), method).to_numpy())))
        own[s] = r if math.isfinite(r) else None
        matrix[i, regions.index(g)] = r
    best: dict[str, dict[str, Any]] = {}
    odd: list[dict[str, Any]] = []
    for i, s in enumerate(sites):
        g = group_of[s]
        cand = [(regions[j], matrix[i, j]) for j in range(len(regions)) if regions[j] != g and math.isfinite(matrix[i, j])]
        if not cand:
            best[s] = {"region": None, "r": None}
            continue
        h, rh = max(cand, key=lambda t: t[1])
        best[s] = {"region": h, "r": float(rh)}
        if own[s] is not None and rh > own[s]:
            odd.append({"site": s, "region": h, "ownRegion": g, "ownR": own[s], "otherR": float(rh), "delta": float(rh - own[s])})
    odd.sort(key=lambda d: -d["delta"])
    return {
        "sites": sites, "regions": regions, "regionOf": {s: group_of[s] for s in sites},
        "matrix": matrix.tolist(), "own": own, "bestOther": best, "behavesLike": odd,
    }
