"""Self-hosted hourly demand database (D2): parsers, validation, storage, refresh, importer, API, MCP.

No network: the parsers run on fixtures captured from the real files (OPSD 2020-10-06 and
EIA-930 2023 Jan-Jun, trimmed to a few BAs / two days); the refresh runs against an
``httpx.MockTransport``. The ENTSO-E XML is hand-written to the documented schema (no token to
capture one). The single live test is marked ``integration`` and skipped unless
``RAGNAROK_INTEGRATION=1``.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

from backend.app.importers.demand_db import catalogue, parsers, refresh, store
from backend.app.importers.databases import demand_db as importer
from backend.app.importers.protocol import ConvertOptions

FIX = Path(__file__).parent / "fixtures" / "demand_db"
OPSD_URL = "https://example.test/opsd.csv"


def _frame(start: str, values: list[float], url: str = "u") -> pd.DataFrame:
    ts = pd.date_range(start, periods=len(values), freq="h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "load_mw": values, "source_url": url})


@pytest.fixture()
def db_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("RAGNAROK_DEMAND_DB_DIR", str(tmp_path / "db"))
    return tmp_path / "db"


# -- parsers ---------------------------------------------------------------------------------------


def test_opsd_parse_is_hour_beginning_utc_mw():
    assert set(parsers.opsd_areas(FIX / "opsd_small.csv")) == {"DE", "FR", "GB_GBN", "GB_NIR"}  # forecast col excluded
    out = parsers.parse_opsd(FIX / "opsd_small.csv", ["DE", "FR"], OPSD_URL)
    de = out["DE"]
    assert len(de) == 48
    assert de["timestamp"].iloc[0] == pd.Timestamp("2019-01-01T00:00:00Z")  # OPSD stamps are period start
    assert de["load_mw"].iloc[0] == 41562.0  # captured value, MW (not the 41275 forecast)
    assert (de["source_url"] == OPSD_URL).all()


def test_opsd_unknown_area_is_an_error():
    with pytest.raises(parsers.ParseError):
        parsers.parse_opsd(FIX / "opsd_small.csv", ["XX"], OPSD_URL)


def test_eia_parse_shifts_hour_ending_to_hour_beginning():
    out = parsers.parse_eia930(FIX / "eia930_small.csv", None, "u")
    assert set(out) == {"CISO", "ERCO"}
    ciso = out["CISO"]
    # first captured row: UTC end 2023-01-01 09:00 -> hour starting 08:00 (RI4, same as eia_demand)
    assert ciso["timestamp"].iloc[0] == pd.Timestamp("2023-01-01T08:00:00Z")
    assert ciso["load_mw"].iloc[0] == 22049.0
    only = parsers.parse_eia930(FIX / "eia930_small.csv", ["ERCO"], "u")
    assert set(only) == {"ERCO"}


def test_eia_parse_falls_back_to_imputed_then_reported(tmp_path):
    csv = tmp_path / "x.csv"
    csv.write_text(
        '"Balancing Authority","UTC Time at End of Hour","Demand (MW)","Demand (MW) (Imputed)","Demand (MW) (Adjusted)"\n'
        '"AAA","01/01/2023 1:00:00 AM","100","","110"\n'      # adjusted wins
        '"AAA","01/01/2023 2:00:00 AM","120","125",""\n'      # imputed fills the missing adjusted
        '"AAA","01/01/2023 3:00:00 AM","130","",""\n'         # raw is the last resort
        '"AAA","01/01/2023 4:00:00 AM","","",""\n'            # nothing -> row dropped
        '"AAA","01/01/2023 5:00:00 AM","1,234","","1,234"\n', # thousands separator
        encoding="utf-8",
    )
    df = parsers.parse_eia930(csv, None, "u")["AAA"]
    assert df["load_mw"].tolist() == [110.0, 125.0, 130.0, 1234.0]


def test_eia_html_body_is_a_parse_error_not_an_empty_result(tmp_path):
    with pytest.raises(parsers.ParseError):
        parsers.parse_eia930(FIX / "html_error_page.html", None, "u")


def test_entsoe_parse_averages_quarter_hours_and_acknowledgement_raises():
    df = parsers.parse_entsoe_load((FIX / "entsoe_load_a65.xml").read_text(), "u")
    assert df["timestamp"].tolist() == [pd.Timestamp("2023-01-01T00:00Z"), pd.Timestamp("2023-01-01T01:00Z")]
    np.testing.assert_allclose(df["load_mw"], [40300.0, 39000.0], rtol=0, atol=1e-9)  # mean of 4 points each
    with pytest.raises(RuntimeError) as ei:
        parsers.parse_entsoe_load((FIX / "entsoe_no_data_ack.xml").read_text(), "u")
    assert parsers.is_no_data_error(ei.value)


# -- validation + store ---------------------------------------------------------------------------


def test_validate_rejects_bad_rows_and_reports_reasons():
    df = _frame("2023-01-01", [10, -5, np.nan, 2e6, 20, 30])
    df.loc[5, "timestamp"] = pd.Timestamp("2023-01-01T05:30:00Z")  # not on the hour
    dup = df.iloc[[0]].copy()
    dup["load_mw"] = 11.0
    clean, rejected = store.validate_frame(pd.concat([df, dup], ignore_index=True))
    assert clean["load_mw"].tolist() == [11.0, 20.0]  # duplicate: last wins
    assert rejected == {"non_finite": 1, "negative": 1, "implausible": 1, "not_on_the_hour": 1, "duplicate_timestamp": 1}


def test_validate_schema_drift_fails_loudly():
    with pytest.raises(store.SchemaDriftError):
        store.validate_frame(pd.DataFrame({"timestamp": [], "mw": []}))
    bad = _frame("2023-01-01", [-1.0] * 150 + [5.0] * 50)  # 75 % rejected
    with pytest.raises(store.SchemaDriftError):
        store.validate_frame(bad)


def test_write_slice_is_idempotent_and_records_revisions(db_dir):
    raw = [{"url": "u", "sha256": "ab", "bytes": 1, "fetched_at": "t"}]
    df = _frame("2023-01-01", [1.0, 2.0, 3.0, 4.0])
    first = store.write_slice("eia930", "ERCO", df, raw_files=raw)
    assert (first["added"], first["changed"], first["written"]) == (4, 0, True)
    again = store.write_slice("eia930", "ERCO", df, raw_files=raw)
    assert (again["added"], again["changed"], again["written"]) == (0, 0, False)
    assert again["sha256"] == first["sha256"] and again["retrieved_at"] == first["retrieved_at"]
    revised = df.copy()
    revised.loc[1, "load_mw"] = 99.0
    third = store.write_slice("eia930", "ERCO", revised, raw_files=raw)
    assert (third["changed"], third["written"]) == (1, True)
    assert store.read_slice("eia930/ERCO")["load_mw"].tolist() == [1.0, 99.0, 3.0, 4.0]
    log = [json.loads(line) for line in (db_dir / store.LOG_NAME).read_text().splitlines()]
    assert [r["changed"] for r in log] == [0, 1]  # the revision is on record


def test_write_slice_merges_years_and_manifest_fields(db_dir):
    store.write_slice("opsd", "DE", _frame("2019-01-01", [1.0] * 24), raw_files=[])
    e = store.write_slice("opsd", "DE", _frame("2019-01-02", [2.0] * 24), raw_files=[])
    assert e["rows"] == 48 and e["added"] == 24
    m = store.load_manifest()["slices"]["opsd/DE"]
    for k in ("licence", "attribution", "coverage_start", "coverage_end", "rows", "sha256", "retrieved_at",
              "unit", "timezone", "timestamp_convention", "schema_version", "measure", "iso3"):
        assert k in m, k
    assert (m["unit"], m["timezone"], m["timestamp_convention"], m["iso3"]) == ("MW", "UTC", "hour-beginning", "DEU")
    assert m["sha256"] == hashlib.sha256((db_dir / m["file"]).read_bytes()).hexdigest()
    assert (store.read_slice("opsd/DE")["source_url"] == "u").all()


def test_failed_write_leaves_previous_slice_and_no_temp_files(db_dir, monkeypatch):
    store.write_slice("opsd", "DE", _frame("2019-01-01", [1.0] * 24), raw_files=[])
    before = (db_dir / "slices/opsd/DE.parquet").read_bytes()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)
    with pytest.raises(OSError):
        store.write_slice("opsd", "DE", _frame("2019-02-01", [3.0] * 24), raw_files=[])
    assert (db_dir / "slices/opsd/DE.parquet").read_bytes() == before
    assert not list((db_dir / "slices/opsd").glob("*.tmp"))
    assert store.load_manifest()["slices"]["opsd/DE"]["rows"] == 24


def test_slice_keys_cannot_escape_the_data_dir(db_dir):
    for bad in ("opsd/../../etc/passwd", "nosuch/DE", "opsd/", "opsd/a/b"):
        with pytest.raises(KeyError):
            store.split_key(bad)


def test_resolve_key_prefers_coverage_then_source_order(db_dir):
    store.write_slice("opsd", "DE", _frame("2019-01-01", [1.0] * 24 * 30), raw_files=[])
    store.write_slice("opsd", "DE_LU", _frame("2019-01-01", [1.0] * 24 * 30), raw_files=[])  # sub-zone: never auto
    assert store.resolve_key("auto", "DEU", 2019, 2019) == "opsd/DE"
    store.write_slice("entsoe", "DEU", _frame("2019-01-01", [1.0] * 24 * 30), raw_files=[])
    assert store.resolve_key(None, "DEU", 2019, 2019) == "entsoe/DEU"  # tie on coverage -> ENTSO-E first
    assert store.resolve_key("opsd/DE", None, 2019, 2019) == "opsd/DE"
    with pytest.raises(KeyError):
        store.resolve_key("auto", "FRA", 2019, 2019)
    with pytest.raises(KeyError):
        store.resolve_key("opsd/XX", None, 2019, 2019)


def test_coverage_view(db_dir):
    assert store.coverage()["slices"] == []
    store.write_slice("opsd", "FR", _frame("2019-01-01", [1.0] * 24), raw_files=[])
    cov = store.coverage()
    assert cov["slices"][0]["key"] == "opsd/FR" and cov["sources"]["opsd"]["slices"] == 1
    assert cov["timestamp_convention"] == "hour-beginning"


# -- selection helpers ----------------------------------------------------------------------------


def test_parse_years_and_match_areas():
    assert refresh.parse_years(["2019", "2021-2022", "2020,2019"]) == [2019, 2020, 2021, 2022]
    assert refresh.parse_years(None) is None
    with pytest.raises(ValueError):
        refresh.parse_years(["2022-2020"])
    avail = ["DE", "DE_LU", "FR", "GB_GBN", "GB_NIR", "GB_UKM", "IE", "IE_sem"]
    assert refresh.match_areas("opsd", avail, ["DE"]) == ["DE"]  # exact wins over DE_*
    assert refresh.match_areas("opsd", avail, ["GB"]) == ["GB_GBN", "GB_NIR", "GB_UKM"]
    assert refresh.match_areas("opsd", avail, ["FRA", "IE_sem"]) == ["FR", "IE_sem"]
    assert refresh.match_areas("opsd", avail, None) == sorted(avail)
    assert refresh.match_areas("eia930", ["ERCO", "PJM"], ["USA"]) == ["ERCO", "PJM"]
    assert refresh.match_areas("eia930", ["ERCO", "PJM"], ["erco"]) == ["ERCO"]
    assert refresh.match_areas("entsoe", ["DEU", "FRA"], ["DE", "FRA"]) == ["DEU", "FRA"]


# -- refresh against a mock server ----------------------------------------------------------------


def _mock_site(calls: list, *, flaky_first: bool = False):
    opsd_csv = (FIX / "opsd_small.csv").read_bytes()
    eia_csv = (FIX / "eia930_small.csv").read_bytes()
    pkg = json.dumps({"resources": [{"path": refresh.OPSD_CSV, "hash": hashlib.sha256(opsd_csv).hexdigest()}]})
    state = {"flaked": False}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("datapackage.json"):
            return httpx.Response(200, text=pkg)
        if path.endswith(refresh.OPSD_CSV):
            if flaky_first and not state["flaked"]:
                state["flaked"] = True
                return httpx.Response(429, headers={"Retry-After": "7"})
            return httpx.Response(200, content=opsd_csv, headers={"ETag": '"o1"'})
        if path.endswith("EIA930_BALANCE_2023_Jan_Jun.csv"):
            return httpx.Response(200, content=eia_csv, headers={"ETag": '"e1"', "Content-Length": str(len(eia_csv))})
        if "EIA930_BALANCE" in path:  # soft 404: HTTP 200 with an HTML page
            return httpx.Response(200, content=(FIX / "html_error_page.html").read_bytes())
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _dl(calls, **kw) -> refresh.Downloader:
    sleeps: list[float] = []
    dl = refresh.Downloader(transport=_mock_site(calls, **kw), pause_seconds=0, sleep=sleeps.append)
    dl.sleeps = sleeps  # type: ignore[attr-defined]
    return dl


def test_refresh_opsd_and_eia_end_to_end_then_rerun_reuses_raw(db_dir):
    calls: list = []
    dl = _dl(calls)
    rep = refresh.run_refresh(base=db_dir, sources=["opsd", "eia930"], countries=["DE", "ERCO"], years=[2019, 2023],
                              downloader=dl, entsoe_token=None)
    assert rep["opsd"]["status"] == "ok" and rep["eia930"]["status"] == "ok"
    keys = {s["key"] for r in rep.values() for s in r["slices"]}
    assert keys == {"opsd/DE", "eia930/ERCO"}
    # 2019 asked of EIA: its files are HTML soft-404s -> skipped, 2023 Jan-Jun used; Jul-Dec 2023 is also HTML here
    erco = store.read_slice("eia930/ERCO")
    assert len(erco) == 48 and erco["timestamp"].iloc[0] == pd.Timestamp("2023-01-01T06:00:00Z")  # ERCO local 1am = 07:00Z end
    assert not list(db_dir.rglob("*.part"))
    assert not (db_dir / "raw/eia930/EIA930_BALANCE_2019_Jan_Jun.csv").exists()  # the HTML was never kept

    n_get = len([c for c in calls if c[0] == "GET"])
    calls.clear()
    rep2 = refresh.run_refresh(base=db_dir, sources=["opsd", "eia930"], countries=["DE", "ERCO"], years=[2023],
                               downloader=dl, entsoe_token=None)
    assert [c for c in calls if c[0] == "GET" and c[1].endswith(".csv") and "opsd" in c[1].lower()] == []  # raw reused
    assert all(not s["written"] for r in rep2.values() for s in r["slices"])  # idempotent
    assert n_get > 0


def test_download_retries_429_honouring_retry_after(db_dir):
    calls: list = []
    dl = _dl(calls, flaky_first=True)
    refresh.refresh_opsd(dl, db_dir, ["FR"], None)
    assert 7.0 in dl.sleeps  # Retry-After honoured exactly, not the jittered backoff
    assert store.read_slice("opsd/FR").shape[0] == 48


def test_download_gives_up_after_max_attempts_and_leaves_no_partial_file(db_dir):
    def handler(request):
        return httpx.Response(503)

    dl = refresh.Downloader(transport=httpx.MockTransport(handler), max_attempts=3, pause_seconds=0, sleep=lambda s: None)
    with pytest.raises(refresh.DownloadError):
        dl.download("https://example.test/a.csv", db_dir / "raw/a.csv")
    assert not (db_dir / "raw/a.csv").exists() and not (db_dir / "raw/a.csv.part").exists()


def test_opsd_hash_mismatch_is_rejected(db_dir):
    def handler(request):
        if request.url.path.endswith("datapackage.json"):
            return httpx.Response(200, json={"resources": [{"path": refresh.OPSD_CSV, "hash": "0" * 64}]})
        return httpx.Response(200, content=b"utc_timestamp,DE_load_actual_entsoe_transparency\n")

    dl = refresh.Downloader(transport=httpx.MockTransport(handler), pause_seconds=0, sleep=lambda s: None)
    rep = refresh.run_refresh(base=db_dir, sources=["opsd"], countries=None, years=None, downloader=dl, entsoe_token=None)
    assert rep["opsd"]["status"] == "error" and "sha256 mismatch" in rep["opsd"]["error"]
    assert not list(db_dir.rglob("time_series_60min_singleindex.csv"))
    assert store.load_manifest()["slices"] == {}


def test_entsoe_step_skipped_without_token_and_error_when_explicit(db_dir):
    dl = _dl([])
    rep = refresh.run_refresh(base=db_dir, sources=None, countries=["ERCO"], years=[2023], downloader=dl, entsoe_token=None)
    assert rep["entsoe"]["status"] == "skipped"
    rep = refresh.run_refresh(base=db_dir, sources=["entsoe"], countries=["DEU"], years=[2023], downloader=dl, entsoe_token=None)
    assert rep["entsoe"]["status"] == "error"


def test_entsoe_refresh_with_token_never_stores_or_logs_the_token(db_dir, caplog):
    seen: list[httpx.URL] = []
    xml = (FIX / "entsoe_load_a65.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        assert request.url.params["securityToken"] == "SECRET-TOKEN"
        year = request.url.params["periodStart"][:4]
        if year == "2022":
            return httpx.Response(200, content=(FIX / "entsoe_no_data_ack.xml").read_bytes())
        return httpx.Response(200, content=xml)

    dl = refresh.Downloader(transport=httpx.MockTransport(handler), pause_seconds=0, sleep=lambda s: None,
                            secrets=["SECRET-TOKEN"])
    out = refresh.refresh_entsoe(dl, db_dir, ["DEU"], [2022, 2023], "SECRET-TOKEN")
    assert [s["key"] for s in out] == ["entsoe/DEU"] and out[0]["rows"] == 2  # 2022 = "no data" ack, skipped not fatal
    assert len(seen) == 2
    blob = (db_dir / store.MANIFEST_NAME).read_text() + "".join(p.read_text() for p in db_dir.rglob("*.meta.json"))
    assert "SECRET-TOKEN" not in blob and "securityToken" not in blob


# -- importer -------------------------------------------------------------------------------------


def _seed(db_dir):
    ts = pd.date_range("2019-01-01", "2019-12-31 23:00", freq="h", tz="UTC")
    vals = 50000 + 10000 * np.sin(2 * np.pi * np.arange(len(ts)) / 24)
    df = pd.DataFrame({"timestamp": ts, "load_mw": vals, "source_url": "https://x/opsd.csv"})
    store.write_slice("opsd", "DE", df, raw_files=[{"url": "https://x/opsd.csv", "sha256": "a", "bytes": 1, "fetched_at": "t"}])
    return df


def _region(iso: str = "DEU"):
    from shapely.geometry import box

    from backend.app.importers.protocol import Region

    return Region(iso, iso, box(5, 47, 15, 55))


def test_registered_and_unavailable_until_a_snapshot_exists(db_dir):
    from backend.app.importers.registry import available_databases, get_database

    db = get_database("demand_db")
    meta = next(d for d in available_databases() if d["id"] == "demand_db")
    assert meta["available"] is False and "refresh" in meta["unavailable_reason"]
    with pytest.raises(RuntimeError, match="refresh"):
        asyncio.run(db.fetch(_region(), {}, None))
    _seed(db_dir)
    meta = next(d for d in available_databases() if d["id"] == "demand_db")  # no restart needed
    assert meta["available"] is True and meta["country_coverage"] == ["DEU"]
    series = next(f for f in meta["filters"] if f["id"] == "series")
    assert [o["value"] for o in series["options"]] == ["auto", "opsd/DE"]
    assert next(f for f in meta["filters"] if f["id"] == "year_from")["max"] == 2019
    assert meta["requires_secrets"] == []


def test_importer_returns_load_snapshots_and_provenance(db_dir):
    from backend.app.importers.registry import get_database

    ref = _seed(db_dir)
    db = get_database("demand_db")
    res = asyncio.run(db.fetch(_region(), {"year_from": 2019, "year_to": 2019, "series": "auto"}, None))
    frag = db.to_sheets(res, ConvertOptions()).to_json()
    assert frag["snapshots"][0] == "2019-01-01 00:00" and len(frag["snapshots"]) == 8760
    load = frag["sheets"]["loads"][0]
    assert (load["name"], load["bus"], load["series"]) == ("DEU_demand", "DEU", "opsd/DE")
    assert load["source_url"] == "https://x/opsd.csv" and "MIT" in load["licence"]
    pset = frag["sheets"]["loads-p_set"]
    np.testing.assert_allclose([r["DEU_demand"] for r in pset], ref["load_mw"].to_numpy(), rtol=0, atol=1e-9)
    prov = json.loads(frag["provenance"]["filters_json"])
    assert prov["resolved_series"] == "opsd/DE" and len(prov["slice_sha256"]) == 64
    pv = db.preview(res).to_json()
    assert pv["counts"]["hours"] == 8760 and pv["counts"]["filled_hours"] == 0


def test_importer_interpolates_interior_gaps_and_never_extends_the_window(db_dir):
    df = _frame("2019-01-01", [10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
    gapped = df.drop(index=[2, 3]).reset_index(drop=True)  # 2 interior hours missing
    out, filled = importer.regularise(gapped, True)
    assert filled == 2 and out["load_mw"].tolist() == [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]  # linear
    trimmed = df.drop(index=[0, 5]).reset_index(drop=True)
    out, filled = importer.regularise(trimmed, True)
    assert filled == 0 and len(out) == 4  # edge gaps are not invented
    out, filled = importer.regularise(gapped, False)
    assert filled == 0 and len(out) == 4


def test_importer_explains_empty_year_window_and_unknown_country(db_dir):
    from backend.app.importers.registry import get_database

    _seed(db_dir)
    db = get_database("demand_db")
    with pytest.raises(RuntimeError, match=r"stored years: \[2019\]"):
        asyncio.run(db.fetch(_region(), {"year_from": 2021, "year_to": 2021, "series": "opsd/DE"}, None))
    with pytest.raises(RuntimeError, match="no demand series for country FRA"):
        asyncio.run(db.fetch(_region("FRA"), {"year_from": 2019, "year_to": 2019}, None))
    with pytest.raises(ValueError):
        asyncio.run(db.fetch(_region(), {"year_from": 2020, "year_to": 2019}, None))


# -- API + MCP -------------------------------------------------------------------------------------


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app.routers import demand_db

    app = FastAPI()
    app.include_router(demand_db.router)
    return TestClient(app)


def test_api_coverage_and_slice(db_dir):
    c = _client()
    assert c.get("/api/demand-db/coverage").json()["slices"] == []
    _seed(db_dir)
    cov = c.get("/api/demand-db/coverage").json()
    assert cov["slices"][0]["key"] == "opsd/DE" and cov["sources"]["opsd"]["licence"].startswith("MIT")
    r = c.get("/api/demand-db/slice", params={"series": "opsd/DE", "year_from": 2019}).json()
    assert r["stats"]["hours"] == 8760 and r["unit"] == "MW" and r["timestamp_convention"] == "hour-beginning"
    assert r["timestamps"][0] == "2019-01-01T00:00:00Z" and len(r["load_mw"]) == 8760
    by_country = c.get("/api/demand-db/slice", params={"country": "DEU", "year_from": 2019, "year_to": 2019}).json()
    assert by_country["series"] == "opsd/DE"
    assert c.get("/api/demand-db/slice", params={"series": "opsd/FR", "year_from": 2019}).status_code == 404
    assert c.get("/api/demand-db/slice", params={"year_from": 2019}).status_code == 400
    assert c.get("/api/demand-db/slice", params={"series": "opsd/DE", "year_from": 2019, "year_to": 2018}).status_code == 400
    assert c.get("/api/demand-db/slice", params={"series": "../x", "year_from": 2019}).status_code == 404


def test_main_app_serves_the_routes(db_dir):
    from fastapi.testclient import TestClient

    from backend.app.main import app

    c = TestClient(app)
    assert c.get("/api/demand-db/coverage").status_code == 200
    assert c.get("/api/demand-db/slice", params={"series": "opsd/DE", "year_from": 2019}).status_code == 404  # empty snapshot


def test_mcp_tools_registered_gated_and_truncating(monkeypatch):
    from backend.mcp import server
    from backend.mcp.server import mcp

    by_name = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert by_name["list_demand_db"].annotations.readOnlyHint is True
    assert by_name["get_demand_db_slice"].annotations.readOnlyHint is True
    assert by_name["import_demand_db"].annotations.readOnlyHint is False

    class Fake:
        calls: list = []

        async def demand_db_slice(self, series, country, year_from, year_to):
            return {"timestamps": [str(i) for i in range(10)], "load_mw": list(range(10)), "stats": {"hours": 10}}

        async def import_dataset(self, iso, ids, filters):
            self.calls.append(("import", iso, ids, filters))
            return {"fragment": {"sheets": {}}, "dataset_ids": ids, "country_iso": iso, "preview": {}}

        async def apply_fragment(self, frag):
            self.calls.append(("apply",))

    fake = Fake()
    monkeypatch.setattr(server, "_client", fake)
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "guided")
    from backend.mcp import tools_demand_db as t

    out = asyncio.run(t.get_demand_db_slice(series="opsd/DE", max_values=3))
    assert out["load_mw"] == [0, 1, 2] and out["truncated"]["total"] == 10 and out["stats"]["hours"] == 10
    prev = asyncio.run(t.import_demand_db("DEU", 2019))
    assert prev["status"] == "preview" and fake.calls == []  # gated: nothing sent without confirm
    done = asyncio.run(t.import_demand_db("DEU", 2019, 2020, confirm=True))
    assert done["status"] == "applied" and fake.calls[0][3]["year_to"] == 2020 and fake.calls[1] == ("apply",)


def test_catalogue_states_what_each_source_measures():
    for sid, info in catalogue.SOURCES.items():
        assert info["licence"] and info["measure"] and info["attribution"], sid
    assert "Actual Total Load" in catalogue.SOURCES["opsd"]["measure"]
    assert "hour-ending" in catalogue.SOURCES["eia930"]["measure"]
    assert catalogue.area_iso3("opsd", "GB_GBN") == "GBR" and catalogue.area_iso3("eia930", "ERCO") == "USA"
    assert not catalogue.valid_area("../x")


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("RAGNAROK_INTEGRATION"), reason="live download; set RAGNAROK_INTEGRATION=1")
def test_live_opsd_germany_2019_is_about_490_twh(tmp_path):
    dl = refresh.Downloader()
    try:
        refresh.refresh_opsd(dl, tmp_path, ["DE"], [2019])
    finally:
        dl.close()
    twh = parsers.summary_stats(store.read_slice("opsd/DE", 2019, 2019, tmp_path))["energy_twh"]
    assert 480 <= twh <= 500
