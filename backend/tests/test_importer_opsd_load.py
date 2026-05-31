"""OPSD hourly load importer — mocked CSV → fragment."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.importers import ConvertOptions, get_database
from backend.app.importers import region
from backend.app.importers.databases.opsd_load import importer as opsd_module
from backend.tests._importer_fixtures import write_countries_fixture


# Fixture CSV with a handful of hourly rows for DE + FR + extra metadata
# columns so we can assert "all upstream columns preserved".
_OPSD_FIXTURE = (
    "utc_timestamp,cet_cest_timestamp,DE_load_actual_entsoe_transparency,"
    "FR_load_actual_entsoe_transparency,extra_column\n"
    "2019-01-01T00:00:00Z,2019-01-01T01:00:00+0100,50000,55000,extra-a\n"
    "2019-01-01T01:00:00Z,2019-01-01T02:00:00+0100,49000,54000,extra-b\n"
    "2019-01-01T02:00:00Z,2019-01-01T03:00:00+0100,48000,53000,extra-c\n"
    "2020-06-15T12:00:00Z,2020-06-15T14:00:00+0200,42000,47000,outside-window\n"
)


# Hijack the country fixture: OPSD slices by ISO-2 derived from ISO-3.
# We need DEU (Germany) — the world-fixture only has KOR. Inject DEU.
_GEOJSON_WITH_DEU = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"ADM0_A3": "DEU", "ADMIN": "Germany"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [6.0, 47.3],
                        [15.0, 47.3],
                        [15.0, 55.0],
                        [6.0, 55.0],
                        [6.0, 47.3],
                    ]
                ],
            },
        }
    ],
}


@pytest.fixture(autouse=True)
def _opsd_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    boundaries = tmp_path / "countries.geojson"
    write_countries_fixture(boundaries)
    # Overwrite with our DE-aware fixture.
    boundaries.write_text(json.dumps(_GEOJSON_WITH_DEU))
    monkeypatch.setenv("RAGNAROK_BOUNDARIES_PATH", str(boundaries))
    region.reset_cache()
    csv_path = tmp_path / "opsd.csv"
    csv_path.write_text(_OPSD_FIXTURE)
    monkeypatch.setenv("RAGNAROK_OPSD_LOAD_PATH", str(csv_path))
    opsd_module.reset_cache()
    yield
    region.reset_cache()
    opsd_module.reset_cache()


def test_opsd_fetch_filters_window():
    db = get_database("opsd_load")
    r = region.get_region("DEU")
    result = db.fetch(r, {"date_from": "2019-01-01", "date_to": "2019-12-31"})
    sliced = result.payload["slice"]
    assert sliced is not None
    assert len(sliced.rows) == 3
    assert sliced.column == "DE_load_actual_entsoe_transparency"


def test_opsd_preview_summarises_hourly_window():
    db = get_database("opsd_load")
    r = region.get_region("DEU")
    result = db.fetch(r, {"date_from": "2019-01-01", "date_to": "2019-12-31"})
    summary = db.preview(result)
    assert summary.counts["hours"] == 3
    assert summary.counts["avg_load_mw"] == 49000
    assert summary.counts["peak_load_mw"] == 50000
    # Sample carries every OPSD column verbatim, not just the load value.
    sample = summary.samples["hourly"][0]
    assert sample["cet_cest_timestamp"] == "2019-01-01T01:00:00+0100"
    assert sample["extra_column"] == "extra-a"


def test_opsd_to_sheets_writes_loads_p_set_and_snapshots():
    db = get_database("opsd_load")
    r = region.get_region("DEU")
    result = db.fetch(r, {"date_from": "2019-01-01", "date_to": "2019-12-31"})
    fragment = db.to_sheets(result, ConvertOptions())
    assert {"loads", "loads-p_set"} <= set(fragment.sheets)
    assert fragment.snapshots is not None and len(fragment.snapshots) == 3
    # Snapshots are ISO-T (no trailing Z).
    assert fragment.snapshots[0] == "2019-01-01T00:00:00"
    # Static row preserves OPSD metadata columns (the extra one in the fixture).
    load = fragment.sheets["loads"][0]
    assert load["name"] == "DEU_national_load"
    assert load["opsd_extra_column"] == "extra-a"
    assert load["opsd_column"] == "DE_load_actual_entsoe_transparency"
    # No fabricated PyPSA defaults on the load row.
    for forbidden in ("carrier", "bus", "sign", "p_min_pu"):
        assert forbidden not in load
    # Temporal sheet shape: snapshot + load_name columns only.
    p_set = fragment.sheets["loads-p_set"][0]
    assert set(p_set.keys()) == {"snapshot", "DEU_national_load"}
    assert p_set["DEU_national_load"] == 50000.0


def test_opsd_returns_empty_fragment_when_country_unsupported():
    db = get_database("opsd_load")
    # Inject a country the fixture doesn't have a column for (KOR isn't in OPSD).
    # We re-use the DEU region object but rename to force the iso2 lookup to
    # produce something OPSD doesn't carry.
    r = region.get_region("DEU")
    fake = region.Region(country_iso="ZZZ", country_name="Nowhere", polygon=r.polygon)
    result = db.fetch(fake, {})
    fragment = db.to_sheets(result, ConvertOptions())
    assert fragment.sheets == {}
    assert fragment.snapshots is None
