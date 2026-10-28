"""Siting screening statistics against analytical cases.

Every statistic is pinned to a closed form: identical series give 1, a negated
series gives -1, uncorrelated equal-variance sites with equal weights give
sigma^2 / n, two sites with known sigma and rho give the textbook
minimum-variance weights, the haversine of a quarter meridian is pi R / 2, a
pure diurnal cycle has zero anomalies, and a lagged copy peaks at its lag.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from numpy.testing import assert_allclose
from scipy.linalg import hadamard

from backend.app.screening import correlation as c

R_KM = 6371.0


def _hourly_index(n: int, start: str = "2019-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="1h")


def _solar(index: pd.DatetimeIndex, peak: float = 0.8) -> np.ndarray:
    """Clear-sky-like diurnal bell: zero at night."""
    return peak * np.clip(np.sin(np.pi * (index.hour - 6) / 12.0), 0.0, None)


# ── correlation ──────────────────────────────────────────────────────────────


def test_identical_series_correlate_to_one_and_negation_to_minus_one() -> None:
    rng = np.random.default_rng(1)
    x = rng.random(500)
    df = pd.DataFrame({"a": x, "b": x, "c": -x}, index=_hourly_index(500))
    for method in ("pearson", "spearman"):
        m = c.correlation_matrix(df, method)
        assert_allclose(m.loc["a", "b"], 1.0, rtol=0, atol=1e-12)
        assert_allclose(m.loc["a", "c"], -1.0, rtol=0, atol=1e-12)
        assert_allclose(np.diag(m.to_numpy()), 1.0, rtol=0, atol=1e-12)


def test_spearman_is_invariant_to_monotone_transform_pearson_is_not() -> None:
    x = np.linspace(0.01, 1.0, 200)
    df = pd.DataFrame({"a": x, "b": x**6}, index=_hourly_index(200))
    assert_allclose(c.correlation_matrix(df, "spearman").loc["a", "b"], 1.0, atol=1e-12)
    assert c.correlation_matrix(df, "pearson").loc["a", "b"] < 0.97


def test_constant_series_has_nan_correlation_and_unknown_method_raises() -> None:
    df = pd.DataFrame({"a": np.arange(10.0), "k": np.ones(10)}, index=_hourly_index(10))
    assert np.isnan(c.correlation_matrix(df).loc["a", "k"])
    with pytest.raises(ValueError):
        c.correlation_matrix(df, "kendall")


def test_reference_correlation_matches_direct_pearson() -> None:
    rng = np.random.default_rng(2)
    idx = _hourly_index(300)
    y = pd.Series(rng.random(300), index=idx)
    df = pd.DataFrame({"a": 2.0 * y.to_numpy() + 1.0, "b": -y.to_numpy()}, index=idx)
    r = c.reference_correlation(df, y)
    assert_allclose(r["a"], 1.0, atol=1e-12)
    assert_allclose(r["b"], -1.0, atol=1e-12)
    # no overlap on the index -> NaN, not an error
    shifted = pd.Series(y.to_numpy(), index=idx + pd.Timedelta(days=400))
    assert c.reference_correlation(df, shifted).isna().all()


# ── geometry ─────────────────────────────────────────────────────────────────


def test_haversine_quarter_meridian_and_known_pair() -> None:
    d = c.haversine_matrix_km([0.0, 90.0], [0.0, 0.0])
    assert_allclose(d[0, 1], math.pi * R_KM / 2, rtol=1e-12)
    assert_allclose(d, d.T, rtol=0, atol=0)
    assert_allclose(np.diag(d), 0.0, atol=0)
    # One degree of latitude = 2 pi R / 360
    assert_allclose(c.haversine_matrix_km([10.0, 11.0], [5.0, 5.0])[0, 1], 2 * math.pi * R_KM / 360, rtol=1e-9)
    # Seoul (37.5665, 126.9780) - Busan (35.1796, 129.0756): about 325 km great-circle
    seoul_busan = c.haversine_matrix_km([37.5665, 35.1796], [126.9780, 129.0756])[0, 1]
    assert_allclose(seoul_busan, 325.0, rtol=0.01)


def test_correlation_vs_distance_pairs_are_upper_triangle() -> None:
    corr = pd.DataFrame([[1, 0.5, 0.1], [0.5, 1, 0.2], [0.1, 0.2, 1]], columns=list("abc"), index=list("abc"))
    pairs = c.correlation_vs_distance(corr, [0.0, 1.0, 2.0], [0.0, 0.0, 0.0])
    assert list(zip(pairs["a"], pairs["b"])) == [("a", "b"), ("a", "c"), ("b", "c")]
    assert_allclose(pairs["r"], [0.5, 0.1, 0.2])
    assert_allclose(pairs["km"], [111.194926, 222.389853, 111.194926], rtol=1e-6)


# ── resampling ───────────────────────────────────────────────────────────────


def test_resample_bases_are_means_of_their_buckets() -> None:
    idx = _hourly_index(24 * 60)  # 2019-01-01 .. 2019-03-01
    df = pd.DataFrame({"a": np.arange(len(idx), dtype=float)}, index=idx)
    daily = c.resample_basis(df, "daily")
    assert len(daily) == 60
    assert_allclose(daily["a"].iloc[0], np.mean(np.arange(24)), rtol=1e-12)
    monthly = c.resample_basis(df, "monthly")
    assert_allclose(monthly["a"].iloc[0], np.mean(np.arange(31 * 24)), rtol=1e-12)
    diurnal = c.resample_basis(df, "diurnal")
    assert len(diurnal) == 24
    assert_allclose(diurnal["a"].iloc[3], np.mean(np.arange(3, len(idx), 24)), rtol=1e-12)
    mh = c.resample_basis(df, "month_hour")
    assert len(mh) == 3 * 24  # Jan, Feb, Mar
    custom = c.resample_basis(df, "custom", rule="6h")
    assert_allclose(custom["a"].iloc[0], 2.5, rtol=1e-12)
    assert c.resample_basis(df, "hourly") is df
    with pytest.raises(ValueError):
        c.resample_basis(df, "custom")
    with pytest.raises(ValueError):
        c.resample_basis(df, "custom", rule="not-a-rule")
    with pytest.raises(ValueError):
        c.resample_basis(df, "fortnightly")


def test_seasonal_assigns_december_to_the_djf_that_starts_it() -> None:
    idx = pd.date_range("2019-12-01", "2020-02-29 23:00", freq="1h")
    df = pd.DataFrame({"a": np.ones(len(idx))}, index=idx)
    out = c.resample_basis(df, "seasonal")
    assert list(out.index) == ["2019 DJF"]  # Dec 2019 + Jan/Feb 2020 are ONE season
    year = pd.date_range("2019-01-01", "2019-12-31 23:00", freq="1h")
    full = c.resample_basis(pd.DataFrame({"a": year.month.astype(float)}, index=year), "seasonal")
    assert list(full.index) == ["2018 DJF", "2019 MAM", "2019 JJA", "2019 SON", "2019 DJF"]
    # custom mapping: wet (Jun-Sep) vs dry, other months dropped
    wet = {6: "wet", 7: "wet", 8: "wet", 9: "wet", 1: "dry", 2: "dry"}
    custom = c.resample_basis(pd.DataFrame({"a": year.month.astype(float)}, index=year), "seasonal", season_map=wet)
    assert set(custom.index) == {"2019 wet", "2019 dry"}
    assert_allclose(custom.loc["2019 wet", "a"], 7.5, rtol=1e-12)


def test_filter_window_offset_dates_and_months() -> None:
    idx = _hourly_index(24 * 365)
    df = pd.DataFrame({"a": np.zeros(len(idx))}, index=idx)
    jan = c.filter_window(df, "2019-01-10", "2019-01-10")  # a bare end date keeps the whole day
    assert len(jan) == 24
    assert len(c.filter_window(df, months=[6, 7, 8])) == (30 + 31 + 31) * 24
    shifted = c.filter_window(df, utc_offset_hours=9)
    assert shifted.index[0] == pd.Timestamp("2019-01-01 09:00")


# ── anomalies ────────────────────────────────────────────────────────────────


def test_pure_cycle_has_zero_anomaly_and_anomaly_removes_the_sun() -> None:
    idx = _hourly_index(24 * 365)
    rng = np.random.default_rng(3)
    shape = _solar(idx)
    cycle_only = pd.DataFrame({"a": shape}, index=idx)
    assert_allclose(c.anomalies(cycle_only, by="hour")["a"].to_numpy(), 0.0, atol=1e-12)

    a = shape * (0.6 + 0.4 * rng.random(len(idx)))  # independent cloud noise per site
    b = shape * (0.6 + 0.4 * rng.random(len(idx)))
    df = pd.DataFrame({"a": a, "b": b}, index=idx)
    raw = c.correlation_matrix(df).loc["a", "b"]
    anom = c.correlation_matrix(c.anomalies(df)).loc["a", "b"]
    assert raw > 0.7  # looks alike only because the sun rises
    assert_allclose(anom, 0.0, rtol=0, atol=0.05)
    std = c.anomalies(df, standardise=True)
    assert np.isfinite(std.to_numpy()).all()
    assert_allclose(std.groupby(std.index.hour).mean().to_numpy(), 0.0, atol=1e-9)


# ── lagged cross-correlation ─────────────────────────────────────────────────


def test_lagged_cross_correlation_peaks_at_the_shift() -> None:
    rng = np.random.default_rng(4)
    a = np.convolve(rng.standard_normal(1200), np.ones(6) / 6, mode="same")  # smooth AR-like signal
    b = np.concatenate([np.zeros(3), a[:-3]])  # b_t = a_{t-3}: b follows a by 3 steps
    lags, r = c.lagged_cross_correlation(a, b, 12)
    assert list(lags[[0, -1]]) == [-12, 12]
    assert lags[int(np.nanargmax(r))] == 3
    assert_allclose(r[lags == 3][0], 1.0, atol=1e-12)
    lags0, r0 = c.lagged_cross_correlation(a, a, 5)
    assert_allclose(r0[lags0 == 0][0], 1.0, atol=1e-12)
    with pytest.raises(ValueError):
        c.lagged_cross_correlation(a, a[:-1], 3)


# ── portfolio ────────────────────────────────────────────────────────────────


def test_uncorrelated_equal_variance_equal_weights_gives_sigma2_over_n() -> None:
    # Columns of a Hadamard matrix are exactly orthogonal with zero mean (except the first):
    # the sample covariance is diagonal, sigma^2 = 8 / 7 for 8 rows.
    h = hadamard(8)[:, 1:5].astype(float)  # 4 sites
    df = pd.DataFrame(h, columns=list("abcd"), index=_hourly_index(8))
    cov = c.covariance_matrix(df)
    sigma2 = 8.0 / 7.0
    assert_allclose(cov, sigma2 * np.eye(4), rtol=1e-12, atol=1e-12)
    w = np.full(4, 0.25)
    assert_allclose(c.portfolio_variance(w, cov), sigma2 / 4, rtol=1e-12)
    # and through the series: var of the equal-weight combination
    assert_allclose(c.portfolio_series(df, w).var(ddof=1), sigma2 / 4, rtol=1e-12)


def test_two_site_closed_form_weights_and_slsqp_agree() -> None:
    s1, s2, rho = 0.20, 0.30, 0.25
    w1, w2 = c.min_variance_weights_two_sites(s1, s2, rho)
    assert_allclose(w1, (s2**2 - rho * s1 * s2) / (s1**2 + s2**2 - 2 * rho * s1 * s2), rtol=1e-14)
    assert_allclose(w1 + w2, 1.0, atol=1e-14)
    # exact sample with these moments: build standardised, orthogonalised columns
    rng = np.random.default_rng(5)
    z = rng.standard_normal((4000, 2))
    z -= z.mean(axis=0)
    q, _ = np.linalg.qr(z)  # orthonormal columns
    q *= math.sqrt(len(q) - 1)  # unit sample variance, zero correlation
    x1 = q[:, 0]
    x2 = rho * q[:, 0] + math.sqrt(1 - rho**2) * q[:, 1]
    df = pd.DataFrame({"a": 0.5 + s1 * x1, "b": 0.5 + s2 * x2}, index=_hourly_index(4000))
    assert_allclose(df["a"].std(), s1, rtol=1e-9)
    assert_allclose(df.corr().loc["a", "b"], rho, rtol=1e-9)
    res = c.optimise_portfolio(df, objective="min_variance")
    assert_allclose(res["weights"]["a"], w1, rtol=0, atol=1e-6)
    assert_allclose(res["weights"]["b"], w2, rtol=0, atol=1e-6)
    var_opt = (w1 * s1) ** 2 + (w2 * s2) ** 2 + 2 * w1 * w2 * rho * s1 * s2
    assert_allclose(res["variance"], var_opt, rtol=1e-6)


def test_long_only_clips_the_closed_form_at_the_boundary() -> None:
    s1, s2, rho = 0.10, 0.30, 0.9  # the unconstrained optimum has w1 > 1 (short b)
    w1, _ = c.min_variance_weights_two_sites(s1, s2, rho)
    assert w1 > 1.0
    rng = np.random.default_rng(6)
    z = rng.standard_normal((3000, 2))
    z -= z.mean(axis=0)
    q, _ = np.linalg.qr(z)
    q *= math.sqrt(len(q) - 1)
    df = pd.DataFrame(
        {"a": 0.4 + s1 * q[:, 0], "b": 0.4 + s2 * (rho * q[:, 0] + math.sqrt(1 - rho**2) * q[:, 1])},
        index=_hourly_index(3000),
    )
    res = c.optimise_portfolio(df)
    assert_allclose([res["weights"]["a"], res["weights"]["b"]], [1.0, 0.0], atol=1e-6)


def test_optimiser_targets_caps_and_infeasibility() -> None:
    rng = np.random.default_rng(7)
    idx = _hourly_index(2000)
    df = pd.DataFrame(
        {
            "low_var": 0.30 + 0.02 * rng.standard_normal(2000),
            "mid": 0.40 + 0.08 * rng.standard_normal(2000),
            "high_mean": 0.55 + 0.15 * rng.standard_normal(2000),
        },
        index=idx,
    )
    base = c.optimise_portfolio(df)
    target = 0.45
    res = c.optimise_portfolio(df, target_mean=target)
    assert res["meanCf"] >= target - 1e-6
    assert res["variance"] >= base["variance"] - 1e-12  # a mean constraint cannot reduce variance
    assert_allclose(sum(res["weights"].values()), 1.0, atol=1e-9)
    assert all(v >= -1e-12 for v in res["weights"].values())

    mx = c.optimise_portfolio(df, objective="max_mean", variance_cap=res["variance"], frontier_points=6)
    assert mx["variance"] <= res["variance"] * (1 + 1e-6)
    assert mx["meanCf"] >= res["meanCf"] - 1e-6  # the same cap cannot give a lower mean than the min-variance point
    assert len(mx["frontier"]) >= 3
    means = [p["meanCf"] for p in mx["frontier"]]
    assert means == sorted(means)

    with pytest.raises(ValueError, match="highest reachable"):
        c.optimise_portfolio(df, target_mean=0.9)
    with pytest.raises(ValueError, match="minimum achievable"):
        c.optimise_portfolio(df, objective="max_mean", variance_cap=1e-9)
    with pytest.raises(ValueError):
        c.optimise_portfolio(df, objective="max_mean")


def test_region_caps_and_max_weight_bind() -> None:
    rng = np.random.default_rng(8)
    idx = _hourly_index(1500)
    df = pd.DataFrame(
        {"n1": 0.35 + 0.05 * rng.standard_normal(1500), "n2": 0.35 + 0.05 * rng.standard_normal(1500),
         "s1": 0.30 + 0.05 * rng.standard_normal(1500)},
        index=idx,
    )
    regions = {"n1": "north", "n2": "north", "s1": "south"}
    res = c.optimise_portfolio(df, regions=regions, region_caps={"north": 0.4})
    assert res["weights"]["n1"] + res["weights"]["n2"] <= 0.4 + 1e-6
    capped = c.optimise_portfolio(df, max_weight=0.4)
    assert max(capped["weights"].values()) <= 0.4 + 1e-6
    with pytest.raises(ValueError):
        c.optimise_portfolio(df, max_weight=0.2)  # 3 x 0.2 < 1


def test_portfolio_metrics_on_constructed_series() -> None:
    idx = _hourly_index(1000)
    ramp = np.linspace(0.0, 1.0, 1000)
    df = pd.DataFrame({"a": ramp, "b": ramp, "c": 1.0 - ramp}, index=idx)
    m = c.portfolio_metrics(df, {"a": 1.0, "b": 1.0}, low_threshold=0.1, worst_n=10)
    p = m["portfolio"]
    assert_allclose(sum(m["weights"].values()), 1.0)
    assert_allclose(p["meanCf"], 0.5, rtol=1e-12)
    assert_allclose(p["cv"], p["std"] / 0.5, rtol=1e-12)
    assert_allclose(p["p90"], np.quantile(ramp, 0.10), rtol=1e-12)  # exceedance convention
    assert_allclose(p["p10"], np.quantile(ramp, 0.90), rtol=1e-12)
    assert_allclose(p["lowOutputShare"], np.mean(ramp < 0.1), rtol=1e-12)
    assert_allclose(p["diversificationRatio"], 1.0, rtol=1e-9)  # identical sites: no diversification
    # identical series are coincidentally low exactly as often as each alone
    cl = np.array(m["coincidentLow"]["matrix"])
    assert_allclose(cl[0, 1], cl[0, 0], atol=1e-12)
    # worst-10 mean of a linear ramp: mean of the 10 smallest values
    assert_allclose(p["worstNMeanCf"], np.mean(np.sort(ramp)[:10]), rtol=1e-12)
    assert_allclose(p["worstNLossFrac"], 1 - np.mean(np.sort(ramp)[:10]) / 0.5, rtol=1e-12)
    assert_allclose(np.array(m["rampCorrelation"]["matrix"])[0, 1], 1.0, atol=1e-9)

    # a and c are perfectly anti-correlated: the 50/50 portfolio is flat at 0.5 -> zero variance, no low hours
    flat = c.portfolio_metrics(df, {"a": 0.5, "c": 0.5}, low_threshold=0.1)
    assert_allclose(flat["portfolio"]["std"], 0.0, atol=1e-12)
    assert flat["portfolio"]["lowOutputShare"] == 0.0
    assert flat["portfolio"]["diversificationRatio"] is None
    cl2 = np.array(flat["coincidentLow"]["matrix"])
    assert cl2[0, 1] == 0.0 and cl2[0, 0] > 0  # never low together though each is low 10 % of the time

    with pytest.raises(ValueError):
        c.portfolio_metrics(df, {"zzz": 1.0})
    with pytest.raises(ValueError):
        c.portfolio_metrics(df, {"a": -1.0})
    with pytest.raises(ValueError):
        c.portfolio_metrics(df, {"a": 0.0})


def test_duration_curve_is_sorted_and_capped() -> None:
    y = np.random.default_rng(9).random(5000)
    d = c.duration_curve(y, 100)
    assert len(d["x"]) <= 100 and d["y"] == sorted(d["y"], reverse=True)
    assert_allclose(d["y"][0], y.max(), rtol=0)
    assert_allclose(d["x"][-1], 100.0, rtol=1e-12)
    assert c.duration_curve([], 10) == {"x": [], "y": []}


# ── clustering ───────────────────────────────────────────────────────────────


def test_clustering_recovers_two_groups_and_orders_them_adjacent() -> None:
    rng = np.random.default_rng(10)
    idx = _hourly_index(1500)
    g1, g2 = rng.standard_normal(1500), rng.standard_normal(1500)
    df = pd.DataFrame(
        {
            "a1": g1 + 0.2 * rng.standard_normal(1500), "b1": g2 + 0.2 * rng.standard_normal(1500),
            "a2": g1 + 0.2 * rng.standard_normal(1500), "b2": g2 + 0.2 * rng.standard_normal(1500),
            "a3": g1 + 0.2 * rng.standard_normal(1500),
        },
        index=idx,
    )
    res = c.cluster_sites(c.correlation_matrix(df), k=2)
    lab = res["labels"]
    assert lab["a1"] == lab["a2"] == lab["a3"] and lab["b1"] == lab["b2"] and lab["a1"] != lab["b1"]
    assert res["nClusters"] == 2 and sorted(res["order"]) == sorted(df.columns)
    pos = {s: i for i, s in enumerate(res["order"])}
    a_pos = sorted(pos[s] for s in ("a1", "a2", "a3"))
    assert a_pos[-1] - a_pos[0] == 2  # contiguous in the dendrogram order
    assert len(res["linkage"]) == 4
    by_threshold = c.cluster_sites(c.correlation_matrix(df), threshold=0.5)
    assert by_threshold["nClusters"] == 2
    one = c.cluster_sites(c.correlation_matrix(df[["a1"]]), k=1)
    assert one["labels"] == {"a1": 1}
    with pytest.raises(ValueError):
        c.cluster_sites(c.correlation_matrix(df))
    with pytest.raises(ValueError):
        c.cluster_sites(c.correlation_matrix(df), k=2, threshold=0.3)
    with pytest.raises(ValueError):
        c.cluster_sites(c.correlation_matrix(df), k=9)


def test_downsample_mean_keeps_the_mean() -> None:
    df = pd.DataFrame({"a": np.arange(1000.0)}, index=_hourly_index(1000))
    small = c.downsample_mean(df, 100)
    assert len(small) == 100
    assert_allclose(small["a"].mean(), df["a"].mean(), rtol=1e-12)
    assert c.downsample_mean(df, 5000) is df
