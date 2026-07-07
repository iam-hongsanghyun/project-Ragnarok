"""CLIMADA-worker seam tests — run WITHOUT conda.

A FAKE worker (a shim ``<env>/bin/python`` that execs a tiny script reading
``request.json`` and writing a canned ``result.json``) stands in for the real
CLIMADA env, so these tests exercise the full subprocess seam of
``backend/app/physical_risk/worker.py``: snake_case request translation,
camelCase result parsing, the timeout fallback, and the silent stub when no
worker env exists.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from backend.app.physical_risk import engine
from backend.app.physical_risk import worker as pr_worker
from backend.app.physical_risk.entities import (
    Asset,
    CostBenefitResult,
    MeasureSpec,
    PhysicalRunOutput,
    Portfolio,
    Scenario,
    UncertaintyResult,
)

# Echoing fake worker: captures the request next to itself, then writes a canned
# result for the physical / uncertainty / cost_benefit modes of the contract.
_ECHO_WORKER = """
import json, sys
from pathlib import Path

run_dir = Path(sys.argv[1])
request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
(Path(__file__).parent / "captured_request.json").write_text(
    json.dumps(request), encoding="utf-8"
)
mode = request.get("mode")
if mode is None:
    result = {
        "status": "ok",
        "climate_scenario": request["climate_scenario"],
        "detail": "fake CLIMADA run",
        "results": [
            {
                "peril": p,
                "status": "ok",
                "target_year": max(request["anchor_years"]),
                "aai_agg": 123.45,
                "present_aai_agg": 100.0,
                "delta_pct": 23.45,
                "total_value": sum(a["value"] for a in request["assets"]),
                "per_asset": [
                    {"id": a["id"], "lat": a["lat"], "lon": a["lon"], "eai": 12.5, "country": "KOR"}
                    for a in request["assets"]
                ],
                "freq_curve": {"return_periods": [10.0, 100.0], "impact": [50.0, 500.0]},
            }
            for p in request["perils"]
        ],
    }
elif mode == "uncertainty":
    result = {
        "status": "ok",
        "peril": "tropical_cyclone",
        "future_year": 2050,
        "n_samples": request["n_samples"],
        "currency": "USD",
        "aai_mean": 200.0,
        "aai_std": 30.0,
        "aai_p5": 150.0,
        "aai_p50": 200.0,
        "aai_p95": 260.0,
        "distribution": [150.0, 200.0, 260.0],
        "sensitivity": {"exposure_value": 0.5},
        "sensitivity_s1": {"exposure_value": 0.4},
        "sensitivity_st": {"exposure_value": 0.5},
        "sensitivity_method": "sobol",
        "present_aai": 180.0,
        "delta_mean": 11.1,
        "delta_p5": 5.0,
        "delta_p95": 20.0,
        "detail": "fake MC",
    }
elif mode == "cost_benefit":
    result = {
        "status": "ok",
        "peril": request["peril"],
        "future_year": 2050,
        "discount_rate": request["discount_rate"],
        "currency": "USD",
        "tot_climate_risk": 5000.0,
        "measures": [
            {"name": m["name"], "cost": m["cost"], "benefit": 2.0 * m["cost"], "benefit_cost_ratio": 2.0}
            for m in request["measures"]
        ],
        "detail": "fake CB",
    }
else:
    result = {"status": "error", "detail": "fake worker: unhandled mode " + str(mode)}
(run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
"""

# Fake worker returning an overall-'partial' physical run: the first requested
# peril succeeds, the second fails with a per-peril error block (the contract's
# per-peril status/detail/interpretation shape — physical.py::compute_physical_risk).
_PARTIAL_WORKER = """
import json, sys
from pathlib import Path

run_dir = Path(sys.argv[1])
request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
ok_peril, bad_peril = request["perils"][0], request["perils"][1]
result = {
    "status": "partial",
    "climate_scenario": request["climate_scenario"],
    "detail": "1 of 2 perils failed",
    "results": [
        {
            "peril": ok_peril,
            "status": "ok",
            "aai_agg": 123.45,
            "per_asset": [{"id": a["id"], "eai": 12.5} for a in request["assets"]],
            "freq_curve": {"return_periods": [10.0, 100.0], "impact": [50.0, 500.0]},
        },
        {
            "peril": bad_peril,
            "status": "error",
            "detail": "hazard tile missing",
            "interpretation": "Failed: hazard tile missing",
        },
    ],
}
(run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
"""

# Fake worker that hangs past any small timeout (never writes a result).
_SLEEPY_WORKER = """
import time
time.sleep(5)
"""

# Fake worker that reports a worker-side failure in the contract's own shape.
_FAILING_WORKER = """
import json, sys
from pathlib import Path
run_dir = Path(sys.argv[1])
(run_dir / "result.json").write_text(
    json.dumps({"status": "error", "climate_scenario": "", "results": [], "detail": "boom"}),
    encoding="utf-8",
)
"""


def _install_fake_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script_body: str
) -> Path:
    """Create a fake ``<env>/bin/python`` and point the engine at it.

    The engine spawns ``<python> -m physical_risk_worker.run_job <job_dir>``; the
    shim ignores the ``-m module`` pair and hands the job dir (``$3``) to the fake
    script. Returns ``tmp_path`` (where ``captured_request.json`` appears).
    """
    env_dir = tmp_path / "climada-env"
    (env_dir / "bin").mkdir(parents=True)
    fake_script = tmp_path / "fake_worker.py"
    fake_script.write_text(script_body, encoding="utf-8")
    shim = env_dir / "bin" / "python"
    shim.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{fake_script}' \"$3\"\n")
    shim.chmod(0o755)
    monkeypatch.setenv("RAGNAROK_CLIMADA_WORKER_ENV", str(env_dir))
    monkeypatch.setenv("RAGNAROK_CLIMADA_WORKER", "1")
    monkeypatch.delenv("RAGNAROK_CLIMADA_TIMEOUT", raising=False)
    return tmp_path


def _portfolio() -> Portfolio:
    return Portfolio(
        assets=[
            Asset(name="gasCC", lat=37.5, lon=127.0, value=1_000_000.0, currency="EUR",
                  vulnerabilityClass="thermal"),
            Asset(name="battery1", lat=35.2, lon=129.0, value=250_000.0, currency="EUR",
                  vulnerabilityClass="grid"),
        ]
    )


_SCENARIO = Scenario(rcp="rcp45", horizon=2050)


def _captured(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "captured_request.json").read_text(encoding="utf-8"))


def test_physical_request_uses_worker_snake_case_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_worker(tmp_path, monkeypatch, _ECHO_WORKER)
    pf = _portfolio()
    engine.run_kind("physical", pf, ["tropical_cyclone"], _SCENARIO, {})

    req = _captured(tmp_path)
    assert "mode" not in req  # physical is the worker's default mode
    assert req["session_id"] == pf.sessionId
    assert req["perils"] == ["tropical_cyclone"]
    assert req["climate_scenario"] == "rcp45"
    assert req["anchor_years"] == [2030, 2040, 2050]  # portfolio anchors, horizon = max
    assert req["options"] == {}

    spec = req["assets"][0]
    # snake_case AssetSpec fields (climaterisk engines/base.py), with the
    # vulnerability class resolved to concrete curve params — no camelCase leaks.
    for key in (
        "id", "name", "lat", "lon", "sector", "value", "currency",
        "vulnerability_class", "tc_v_half", "wf_max_mdd",
        "flood_depth_m", "flood_mdr", "eq_mmi", "eq_mdr", "geometry",
    ):
        assert key in spec
    assert "vulnerabilityClass" not in spec
    assert spec["id"] == pf.assets[0].id
    assert spec["vulnerability_class"] == "industrial_heavy"  # thermal borrows this class
    assert len(spec["flood_mdr"]) == len(spec["flood_depth_m"])
    assert len(spec["eq_mdr"]) == len(spec["eq_mmi"])


def test_physical_result_parsed_into_camel_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_worker(tmp_path, monkeypatch, _ECHO_WORKER)
    pf = _portfolio()
    result = engine.run_kind("physical", pf, ["tropical_cyclone"], _SCENARIO, {})

    assert isinstance(result, PhysicalRunOutput)
    assert result.currency == "EUR"  # portfolio currency, not a worker guess
    assert result.detail == "fake CLIMADA run"
    block = result.perils[0]
    assert block.peril == "tropical_cyclone"
    assert block.aaiAgg == 123.45  # aai_agg -> aaiAgg
    assert block.deltaPct == 23.45  # delta_pct -> deltaPct
    assert block.freqCurve.returnPeriods == [10.0, 100.0]  # return_periods
    assert block.freqCurve.losses == [50.0, 500.0]  # impact -> losses
    assert [p.assetId for p in block.perAsset] == [a.id for a in pf.assets]  # id -> assetId
    assert all(p.eai == 12.5 for p in block.perAsset)


def test_uncertainty_worker_result_wrapped_in_peril_band(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_worker(tmp_path, monkeypatch, _ECHO_WORKER)
    result = engine.run_kind(
        "uncertainty", _portfolio(), ["tropical_cyclone"], _SCENARIO, {"nSamples": 25}
    )

    req = _captured(tmp_path)
    assert req["mode"] == "uncertainty"
    assert req["n_samples"] == 25  # nSamples -> n_samples

    assert isinstance(result, UncertaintyResult)
    assert result.nSamples == 25
    assert len(result.perils) == 1  # single-peril worker result -> one band
    band = result.perils[0]
    assert band.aaiP95 == 260.0  # aai_p95 -> aaiP95
    assert band.sensitivityS1 == {"exposure_value": 0.4}  # sensitivity_s1
    assert band.presentAai == 180.0  # present_aai
    assert band.deltaMean == 11.1  # delta_mean


def test_cost_benefit_measures_translated_both_ways(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_worker(tmp_path, monkeypatch, _ECHO_WORKER)
    measures = [MeasureSpec(name="Dyke", cost=100.0, damageReduction=0.3)]
    result = engine.run_kind(
        "cost-benefit",
        _portfolio(),
        ["tropical_cyclone"],
        _SCENARIO,
        {"measures": measures, "discountRate": 0.07},
    )

    req = _captured(tmp_path)
    assert req["mode"] == "cost_benefit"
    assert req["discount_rate"] == 0.07  # discountRate -> discount_rate
    sent = req["measures"][0]
    assert sent["damage_reduction"] == 0.3  # damageReduction -> damage_reduction
    assert sent["hazard_freq_cutoff"] == 0.0
    assert sent["risk_transf_attach"] == 0.0

    assert isinstance(result, CostBenefitResult)
    assert result.totClimateRisk == 5000.0  # tot_climate_risk
    assert result.measures[0].benefitCostRatio == 2.0  # benefit_cost_ratio


def test_partial_worker_result_keeps_failed_peril_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An overall-'partial' worker run (some perils ok, some failed) must not
    silently zero the failed perils: the failure reason lands on the failed
    block's ``detail`` (so its zero reads as "not modeled", not "modeled as
    zero") and the output-level detail names the failed peril, appended to the
    worker's own detail rather than overwriting it."""
    _install_fake_worker(tmp_path, monkeypatch, _PARTIAL_WORKER)
    pf = _portfolio()
    result = engine.run_kind(
        "physical", pf, ["tropical_cyclone", "river_flood"], _SCENARIO, {}
    )

    assert isinstance(result, PhysicalRunOutput)
    assert [b.peril for b in result.perils] == ["tropical_cyclone", "river_flood"]
    ok_block, failed_block = result.perils

    # The ok peril parses exactly as in a fully-ok run — no failure flag.
    assert ok_block.detail is None
    assert ok_block.aaiAgg == 123.45
    assert [p.assetId for p in ok_block.perAsset] == [a.id for a in pf.assets]

    # The failed peril keeps its zeroed numbers but is FLAGGED, not silent.
    assert failed_block.aaiAgg == 0.0
    assert failed_block.perAsset == []
    assert failed_block.freqCurve.returnPeriods == []
    assert failed_block.detail is not None
    assert "hazard tile missing" in failed_block.detail

    # Output-level detail: the worker's own note is kept AND the failed peril named.
    assert result.detail is not None
    assert "1 of 2 perils failed" in result.detail
    assert "river_flood" in result.detail


def test_timeout_falls_back_to_stub_with_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_worker(tmp_path, monkeypatch, _SLEEPY_WORKER)
    monkeypatch.setenv("RAGNAROK_CLIMADA_TIMEOUT", "1")
    pf = _portfolio()
    result = engine.run_kind("physical", pf, ["tropical_cyclone"], _SCENARIO, {})

    assert isinstance(result, PhysicalRunOutput)
    stub = engine._run_engine(pf, ["tropical_cyclone"], _SCENARIO)
    assert result.perils[0].aaiAgg == stub.perils[0].aaiAgg  # the stub numbers
    assert result.detail is not None
    assert "Worker fallback" in result.detail
    assert "timed out" in result.detail


def test_worker_error_status_falls_back_to_stub_with_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_worker(tmp_path, monkeypatch, _FAILING_WORKER)
    pf = _portfolio()
    result = engine.run_kind("physical", pf, ["tropical_cyclone"], _SCENARIO, {})

    assert isinstance(result, PhysicalRunOutput)
    stub = engine._run_engine(pf, ["tropical_cyclone"], _SCENARIO)
    assert result.perils[0].aaiAgg == stub.perils[0].aaiAgg
    assert result.detail is not None and "boom" in result.detail


def test_missing_env_in_auto_mode_serves_stub_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAGNAROK_CLIMADA_WORKER_ENV", str(tmp_path / "nonexistent"))
    monkeypatch.delenv("RAGNAROK_CLIMADA_WORKER", raising=False)  # default: auto
    pf = _portfolio()
    result = engine.run_kind("physical", pf, ["tropical_cyclone"], _SCENARIO, {})

    assert isinstance(result, PhysicalRunOutput)
    assert result.detail is None  # silent — no worker was expected
    assert not pr_worker.available()
    stub = engine._run_engine(pf, ["tropical_cyclone"], _SCENARIO)
    assert result.perils[0].aaiAgg == stub.perils[0].aaiAgg


def test_missing_env_when_forced_notes_the_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAGNAROK_CLIMADA_WORKER_ENV", str(tmp_path / "nonexistent"))
    monkeypatch.setenv("RAGNAROK_CLIMADA_WORKER", "1")
    result = engine.run_kind("physical", _portfolio(), ["tropical_cyclone"], _SCENARIO, {})

    assert isinstance(result, PhysicalRunOutput)
    assert result.detail is not None
    assert "Worker fallback" in result.detail
    assert "no worker env" in result.detail


def test_worker_python_resolves_windows_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows conda prefix envs put python.exe at the env ROOT (no bin/).

    worker_python() must fall back to that layout so the .bat/.ps1 installers
    produce an env available() actually detects; POSIX bin/python still wins
    when both exist.
    """
    env_dir = tmp_path / "climada-env-win"
    env_dir.mkdir()
    (env_dir / "python.exe").write_text("")
    monkeypatch.setenv("RAGNAROK_CLIMADA_WORKER_ENV", str(env_dir))

    assert pr_worker.worker_python() == env_dir / "python.exe"
    assert pr_worker.available()

    # POSIX layout takes precedence when present.
    (env_dir / "bin").mkdir()
    (env_dir / "bin" / "python").write_text("")
    assert pr_worker.worker_python() == env_dir / "bin" / "python"
