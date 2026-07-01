"""Renewables.ninja importer — CF parsing, sheet building, BYOK enforcement."""
from __future__ import annotations

import asyncio

import pytest
from shapely.geometry import box

from backend.app.importers.context import ImportContext
from backend.app.importers.databases.renewables_ninja import RenewablesNinja, _series
from backend.app.importers.protocol import ConvertOptions, FetchResult, Region


def _region() -> Region:
    return Region("FRA", "France", box(-5.0, 42.0, 8.0, 51.0))


def test_series_parses_electricity_as_capacity_factor() -> None:
    body = {"data": {
        "2019-01-01 01:00": {"electricity": 0.42},
        "2019-01-01 00:00": {"electricity": 0.0},
        "2019-01-01 02:00": {"electricity": None},  # skipped
    }}
    assert _series(body) == [("2019-01-01 00:00", 0.0), ("2019-01-01 01:00", 0.42)]


def test_to_sheets_builds_tagged_solar_and_wind() -> None:
    db = RenewablesNinja()
    result = FetchResult(
        "renewables_ninja", _region(), {"capacity_mw": 100.0},
        {"iso": "FRA", "lat": 46.5, "lon": 2.0, "cf": {
            "solar": [("2019-01-01 00:00", 0.0), ("2019-01-01 01:00", 0.5)],
            "wind": [("2019-01-01 00:00", 0.6), ("2019-01-01 01:00", 0.7)],
        }},
    )
    frag = db.to_sheets(result, ConvertOptions())
    assert frag.sheets["buses"][0]["name"] == "re_ninja_FRA"
    gens = {g["name"]: g for g in frag.sheets["generators"]}
    # Source-tagged so it never collides with the keyless weather importers.
    assert set(gens) == {"solar_ninja_FRA", "wind_ninja_FRA"}
    assert gens["solar_ninja_FRA"]["p_nom"] == 100.0
    rows = frag.sheets["generators-p_max_pu"]
    assert [r["solar_ninja_FRA"] for r in rows] == [0.0, 0.5]
    assert [r["wind_ninja_FRA"] for r in rows] == [0.6, 0.7]


def test_fetch_without_token_raises_permission_error() -> None:
    db = RenewablesNinja()
    ctx = ImportContext(secrets={}, http=None)  # no key
    with pytest.raises(PermissionError):
        asyncio.run(db.fetch(_region(), {"technologies": ["solar"]}, ctx))
