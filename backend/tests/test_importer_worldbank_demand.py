"""World Bank demand importer — series math + workbook fragment."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.importers import ConvertOptions, get_database
from backend.app.importers import region
from backend.app.importers.databases.worldbank_demand import importer as wb_module
from backend.tests._importer_fixtures import write_countries_fixture


@pytest.fixture(autouse=True)
def _wb_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    boundaries = tmp_path / "countries.geojson"
    write_countries_fixture(boundaries)
    monkeypatch.setenv("RAGNAROK_BOUNDARIES_PATH", str(boundaries))
    region.reset_cache()

    fake_kwh = {2010: 9000.0, 2014: 10000.0, 2020: 11000.0}
    fake_pop = {2010: 50_000_000, 2014: 51_000_000, 2020: 52_000_000}

    def _fake_fetch(country_iso3: str, indicator: str) -> dict[int, float]:
        if indicator == "EG.USE.ELEC.KH.PC":
            return dict(fake_kwh)
        if indicator == "SP.POP.TOTL":
            return dict(fake_pop)
        return {}

    monkeypatch.setattr(wb_module, "_fetch_indicator", _fake_fetch)
    yield
    region.reset_cache()


def test_worldbank_fetch_returns_series():
    db = get_database("worldbank_demand")
    r = region.get_region("KOR")
    result = db.fetch(r, {"year": 2014})
    series = result.payload["series"]
    assert series.kwh_per_capita[2014] == 10000.0
    assert series.population[2014] == 51_000_000


def test_worldbank_preview_counts_and_history():
    db = get_database("worldbank_demand")
    r = region.get_region("KOR")
    result = db.fetch(r, {"year": 2014})
    summary = db.preview(result)
    assert summary.counts["loads"] == 1
    # Annual MW = 10000 * 51_000_000 / 8760 / 1000 ≈ 58219 MW
    assert summary.counts["annual_avg_mw_2014"] == 58219
    assert len(summary.samples["history"]) == 3


def test_worldbank_to_sheets_emits_one_load_row():
    db = get_database("worldbank_demand")
    r = region.get_region("KOR")
    result = db.fetch(r, {"year": 2014, "load_name": "national_load"})
    fragment = db.to_sheets(result, ConvertOptions())
    assert "loads" in fragment.sheets
    loads = fragment.sheets["loads"]
    assert len(loads) == 1
    assert loads[0]["name"] == "national_load_KOR"
    assert loads[0]["p_set"] > 0
    assert loads[0]["year"] == 2014
    assert fragment.provenance is not None
    # carrier / bus / sign are NOT fabricated — PyPSA defaults apply.
    for forbidden in ("carrier", "bus", "sign", "p_min_pu", "p_max_pu"):
        assert forbidden not in loads[0], (
            f"Load row should not carry hardcoded {forbidden!r}"
        )


def test_worldbank_preserves_full_indicator_history():
    """Every year of every indicator is preserved as an extra column."""
    db = get_database("worldbank_demand")
    r = region.get_region("KOR")
    result = db.fetch(r, {"year": 2014})
    fragment = db.to_sheets(result, ConvertOptions())
    load = fragment.sheets["loads"][0]
    # Fixture provides 2010, 2014, 2020 across both indicators.
    for y in (2010, 2014, 2020):
        assert f"kwh_per_capita_{y}" in load
        assert f"population_{y}" in load
        assert f"annual_avg_mw_{y}" in load


def test_worldbank_falls_back_when_year_missing():
    db = get_database("worldbank_demand")
    r = region.get_region("KOR")
    result = db.fetch(r, {"year": 2025})  # Out of range — fixture only has up to 2020.
    fragment = db.to_sheets(result, ConvertOptions())
    assert fragment.sheets.get("loads") is not None
    assert fragment.sheets["loads"][0]["year"] == 2020
