"""PyPSA-Earth builder (I9) — env gating, job lifecycle, network ingest.

The heavy workflow needs an external conda env + CDS key and isn't run in CI;
what's tested is the queue/status plumbing, the graceful not-configured error,
env resolution, and the network→workbook ingest on a real ``.nc``.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pypsa
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import pypsa_earth as pe

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate all env-detection so tests never see the real
    backend/data/pypsa_earth.json, a locally-cloned <repo>/pypsa-earth, or a
    checkout in the developer's home dir."""
    monkeypatch.setattr(pe, "_STATE_FILE", tmp_path / "pe_state.json")
    monkeypatch.setattr(pe, "_auto_dir", lambda: None)
    monkeypatch.setattr(pe, "_suggested_dirs", lambda: [])


def test_available_reports_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAGNAROK_PYPSA_EARTH_DIR", raising=False)
    r = client.get("/api/pypsa-earth/available").json()
    assert r["available"] is False
    assert "not configured" in r["detail"].lower()
    assert r["docs"].endswith("pypsa-earth-integration.md")


def test_resolve_env_requires_a_snakefile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGNAROK_PYPSA_EARTH_DIR", str(tmp_path))
    assert pe.resolve_env() is None  # no Snakefile
    (tmp_path / "Snakefile").write_text("# workflow root\n")
    assert pe.resolve_env() == tmp_path


def test_build_job_fails_cleanly_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAGNAROK_PYPSA_EARTH_DIR", raising=False)
    job = client.post("/api/pypsa-earth/build", json={"countryIso": "NGA", "countryName": "Nigeria"}).json()
    assert job["status"] in ("queued", "running")
    job_id = job["jobId"]
    # Poll — each request drives the app's event loop, letting the queued
    # coroutine run its (instant, no-env) check and settle to 'error'.
    status = {}
    for _ in range(20):
        status = client.get(f"/api/pypsa-earth/build/{job_id}").json()
        if status["status"] not in ("queued", "running"):
            break
        time.sleep(0.02)
    assert status["status"] == "error"
    assert "not configured" in status["error"].lower()
    # Result is 409 until (if ever) done.
    assert client.get(f"/api/pypsa-earth/build/{job_id}/result").status_code == 409


def test_build_status_404_for_unknown_job() -> None:
    assert client.get("/api/pypsa-earth/build/nope").status_code == 404


def test_configure_persists_a_valid_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAGNAROK_PYPSA_EARTH_DIR", raising=False)
    workflow = tmp_path / "pypsa-earth"
    workflow.mkdir()
    (workflow / "Snakefile").write_text("# workflow root\n")

    r = client.post("/api/pypsa-earth/configure", json={"dir": str(workflow)}).json()
    assert r["available"] is True and r["dir"] == str(workflow)
    # Persisted → a fresh /available (no env var) still reports it.
    assert client.get("/api/pypsa-earth/available").json()["available"] is True


def test_configure_rejects_missing_directory() -> None:
    r = client.post("/api/pypsa-earth/configure", json={"dir": "/no/such/dir-xyz"})
    assert r.status_code == 400 and "No such directory" in r.json()["detail"]


def test_configure_rejects_dir_without_snakefile(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    r = client.post("/api/pypsa-earth/configure", json={"dir": str(tmp_path / "empty")})
    assert r.status_code == 400 and "Snakefile" in r.json()["detail"]


def test_auto_detects_in_project_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAGNAROK_PYPSA_EARTH_DIR", raising=False)
    workflow = tmp_path / "pypsa-earth"
    workflow.mkdir()
    (workflow / "Snakefile").write_text("# root\n")
    # Simulate the setup script's in-project clone being present.
    monkeypatch.setattr(pe, "_auto_dir", lambda: workflow)
    r = client.get("/api/pypsa-earth/available").json()
    assert r["available"] is True and r["dir"] == str(workflow)


def test_available_offers_clickable_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAGNAROK_PYPSA_EARTH_DIR", raising=False)
    found = tmp_path / "somewhere" / "pypsa-earth"
    found.mkdir(parents=True)
    (found / "Snakefile").write_text("# root\n")
    monkeypatch.setattr(pe, "_suggested_dirs", lambda: [str(found)])
    r = client.get("/api/pypsa-earth/available").json()
    # Not auto-configured (not the in-project default), but offered as a choice.
    assert r["available"] is False
    assert str(found) in r["candidates"]


def test_configure_clear_removes_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAGNAROK_PYPSA_EARTH_DIR", raising=False)
    workflow = tmp_path / "pe"
    workflow.mkdir()
    (workflow / "Snakefile").write_text("# root\n")
    assert client.post("/api/pypsa-earth/configure", json={"dir": str(workflow)}).json()["available"] is True
    assert client.post("/api/pypsa-earth/configure", json={"dir": ""}).json()["available"] is False


def test_ingest_network_maps_a_netcdf_to_sheets(tmp_path: Path) -> None:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Bus", "b", v_nom=380.0)
    n.add("Carrier", "wind")
    n.add("Generator", "g", bus="b", carrier="wind", p_nom=100.0)
    n.add("Load", "d", bus="b", p_set=50.0)
    nc = tmp_path / "elec.nc"
    n.export_to_netcdf(str(nc))

    sheets = pe.ingest_network(nc)
    assert {"buses", "generators", "loads"} <= set(sheets)
    assert any(row.get("name") == "g" for row in sheets["generators"])
    assert any(row.get("name") == "b" for row in sheets["buses"])
