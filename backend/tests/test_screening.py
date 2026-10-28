"""Siting screening: dataset validation + store, the /api/screening routes, promotion.

Datasets are synthetic and seeded. The routes run on a bare FastAPI app with the
data root and the session store pointed at a tmp dir, so nothing touches the
checkout.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from numpy.testing import assert_allclose

from backend.app import model_store, session_store
from backend.app.routers import screening as screening_router
from backend.app.screening import datasets as ds
from backend.app.screening.promote import build_promotion, generator_name

HOURS = 24 * 30  # a month keeps the suite fast


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGNAROK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(screening_router.router)
    return TestClient(app)


def _frame(hours: int = HOURS, seed: int = 0, start: str = "2019-06-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=hours, freq="1h")
    rng = np.random.default_rng(seed)
    sun = np.clip(np.sin(np.pi * (idx.hour - 6) / 12.0), 0, None)
    shared = np.convolve(rng.standard_normal(hours), np.ones(12) / 12, mode="same")
    cols = {
        "S1": 0.7 * sun * (0.7 + 0.3 * rng.random(hours)),
        "S2": 0.7 * sun * (0.7 + 0.3 * rng.random(hours)),
        "W1": np.clip(0.35 + 1.5 * shared + 0.05 * rng.standard_normal(hours), 0, 1),
        "W2": np.clip(0.35 + 1.5 * shared + 0.10 * rng.standard_normal(hours), 0, 1),
    }
    return pd.DataFrame(cols, index=idx)


SITES = pd.DataFrame(
    {
        "name": ["S1", "S2", "W1", "W2"],
        "lat": [37.5, 35.2, 36.0, 36.4],
        "lon": [127.0, 129.0, 126.5, 127.2],
        "technology": ["solar", "solar", "wind", "wind"],
        "region": ["north", "south", "north", "south"],
    }
)


def _csv(df: pd.DataFrame, index_label: str = "timestamp") -> bytes:
    out = df.copy()
    out.index.name = index_label
    return out.to_csv().encode()


def _upload(client: TestClient, wide: pd.DataFrame | None = None, **form: Any) -> dict[str, Any]:
    wide = _frame() if wide is None else wide
    files = {"file": ("series.csv", _csv(wide), "text/csv"), "sitesFile": ("sites.csv", SITES.to_csv(index=False).encode(), "text/csv")}
    resp = client.post("/api/screening/datasets", files=files, data={"name": "test", **form})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── validation ───────────────────────────────────────────────────────────────


def test_wide_and_long_layouts_give_the_same_dataset() -> None:
    wide = _frame(48)
    long = wide.reset_index(names="timestamp").melt(id_vars="timestamp", var_name="site", value_name="value")
    a, sites_a, rep_a = ds.build_dataset(ds.read_table(_csv(wide), "w.csv"), layout="wide", sites_df=SITES)
    b, sites_b, _ = ds.build_dataset(ds.read_table(long.to_csv(index=False).encode(), "l.csv"), layout="long", sites_df=SITES)
    assert_allclose(a.to_numpy(), b[a.columns].to_numpy(), atol=1e-12)
    assert [s["name"] for s in sites_a] == [s["name"] for s in sites_b]
    assert rep_a["resolution"]["stepMinutes"] == 60.0 and rep_a["gaps"]["sitesWithGaps"] == 0


def test_xlsx_upload_is_read() -> None:
    wide = _frame(48)
    buf = io.BytesIO()
    out = wide.reset_index(names="timestamp")
    out.to_excel(buf, index=False)
    grid, _, _ = ds.build_dataset(ds.read_table(buf.getvalue(), "w.xlsx"), layout="wide", sites_df=SITES)
    assert len(grid) == 48
    with pytest.raises(ds.DatasetError, match="Unsupported"):
        ds.read_table(b"x", "w.json")


def test_gaps_are_reported_then_interpolated_or_dropped() -> None:
    wide = _frame(200)
    wide.iloc[50:53, 0] = np.nan  # a 3-step hole in S1
    wide.iloc[120:180, 2] = np.nan  # a 60-step hole in W1 (longer than the 48-step limit)
    raw = ds.read_table(_csv(wide), "w.csv")
    grid, _, rep = ds.build_dataset(raw, layout="wide", sites_df=SITES, gap_policy="interpolate")
    assert rep["gaps"]["sitesWithGaps"] == 2
    assert rep["gaps"]["bySite"]["S1"]["longestRunSteps"] == 3 and rep["gaps"]["bySite"]["W1"]["missingSteps"] == 60
    assert rep["gaps"]["interpolatedValues"] == 3 + 48  # the 60-step hole: only its first 48 steps are filled
    assert not grid.isna().any().any()
    # the 3-step hole is a straight line between its neighbours
    expect = np.linspace(wide["S1"].iloc[49], wide["S1"].iloc[53], 5)[1:-1]
    assert_allclose(grid["S1"].iloc[50:53].to_numpy(), expect, atol=1e-12)
    dropped, _, rep_d = ds.build_dataset(raw, layout="wide", sites_df=SITES, gap_policy="drop")
    assert rep_d["gaps"]["interpolatedValues"] == 0 and len(dropped) == 200 - 3 - 60
    assert any("gaps" in w for w in rep_d["warnings"])


def test_duplicates_averaged_and_bad_timestamps_trimmed() -> None:
    wide = _frame(100)
    raw = wide.reset_index(names="timestamp")
    raw["timestamp"] = raw["timestamp"].astype(str)
    dup = pd.concat([raw, raw.iloc[[10]].assign(S1=0.99)], ignore_index=True)
    dup.loc[5, "timestamp"] = "not a date"
    grid, _, rep = ds.build_dataset(ds.read_table(dup.to_csv(index=False).encode(), "w.csv"), layout="wide", sites_df=SITES)
    assert rep["duplicates"]["count"] == 1 and rep["timestamps"]["unparseable"] == 1
    assert_allclose(grid["S1"].iloc[10], (wide["S1"].iloc[10] + 0.99) / 2, atol=1e-12)
    junk = pd.DataFrame({"timestamp": ["x"] * 50, "S1": [0.1] * 50})
    with pytest.raises(ds.DatasetError, match="could not be parsed"):
        ds.build_dataset(junk, layout="wide", sites_df=SITES.iloc[:1])


def test_time_zone_conversion_and_offset_timestamps() -> None:
    wide = _frame(48)[["S1"]]
    raw = ds.read_table(_csv(wide), "w.csv")
    utc, _, rep = ds.build_dataset(raw, layout="wide", sites_df=SITES.iloc[:1])
    seoul, _, rep_s = ds.build_dataset(raw, layout="wide", sites_df=SITES.iloc[:1], timezone_name="Asia/Seoul")
    assert seoul.index[0] == utc.index[0] - pd.Timedelta(hours=9)
    assert "Asia/Seoul" in rep_s["timestamps"]["interpretation"] and "UTC" in rep["timestamps"]["interpretation"]
    stamped = wide.copy()
    stamped.index = [t.isoformat() + "+09:00" for t in stamped.index]
    off, _, rep_o = ds.build_dataset(ds.read_table(_csv(stamped), "w.csv"), layout="wide", sites_df=SITES.iloc[:1])
    assert off.index[0] == pd.Timestamp("2019-05-31 15:00") and "offset" in rep_o["timestamps"]["interpretation"]
    with pytest.raises(ds.DatasetError, match="Unknown time zone"):
        ds.build_dataset(raw, layout="wide", sites_df=SITES.iloc[:1], timezone_name="Mars/Olympus")


def test_unit_sanity_cf_range_and_mw_normalisation() -> None:
    wide = _frame(48)[["S1"]]
    pct = wide * 100  # percent, not CF
    with pytest.raises(ds.DatasetError) as ei:
        ds.build_dataset(ds.read_table(_csv(pct), "w.csv"), layout="wide", sites_df=SITES.iloc[:1])
    assert "outside the capacity-factor range" in str(ei.value) and "percent" in str(ei.value)
    assert ei.value.report["units"]["outOfRange"][0]["site"] == "S1"
    mw = SITES.iloc[:1].assign(unit="mw", capacity_mw=50.0)
    grid, sites, _ = ds.build_dataset(ds.read_table(_csv(wide * 50), "w.csv"), layout="wide", sites_df=mw)
    assert_allclose(grid["S1"].to_numpy(), wide["S1"].to_numpy(), atol=1e-12)
    assert sites[0]["capacityMw"] == 50.0 and sites[0]["unit"] == "mw"
    with pytest.raises(ds.DatasetError, match="capacity_mw"):
        ds.build_dataset(ds.read_table(_csv(wide), "w.csv"), layout="wide", sites_df=SITES.iloc[:1].assign(unit="mw"))
    with pytest.raises(ds.DatasetError, match="outside the capacity-factor"):  # wrong capacity: 5 MW series on 1 MW site
        ds.build_dataset(ds.read_table(_csv(wide * 50), "w.csv"), layout="wide", sites_df=SITES.iloc[:1].assign(unit="mw", capacity_mw=5.0))


def test_site_table_errors() -> None:
    wide = ds.read_table(_csv(_frame(24)), "w.csv")
    bad = SITES.copy()
    bad.loc[0, "technology"] = "coal"
    with pytest.raises(ds.DatasetError, match="technology"):
        ds.build_dataset(wide, layout="wide", sites_df=bad)
    with pytest.raises(ds.DatasetError, match="missing"):
        ds.build_dataset(wide, layout="wide", sites_df=SITES.drop(columns=["lat"]))
    off = SITES.copy()
    off.loc[1, "lat"] = 123.0
    with pytest.raises(ds.DatasetError, match="out of WGS84"):
        ds.build_dataset(wide, layout="wide", sites_df=off)
    with pytest.raises(ds.DatasetError, match="not in the site table"):
        ds.build_dataset(wide, layout="wide", sites_df=SITES.iloc[:2])


# ── routes: datasets ─────────────────────────────────────────────────────────


def test_upload_list_get_delete_and_survives_a_fresh_app(client: TestClient) -> None:
    meta = _upload(client)
    assert meta["kind"] == "sites" and len(meta["sites"]) == 4 and meta["rows"] == HOURS
    assert all(0 <= s["meanCf"] <= 1 for s in meta["sites"])
    listed = client.get("/api/screening/datasets").json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == meta["id"] and listed["items"][0]["siteCount"] == 4
    # a new app instance over the same data root still sees it (survives reload / restart)
    app2 = FastAPI()
    app2.include_router(screening_router.router)
    again = TestClient(app2).get(f"/api/screening/datasets/{meta['id']}").json()
    assert again["report"]["resolution"]["stepMinutes"] == 60.0 and again["name"] == "test"
    assert client.get("/api/screening/datasets", params={"limit": 1, "offset": 1}).json()["items"] == []
    assert client.delete(f"/api/screening/datasets/{meta['id']}").json() == {"deleted": True}
    assert client.get(f"/api/screening/datasets/{meta['id']}").status_code == 404
    assert client.delete(f"/api/screening/datasets/{meta['id']}").json() == {"deleted": False}


def test_validate_reports_without_storing_and_invalid_upload_is_422(client: TestClient) -> None:
    files = {"file": ("s.csv", _csv(_frame(48) * 200), "text/csv"), "sitesFile": ("t.csv", SITES.to_csv(index=False).encode(), "text/csv")}
    v = client.post("/api/screening/validate", files=files).json()
    assert v["ok"] is False and v["report"]["units"]["outOfRange"]
    assert client.get("/api/screening/datasets").json()["total"] == 0
    r = client.post("/api/screening/datasets", files=files)
    assert r.status_code == 422 and "report" in r.json()["detail"]
    ok = client.post(
        "/api/screening/validate",
        files={"file": ("s.csv", _csv(_frame(48)), "text/csv")},
        data={"sitesJson": json.dumps(SITES.to_dict("records"))},
    ).json()
    assert ok["ok"] is True and ok["siteCount"] == 4


def test_path_traversal_ids_are_rejected(client: TestClient) -> None:
    assert client.get("/api/screening/datasets", params={"sessionId": "../x"}).status_code == 400
    assert client.get("/api/screening/datasets/..%2Fetc").status_code in (400, 404)


def test_reference_dataset_upload(client: TestClient) -> None:
    load = pd.DataFrame({"load": 1000 + 300 * np.sin(np.arange(HOURS) * 2 * np.pi / 24)}, index=_frame().index)
    r = client.post(
        "/api/screening/datasets",
        files={"file": ("load.csv", _csv(load), "text/csv")},
        data={"kind": "reference", "referenceKind": "load", "unit": "MW", "name": "grid load"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "reference" and r.json()["sites"] == []
    assert client.get("/api/screening/datasets", params={"kind": "reference"}).json()["total"] == 1
    assert client.get("/api/screening/datasets", params={"kind": "sites"}).json()["total"] == 0


# ── routes: statistics ───────────────────────────────────────────────────────


def test_correlation_matrix_distance_and_anomaly(client: TestClient) -> None:
    meta = _upload(client)
    base = {"datasetId": meta["id"], "basis": "hourly"}
    r = client.post("/api/screening/correlation", json=base).json()
    m = np.array(r["matrix"], dtype=float)
    assert r["sites"] == ["S1", "S2", "W1", "W2"] and m.shape == (4, 4)
    assert_allclose(np.diag(m), 1.0, atol=1e-12)
    assert_allclose(m, m.T, atol=1e-12)
    assert m[2, 3] > 0.8  # the two wind sites share the synoptic component
    assert m[0, 1] > 0.5  # the sun
    assert len(r["distance"]) == 6 and all(p["km"] > 0 for p in r["distance"])
    anom = client.post("/api/screening/correlation", json={**base, "anomaly": True}).json()
    assert abs(np.array(anom["matrix"], dtype=float)[0, 1]) < m[0, 1] - 0.3  # sun removed
    sp = client.post("/api/screening/correlation", json={**base, "method": "spearman", "basis": "daily"}).json()
    assert sp["method"] == "spearman" and sp["nObs"] == 30
    for basis, n in [("diurnal", 24), ("month_hour", 24), ("seasonal", 1), ("weekly", 5), ("monthly", 1)]:
        rb = client.post("/api/screening/correlation", json={**base, "basis": basis})
        assert rb.status_code == 200, (basis, rb.text)
        assert rb.json()["nObs"] == n or basis in ("weekly", "seasonal", "monthly")
    cus = client.post("/api/screening/correlation", json={**base, "basis": "custom", "rule": "6h"}).json()
    assert cus["nObs"] == HOURS // 6
    win = client.post("/api/screening/correlation", json={**base, "start": "2019-06-05", "end": "2019-06-06"}).json()
    assert win["nObs"] == 48
    assert client.post("/api/screening/correlation", json={**base, "basis": "custom"}).status_code == 422
    assert client.post("/api/screening/correlation", json={**base, "basis": "diurnal", "anomaly": True}).status_code == 422
    assert client.post("/api/screening/correlation", json={**base, "sites": ["S1"]}).status_code == 422
    assert client.post("/api/screening/correlation", json={**base, "sites": ["S1", "nope"]}).status_code == 422
    assert client.post("/api/screening/correlation", json={**base, "start": "2030-01-01"}).status_code == 422
    assert client.post("/api/screening/correlation", json={"datasetId": "ds_missing"}).status_code == 404


def test_matrix_size_cap(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = _upload(client)
    monkeypatch.setattr(screening_router, "MAX_MATRIX_SITES", 3)
    r = client.post("/api/screening/correlation", json={"datasetId": meta["id"]})
    assert r.status_code == 422 and "at most 3" in r.json()["detail"]


def test_reference_correlation_with_uploaded_load_and_calendar_alignment(client: TestClient) -> None:
    meta = _upload(client)
    sun = np.clip(np.sin(np.pi * (_frame().index.hour - 6) / 12.0), 0, None)
    load = pd.DataFrame({"load": 500 + 200 * sun}, index=_frame().index)
    ref = client.post(
        "/api/screening/datasets", files={"file": ("l.csv", _csv(load), "text/csv")}, data={"kind": "reference"}
    ).json()
    body = {"datasetId": meta["id"], "basis": "hourly", "reference": {"type": "dataset", "datasetId": ref["id"]}}
    r = client.post("/api/screening/correlation", json=body).json()
    assert r["reference"]["nOverlap"] == HOURS
    assert r["reference"]["correlations"]["S1"] > 0.7
    assert r["reference"]["correlations"]["S1"] > r["reference"]["correlations"]["W1"]
    # a reference from another year: no overlap on exact, full overlap on calendar
    other = load.copy()
    other.index = other.index + pd.DateOffset(years=5)
    ref2 = client.post("/api/screening/datasets", files={"file": ("l2.csv", _csv(other), "text/csv")}, data={"kind": "reference"}).json()
    miss = client.post("/api/screening/correlation", json={**body, "reference": {"type": "dataset", "datasetId": ref2["id"]}}).json()
    assert miss["reference"]["nOverlap"] == 0 and any("overlaps" in w for w in miss["warnings"])
    cal = client.post("/api/screening/correlation", json={**body, "reference": {"type": "dataset", "datasetId": ref2["id"], "align": "calendar"}}).json()
    assert cal["reference"]["nOverlap"] == HOURS
    assert_allclose(cal["reference"]["correlations"]["S1"], r["reference"]["correlations"]["S1"], atol=1e-9)
    # a sites dataset is not a reference; missing load in the model is a clear 422
    assert client.post("/api/screening/correlation", json={**body, "reference": {"type": "dataset", "datasetId": meta["id"]}}).status_code == 422
    assert client.post("/api/screening/correlation", json={**body, "reference": {"type": "load"}}).status_code == 422
    assert client.post("/api/screening/correlation", json={**body, "reference": {"type": "price"}}).status_code == 422


def test_reference_from_model_load(client: TestClient) -> None:
    meta = _upload(client)
    idx = _frame().index
    sun = np.clip(np.sin(np.pi * (idx.hour - 6) / 12.0), 0, None)
    model_store.save_model("default", {
        "buses": [{"name": "b", "x": 127.0, "y": 37.0}],
        "snapshots": [{"snapshot": t.strftime("%Y-%m-%d %H:%M")} for t in idx],
        "loads": [{"name": "l", "bus": "b"}],
        "loads-p_set": [{"snapshot": t.strftime("%Y-%m-%d %H:%M"), "l": 100 + 50 * s} for t, s in zip(idx, sun)],
    })
    r = client.post("/api/screening/correlation", json={"datasetId": meta["id"], "basis": "hourly", "reference": {"type": "load"}}).json()
    assert_allclose(r["reference"]["correlations"]["S1"], np.corrcoef(_frame()["S1"], sun)[0, 1], atol=1e-9)
    # the model clock is UTC+9: shifting labels back by 9 h breaks the sun alignment
    shifted = client.post("/api/screening/correlation", json={"datasetId": meta["id"], "basis": "hourly",
                          "reference": {"type": "load", "modelUtcOffsetHours": 9}}).json()
    assert shifted["reference"]["correlations"]["S1"] < r["reference"]["correlations"]["S1"] - 0.2


def test_lagged_profiles_cluster(client: TestClient) -> None:
    wide = _frame()
    wide["W2"] = wide["W1"].shift(5).bfill()  # W2 sees W1's weather 5 h later
    meta = _upload(client, wide)
    lag = client.post("/api/screening/lagged", json={"datasetId": meta["id"], "site": "W1", "others": ["W2", "S1"], "maxLagHours": 12}).json()
    assert lag["best"]["W2"]["lagHours"] == 5.0 and lag["best"]["W2"]["r"] > 0.99
    assert lag["lagsHours"][0] == -12.0 and len(lag["series"]["S1"]) == 25
    assert client.post("/api/screening/lagged", json={"datasetId": meta["id"], "site": "W1", "maxLagHours": 99999}).status_code == 422

    prof = client.post("/api/screening/profiles", json={"datasetId": meta["id"], "sites": ["S1", "W1"]}).json()
    assert prof["diurnal"]["hours"] == list(range(24)) and len(prof["diurnal"]["series"]["S1"]) == 24
    assert prof["diurnal"]["series"]["S1"][0] == 0.0 and max(prof["diurnal"]["series"]["S1"]) > 0.3  # noon peak, night zero
    assert prof["monthly"]["months"] == [6] and prof["seasonal"]["labels"] == ["JJA"]
    assert len(prof["timeseries"]["timestamps"]) == screening_router.MAX_CHART_POINTS < HOURS  # capped for the chart

    cl = client.post("/api/screening/cluster", json={"datasetId": meta["id"], "basis": "hourly", "k": 2}).json()
    assert cl["nClusters"] == 2 and cl["labels"]["S1"] == cl["labels"]["S2"] != cl["labels"]["W1"]
    assert sorted(cl["order"]) == ["S1", "S2", "W1", "W2"]
    default_k = client.post("/api/screening/cluster", json={"datasetId": meta["id"]}).json()
    assert default_k["nClusters"] >= 1
    cut = client.post("/api/screening/cluster", json={"datasetId": meta["id"], "threshold": 0.4, "basis": "hourly"})
    assert cut.status_code == 200


def test_chart_series_are_downsampled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = _upload(client)
    monkeypatch.setattr(screening_router, "MAX_CHART_POINTS", 100)
    prof = client.post("/api/screening/profiles", json={"datasetId": meta["id"]}).json()
    assert len(prof["timeseries"]["timestamps"]) == 100 and prof["timeseries"]["downsampledFrom"] == HOURS


def test_metrics_optimise_routes(client: TestClient) -> None:
    meta = _upload(client)
    m = client.post("/api/screening/metrics", json={"datasetId": meta["id"], "weights": {"S1": 1, "W1": 1}, "lowThreshold": 0.05, "worstN": 24}).json()
    assert_allclose(sum(m["weights"].values()), 1.0)
    assert 0 < m["portfolio"]["meanCf"] < 1 and m["portfolio"]["p90"] <= m["portfolio"]["p50"] <= m["portfolio"]["p10"]
    assert m["durationCurve"]["portfolio"]["y"] == sorted(m["durationCurve"]["portfolio"]["y"], reverse=True)
    assert set(m["durationCurve"]["sites"]) == {"S1", "W1"} and m["worstN"] == 24
    assert client.post("/api/screening/metrics", json={"datasetId": meta["id"], "weights": {"S1": 0}}).status_code == 422

    o = client.post("/api/screening/optimise", json={"datasetId": meta["id"], "objective": "min_variance", "frontierPoints": 6}).json()
    assert_allclose(sum(o["weights"].values()), 1.0, atol=1e-9)
    assert o["metrics"]["portfolio"]["std"] > 0
    eq = client.post("/api/screening/metrics", json={"datasetId": meta["id"], "weights": {k: 1 for k in ("S1", "S2", "W1", "W2")}}).json()
    assert o["metrics"]["portfolio"]["std"] <= eq["portfolio"]["std"] + 1e-9  # min-variance beats equal weights
    capped = client.post("/api/screening/optimise", json={"datasetId": meta["id"], "regionCaps": {"north": 0.3}}).json()
    assert capped["weights"].get("S1", 0) + capped["weights"].get("W1", 0) <= 0.3 + 1e-6
    bad = client.post("/api/screening/optimise", json={"datasetId": meta["id"], "targetMeanCf": 0.99})
    assert bad.status_code == 422 and "highest reachable" in bad.json()["detail"]
    one = client.post("/api/screening/optimise", json={"datasetId": meta["id"], "sites": ["S1"]})
    assert one.status_code == 422


# ── promote ──────────────────────────────────────────────────────────────────


def _model_on(idx: pd.DatetimeIndex, step_label: str = "%Y-%m-%d %H:%M") -> None:
    model_store.save_model("default", {
        "buses": [{"name": "north_bus", "x": 127.0, "y": 37.5}, {"name": "south_bus", "x": 129.0, "y": 35.2}],
        "carriers": [{"name": "AC"}],
        "snapshots": [{"snapshot": t.strftime(step_label)} for t in idx],
        "generators": [{"name": "gas", "bus": "north_bus", "carrier": "gas", "p_nom": 1000.0}],
        "loads": [{"name": "l", "bus": "north_bus"}],
        "loads-p_set": [{"snapshot": t.strftime(step_label), "l": 100.0} for t in idx],
        "generators-p_max_pu": [{"snapshot": t.strftime(step_label), "gas": 1.0} for t in idx],
    })


def test_promote_preview_then_apply_aligns_profiles_to_model_snapshots(client: TestClient) -> None:
    wide = _frame()
    meta = _upload(client, wide)
    idx = wide.index[:200]
    _model_on(idx)
    prev = client.post("/api/screening/promote", json={"datasetId": meta["id"], "sites": ["S1", "W1"]}).json()
    assert prev["applied"] is False and prev["report"]["ok"] and prev["report"]["mode"] == "model-snapshots"
    assert prev["generators"] == [generator_name("solar", "S1"), generator_name("wind", "W1")]
    s1 = prev["report"]["sites"][0]
    assert s1["bus"] == "north_bus" and s1["alignment"]["exact"] == 200 and s1["alignment"]["unaligned"] == 0
    rows = prev["fragment"]["sheets"]["generators-p_max_pu"]
    assert len(rows) == 200
    assert_allclose([r[generator_name("solar", "S1")] for r in rows], wide["S1"].iloc[:200].round(4).to_numpy(), atol=1e-12)
    assert model_store.load_full_model("default")["generators"][0]["name"] == "gas"  # preview changed nothing
    assert len(model_store.load_full_model("default")["generators"]) == 1

    done = client.post("/api/screening/promote", json={"datasetId": meta["id"], "sites": ["S1", "W1"], "apply": True, "includeFragment": False}).json()
    assert done["applied"] is True and "fragment" not in done
    full = model_store.load_full_model("default")
    names = [g["name"] for g in full["generators"]]
    assert names == ["gas", "screen_solar_S1", "screen_wind_W1"]
    pmax = {k: v for k, v in full["generators-p_max_pu"][100].items()}
    assert pmax["gas"] == 1.0
    assert_allclose(pmax["screen_solar_S1"], round(float(wide["S1"].iloc[100]), 4), atol=1e-12)
    assert len(full["snapshots"]) == 200  # the model's own window was kept
    g = next(g for g in full["generators"] if g["name"] == "screen_wind_W1")
    assert g["carrier"] == "wind" and g["p_nom"] == 100.0 and g["bus"] == "north_bus"


def test_promote_reports_misalignment_and_blocks_apply(client: TestClient) -> None:
    meta = _upload(client)
    # model year 2030: no exact match, calendar match falls back to the same month-day-hour of 2019
    idx = pd.date_range("2030-06-03", periods=48, freq="1h")
    _model_on(idx)
    prev = client.post("/api/screening/promote", json={"datasetId": meta["id"], "sites": ["S1"]}).json()
    assert prev["report"]["ok"] is False and prev["report"]["exactShare"] == 0.0
    assert prev["report"]["sites"][0]["alignment"]["monthDayHour"] == 48
    assert any("calendar hour of another year" in w for w in prev["report"]["warnings"])
    blocked = client.post("/api/screening/promote", json={"datasetId": meta["id"], "sites": ["S1"], "apply": True})
    assert blocked.status_code == 409 and blocked.json()["detail"]["report"]["ok"] is False
    forced = client.post("/api/screening/promote", json={"datasetId": meta["id"], "sites": ["S1"], "apply": True, "force": True})
    assert forced.status_code == 200 and forced.json()["applied"] is True


def test_promote_utc_offset_shifts_the_profile_onto_the_models_clock(client: TestClient) -> None:
    wide = _frame()
    meta = _upload(client, wide)
    local = wide.index[:48] + pd.Timedelta(hours=9)  # model labelled in UTC+9
    _model_on(local)
    prev = client.post("/api/screening/promote", json={"datasetId": meta["id"], "sites": ["S1"], "utcOffset": 9}).json()
    assert prev["report"]["sites"][0]["alignment"]["exact"] == 48
    col = [r["screen_solar_S1"] for r in prev["fragment"]["sheets"]["generators-p_max_pu"]]
    assert_allclose(col, wide["S1"].iloc[:48].round(4).to_numpy(), atol=1e-12)
    wrong = client.post("/api/screening/promote", json={"datasetId": meta["id"], "sites": ["S1"], "utcOffset": 0}).json()
    wrong_col = [r["screen_solar_S1"] for r in wrong["fragment"]["sheets"]["generators-p_max_pu"]]
    assert_allclose(wrong_col, wide["S1"].iloc[9:57].round(4).to_numpy(), atol=1e-12)  # same labels, 9 h later weather


def test_promote_overrides_extendable_errors_and_empty_model(client: TestClient) -> None:
    meta = _upload(client)
    r = client.post("/api/screening/promote", json={"datasetId": meta["id"], "sites": ["S1"]})
    assert r.status_code == 422 and "bus" in r.json()["detail"]  # an empty session has no bus to attach to
    own = client.post("/api/screening/promote", json={
        "datasetId": meta["id"], "sites": ["S1", "S2"], "buses": [{"name": "hub", "x": 128.0, "y": 36.0}], "targetSnapshots": [],
        "extendable": True, "capitalCost": {"solar": 55000}, "discountRate": 0.06, "pNomMw": {"S1": 250}, "busOverrides": {"S2": "elsewhere"},
    }).json()
    assert own["report"]["mode"] == "own-snapshots" and own["report"]["snapshots"] == HOURS
    gens = {g["name"]: g for g in own["fragment"]["sheets"]["generators"]}
    s1 = gens["screen_solar_S1"]
    assert s1["p_nom"] == 0.0 and s1["p_nom_extendable"] is True and s1["p_nom_max"] == 250.0 and s1["overnight_cost"] == 55000.0
    assert s1["discount_rate"] == 0.06 and s1["lifetime"] == 25.0 and "capital_cost" not in s1
    assert gens["screen_solar_S2"]["bus"] == "elsewhere"
    assert any("no snapshots" in w for w in own["report"]["warnings"])
    assert client.post("/api/screening/promote", json={"datasetId": meta["id"], "sites": []}).status_code == 422
    assert client.post("/api/screening/promote", json={"datasetId": meta["id"], "sites": ["ghost"]}).status_code == 422


def test_build_promotion_resamples_non_hourly_datasets() -> None:
    idx = pd.date_range("2019-06-01", periods=96, freq="30min")
    series = pd.DataFrame({"S1": np.linspace(0, 1, 96)}, index=idx)
    site = [{"name": "S1", "lat": 36.0, "lon": 127.0, "technology": "solar", "capacityMw": 20.0}]
    targets = [t.strftime("%Y-%m-%d %H:%M") for t in pd.date_range("2019-06-01", periods=48, freq="1h")]
    frag, rep = build_promotion(series, site, ["S1"], step_minutes=30.0, target_snapshots=targets,
                                buses=[{"name": "b", "x": 127.0, "y": 36.0}])
    assert any("averaged to hourly" in w for w in rep["warnings"]) and rep["ok"]
    col = [r["screen_solar_S1"] for r in frag.sheets["generators-p_max_pu"]]
    assert_allclose(col[0], round((0.0 + 1 / 95) / 2, 4), atol=1e-4)
    assert frag.sheets["generators"][0]["p_nom"] == 20.0  # the site's own capacity


# ── regions ──────────────────────────────────────────────────────────────────

BASE = "/api/screening"


def _region_world(hours: int = 24 * 40, seed: int = 4) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Three regions of three sites: a weather factor per region plus a weaker shared national factor."""
    rng = np.random.default_rng(seed)
    nat = rng.standard_normal(hours)
    cols: dict[str, np.ndarray] = {}
    rows = []
    for ri, region in enumerate(("north", "mid", "south")):
        factor = rng.standard_normal(hours)
        for k in range(3):
            name = f"{region[0].upper()}{k + 1}"
            z = 0.8 * factor + 0.4 * nat + 0.4 * rng.standard_normal(hours)
            cols[name] = np.clip(0.4 + 0.12 * z, 0, 1)
            rows.append({"name": name, "lat": 38 - 1.5 * ri + 0.1 * k, "lon": 127 + 0.2 * k, "technology": "wind" if k < 2 else "solar",
                         "region": region, "capacity_mw": 50.0 * (k + 1)})
    return pd.DataFrame(cols, index=pd.date_range("2019-01-01", periods=hours, freq="1h")), pd.DataFrame(rows)


def _upload_world(client: TestClient, **form: Any) -> dict[str, Any]:
    wide, sites = _region_world()
    files = {"file": ("s.csv", _csv(wide), "text/csv"), "sitesFile": ("sites.csv", sites.to_csv(index=False).encode(), "text/csv")}
    resp = client.post(f"{BASE}/datasets", files=files, data={"name": "world", **form})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_region_level_correlation_is_the_correlation_of_the_aggregated_series(client: TestClient) -> None:
    meta = _upload_world(client)
    wide, sites = _region_world()
    body = {"datasetId": meta["id"], "level": "region", "basis": "daily", "weighting": "capacity"}
    out = client.post(f"{BASE}/correlation", json=body).json()
    assert out["level"] == "region" and out["sites"] == ["north", "mid", "south"]
    cap = sites.set_index("name")["capacity_mw"]
    agg = pd.DataFrame({r: (wide[g["name"]] * cap[g["name"]]).sum(axis=1) / cap[g["name"]].sum()
                        for r, g in sites.groupby("region").__iter__() for g in [g]}, index=wide.index)
    expect = agg.resample("D").mean().corr().loc[out["sites"], out["sites"]].to_numpy()
    assert_allclose(np.array(out["matrix"], dtype=float), expect, rtol=0, atol=1e-9)
    assert len(out["distance"]) == 3 and all(p["km"] > 0 for p in out["distance"])  # centroids from the member sites
    # the same request at site level is a 9 x 9 matrix: the level switch changes the unit of analysis, not the shape
    site = client.post(f"{BASE}/correlation", json={"datasetId": meta["id"], "basis": "daily"}).json()
    assert len(site["sites"]) == 9


def test_region_level_all_the_bases_and_the_portfolio_routes(client: TestClient) -> None:
    meta = _upload_world(client)
    base = {"datasetId": meta["id"], "level": "region"}
    for basis in ("hourly", "daily", "weekly", "monthly", "seasonal", "diurnal", "month_hour"):
        r = client.post(f"{BASE}/correlation", json={**base, "basis": basis, "method": "spearman"})
        assert r.status_code == 200, (basis, r.text)
        assert len(r.json()["matrix"]) == 3
    assert client.post(f"{BASE}/correlation", json={**base, "basis": "custom", "rule": "6h", "anomaly": True,
                                                    "start": "2019-01-05", "end": "2019-02-05", "months": [1, 2]}).status_code == 200
    assert client.post(f"{BASE}/cluster", json={**base, "basis": "daily", "k": 2}).json()["nClusters"] == 2
    lag = client.post(f"{BASE}/lagged", json={**base, "site": "north", "maxLagHours": 6}).json()
    assert lag["site"] == "north" and set(lag["series"]) == {"mid", "south"}
    prof = client.post(f"{BASE}/profiles", json=base).json()
    assert prof["sites"] == ["north", "mid", "south"] and len(prof["diurnal"]["hours"]) == 24
    m = client.post(f"{BASE}/metrics", json={**base, "weights": {"north": 1, "south": 1}}).json()
    assert set(m["weights"]) == {"north", "south"}
    assert m["portfolio"]["diversificationRatio"] > 1
    opt = client.post(f"{BASE}/optimise", json={**base, "regionCaps": {"north": 0.3}, "maxWeight": 0.6}).json()
    assert opt["weights"]["north"] <= 0.3 + 1e-6 and abs(sum(opt["weights"].values()) - 1) < 1e-6
    ref = client.post(f"{BASE}/correlation", json={**base, "basis": "daily", "reference": {"type": "load"}})
    assert ref.status_code == 422  # no model load: the reference path is shared with the site level


def test_by_technology_and_region_caps(client: TestClient) -> None:
    meta = _upload_world(client)
    base = {"datasetId": meta["id"], "level": "region", "byTechnology": True}
    out = client.post(f"{BASE}/correlation", json={**base, "basis": "daily"}).json()
    assert out["sites"] == ["north | wind", "north | solar", "mid | wind", "mid | solar", "south | wind", "south | solar"]
    opt = client.post(f"{BASE}/optimise", json={**base, "regionCaps": {"north": 0.2}}).json()  # caps the sum of north's two columns
    assert opt["weights"]["north | wind"] + opt["weights"]["north | solar"] <= 0.2 + 1e-6
    only = client.post(f"{BASE}/regions", json={"datasetId": meta["id"], "technology": "solar"}).json()
    assert [r["nSites"] for r in only["regions"]] == [1, 1, 1] and only["source"] == "sites"


def test_regions_route_reports_members_weights_and_errors(client: TestClient) -> None:
    meta = _upload_world(client)
    out = client.post(f"{BASE}/regions", json={"datasetId": meta["id"], "weighting": "capacity"}).json()
    north = out["regions"][0]
    assert north["name"] == "north" and north["nSites"] == 3 and north["capacityMw"] == 300.0
    assert_allclose([m["weight"] for m in north["members"]], [50 / 300, 100 / 300, 150 / 300], atol=1e-12)
    bad = client.post(f"{BASE}/regions", json={"datasetId": meta["id"], "weighting": "custom", "siteWeights": {"N1": 1}})
    assert bad.status_code == 422 and "zero" in bad.json()["detail"]
    assert client.post(f"{BASE}/correlation", json={"datasetId": meta["id"], "level": "country"}).status_code == 422


def test_region_structure_route_within_beats_between(client: TestClient) -> None:
    meta = _upload_world(client)
    out = client.post(f"{BASE}/regions/structure", json={"datasetId": meta["id"], "basis": "hourly"}).json()
    s = out["summary"]
    # factor share 0.64 + 0.16 vs 0.16 national: within pair r ~ (0.64 + 0.16) / 0.96 = 0.83, between ~ 0.16 / 0.96 = 0.17
    assert_allclose(s["withinMean"], 0.80 / 0.96, atol=0.05)
    assert_allclose(s["betweenMean"], 0.16 / 0.96, atol=0.05)
    assert s["nWithinPairs"] == 9 and s["nBetweenPairs"] == 27 and s["gain"] > 0.5
    assert [w["nSites"] for w in out["within"]] == [3, 3, 3] and len(out["between"]) == 3
    assert all(b["aggregateR"] is not None for b in out["between"])
    sv = out["siteVsRegion"]
    assert len(sv["sites"]) == 9 and sv["regions"] == ["north", "mid", "south"] and sv["behavesLike"] == []
    assert all(sv["own"][n] > 0.7 for n in sv["sites"])
    one = client.post(f"{BASE}/regions/structure", json={"datasetId": meta["id"], "regions": ["north"]})
    assert one.status_code == 422  # a single region has nothing to compare


def test_region_dataset_upload_with_centroid_polygon_and_validation(client: TestClient) -> None:
    wide, _ = _region_world()
    reg = pd.DataFrame({r: wide[[c for c in wide.columns if c.startswith(r[0].upper())]].mean(axis=1) for r in ("north", "mid", "south")})
    square = {"type": "Polygon", "coordinates": [[[126.0, 35.0], [128.0, 35.0], [128.0, 37.0], [126.0, 37.0], [126.0, 35.0]]]}
    table = [{"name": "north", "lat": 37.5, "lon": 127.0, "technology": "wind"}, {"name": "mid"}, {"name": "south", "lat": 35.1, "lon": 126.9}]
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "mid"}, "geometry": square},
        {"type": "Feature", "properties": {"name": "nowhere"}, "geometry": square}]}
    files = {"file": ("r.csv", _csv(reg), "text/csv")}
    form = {"kind": "regions", "name": "zones", "sitesJson": json.dumps(table), "geojson": json.dumps(gj)}
    resp = client.post(f"{BASE}/datasets", files=files, data=form)
    assert resp.status_code == 200, resp.text
    meta = resp.json()
    mid = next(r for r in meta["regions"] if r["name"] == "mid")
    assert_allclose([mid["lat"], mid["lon"]], [36.0, 127.0], atol=1e-9)
    assert mid["geometry"]["type"] == "Polygon"
    assert any("nowhere" in w for w in meta["report"]["warnings"])
    listed = client.get(f"{BASE}/datasets", params={"kind": "regions"}).json()
    assert listed["total"] == 1 and listed["items"][0]["regionCount"] == 3 and listed["items"][0]["siteCount"] == 0
    out = client.post(f"{BASE}/correlation", json={"datasetId": meta["id"], "level": "region", "basis": "daily"}).json()
    expect = reg.resample("D").mean().corr().to_numpy()
    assert_allclose(np.array(out["matrix"], dtype=float), expect, atol=1e-9)
    assert len(out["distance"]) == 3  # centroids: two given, one from the polygon
    info = client.post(f"{BASE}/regions", json={"datasetId": meta["id"]}).json()
    assert info["source"] == "regions" and info["regions"][1]["geometry"]["type"] == "Polygon" and info["regions"][0]["nSites"] is None
    # the site routes refuse a region dataset; the structure route needs sites
    assert client.post(f"{BASE}/correlation", json={"datasetId": meta["id"], "basis": "daily"}).status_code == 422
    assert client.post(f"{BASE}/regions/structure", json={"datasetId": meta["id"]}).status_code == 422
    # the same validation as a site upload: a CF outside 0-1, an unknown series, a bad polygon
    bad = reg.assign(north=reg["north"] * 5)
    r = client.post(f"{BASE}/datasets", files={"file": ("r.csv", _csv(bad), "text/csv")}, data=form)
    assert r.status_code == 422 and "outside the capacity-factor range" in r.text
    r = client.post(f"{BASE}/datasets", files={"file": ("r.csv", _csv(reg.assign(extra=0.1)), "text/csv")}, data=form)
    assert r.status_code == 422 and "not in the region table" in r.text
    badtable = [{"name": "north", "geometry": {"type": "Point", "coordinates": [1, 2]}}, {"name": "mid"}, {"name": "south"}]
    r = client.post(f"{BASE}/datasets", files={"file": ("r.csv", _csv(reg), "text/csv")}, data={"kind": "regions", "sitesJson": json.dumps(badtable)})
    assert r.status_code == 422 and "Polygon" in r.text
    v = client.post(f"{BASE}/validate", files={"file": ("r.csv", _csv(reg), "text/csv")}, data=form).json()
    assert v["ok"] is True and v["siteCount"] == 3


def test_datasets_stored_under_the_old_siting_folder_still_load(client: TestClient, tmp_path: Path) -> None:
    meta = _upload_world(client)
    root = tmp_path / "data"
    new = root / "screening_datasets" / "default" / meta["id"]
    assert new.is_dir()
    legacy = root / "siting_datasets" / "default"
    legacy.mkdir(parents=True)
    new.rename(legacy / meta["id"])  # as the earlier Siting > Screening step stored it
    assert not new.exists()
    got = client.get(f"{BASE}/datasets/{meta['id']}").json()
    assert got["id"] == meta["id"] and len(got["sites"]) == 9
    assert new.is_dir() and not legacy.exists()  # moved, the empty old folder removed
    again = client.get(f"{BASE}/datasets", params={"kind": "sites"}).json()
    assert again["total"] == 1  # idempotent: nothing duplicated on a second touch
