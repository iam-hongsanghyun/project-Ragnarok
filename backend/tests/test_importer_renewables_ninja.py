"""Renewables.ninja importer — mocked API → fragment + snapshot union."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.importers import ConvertOptions, get_database
from backend.app.importers import region
from backend.app.importers.databases.renewables_ninja import importer as rn_module
from backend.tests._importer_fixtures import write_countries_fixture


# Tiny RN-shaped CSV with 3 rows + extras to validate "all columns preserved".
_WIND_FIXTURE = (
    "## headers\n"
    "## (skipped)\n"
    "\n"
    "time,electricity,wind_speed\n"
    "2019-01-01 00:00,0.42,7.5\n"
    "2019-01-01 01:00,0.45,7.8\n"
    "2019-01-01 02:00,0.50,8.1\n"
)
_SOLAR_FIXTURE = (
    "## headers\n"
    "## (skipped)\n"
    "\n"
    "time,electricity,irradiance_direct,irradiance_diffuse,temperature\n"
    "2019-01-01 00:00,0.0,0,0,1.5\n"
    "2019-01-01 01:00,0.0,0,0,1.2\n"
    "2019-01-01 02:00,0.1,12,5,2.1\n"
)


@pytest.fixture(autouse=True)
def _rn_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    boundaries = tmp_path / "countries.geojson"
    write_countries_fixture(boundaries)
    monkeypatch.setenv("RAGNAROK_BOUNDARIES_PATH", str(boundaries))
    region.reset_cache()

    def fake_http_get_csv(url: str, **_kw: Any) -> bytes:
        if "/wind?" in url:
            return _WIND_FIXTURE.encode("utf-8")
        if "/pv?" in url:
            return _SOLAR_FIXTURE.encode("utf-8")
        raise RuntimeError(f"unexpected URL: {url}")

    monkeypatch.setattr(rn_module, "_http_get_csv", fake_http_get_csv)
    yield
    region.reset_cache()


def test_rn_fetch_two_techs():
    db = get_database("renewables_ninja")
    r = region.get_region("KOR")
    result = db.fetch(r, {"date_from": "2019-01-01", "date_to": "2019-01-31", "tech": ["wind", "solar"]})
    series = result.payload["series"]
    assert len(series) == 2
    techs = {s.tech for s in series}
    assert techs == {"wind", "solar"}


def test_rn_to_sheets_emits_generators_and_p_max_pu_with_full_columns():
    db = get_database("renewables_ninja")
    r = region.get_region("KOR")
    result = db.fetch(r, {"tech": ["wind", "solar"]})
    fragment = db.to_sheets(result, ConvertOptions())
    assert {"generators", "carriers", "generators-p_max_pu"} <= set(fragment.sheets)
    # Two generator rows, named per tech.
    names = {g["name"] for g in fragment.sheets["generators"]}
    assert names == {"KOR_wind_profile", "KOR_solar_profile"}
    # No fabricated p_nom / capital_cost / marginal_cost.
    for g in fragment.sheets["generators"]:
        for forbidden in ("p_nom", "capital_cost", "marginal_cost", "efficiency", "p_min_pu"):
            assert forbidden not in g, f"Generator should not fabricate {forbidden!r}"
    # All RN columns preserved on the solar row (irradiance_*, temperature).
    solar = next(g for g in fragment.sheets["generators"] if g["name"] == "KOR_solar_profile")
    assert solar["rn_irradiance_direct"] == "0"
    assert solar["rn_temperature"] == "1.5"
    # Snapshots are the union of both tech series — same in this fixture.
    assert fragment.snapshots is not None
    assert fragment.snapshots[0] == "2019-01-01T00:00"
    # p_max_pu sheet has both tech columns per snapshot.
    first = fragment.sheets["generators-p_max_pu"][0]
    assert first["snapshot"] == "2019-01-01T00:00"
    assert first["KOR_wind_profile"] == 0.42
    assert first["KOR_solar_profile"] == 0.0
