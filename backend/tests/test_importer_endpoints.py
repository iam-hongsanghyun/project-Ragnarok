"""FastAPI endpoints for the importer subsystem (smoke tests)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.importers import region
from backend.app.importers.databases.osm import overpass
from backend.app.importers.databases.wri_gppd import importer as wri_module
from backend.app.main import app
from backend.tests._importer_fixtures import (
    OVERPASS_PAYLOAD,
    WRI_GPPD_CSV,
    write_countries_fixture,
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    boundaries = tmp_path / "countries.geojson"
    write_countries_fixture(boundaries)
    monkeypatch.setenv("RAGNAROK_BOUNDARIES_PATH", str(boundaries))
    region.reset_cache()
    csv_path = tmp_path / "wri.csv"
    csv_path.write_text(WRI_GPPD_CSV)
    monkeypatch.setenv("RAGNAROK_WRI_GPPD_PATH", str(csv_path))
    wri_module.reset_cache()
    monkeypatch.setattr(
        overpass, "post_query", lambda *_a, **_kw: OVERPASS_PAYLOAD
    )
    return TestClient(app)


def test_list_databases(client: TestClient):
    resp = client.get("/api/import/databases")
    assert resp.status_code == 200
    body = resp.json()
    ids = {d["id"] for d in body["databases"]}
    assert {"osm", "wri_gppd"} <= ids
    assert "pypsa_earth" not in ids


def test_list_countries(client: TestClient):
    resp = client.get("/api/import/countries")
    assert resp.status_code == 200
    isos = {c["iso"] for c in resp.json()["countries"]}
    assert "KOR" in isos


def test_boundaries_geojson(client: TestClient):
    resp = client.get("/api/import/boundaries/countries.geojson")
    assert resp.status_code == 200
    assert "FeatureCollection" in resp.text


def test_run_returns_preview_and_fragment_together(client: TestClient):
    """One-trip endpoint must carry both halves."""
    resp = client.post(
        "/api/import/run",
        json={
            "database_id": "wri_gppd",
            "country_iso": "KOR",
            "filters": {},
            "convert_options": {},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["database_id"] == "wri_gppd"
    assert body["country_iso"] == "KOR"
    assert body["preview"]["counts"]["generators"] == 3
    assert "generators" in body["fragment"]["sheets"]
    assert body["fragment"]["provenance"]["database_id"] == "wri_gppd"


def test_run_osm(client: TestClient):
    resp = client.post(
        "/api/import/run",
        json={
            "database_id": "osm",
            "country_iso": "KOR",
            "filters": {"min_voltage_kv": 110, "include_cables": True, "include_dc": True},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["preview"]["counts"]["substations"] == 2
    assert "buses" in body["fragment"]["sheets"]


def test_legacy_preview_endpoint_is_gone(client: TestClient):
    """The two-trip preview/fetch endpoints have been collapsed into /run."""
    assert client.post(
        "/api/import/preview", json={"database_id": "wri_gppd", "country_iso": "KOR"}
    ).status_code == 404
    assert client.post(
        "/api/import/fetch", json={"database_id": "wri_gppd", "country_iso": "KOR"}
    ).status_code == 404


def test_unknown_database_404(client: TestClient):
    resp = client.post(
        "/api/import/run",
        json={"database_id": "nope", "country_iso": "KOR", "filters": {}},
    )
    assert resp.status_code == 404


def test_unknown_country_404(client: TestClient):
    resp = client.post(
        "/api/import/run",
        json={"database_id": "wri_gppd", "country_iso": "ZZZ", "filters": {}},
    )
    assert resp.status_code == 404
