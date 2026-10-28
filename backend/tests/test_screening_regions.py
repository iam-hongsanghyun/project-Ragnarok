"""Region statistics of the Screening module against analytical cases.

Each statistic is pinned to a closed form or a hand calculation: identical
regions correlate to 1; a region made of one site repeated k times is that
site; capacity weighting equals sum(P x) / sum(P) worked by hand; two blocks of
sites driven by independent factors have within-region correlation near the
factor share and between-region correlation near 0 (seeded, stated tolerance);
a site driven by another region's factor is found by the site-vs-region table.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from numpy.testing import assert_allclose

from backend.app.screening import correlation as c


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2019-01-01", periods=n, freq="1h")


def _site(name: str, region: str, tech: str = "wind", cap: float | None = None, lat: float = 36.0, lon: float = 127.0) -> dict:
    return {"name": name, "region": region, "technology": tech, "capacityMw": cap, "lat": lat, "lon": lon}


def _blocks(n_per: int = 4, hours: int = 4000, rho: float = 0.8, seed: int = 7) -> tuple[pd.DataFrame, list[dict]]:
    """Two regions; every site = sqrt(rho) * its region's factor + sqrt(1-rho) * own noise (independent factors)."""
    rng = np.random.default_rng(seed)
    f = {"A": rng.standard_normal(hours), "B": rng.standard_normal(hours)}
    cols: dict[str, np.ndarray] = {}
    sites = []
    for region in ("A", "B"):
        for k in range(n_per):
            name = f"{region}{k}"
            cols[name] = np.sqrt(rho) * f[region] + np.sqrt(1 - rho) * rng.standard_normal(hours)
            sites.append(_site(name, region))
    return pd.DataFrame(cols, index=_idx(hours)), sites


def test_identical_regions_correlate_to_one() -> None:
    rng = np.random.default_rng(1)
    x = rng.random(300)
    df = pd.DataFrame({"s1": x, "s2": x, "s3": x, "s4": x}, index=_idx(300))
    sites = [_site("s1", "N"), _site("s2", "N"), _site("s3", "S"), _site("s4", "S")]
    frame, regions, _ = c.aggregate_regions(df, sites)
    for method in ("pearson", "spearman"):
        r = c.correlation_matrix(frame, method).to_numpy()
        assert_allclose(r, np.ones((2, 2)), rtol=0, atol=1e-12)
    assert [g["nSites"] for g in regions] == [2, 2]


def test_region_of_one_site_repeated_k_times_is_that_site() -> None:
    rng = np.random.default_rng(2)
    x = rng.random(200)
    for k in (1, 3, 5):
        df = pd.DataFrame({f"c{i}": x for i in range(k)}, index=_idx(200))
        sites = [_site(f"c{i}", "R", cap=10.0 * (i + 1)) for i in range(k)]
        for weighting in ("equal", "capacity"):
            frame, regions, _ = c.aggregate_regions(df, sites, weighting=weighting)
            assert_allclose(frame["R"].to_numpy(), x, rtol=0, atol=1e-12)
            assert_allclose(sum(m["weight"] for m in regions[0]["members"]), 1.0, atol=1e-12)


def test_capacity_weighting_matches_hand_calculation() -> None:
    df = pd.DataFrame({"A": [0.2, 0.4, 0.6], "B": [0.4, 0.2, 0.0]}, index=_idx(3))
    sites = [_site("A", "R", cap=100.0, lat=35.0, lon=126.0), _site("B", "R", cap=300.0, lat=37.0, lon=128.0)]
    # (100 A + 300 B) / 400: [20+120, 40+60, 60+0] / 400
    frame, regions, _ = c.aggregate_regions(df, sites, weighting="capacity")
    assert_allclose(frame["R"].to_numpy(), [0.35, 0.25, 0.15], rtol=0, atol=1e-12)
    assert_allclose(regions[0]["capacityMw"], 400.0)
    assert_allclose([regions[0]["lat"], regions[0]["lon"]], [36.5, 127.5], atol=1e-12)  # weights 1/4, 3/4
    equal, _, _ = c.aggregate_regions(df, sites, weighting="equal")
    assert_allclose(equal["R"].to_numpy(), [0.3, 0.3, 0.3], atol=1e-12)
    custom, _, _ = c.aggregate_regions(df, sites, weighting="custom", weights={"A": 1.0, "B": 3.0})
    assert_allclose(custom["R"].to_numpy(), frame["R"].to_numpy(), atol=1e-12)  # 1:3 = 100:300


def test_aggregation_errors_and_grouping() -> None:
    df = pd.DataFrame({"A": [0.1, 0.2, 0.3], "B": [0.3, 0.2, 0.1], "C": [0.5, 0.5, 0.5]}, index=_idx(3))
    sites = [_site("A", "R", "solar"), _site("B", "R", "wind", cap=5.0), _site("C", "")]
    with pytest.raises(ValueError, match="capacity"):
        c.aggregate_regions(df, sites, weighting="capacity")
    with pytest.raises(ValueError, match="zero"):
        c.aggregate_regions(df, sites, weighting="custom", weights={"C": 1.0})
    frame, regions, unassigned = c.aggregate_regions(df, sites, by_technology=True)
    assert list(frame.columns) == ["R | solar", "R | wind"] and unassigned == ["C"]
    assert [g["region"] for g in regions] == ["R", "R"]
    only_wind, _, _ = c.aggregate_regions(df, sites, technology="wind")
    assert list(only_wind.columns) == ["R"]
    assert_allclose(only_wind["R"].to_numpy(), df["B"].to_numpy())


def test_pair_stats_and_within_between_on_a_known_matrix() -> None:
    names = ["a1", "a2", "a3", "b1", "b2"]
    r = np.array([
        [1.0, 0.9, 0.7, 0.1, 0.2],
        [0.9, 1.0, 0.8, 0.0, 0.3],
        [0.7, 0.8, 1.0, -0.1, 0.1],
        [0.1, 0.0, -0.1, 1.0, 0.6],
        [0.2, 0.3, 0.1, 0.6, 1.0],
    ])
    out = c.within_between_correlation(pd.DataFrame(r, index=names, columns=names), {"a1": "A", "a2": "A", "a3": "A", "b1": "B", "b2": "B"})
    wa, wb = out["within"]
    assert wa["n"] == 3
    assert_allclose([wa["mean"], wa["median"], wa["min"], wa["max"]], [0.8, 0.8, 0.7, 0.9], atol=1e-12)  # {0.9, 0.7, 0.8}
    assert_allclose([wb["n"], wb["mean"]], [1, 0.6])
    (ab,) = out["between"]
    assert ab["n"] == 6
    assert_allclose(ab["mean"], np.mean([0.1, 0.2, 0.0, 0.3, -0.1, 0.1]), atol=1e-12)
    s = out["summary"]
    assert s["nWithinPairs"] == 4 and s["nBetweenPairs"] == 6
    assert_allclose(s["withinMean"], np.mean([0.9, 0.7, 0.8, 0.6]), atol=1e-12)
    assert_allclose(s["gain"], s["withinMean"] - s["betweenMean"], atol=1e-12)


def test_independent_blocks_have_high_within_and_zero_between_correlation() -> None:
    df, sites = _blocks(n_per=4, hours=4000, rho=0.8, seed=7)
    out = c.within_between_correlation(c.correlation_matrix(df), {s["name"]: s["region"] for s in sites})
    # Pair correlation of two sites with shared-factor share rho = 0.8 is 0.8; its sampling sd at T = 4000
    # is (1 - rho^2) / sqrt(T) = 0.006, so 6 pairs average to well inside 0.03. Between pairs: sd 1/sqrt(T) = 0.016.
    assert_allclose(out["summary"]["withinMean"], 0.8, atol=0.03)
    assert_allclose(out["summary"]["betweenMean"], 0.0, atol=0.03)
    assert out["summary"]["gain"] > 0.75
    for w in out["within"]:
        assert w["min"] > 0.7 and w["n"] == 6
    (ab,) = out["between"]
    assert ab["n"] == 16 and abs(ab["max"]) < 0.08  # 16 pairs, each within 5 sd of 0


def test_aggregated_regions_of_independent_blocks_are_uncorrelated() -> None:
    df, sites = _blocks(n_per=5, hours=4000, rho=0.5, seed=11)
    frame, _, _ = c.aggregate_regions(df, sites)
    r = c.correlation_matrix(frame).to_numpy()
    assert_allclose(r[0, 1], 0.0, atol=0.04)
    assert_allclose(np.diag(r), 1.0, atol=1e-12)


def test_site_vs_region_leave_one_out_by_hand_and_odd_site_found() -> None:
    # hand case: a, b, c in region R with equal weights; own series of a = (b + c) / 2
    rng = np.random.default_rng(3)
    a, b, cc, d = (rng.random(60) for _ in range(4))
    df = pd.DataFrame({"a": a, "b": b, "c": cc, "d": d}, index=_idx(60))
    res = c.site_region_correlation(df, {"a": "R", "b": "R", "c": "R", "d": "S"})
    assert_allclose(res["own"]["a"], np.corrcoef(a, (b + cc) / 2)[0, 1], atol=1e-12)
    assert res["own"]["d"] is None  # a one-site region has no leave-one-out region
    assert_allclose(res["matrix"][0][res["regions"].index("S")], np.corrcoef(a, d)[0, 1], atol=1e-12)
    # an odd site: labelled A, driven by region B's factor
    block, sites = _blocks(n_per=3, hours=3000, rho=0.8, seed=5)
    rng = np.random.default_rng(99)
    f_b = block[["B0", "B1", "B2"]].mean(axis=1)
    block["X"] = 0.9 * f_b + 0.1 * rng.standard_normal(len(block))
    group = {s["name"]: s["region"] for s in sites} | {"X": "A"}
    out = c.site_region_correlation(block, group)
    assert [o["site"] for o in out["behavesLike"]] == ["X"]
    odd = out["behavesLike"][0]
    assert odd["region"] == "B" and odd["otherR"] > 0.8 and odd["ownR"] < 0.1 and odd["delta"] > 0.7
    # a normal site is closer to its own region
    assert out["own"]["A0"] > 0.7 and out["bestOther"]["A0"]["r"] < 0.2


def test_geometry_centroid_of_a_square_and_validation() -> None:
    from backend.app.screening import datasets as ds

    square = {"type": "Polygon", "coordinates": [[[126.0, 35.0], [128.0, 35.0], [128.0, 37.0], [126.0, 37.0], [126.0, 35.0]]]}
    lat, lon = ds.geometry_centroid(ds.validate_geometry(square, "sq"))
    assert_allclose([lat, lon], [36.0, 127.0], atol=1e-12)
    with pytest.raises(ds.DatasetError):
        ds.validate_geometry({"type": "Point", "coordinates": [1, 2]}, "pt")
    with pytest.raises(ds.DatasetError):
        ds.validate_geometry({"type": "Polygon", "coordinates": [[[200, 0], [1, 0], [1, 1], [200, 0]]]}, "far")
