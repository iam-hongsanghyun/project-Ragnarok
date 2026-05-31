"""PyPSA technology-data costs importer — mocked CSV → carrier rows."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.importers import ConvertOptions, get_database
from backend.app.importers import region
from backend.app.importers.databases.pypsa_technology_data import importer as td_module
from backend.tests._importer_fixtures import write_countries_fixture


_TECHDATA_FIXTURE = (
    "technology,parameter,value,unit,source\n"
    "OCGT,investment,420000,EUR/MW,DEA\n"
    "OCGT,FOM,1.4,%/year,DEA\n"
    "OCGT,VOM,3.0,EUR/MWh,DEA\n"
    "OCGT,efficiency,0.41,p.u.,DEA\n"
    "OCGT,lifetime,25,years,DEA\n"
    "OCGT,CO2 intensity,0.198,t/MWh_th,IPCC\n"
    "solar,investment,300000,EUR/MW,DEA\n"
    "solar,FOM,3.0,%/year,DEA\n"
    "solar,lifetime,30,years,DEA\n"
)


@pytest.fixture(autouse=True)
def _td_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    boundaries = tmp_path / "countries.geojson"
    write_countries_fixture(boundaries)
    monkeypatch.setenv("RAGNAROK_BOUNDARIES_PATH", str(boundaries))
    region.reset_cache()
    csv_path = tmp_path / "costs.csv"
    csv_path.write_text(_TECHDATA_FIXTURE)
    monkeypatch.setenv("RAGNAROK_TECHDATA_PATH", str(csv_path))
    yield
    region.reset_cache()


def test_techdata_preview_counts():
    db = get_database("pypsa_technology_data")
    r = region.get_region("KOR")
    result = db.fetch(r, {"year": "2030"})
    summary = db.preview(result)
    assert summary.counts["technologies"] == 2
    assert summary.counts["total_parameters"] == 9


def test_techdata_to_sheets_emits_carrier_rows_with_all_parameters():
    db = get_database("pypsa_technology_data")
    r = region.get_region("KOR")
    result = db.fetch(r, {"year": "2030"})
    fragment = db.to_sheets(result, ConvertOptions())
    assert "carriers" in fragment.sheets
    rows = {r["name"]: r for r in fragment.sheets["carriers"]}
    # OCGT maps to Gas via carrier_map.json
    assert "Gas" in rows
    gas = rows["Gas"]
    # Every parameter from the CSV is present on the carrier row.
    assert gas["investment"] == 420000
    assert gas["efficiency"] == 0.41
    assert gas["lifetime"] == 25
    assert gas["CO2 intensity"] == 0.198
    # Units + source preserved as auxiliary columns.
    assert gas["investment_unit"] == "EUR/MW"
    assert gas["investment_source"] == "DEA"
    assert gas["tech_data_year"] == "2030"
    assert gas["tech_data_source"] == "OCGT"
    # solar maps to Solar.
    assert "Solar" in rows
    assert rows["Solar"]["lifetime"] == 30
