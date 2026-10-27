"""Review 2026-10-27 RI1-RI4 importer regressions (fixtures only, no network)."""
from __future__ import annotations

import pytest
from shapely.geometry import box

from backend.app.importers.combine import combine_fragments
from backend.app.importers.protocol import ConvertOptions, FetchResult, Region, WorkbookFragment


# ── RI1: KPG193 transformer per-unit on s_nom, status-0 dropped ────────────────

def test_kpg193_transformer_pu_on_snom_and_status_zero_dropped() -> None:
    from backend.app.importers.databases.kpg193 import (
        _build_lines,
        _build_transformers,
        _enrich_branches,
    )

    buses = [{"name": "1", "v_nom": 345.0}, {"name": "2", "v_nom": 154.0}, {"name": "3", "v_nom": 154.0}]
    base_mva = 100.0
    rows = [
        # transformer: x = 0.01 pu on 100 MVA, rateA 400 MVA, b = 0.02 pu
        {"fbus": 1, "tbus": 2, "r": 0.001, "x": 0.01, "b": 0.02, "rateA": 400.0,
         "ratio": 1.0, "angle": 0, "status": 1},
        # line: x = 0.1 pu -> ohm on 154 kV, 100 MVA = 0.1 * 154^2/100 = 23.716
        {"fbus": 2, "tbus": 3, "r": 0.01, "x": 0.1, "b": 0.0, "rateA": 200.0,
         "ratio": 0, "angle": 0, "status": 1},
        # out of service
        {"fbus": 1, "tbus": 3, "r": 0.01, "x": 0.1, "b": 0.0, "rateA": 200.0,
         "ratio": 0, "angle": 0, "status": 0},
    ]
    branches = _enrich_branches(rows, buses, base_mva)
    assert len(branches) == 2  # status-0 branch dropped
    (tr,) = _build_transformers(branches)
    assert tr["x"] == pytest.approx(0.01 * 400.0 / 100.0)   # 0.04 pu on s_nom
    assert tr["r"] == pytest.approx(0.001 * 400.0 / 100.0)  # 0.004
    assert tr["b"] == pytest.approx(0.02 * 100.0 / 400.0)   # admittance inverts: 0.005
    assert tr["s_nom"] == 400.0
    (ln,) = _build_lines(branches)
    assert ln["x"] == pytest.approx(23.716)  # lines stay in ohm


def test_kpg193_transformer_zero_rate_keeps_system_base() -> None:
    from backend.app.importers.databases.kpg193 import _build_transformers, _enrich_branches

    buses = [{"name": "1", "v_nom": 345.0}, {"name": "2", "v_nom": 154.0}]
    rows = [{"fbus": 1, "tbus": 2, "r": 0.001, "x": 0.01, "b": 0.02, "rateA": 0,
             "ratio": 1.0, "angle": 0, "status": 1}]
    (tr,) = _build_transformers(_enrich_branches(rows, buses, 100.0))
    assert tr["x"] == pytest.approx(0.01) and tr["b"] == pytest.approx(0.02)


# ── RI4: combine dedupes static rows by name ───────────────────────────────────

def test_combine_dedupes_static_rows_by_name() -> None:
    a = WorkbookFragment(sheets={"buses": [{"name": "DEU", "x": 10.0, "carrier": ""}],
                                 "loads": [{"name": "l1", "bus": "DEU"}]})
    b = WorkbookFragment(sheets={"buses": [{"name": "DEU", "x": 99.0, "carrier": "AC"}, {"name": "FRA"}]})
    out = combine_fragments([a, b], source_id="s", country_iso="DEU", country_name="G",
                            filters={}, dataset_ids=["a", "b"])
    buses = out.sheets["buses"]
    assert [r["name"] for r in buses] == ["DEU", "FRA"]
    assert buses[0]["x"] == 10.0 and buses[0]["carrier"] == "AC"  # first wins, empties filled
    assert len(out.sheets["loads"]) == 1


# ── RI3: ENTSO-E A03 fill, price zones, currency ───────────────────────────────

_A03_LOAD = """<GL_MarketDocument xmlns="urn:x"><TimeSeries><curveType>A03</curveType><Period>
<timeInterval><start>2024-01-01T00:00Z</start><end>2024-01-01T06:00Z</end></timeInterval>
<resolution>PT60M</resolution>
<Point><position>1</position><quantity>100</quantity></Point>
<Point><position>2</position><quantity>200</quantity></Point>
<Point><position>4</position><quantity>300</quantity></Point>
</Period></TimeSeries></GL_MarketDocument>"""


def test_entsoe_a03_forward_fills_to_period_end() -> None:
    from backend.app.importers.databases.entsoe_load import _aggregate_hourly, _parse_load_xml

    hourly = dict(_aggregate_hourly(_parse_load_xml(_A03_LOAD)))
    assert [hourly[f"2024-01-01 0{h}:00"] for h in range(6)] == [100, 200, 200, 300, 300, 300]


def test_entsoe_a01_is_not_filled() -> None:
    from backend.app.importers.databases.entsoe_load import _parse_load_xml

    xml = _A03_LOAD.replace("A03", "A01")
    assert len(_parse_load_xml(xml)) == 3


def test_entsoe_price_a03_fill_and_currency() -> None:
    from backend.app.importers.databases.entsoe_price import (
        _aggregate_hourly,
        _parse_price_currency,
        _parse_price_xml,
    )

    xml = """<Publication_MarketDocument xmlns="urn:x"><TimeSeries><currency_Unit.name>EUR</currency_Unit.name>
    <curveType>A03</curveType><Period>
    <timeInterval><start>2024-01-01T00:00Z</start><end>2024-01-01T04:00Z</end></timeInterval>
    <resolution>PT60M</resolution>
    <Point><position>1</position><price.amount>50.5</price.amount></Point>
    <Point><position>3</position><price.amount>70</price.amount></Point>
    </Period></TimeSeries></Publication_MarketDocument>"""
    assert [v for _, v in _aggregate_hourly(_parse_price_xml(xml))] == [50.5, 50.5, 70, 70]
    assert _parse_price_currency(xml) == "EUR"


def test_entsoe_generation_a03_fill() -> None:
    from backend.app.importers.databases.entsoe_generation_profile import _parse_generation_xml

    xml = """<GL_MarketDocument xmlns="urn:x"><TimeSeries><curveType>A03</curveType>
    <MktPSRType><psrType>B16</psrType></MktPSRType><Period>
    <timeInterval><start>2024-01-01T00:00Z</start><end>2024-01-01T03:00Z</end></timeInterval>
    <resolution>PT60M</resolution>
    <Point><position>1</position><quantity>0</quantity></Point>
    <Point><position>2</position><quantity>5</quantity></Point></Period></TimeSeries></GL_MarketDocument>"""
    assert [v for _, v in _parse_generation_xml(xml)["B16"]] == [0, 5, 5]


def test_entsoe_price_zone_map() -> None:
    from backend.app.importers.databases.entsoe_price import META, price_segments

    # explicit Nordic / Italian zones
    assert price_segments("NOR", "NO3", "2024-01-01", "2024-01-02")[0][0] == "10YNO-3--------J"
    assert price_segments("SWE", "SE4", "2024-01-01", "2024-01-02")[0][0] == "10Y1001A1001A47J"
    assert price_segments("ITA", "IT-SUD", "2024-01-01", "2024-01-02")[0][0] == "10Y1001A1001A788"
    # auto defaults: DK1, SEM (not the control-area codes)
    assert price_segments("DNK", "auto", "2024-01-01", "2024-01-02")[0][0] == "10YDK-1--------W"
    assert price_segments("IRL", None, "2024-01-01", "2024-01-02")[0][0] == "10Y1001A1001A59C"
    # DE-LU only from 2018-10-01; DE-AT-LU before; a straddling window splits
    assert price_segments("DEU", "auto", "2018-01-01", "2018-02-01")[0][1] == "DE-AT-LU"
    assert price_segments("DEU", "auto", "2019-01-01", "2019-02-01")[0][1] == "DE-LU"
    seg = price_segments("DEU", "auto", "2018-09-30", "2018-10-02")
    assert [(s[1], s[2], s[3]) for s in seg] == [
        ("DE-AT-LU", "2018-09-30", "2018-09-30"), ("DE-LU", "2018-10-01", "2018-10-02")]
    assert price_segments("AUT", "auto", "2019-01-01", "2019-01-02")[0][0] == "10YAT-APG------L"
    # a country with a single zone keeps its national code
    assert price_segments("FRA", "auto", "2024-01-01", "2024-01-02")[0][0] == "10YFR-RTE------C"
    zone = next(f for f in META.filters if f.id == "zone")
    assert {o["value"] for o in zone.options} >= {"auto", "DK1", "DK2", "NO5", "SE1", "IT-SARD", "IE-SEM"}
    with pytest.raises(RuntimeError):
        price_segments("DEU", "XX9", "2024-01-01", "2024-01-02")


# ── RI4: EIA paging, OSM thousands separator ───────────────────────────────────

def test_eia_pages_with_offset_until_total() -> None:
    import asyncio

    from backend.app.importers.context import ImportContext
    from backend.app.importers.databases import eia_demand

    total = 12000  # > 2 full pages: last page is partial
    calls: list[int] = []

    class _Http:
        async def get_json(self, url, *, params=None, headers=None):
            off = int(params["offset"])
            calls.append(off)
            n = min(5000, total - off)
            data = [{"period": f"p{off + i}", "value": "1"} for i in range(n)]
            return {"response": {"total": str(total), "data": data}}

    ctx = ImportContext(secrets={"eia_key": "k"}, http=_Http())
    res = asyncio.run(eia_demand.EiaDemand().fetch(
        Region("USA", "US", box(-125, 25, -66, 49)),
        {"respondent": "US48", "date_from": "2023-01-01", "date_to": "2024-05-15"}, ctx))
    assert calls == [0, 5000, 10000]
    assert len(res.payload["rows"]) == total


def test_eia_exact_multiple_of_page_size_stops_at_total() -> None:
    import asyncio

    from backend.app.importers.context import ImportContext
    from backend.app.importers.databases import eia_demand

    calls: list[int] = []

    class _Http:
        async def get_json(self, url, *, params=None, headers=None):
            calls.append(int(params["offset"]))
            return {"response": {"total": 5000, "data": [{"period": "x", "value": "1"}] * 5000}}

    ctx = ImportContext(secrets={"eia_key": "k"}, http=_Http())
    asyncio.run(eia_demand.EiaDemand().fetch(
        Region("USA", "US", box(-125, 25, -66, 49)), {"respondent": "US48"}, ctx))
    assert calls == [0]  # a full last page must not trigger a second request


def test_osm_power_thousands_separator() -> None:
    from backend.app.importers.databases.osm_powerplants import _parse_power_mw as p

    assert p("1,300 MW") == 1300.0
    assert p("1,300.5 MW") == 1300.5
    assert p("1,300,000 W") == pytest.approx(1.3)
    assert p("0,5 MW") == 0.5
    assert p("1.5 GW") == 1500.0
    assert p("300000000 W") == 300.0


# ── RI4 suspected items ────────────────────────────────────────────────────────

def test_ninja_epoch_ms_keys_become_utc_stamps() -> None:
    from backend.app.importers.databases.renewables_ninja import _series

    body = {"data": {"1546300800000": {"electricity": 0.0}, "1546304400000": {"electricity": 0.25}}}
    assert _series(body) == [("2019-01-01 00:00", 0.0), ("2019-01-01 01:00", 0.25)]
    assert _series({"data": {"2019-01-01 05:00": {"electricity": 0.5}}}) == [("2019-01-01 05:00", 0.5)]


def test_ninja_pv_azimuth_faces_equator() -> None:
    import asyncio

    from backend.app.importers.context import ImportContext
    from backend.app.importers.databases.renewables_ninja import RenewablesNinja

    seen: list[dict] = []

    class _Http:
        async def get_json(self, url, *, params=None, headers=None):
            seen.append(dict(params))
            return {"data": {}}

    ctx = ImportContext(secrets={"renewables_ninja_key": "k"}, http=_Http())
    for poly, azim in ((box(10, 40, 12, 42), 180), (box(140, -40, 142, -38), 0)):
        seen.clear()
        asyncio.run(RenewablesNinja().fetch(Region("XXX", "X", poly), {"technologies": ["solar"]}, ctx))
        assert seen[0]["azim"] == azim


def test_nasa_power_requests_utc_time_standard() -> None:
    import asyncio

    from backend.app.importers.databases.openmeteo_renewable.sources import nasa_power

    seen: dict = {}

    class _Http:
        async def get_json(self, url, *, params=None):
            seen.update(params)
            return {}

    asyncio.run(nasa_power(_Http(), 45.0, 8.0, "2022-01-01", "2022-01-01", None))
    assert seen["time-standard"] == "UTC"


def _cw_ctx(pages):
    from backend.app.importers.context import ImportContext

    calls: list[int] = []

    class _Http:
        async def get_json(self, url, *, params=None, headers=None):
            calls.append(params["page"])
            return pages[params["page"] - 1]

    return ImportContext(secrets={}, http=_Http()), calls


def test_climatewatch_follows_pagination_scales_cap_and_warns_on_co2e() -> None:
    import asyncio

    from backend.app.importers.databases.climatewatch_policy import ClimateWatchPolicy

    p1 = {"data": [{"sector": "Energy", "gas": "CO2", "emissions": [{"year": 2022, "value": 1.0}]}],
          "meta": {"next_page": 2}}
    p2 = {"data": [{"sector": "Electricity/Heat", "gas": "All GHG",
                    "emissions": [{"year": 2022, "value": 100.0}]}], "meta": {"next_page": None}}
    ctx, calls = _cw_ctx([p1, p2])
    db = ClimateWatchPolicy()
    res = asyncio.run(db.fetch(Region("DEU", "G", box(5, 47, 15, 55)),
                               {"sector": "electricity", "base_year": 2022, "reduction_pct": 50,
                                "window_hours": 876}, ctx))
    assert calls == [1, 2]
    gc = db.to_sheets(res, ConvertOptions()).sheets["global_constraints"][0]
    # 100 Mt * 50 % = 50 Mt/yr; 876 h window = 10 % of a year -> 5 Mt
    assert gc["constant"] == pytest.approx(5_000_000.0)
    assert "All GHG" in gc["source"]
    assert any("CO₂e" in n for n in db.preview(res).notes)


def test_natural_earth_iso_preferred_over_adm0() -> None:
    from backend.app.importers.region import _feature_iso

    assert _feature_iso({"ADM0_A3": "SDS", "ISO_A3": "SSD", "ISO_A3_EH": "SSD"}) == "SSD"
    assert _feature_iso({"ADM0_A3": "SDS", "ISO_A3": "-99", "ISO_A3_EH": "-99"}) == "SSD"  # alias
    assert _feature_iso({"ADM0_A3": "KOS", "ISO_A3": "-99", "ISO_A3_EH": "-99"}) == "XKX"
    assert _feature_iso({"ADM0_A3": "FRA", "ISO_A3": "-99", "ISO_A3_EH": "FRA"}) == "FRA"
    assert _feature_iso({"ADM0_A3": "KOR"}) == "KOR"
