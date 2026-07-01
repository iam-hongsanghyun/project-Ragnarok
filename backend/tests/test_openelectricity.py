"""OpenElectricity (Australia) importer — response parsing + sheet building.

BYOK + no test key, so the async fetch is stubbed with a fake HTTP client that
returns the documented APIV4 TimeSeries shape; the parser/build logic is what's
exercised.
"""
from __future__ import annotations

import asyncio
from typing import Any

from shapely.geometry import box

from backend.app.importers.context import ImportContext
from backend.app.importers.databases.openelectricity import (
    OpenElectricityDemand,
    OpenElectricityRenewable,
    _results_by_label,
    _snapshot,
)
from backend.app.importers.protocol import ConvertOptions, Region


def _region() -> Region:
    return Region("AUS", "Australia", box(113.0, -43.0, 154.0, -10.0))


class _FakeHttp:
    def __init__(self, body: Any) -> None:
        self.body = body

    async def get_json(self, url: str, *, params=None, headers=None) -> Any:
        return self.body


def _ctx(body: Any) -> ImportContext:
    return ImportContext(secrets={"openelectricity_key": "tok"}, http=_FakeHttp(body))


def test_snapshot_drops_offset_keeps_local_wallclock() -> None:
    assert _snapshot("2024-09-01T00:00:00+10:00") == "2024-09-01 00:00"
    assert _snapshot("2024-09-01T13:00:00+10:00") == "2024-09-01 13:00"


def test_results_by_label_groups_and_skips_nulls() -> None:
    body = {"data": [{"metric": "power", "results": [
        {"name": "solar", "columns": {"fueltech_group": "solar"},
         "data": [["2024-01-01T00:00:00+10:00", 0.0], ["2024-01-01T01:00:00+10:00", 500.0], ["2024-01-01T02:00:00+10:00", None]]},
        {"name": "wind", "columns": {"fueltech_group": "wind"},
         "data": [["2024-01-01T00:00:00+10:00", 300.0]]},
    ]}]}
    out = _results_by_label(body, "power", "fueltech_group")
    assert set(out) == {"solar", "wind"}
    assert out["solar"] == [("2024-01-01 00:00", 0.0), ("2024-01-01 01:00", 500.0)]  # null dropped
    assert out["wind"] == [("2024-01-01 00:00", 300.0)]


def test_demand_dataset_builds_load_series() -> None:
    body = {"data": [{"metric": "demand", "results": [
        {"name": "NEM", "columns": {}, "data": [
            ["2024-01-01T00:00:00+10:00", 20000.0],
            ["2024-01-01T01:00:00+10:00", 21000.0],
        ]},
    ]}]}
    db = OpenElectricityDemand()
    result = asyncio.run(db.fetch(_region(), {"network": "NEM", "date_from": "2024-01-01", "date_to": "2024-01-02"}, _ctx(body)))
    frag = db.to_sheets(result, ConvertOptions())
    assert [b["name"] for b in frag.sheets["buses"]] == ["NEM"]
    assert frag.sheets["loads"][0]["name"] == "NEM_demand"
    rows = frag.sheets["loads-p_set"]
    assert [r["NEM_demand"] for r in rows] == [20000.0, 21000.0]
    assert frag.snapshots == ["2024-01-01 00:00", "2024-01-01 01:00"]


def test_renewable_dataset_peak_normalises_solar_and_wind() -> None:
    body = {"data": [{"metric": "power", "results": [
        {"name": "solar", "columns": {"fueltech_group": "solar"},
         "data": [["2024-01-01T00:00:00+10:00", 0.0], ["2024-01-01T01:00:00+10:00", 4000.0]]},
        {"name": "wind", "columns": {"fueltech_group": "wind"},
         "data": [["2024-01-01T00:00:00+10:00", 1500.0], ["2024-01-01T01:00:00+10:00", 3000.0]]},
        {"name": "coal", "columns": {"fueltech_group": "coal"},
         "data": [["2024-01-01T00:00:00+10:00", 9000.0], ["2024-01-01T01:00:00+10:00", 9000.0]]},
    ]}]}
    db = OpenElectricityRenewable()
    result = asyncio.run(db.fetch(_region(), {"network": "NEM", "date_from": "2024-01-01", "date_to": "2024-01-02"}, _ctx(body)))
    frag = db.to_sheets(result, ConvertOptions())
    gens = {g["name"]: g for g in frag.sheets["generators"]}
    assert set(gens) == {"NEM_solar", "NEM_wind"}  # coal is not a VRE profile
    assert gens["NEM_solar"]["p_nom"] == 4000.0
    rows = frag.sheets["generators-p_max_pu"]
    assert [r["NEM_solar"] for r in rows] == [0.0, 1.0]      # 0/4000, 4000/4000
    assert [r["NEM_wind"] for r in rows] == [0.5, 1.0]       # 1500/3000, 3000/3000
