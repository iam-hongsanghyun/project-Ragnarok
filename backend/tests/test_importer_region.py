"""Country boundaries loader + ISO-A3 → polygon lookup."""
from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import Point

from backend.app.importers import region
from backend.tests._importer_fixtures import write_countries_fixture


@pytest.fixture
def boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "countries.geojson"
    write_countries_fixture(target)
    monkeypatch.setenv("RAGNAROK_BOUNDARIES_PATH", str(target))
    region.reset_cache()
    yield target
    region.reset_cache()


def test_country_list(boundaries: Path):
    countries = region.country_list()
    isos = {c["iso"] for c in countries}
    assert {"KOR", "TST"} <= isos
    kor = next(c for c in countries if c["iso"] == "KOR")
    assert kor["name"] == "South Korea"
    assert kor["bbox"][0] < kor["bbox"][2]
    assert kor["bbox"][1] < kor["bbox"][3]


def test_get_region_contains_seoul(boundaries: Path):
    r = region.get_region("KOR")
    assert r.country_iso == "KOR"
    # Seoul lat/lon roughly (37.5, 127.0). Polygon includes it.
    assert r.polygon.contains(Point(127.0, 37.5))
    # Outside the KOR box.
    assert not r.polygon.contains(Point(-100.0, 40.0))


def test_get_region_unknown_iso_raises(boundaries: Path):
    with pytest.raises(KeyError):
        region.get_region("ZZZ")


def test_boundaries_bytes_returns_geojson(boundaries: Path):
    blob = region.boundaries_geojson_bytes()
    assert b"FeatureCollection" in blob
