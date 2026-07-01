"""Elexon (Great Britain) importer — half-hourly→hourly + sheet building.

Keyless, but the async fetch is stubbed with a fake HTTP client returning the
documented BMRS shapes so CI stays hermetic.
"""
from __future__ import annotations

import asyncio
from typing import Any

from shapely.geometry import box

from backend.app.importers.context import ImportContext
from backend.app.importers.databases.elexon import (
    ElexonDemand,
    ElexonRenewable,
    _hourly_mean,
)
from backend.app.importers.protocol import ConvertOptions, Region


def _region() -> Region:
    return Region("GBR", "United Kingdom", box(-8.0, 50.0, 2.0, 59.0))


class _FakeHttp:
    def __init__(self, body: Any) -> None:
        self.body = body

    async def get_json(self, url: str, *, params=None, headers=None) -> Any:
        return self.body


def _ctx(body: Any) -> ImportContext:
    return ImportContext(secrets={}, http=_FakeHttp(body))


def test_hourly_mean_averages_half_hours() -> None:
    out = _hourly_mean([
        ("2024-01-01T00:00:00Z", 20000.0),
        ("2024-01-01T00:30:00Z", 22000.0),
        ("2024-01-01T01:00:00Z", 24000.0),
    ])
    assert out == [("2024-01-01 00:00", 21000.0), ("2024-01-01 01:00", 24000.0)]


def test_demand_dataset_builds_hourly_load() -> None:
    body = {"data": [
        {"startTime": "2024-01-01T00:00:00Z", "initialDemandOutturn": 20000},
        {"startTime": "2024-01-01T00:30:00Z", "initialDemandOutturn": 22000},
        {"startTime": "2024-01-01T01:00:00Z", "initialDemandOutturn": 24000},
    ]}
    db = ElexonDemand()
    result = asyncio.run(db.fetch(_region(), {"date_from": "2024-01-01", "date_to": "2024-01-01"}, _ctx(body)))
    frag = db.to_sheets(result, ConvertOptions())
    assert frag.sheets["buses"][0]["name"] == "GBR"
    assert frag.sheets["loads"][0]["name"] == "GBR_demand"
    assert [r["GBR_demand"] for r in frag.sheets["loads-p_set"]] == [21000.0, 24000.0]


def test_renewable_dataset_peak_normalises_and_filters_psrtypes() -> None:
    body = {"data": [
        {"startTime": "2024-01-01T00:00:00Z", "data": [
            {"psrType": "Solar", "quantity": 500}, {"psrType": "Wind Onshore", "quantity": 1000},
            {"psrType": "Fossil Gas", "quantity": 5000},
        ]},
        {"startTime": "2024-01-01T01:00:00Z", "data": [
            {"psrType": "Solar", "quantity": 1000}, {"psrType": "Wind Onshore", "quantity": 2000},
        ]},
    ]}
    db = ElexonRenewable()
    result = asyncio.run(db.fetch(_region(), {"date_from": "2024-01-01", "date_to": "2024-01-01"}, _ctx(body)))
    frag = db.to_sheets(result, ConvertOptions())
    gens = {g["name"]: g for g in frag.sheets["generators"]}
    assert set(gens) == {"GBR_solar", "GBR_onwind"}  # gas ignored
    rows = frag.sheets["generators-p_max_pu"]
    assert [r["GBR_solar"] for r in rows] == [0.5, 1.0]
    assert [r["GBR_onwind"] for r in rows] == [0.5, 1.0]
