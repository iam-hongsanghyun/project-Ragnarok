"""PyPSA-Earth builder (I9) — env gating, job lifecycle, network ingest.

The heavy workflow needs an external conda env + CDS key and isn't run in CI;
what's tested is the queue/status plumbing, the graceful not-configured error,
env resolution, and the network→workbook ingest on a real ``.nc``.
"""
from __future__ import annotations

import shutil
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
    monkeypatch.setattr(pe, "_PID_FILE", tmp_path / "pe_run.pid")
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


def test_snakemake_argv_uses_path_binary_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/snakemake" if name == "snakemake" else None)
    argv = pe._snakemake_argv("results/networks/elec_s_10.nc")
    assert argv[0] == "snakemake" and "results/networks/elec_s_10.nc" in argv


def test_snakemake_argv_runs_through_mamba_without_conda_only_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAGNAROK_PYPSA_EARTH_CONDA_ENV", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/opt/conda/bin/mamba" if name == "mamba" else None)
    argv = pe._snakemake_argv("results/networks/elec_s_10.nc")
    assert argv[:2] == ["/opt/conda/bin/mamba", "run"]
    assert "pypsa-earth" in argv and "snakemake" in argv
    # mamba 2.x rejects conda's --no-capture-output ("exec: --: invalid option").
    assert "--no-capture-output" not in argv


def test_snakemake_argv_keeps_no_capture_flag_for_conda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAGNAROK_PYPSA_EARTH_CONDA_ENV", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/opt/conda/bin/conda" if name == "conda" else None)
    argv = pe._snakemake_argv("results/networks/elec_s_10.nc")
    assert argv[:3] == ["/opt/conda/bin/conda", "run", "--no-capture-output"]
    assert "pypsa-earth" in argv and "snakemake" in argv


def test_snakemake_argv_raises_when_nothing_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="snakemake is not on"):
        pe._snakemake_argv("t.nc")


class _FakeProc:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def test_conda_env_exists_parses_env_list(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = ("# conda environments:\n"
               "base                  *  /opt/miniconda3\n"
               "pypsa-earth              /opt/miniconda3/envs/pypsa-earth\n")
    monkeypatch.setattr(pe.subprocess, "run", lambda *a, **k: _FakeProc(listing))
    assert pe._conda_env_exists("conda", "pypsa-earth") is True
    assert pe._conda_env_exists("conda", "nope") is False


def test_preflight_raises_when_conda_env_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "envs").mkdir()
    monkeypatch.setattr(pe.subprocess, "run", lambda *a, **k: _FakeProc("base  /opt/miniconda3\n"))
    argv = ["/opt/miniconda3/bin/conda", "run", "--no-capture-output", "-n", "pypsa-earth", "snakemake", "x.nc"]
    with pytest.raises(RuntimeError, match="conda env does not exist"):
        pe._preflight(tmp_path, argv)


def test_preflight_ok_when_env_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pe.subprocess, "run", lambda *a, **k: _FakeProc("pypsa-earth  /x/envs/pypsa-earth\n"))
    argv = ["conda", "run", "--no-capture-output", "-n", "pypsa-earth", "snakemake", "x.nc"]
    pe._preflight(tmp_path, argv)  # no raise
    # Direct-PATH invocation (no conda run) skips the env check entirely.
    pe._preflight(tmp_path, ["snakemake", "-j", "4", "x.nc"])


def test_build_overlay_pins_country_clusters_and_run(monkeypatch: pytest.MonkeyPatch) -> None:
    req = pe.BuildRequest(countryIso="KOR", countryName="South Korea", horizonYear=2033, clusters=12)
    overlay = pe._build_overlay(req, "KR")
    assert overlay["countries"] == ["KR"]
    assert overlay["run"]["name"] == "ragnarok_KR"
    assert overlay["scenario"]["clusters"] == [12]
    # All four wildcards pinned so the output filename is deterministic.
    assert overlay["scenario"]["simpl"] == [""] and overlay["scenario"]["ll"] == ["copt"]
    assert overlay["costs"]["year"] == 2035  # snapped to the 5-year cost grid


def test_target_is_the_prepared_network_not_the_solved_one() -> None:
    # networks/<run>/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}.nc — pre-solve
    # (results/… would run PyPSA-Earth's own solve, on restricted Gurobi).
    assert pe._target_for("KR", 10) == "networks/ragnarok_KR/elec_s_10_ec_lcopt_Co2L-3h.nc"


def test_snakemake_argv_includes_configfile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/snakemake" if name == "snakemake" else None)
    argv = pe._snakemake_argv("results/x.nc", "ragnarok_config_KR.yaml")
    i = argv.index("--configfile")
    assert argv[i + 1] == "ragnarok_config_KR.yaml"
    # Target must come BEFORE --configfile (snakemake's flag is greedy, nargs='+').
    assert argv.index("results/x.nc") < i


def test_stream_log_tails_lines_and_lifts_progress() -> None:
    pe._JOBS["stream-t"] = {"jobId": "stream-t", "status": "running"}
    try:
        lines = [
            "Building DAG of jobs...\n",
            "1 of 4 steps (25%) done\n",
            "\n",  # blank — dropped
            "rule build_cutout:\n",
            "4 of 4 steps (100%) done\n",
        ]
        pe._stream_log(iter(lines), "stream-t")
        job = pe._JOBS["stream-t"]
        assert job["progress"] == 100
        assert "100%" in job["detail"]
        assert "" not in job["log"]                       # blanks skipped
        assert any("25%" in line for line in job["log"])  # earlier lines retained in the tail
    finally:
        pe._JOBS.pop("stream-t", None)


def test_kill_orphaned_child_no_pid_file_is_noop() -> None:
    assert pe._kill_orphaned_child() is False


def test_kill_orphaned_child_ignores_recycled_pid() -> None:
    import json
    import os

    # Record OUR OWN pid — alive, but its command is pytest, not snakemake, so it
    # must be treated as a recycled pid: not killed, record dropped.
    pe._record_child(os.getpid())
    assert pe._kill_orphaned_child() is False
    assert not pe._PID_FILE.exists()
    # And a dead pid is also just dropped.
    pe._PID_FILE.write_text(json.dumps({"pid": 2**22 - 7}), encoding="utf-8")
    assert pe._kill_orphaned_child() is False


def test_stream_log_collapses_tqdm_redraws_in_place() -> None:
    pe._JOBS["tqdm-t"] = {"jobId": "tqdm-t", "status": "running"}
    try:
        lines = [
            "Downloading data bundle...\n",
            "  1%|          | 1.0/100 [00:10<16:00,  9.7s/it]\n",
            "  2%|▏         | 2.0/100 [00:21<17:45, 10.87s/it]\n",
            "  3%|▎         | 3.0/100 [00:32<17:30, 10.90s/it]\n",
            "rule build_shapes:\n",
            " 50%|█████     | 50/100 [05:00<05:00,  6.0s/it]\r 51%|█████     | 51/100 [05:06<04:54,  6.0s/it]\n",
        ]
        pe._stream_log(iter(lines), "tqdm-t")
        logged = pe._JOBS["tqdm-t"]["log"]
        # The three redraws collapsed into one (the latest), like a terminal.
        assert sum(1 for line in logged if "/100 [" in line and "s/it]" in line) == 2
        assert any("3.0/100" in line for line in logged)
        assert not any("2.0/100" in line for line in logged)
        # A \r-joined chunk keeps only its final state.
        assert any("51/100" in line for line in logged)
        assert not any(" 50/100" in line for line in logged)
        # Normal lines still stack.
        assert any(line.startswith("Downloading") for line in logged)
        assert any(line.startswith("rule build_shapes") for line in logged)
    finally:
        pe._JOBS.pop("tqdm-t", None)


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
