"""ENTSO-E measured renewable profiles: A75 parsing + capacity-factor build."""
from __future__ import annotations

from shapely.geometry import box

from backend.app.importers.databases.entsoe_generation_profile import (
    _parse_generation_xml,
    EntsoeGenerationProfile,
)
from backend.app.importers.protocol import ConvertOptions, FetchResult, Region

_A75 = """<GL_MarketDocument xmlns="urn:x">
  <TimeSeries>
    <MktPSRType><psrType>B16</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2023-01-01T00:00Z</start><end>2023-01-01T02:00Z</end></timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><quantity>50</quantity></Point>
      <Point><position>2</position><quantity>100</quantity></Point>
    </Period>
  </TimeSeries>
  <TimeSeries>
    <MktPSRType><psrType>B10</psrType></MktPSRType>
    <outBiddingZone_Domain.mRID>10YXX</outBiddingZone_Domain.mRID>
    <Period>
      <timeInterval><start>2023-01-01T00:00Z</start><end>2023-01-01T02:00Z</end></timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><quantity>30</quantity></Point>
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""


def test_parse_generation_xml_reads_per_psrtype_and_skips_consumption() -> None:
    parsed = _parse_generation_xml(_A75)
    # Solar generation kept; the pumped-storage consumption leg is skipped.
    assert set(parsed) == {"B16"}
    vals = [mw for _, mw in parsed["B16"]]
    assert vals == [50.0, 100.0]


def _result(gen_hourly: dict, capacity: dict) -> FetchResult:
    region = Region("FRA", "France", box(-5.0, 42.0, 8.0, 51.0))
    return FetchResult(
        "entsoe_generation_profile", region, {},
        {"iso": "FRA", "eic": "10YFR", "zone_name": "France",
         "date_from": "2023-01-01", "date_to": "2023-01-01",
         "gen_hourly": gen_hourly, "capacity": capacity},
    )


def test_capacity_factor_from_installed_capacity() -> None:
    db = EntsoeGenerationProfile()
    result = _result(
        {"B16": [("2023-01-01 00:00", 50.0), ("2023-01-01 01:00", 100.0)]},
        {"B16": 200.0},
    )
    frag = db.to_sheets(result, ConvertOptions())
    gen = frag.sheets["generators"][0]
    assert gen["name"] == "gen_FRA_solar" and gen["carrier"] == "solar" and gen["p_nom"] == 200.0
    rows = frag.sheets["generators-p_max_pu"]
    assert [r["gen_FRA_solar"] for r in rows] == [0.25, 0.5]  # 50/200, 100/200
    assert frag.snapshots == ["2023-01-01 00:00", "2023-01-01 01:00"]


def test_peak_normalization_when_capacity_missing() -> None:
    db = EntsoeGenerationProfile()
    result = _result(
        {"B19": [("2023-01-01 00:00", 40.0), ("2023-01-01 01:00", 80.0)]},
        {},  # no A68 capacity → normalise by the window peak (80)
    )
    frag = db.to_sheets(result, ConvertOptions())
    rows = frag.sheets["generators-p_max_pu"]
    assert [r["gen_FRA_onwind"] for r in rows] == [0.5, 1.0]
    assert frag.sheets["generators"][0]["carrier"] == "onwind"


def test_cf_clipped_to_one_when_generation_exceeds_capacity() -> None:
    db = EntsoeGenerationProfile()
    result = _result({"B16": [("2023-01-01 00:00", 250.0)]}, {"B16": 200.0})
    frag = db.to_sheets(result, ConvertOptions())
    assert frag.sheets["generators-p_max_pu"][0]["gen_FRA_solar"] == 1.0
