"""End-to-end tests for ``GET /api/config``.

Asserts the boot-bundle contract the frontend depends on:

* every required key is present,
* schema is computed from PyPSA (not from a stale JSON file),
* build_id is deterministic for a given backend state and changes on
  reload only if PyPSA actually changed,
* the cheap ``/build-id`` probe agrees with the full bundle,
* ``POST /reload`` resets the cache and the next GET produces the
  same id (PyPSA hasn't changed under us during the test).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.config_provider import reset_cache
from backend.app.main import app


client = TestClient(app)


def test_config_bundle_contract():
    reset_cache()
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "schema",
        "standard_types",
        "network_import_policy",
        "capabilities",
        "simulation_defaults",
        "build_id",
        "backend_version",
    }
    # Schema is computed live, not loaded from disk.
    assert body["schema"]["meta"]["source"] == "installed pypsa package"
    assert "pypsa_version" in body["schema"]["meta"]
    # Has the expected non-zero number of components (loose lower bound).
    assert len(body["schema"]["components"]) >= 10
    # Standard types frame round-tripped.
    assert isinstance(body["standard_types"]["line_types"], list)
    assert len(body["standard_types"]["line_types"]) > 0
    # Each line-type row carries a name and ohms-per-km style columns.
    sample_row = body["standard_types"]["line_types"][0]
    assert "name" in sample_row
    # Simulation defaults are populated.
    sim = body["simulation_defaults"]
    assert sim["maxSnapshots"] > 0
    assert sim["defaultSnapshotCount"] > 0
    # build_id has the version-dash-hash shape.
    assert "-" in body["build_id"]


def test_build_id_probe_matches_full_bundle():
    reset_cache()
    full = client.get("/api/config").json()
    probe = client.get("/api/config/build-id").json()
    assert probe["build_id"] == full["build_id"]
    assert probe["backend_version"] == full["backend_version"]


def test_reload_resets_cache_and_returns_same_id_when_unchanged():
    reset_cache()
    before = client.get("/api/config").json()["build_id"]
    resp = client.post("/api/config/reload")
    assert resp.status_code == 200
    after = resp.json()["build_id"]
    # PyPSA hasn't changed during the test, so the rebuilt id matches.
    assert after == before


def test_config_endpoint_is_idempotent():
    """Two consecutive GETs return identical bundles when nothing has
    changed — the cache is doing its job, AND the build_id is stable.
    """
    reset_cache()
    a = client.get("/api/config").json()
    b = client.get("/api/config").json()
    assert a == b
