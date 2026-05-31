"""WRI GPPD importer — CSV → workbook fragment with mocked HTTP."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.importers import (
    ConvertOptions,
    available_databases,
    get_database,
)
from backend.app.importers import region
from backend.app.importers.databases.wri_gppd import importer as wri_module
from backend.tests._importer_fixtures import WRI_GPPD_CSV, write_countries_fixture


@pytest.fixture(autouse=True)
def _wri_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    boundaries = tmp_path / "countries.geojson"
    write_countries_fixture(boundaries)
    monkeypatch.setenv("RAGNAROK_BOUNDARIES_PATH", str(boundaries))
    region.reset_cache()
    csv_path = tmp_path / "wri.csv"
    csv_path.write_text(WRI_GPPD_CSV)
    monkeypatch.setenv("RAGNAROK_WRI_GPPD_PATH", str(csv_path))
    wri_module.reset_cache()
    yield
    region.reset_cache()
    wri_module.reset_cache()


def test_wri_fetch_filters_by_polygon_and_fuel():
    db = get_database("wri_gppd")
    r = region.get_region("KOR")
    result = db.fetch(r, {"min_capacity_mw": 10, "fuels": ["Coal", "Wind"]})
    plants = result.payload["plants"]
    names = sorted(p.name for p in plants)
    assert names == ["Test Coal Plant", "Test Wind Farm"]


def test_wri_fetch_drops_below_min_capacity():
    db = get_database("wri_gppd")
    r = region.get_region("KOR")
    result = db.fetch(r, {"min_capacity_mw": 100})
    names = [p.name for p in result.payload["plants"]]
    assert names == ["Test Coal Plant"]


def test_wri_fetch_owner_substring_filter():
    db = get_database("wri_gppd")
    r = region.get_region("KOR")
    result = db.fetch(r, {"owner_contains": "kepco"})
    names = [p.name for p in result.payload["plants"]]
    assert names == ["Test Coal Plant"]


def test_wri_preview_counts_and_overlay():
    db = get_database("wri_gppd")
    r = region.get_region("KOR")
    result = db.fetch(r, {})
    summary = db.preview(result)
    assert summary.counts["generators"] == 3
    assert summary.counts["total_capacity_mw"] == 585
    assert len(summary.overlay["features"]) == 3
    assert summary.samples["generators"][0]["carrier"] in {"Coal", "Wind", "Solar"}


def test_wri_to_sheets_emits_generators_buses_carriers():
    db = get_database("wri_gppd")
    r = region.get_region("KOR")
    result = db.fetch(r, {})
    fragment = db.to_sheets(result, ConvertOptions())
    assert {"generators", "buses", "carriers"} <= set(fragment.sheets)
    gens = fragment.sheets["generators"]
    assert {row["carrier"] for row in gens} == {"Coal", "Wind", "Solar"}
    # Provenance row is populated.
    assert fragment.provenance is not None
    assert fragment.provenance.country_iso == "KOR"
    assert fragment.provenance.database_id == "wri_gppd"
    counts = {sheet: len(rows) for sheet, rows in fragment.sheets.items()}
    assert counts["generators"] == 3
    assert counts["buses"] == 3
    assert counts["carriers"] == 3


def test_wri_preserves_all_upstream_csv_columns():
    """Each generator row must carry every CSV column the upstream ships,
    plus the schema-required ones — nothing dropped on the floor."""
    db = get_database("wri_gppd")
    r = region.get_region("KOR")
    result = db.fetch(r, {})
    fragment = db.to_sheets(result, ConvertOptions())
    # Pick the Coal Plant row deterministically.
    coal = next(g for g in fragment.sheets["generators"] if g["carrier"] == "Coal")
    # Schema-required columns are present.
    assert coal["name"] == "Test_Coal_Plant"
    assert coal["p_nom"] == 500.0
    # Every column from the WRI CSV is preserved verbatim.
    assert coal["gppd_idnr"] == "KOR0000001"
    assert coal["country_long"] == "South Korea"
    assert coal["primary_fuel"] == "Coal"
    assert coal["owner"] == "KEPCO"
    assert coal["commissioning_year"] == "1995"
    # source breadcrumb wins last
    assert coal["source"] == "WRI GPPD"


def test_wri_does_not_fabricate_pypsa_defaults():
    """Empty stays empty — the importer must not invent marginal_cost /
    efficiency / co2_emissions when the upstream is silent."""
    db = get_database("wri_gppd")
    r = region.get_region("KOR")
    result = db.fetch(r, {})
    fragment = db.to_sheets(result, ConvertOptions())
    for gen in fragment.sheets["generators"]:
        for forbidden in (
            "marginal_cost",
            "efficiency",
            "co2_emissions",
            "capital_cost",
            "lifetime",
            "p_nom_extendable",
            "p_min_pu",
            "p_max_pu",
        ):
            assert forbidden not in gen, (
                f"Generator row should not carry hardcoded {forbidden!r}; "
                f"got value {gen[forbidden]!r}"
            )
    for carrier in fragment.sheets["carriers"]:
        for forbidden in ("co2_emissions", "marginal_cost", "color"):
            assert forbidden not in carrier, (
                f"Carrier row should not carry hardcoded {forbidden!r}"
            )
