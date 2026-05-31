"""OSM importer — Overpass JSON → workbook fragment with mocked HTTP."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.app.importers import ConvertOptions, get_database
from backend.app.importers import region
from backend.app.importers.databases.osm import importer as osm_module
from backend.app.importers.databases.osm import overpass
from backend.tests._importer_fixtures import OVERPASS_PAYLOAD, write_countries_fixture


@pytest.fixture(autouse=True)
def _osm_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    boundaries = tmp_path / "countries.geojson"
    write_countries_fixture(boundaries)
    monkeypatch.setenv("RAGNAROK_BOUNDARIES_PATH", str(boundaries))
    region.reset_cache()

    def _fake_post(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return OVERPASS_PAYLOAD

    monkeypatch.setattr(overpass, "post_query", _fake_post)
    yield
    region.reset_cache()


def test_osm_fetch_parses_substations_and_lines():
    db = get_database("osm")
    r = region.get_region("KOR")
    result = db.fetch(r, {"min_voltage_kv": 110, "include_cables": True, "include_dc": True})
    parsed = result.payload["parsed"]
    assert len(parsed.substations) == 2
    # The 66 kV line is filtered out by min_voltage_kv=110.
    assert len(parsed.lines) == 1
    assert parsed.lines[0].voltage_kv == 220.0
    assert parsed.lines[0].circuits == 2


def test_osm_preview_emits_overlay_and_counts():
    db = get_database("osm")
    r = region.get_region("KOR")
    result = db.fetch(r, {"min_voltage_kv": 110, "include_cables": True, "include_dc": True})
    summary = db.preview(result)
    assert summary.counts["substations"] == 2
    assert summary.counts["lines"] == 1
    assert summary.overlay["type"] == "FeatureCollection"
    kinds = {f["properties"]["kind"] for f in summary.overlay["features"]}
    assert {"line", "substation"} <= kinds


def test_osm_to_sheets_emits_buses_lines_transformers():
    db = get_database("osm")
    r = region.get_region("KOR")
    result = db.fetch(r, {"min_voltage_kv": 110, "include_cables": True, "include_dc": True})
    fragment = db.to_sheets(result, ConvertOptions())
    assert "buses" in fragment.sheets and "lines" in fragment.sheets
    # Seoul HV has 110 and 220 kV → two buses + one transformer.
    bus_names = {row["name"] for row in fragment.sheets["buses"]}
    seoul_names = {n for n in bus_names if n.startswith("Seoul_HV")}
    assert len(seoul_names) >= 2
    assert "transformers" in fragment.sheets and len(fragment.sheets["transformers"]) >= 1
    # The 220 kV line snapped both endpoints to substations (no synthesised buses).
    line = fragment.sheets["lines"][0]
    assert line["v_nom"] == 220.0
    assert line["bus0"].startswith("Seoul_HV") or line["bus0"].startswith("Andong")
    assert line["bus1"].startswith("Seoul_HV") or line["bus1"].startswith("Andong")
    assert line["bus0"] != line["bus1"]
    # Line params come from PyPSA's line_types catalogue via the `type`
    # reference. r/x/b/s_nom are NOT fabricated by the importer.
    assert line["type"] == "490-AL1/64-ST1A 220.0"
    for forbidden in ("r", "x", "b", "s_nom"):
        assert forbidden not in line, (
            f"OSM line should not fabricate {forbidden!r}; PyPSA fills from `type`"
        )


def test_osm_preserves_all_upstream_tags():
    """Every OSM tag is preserved on the corresponding row, prefixed `osm_*`."""
    db = get_database("osm")
    r = region.get_region("KOR")
    result = db.fetch(r, {"min_voltage_kv": 110, "include_cables": True, "include_dc": True})
    fragment = db.to_sheets(result, ConvertOptions())
    line = fragment.sheets["lines"][0]
    # The fixture tags name = "Seoul–Andong 220 kV" + circuits=2.
    assert line["osm_name"] == "Seoul–Andong 220 kV"
    assert line["osm_voltage"] == "220000"
    assert line["osm_circuits"] == "2"
    # Substation rows preserve operator + voltage tags too.
    seoul_bus = next(b for b in fragment.sheets["buses"] if b["name"].startswith("Seoul_HV"))
    assert seoul_bus["osm_operator"] == "KEPCO"
    assert seoul_bus["osm_voltage"] == "220000;110000"


def test_osm_does_not_fabricate_electrical_defaults():
    db = get_database("osm")
    r = region.get_region("KOR")
    result = db.fetch(r, {"min_voltage_kv": 110, "include_cables": True, "include_dc": True})
    fragment = db.to_sheets(result, ConvertOptions())
    for line in fragment.sheets["lines"]:
        for forbidden in ("r", "x", "b", "s_nom", "carrier"):
            assert forbidden not in line, (
                f"Line should not carry hardcoded {forbidden!r}"
            )
    for tx in fragment.sheets["transformers"]:
        for forbidden in ("s_nom", "r", "x", "type"):
            assert forbidden not in tx, (
                f"Transformer should not carry hardcoded {forbidden!r}"
            )


def test_osm_voltage_threshold_drops_lines_below():
    db = get_database("osm")
    r = region.get_region("KOR")
    # All lines in the fixture are ≥ 66 kV; raise threshold above 220 to drop everything.
    result = db.fetch(r, {"min_voltage_kv": 400, "include_cables": True, "include_dc": True})
    assert len(result.payload["parsed"].lines) == 0
