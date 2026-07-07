"""Tests for the extended physical-risk capability (climaterisk feature port).

Covers: the vendored libraries endpoint, the REAL transition (NGFS carbon cost) and
finance (climate-risk-premium) math, every worker-gated run kind against the
deterministic stub engine, portfolio scenario-config round-trips (with Phase-0
back-compat), and the JSON report bundle.

Hand-computed anchors use the vendored ``ngfs_carbon_prices.json`` (current_policies:
2030 -> 10.3, 2035 -> 10.16, so 2032 interpolates to 10.244) and the
``finance_reference.json`` financing defaults (debt 70% at rf 3% + 150 bps over an
18y annuity).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import session_store
from backend.app.main import app
from backend.app.physical_risk import store as physical_risk_store

client = TestClient(app)

# Stub-engine expectations for the seeded 2-asset portfolio (see _load_model):
#   gasCC   value = capital_cost * p_nom = 800 * 400   = 320_000
#   battery value = default_value_per_mw * p_nom = 1e6 * 100 = 100_000_000
# Tropical-cyclone EAI (factor 0.012, index spread 1.00 / 1.05):
#   gasCC 3_840.0, battery 1_260_000.0 -> aggregate 1_263_840.0
_TC_AAI_GAS = 3_840.0
_TC_AAI_BATTERY = 1_260_000.0
_TC_AAI_TOTAL = _TC_AAI_GAS + _TC_AAI_BATTERY


@pytest.fixture(autouse=True)
def _stub_engine_and_isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the deterministic stub engine (a local .climada-env would route runs
    to real CLIMADA) and keep the store's persistence out of backend/data."""
    monkeypatch.setenv("RAGNAROK_CLIMADA_WORKER", "0")
    monkeypatch.setattr(physical_risk_store, "DATA_DIR", tmp_path / "physical_risk")


@pytest.fixture()
def _session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the session store at a temp dir so nothing touches real session data."""
    target = tmp_path / "session"
    monkeypatch.setattr(session_store, "SESSION_DIR", target)
    return target


def _load_model() -> None:
    """Load a 2-bus model: bus B1 (a gas gen), bus B2 (a battery storage unit)."""
    model = {
        "buses": [
            {"name": "B1", "x": 127.0, "y": 37.5},
            {"name": "B2", "x": 129.0, "y": 35.2},
        ],
        "generators": [
            {"name": "gasCC", "bus": "B1", "carrier": "gas", "p_nom": 400.0, "capital_cost": 800.0},
        ],
        "storage_units": [
            {"name": "battery1", "bus": "B2", "carrier": "battery", "p_nom": 100.0},
        ],
        "snapshots": [{"snapshot": "2030-01-01T00:00:00"}],
    }
    resp = client.post(
        "/api/session/model",
        json={"sessionId": "default", "model": model, "filename": "case.xlsx", "scenarioName": "ref"},
    )
    assert resp.status_code == 200, resp.text


def _seed() -> str:
    _load_model()
    resp = client.post("/api/physical-risk/seed-from-model")
    assert resp.status_code == 200, resp.text
    return resp.json()["sessionId"]


def _run_to_done(sid: str, body: dict) -> dict:
    """Submit a run and poll it once (submit grace-joins the near-instant stub,
    so a stub run is already done by the first poll)."""
    submit = client.post(f"/api/physical-risk/session/{sid}/run", json=body)
    assert submit.status_code == 200, submit.text
    rid = submit.json()["id"]
    poll = client.get(f"/api/physical-risk/session/{sid}/run/{rid}")
    assert poll.status_code == 200, poll.text
    done = poll.json()
    assert done["status"] == "done", done
    return done


# ── libraries ──────────────────────────────────────────────────────────────────


def test_libraries_serves_all_eight_keys_with_vendored_content(_session_dir: Path) -> None:
    body = client.get("/api/physical-risk/libraries").json()
    for key in (
        "perils",
        "scenarios",
        "sectors",
        "vulnerabilityClasses",
        "impactFunctions",
        "ngfsScenarios",
        "financeChannels",
        "dataSources",
    ):
        assert body.get(key), f"libraries key '{key}' missing or empty"

    # perils: vendored list, labelled, worker-gated flag present.
    tc = next(p for p in body["perils"] if p["id"] == "tropical_cyclone")
    assert tc["label"] == "Tropical cyclone"
    assert tc["workerGated"] is True
    assert tc["engineHazardType"] == "TC"

    # scenarios: RCP list + NGFS transition list + anchor years.
    assert {s["id"] for s in body["scenarios"]["climate"]} == {"rcp26", "rcp45", "rcp60", "rcp85"}
    assert "net_zero_2050" in {s["id"] for s in body["scenarios"]["transition"]}
    assert body["scenarios"]["anchorYears"] == [2030, 2040, 2050, 2060]

    # sectors: emission intensities present (utilities drives the PyPSA-seeded proxy).
    utilities = next(s for s in body["sectors"] if s["id"] == "utilities")
    assert utilities["emissionIntensityTco2ePerMusd"] == pytest.approx(2500.0)

    # vulnerability classes carry full curve data matching the breakpoints.
    depths = body["impactFunctions"]["floodDepthM"]
    mmi = body["impactFunctions"]["eqMmi"]
    assert len(depths) == 8 and len(mmi) == 6
    for vc in body["vulnerabilityClasses"]:
        assert len(vc["floodMdr"]) == len(depths), vc["id"]
        assert len(vc["eqMdr"]) == len(mmi), vc["id"]
        assert vc["tcVHalf"] > 0
    assert body["impactFunctions"]["presets"]  # impact-function studio presets

    # NGFS carbon prices: all four vendored trajectories with year -> price maps.
    ngfs_ids = {s["id"] for s in body["ngfsScenarios"]["scenarios"]}
    assert ngfs_ids == {"net_zero_2050", "below_2c", "delayed_transition", "current_policies"}
    nz = next(s for s in body["ngfsScenarios"]["scenarios"] if s["id"] == "net_zero_2050")
    assert nz["prices"]["2030"] == pytest.approx(183.3)
    assert nz["label"]

    # finance channels + nested reference framework.
    fc = body["financeChannels"]
    assert fc["generationDefaults"]["capacityFactorByFuel"]["nuclear"] == pytest.approx(0.85)
    ref = fc["reference"]
    assert ref["ratingScale"][0] == "AAA"
    assert ref["ratingDscrThresholds"][0]["dscrMin"] == pytest.approx(2.5)
    assert "moodys_sp" in ref["ratingMethods"]
    assert ref["financingDefaults"]["debtFraction"]["value"] == pytest.approx(0.70)

    # data sources registry.
    assert body["dataSources"]["categories"]
    assert any(s["id"] == "aqueduct" for s in body["dataSources"]["sources"])


# ── portfolio scenario config (round-trip + Phase-0 back-compat) ───────────────


def test_scenario_config_round_trips_and_defaults(_session_dir: Path) -> None:
    sid = _seed()
    pf = client.get(f"/api/physical-risk/session/{sid}").json()

    # Seeded defaults (back-compat: Phase-0 clients never sent these).
    assert pf["scenario"]["perils"] == ["tropical_cyclone"]
    assert pf["scenario"]["climate"] == "rcp45"
    assert pf["scenario"]["transition"] == "net_zero_2050"
    assert pf["scenario"]["horizonYear"] == 2050
    assert pf["assets"][0]["sector"] == "utilities"
    assert pf["assets"][0]["annualEmissionsTco2e"] is None

    pf["scenario"].update(
        {
            "perils": ["river_flood", "earthquake"],
            "climate": "rcp85",
            "transition": "below_2c",
            "horizonYear": 2040,
            "anchorYears": [2030, 2040],
            "discountRate": 0.03,
            "vulnerabilityOverrides": {
                "industrial_heavy": {"floodMdr": [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]}
            },
        }
    )
    put = client.put(f"/api/physical-risk/session/{sid}", json=pf)
    assert put.status_code == 200, put.text
    again = client.get(f"/api/physical-risk/session/{sid}").json()
    assert again["scenario"]["perils"] == ["river_flood", "earthquake"]
    assert again["scenario"]["climate"] == "rcp85"
    assert again["scenario"]["horizonYear"] == 2040
    assert again["scenario"]["vulnerabilityOverrides"]["industrial_heavy"]["floodMdr"][1] == 0.2
    # Phase-0 fields untouched by the scenario edit.
    assert {a["name"] for a in again["assets"]} == {"gasCC", "battery1"}
    assert again["assets"][0]["vulnerabilityClass"] in ("thermal", "grid")


def test_phase0_shaped_put_still_accepted(_session_dir: Path) -> None:
    """A Phase-0 document (no scenario key, no new asset fields) must still validate."""
    sid = _seed()
    phase0_doc = {
        "sessionId": sid,
        "assets": [
            {
                "id": "a1",
                "name": "legacy",
                "kind": "generator",
                "lat": 37.0,
                "lon": 127.0,
                "value": 5_000.0,
                "currency": "USD",
                "vulnerabilityClass": "thermal",
                "carrier": "gas",
            }
        ],
    }
    put = client.put(f"/api/physical-risk/session/{sid}", json=phase0_doc)
    assert put.status_code == 200, put.text
    saved = put.json()
    assert saved["assets"][0]["value"] == pytest.approx(5_000.0)
    # New fields materialise with defaults.
    assert saved["scenario"]["transition"] == "net_zero_2050"
    assert saved["assets"][0]["sector"] == "utilities"


# ── transition (REAL math) ─────────────────────────────────────────────────────


def test_transition_hand_computed_against_vendored_prices(_session_dir: Path) -> None:
    sid = _seed()
    pf = client.get(f"/api/physical-risk/session/{sid}").json()
    assets = {a["name"]: a for a in pf["assets"]}
    assets["gasCC"]["annualEmissionsTco2e"] = 2.0  # reported Scope-1
    pf["scenario"]["transition"] = "current_policies"
    pf["scenario"]["discountRate"] = 0.0
    assert client.put(f"/api/physical-risk/session/{sid}", json=pf).status_code == 200

    res = client.post(f"/api/physical-risk/session/{sid}/transition", json={})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["scenario"] == "current_policies"
    assert out["baseYear"] == 2025
    assert out["years"][0] == 2025 and out["years"][-1] == 2050
    per = {a["name"]: a for a in out["perAsset"]}

    gas = per["gasCC"]
    assert gas["emissionsSource"] == "reported"
    assert gas["emissionsTco2e"] == pytest.approx(2.0)
    # 2032 interpolates current_policies between 2030 (10.3) and 2035 (10.16):
    # 10.3 + (2/5) * (10.16 - 10.3) = 10.244 -> cost = 2.0 * 10.244 = 20.488
    assert gas["annualCostByYear"]["2032"] == pytest.approx(20.488)
    # Zero discount rate: NPV is the plain sum of the annual costs.
    assert gas["npv"] == pytest.approx(sum(gas["annualCostByYear"].values()))

    battery = per["battery1"]
    assert battery["emissionsSource"] == "sector_proxy"
    # (value / 1e6) * utilities intensity = (1e8 / 1e6) * 2500 = 250_000 tCO2e
    assert battery["emissionsTco2e"] == pytest.approx(250_000.0)

    assert out["totalNpv"] == pytest.approx(sum(a["npv"] for a in out["perAsset"]))

    # A different NGFS scenario changes the numbers (net-zero prices are far higher).
    nz = client.post(
        f"/api/physical-risk/session/{sid}/transition", json={"scenario": "net_zero_2050"}
    ).json()
    assert nz["scenario"] == "net_zero_2050"
    assert nz["totalNpv"] > out["totalNpv"]
    # net_zero_2050 2030 anchor: 183.3 exactly (no interpolation needed).
    nz_gas = {a["name"]: a for a in nz["perAsset"]}["gasCC"]
    assert nz_gas["annualCostByYear"]["2030"] == pytest.approx(2.0 * 183.3)


def test_transition_unknown_scenario_reports_detail(_session_dir: Path) -> None:
    sid = _seed()
    res = client.post(
        f"/api/physical-risk/session/{sid}/transition", json={"scenario": "not_a_scenario"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["years"] == []
    assert "no carbon-price trajectory" in (body["detail"] or "")


# ── finance (REAL math) ────────────────────────────────────────────────────────


def _set_profile(sid: str, profile: dict) -> None:
    pf = client.get(f"/api/physical-risk/session/{sid}").json()
    pf["scenario"]["financialProfile"] = profile
    resp = client.put(f"/api/physical-risk/session/{sid}", json=pf)
    assert resp.status_code == 200, resp.text


def test_finance_generic_hand_computed(_session_dir: Path) -> None:
    sid = _seed()
    _set_profile(sid, {"capex": 1_000_000.0, "annualEbitda": 200_000.0})
    run = _run_to_done(sid, {"perils": ["tropical_cyclone"]})

    res = client.post(
        f"/api/physical-risk/session/{sid}/finance",
        json={"runId": run["id"], "transitionCost": 0.0},
    )
    assert res.status_code == 200, res.text
    fin = res.json()

    assert fin["totalPhysicalAai"] == pytest.approx(_TC_AAI_TOTAL)
    assert fin["financialModel"] == "generic"
    assert fin["ratingMethod"] == "moodys_sp"

    baseline = fin["portfolio"]["baseline"]
    # Hand-computed from finance_reference defaults: debt = 0.7 * 1e6 at
    # rate 0.03 + 150 bps = 0.045 over 18y -> annuity 57_565.06/yr;
    # DSCR = 200_000 / 57_565.06 = 3.4744 -> AAA (>= 2.5) -> 50 bps.
    assert baseline["minDscr"] == pytest.approx(3.4744, rel=1e-3)
    assert baseline["rating"] == "AAA"
    assert baseline["spreadBps"] == pytest.approx(50.0)
    # WACC = 0.7 * 0.045 + 0.3 * 0.12 = 0.0675
    assert baseline["wacc"] == pytest.approx(0.0675)

    # Stressed EBITDA = 200_000 - 1_263_840 < 0 -> DSCR < 0 -> D -> 5000 bps.
    stressed = fin["portfolio"]["stressed"]
    assert stressed["rating"] == "D"
    assert fin["portfolio"]["annualClimateLoss"] == pytest.approx(_TC_AAI_TOTAL)
    assert fin["portfolio"]["crpBps"] == pytest.approx(5000.0 - 50.0)
    assert fin["portfolio"]["downgrade"] is True
    assert fin["methodsCompared"][0]["method"] == "moodys_sp"


def test_finance_power_gen_channels(_session_dir: Path) -> None:
    sid = _seed()
    _set_profile(
        sid,
        {
            "capex": 1_000_000.0,
            "financialModel": "power_gen",
            "capacityMw": 100.0,
            "powerPrice": 50.0,
            "capacityFactor": 0.5,
            "outageRate": 0.1,
        },
    )
    run = _run_to_done(sid, {"perils": ["tropical_cyclone"]})
    res = client.post(
        f"/api/physical-risk/session/{sid}/finance",
        json={"runId": run["id"], "transitionCost": 0.0},
    )
    assert res.status_code == 200, res.text
    fin = res.json()
    assert fin["financialModel"] == "power_gen"
    br = fin["portfolioBreakdown"]
    # CF stressed by the 10% forced-outage channel only: 0.5 * 0.9 = 0.45.
    assert br["cfBaseline"] == pytest.approx(0.5)
    assert br["cfEffective"] == pytest.approx(0.45)
    # Generation 100 MW * 8760 h * CF; revenue at 50/MWh.
    assert br["generationMwhBaseline"] == pytest.approx(438_000.0)
    assert br["revenueBaseline"] == pytest.approx(21_900_000.0)
    # Stressed run also subtracts the physical AAI.
    assert br["annualAai"] == pytest.approx(_TC_AAI_TOTAL)
    assert br["channels"]["outageRate"] == pytest.approx(0.1)


def test_finance_requires_profile_and_finished_physical_run(_session_dir: Path) -> None:
    sid = _seed()
    run = _run_to_done(sid, {"perils": ["tropical_cyclone"]})
    # No financial profile -> 400.
    res = client.post(
        f"/api/physical-risk/session/{sid}/finance", json={"runId": run["id"]}
    )
    assert res.status_code == 400
    # Unknown run -> 404.
    _set_profile(sid, {"capex": 1_000_000.0, "annualEbitda": 200_000.0})
    res = client.post(
        f"/api/physical-risk/session/{sid}/finance", json={"runId": "nope"}
    )
    assert res.status_code == 404


# ── worker-gated run kinds (stub results, faithful shapes) ─────────────────────


def test_uncertainty_run_bands_per_peril(_session_dir: Path) -> None:
    sid = _seed()
    done = _run_to_done(
        sid,
        {"kind": "uncertainty", "perils": ["tropical_cyclone", "river_flood"], "nSamples": 25},
    )
    assert done["kind"] == "uncertainty"
    out = done["result"]
    assert out["kind"] == "uncertainty"
    assert out["status"] == "ok"
    assert out["nSamples"] == 25
    assert len(out["perils"]) == 2
    for band in out["perils"]:
        assert band["aaiP5"] <= band["aaiP50"] <= band["aaiP95"]
        assert band["aaiP5"] == pytest.approx(0.8 * band["aaiMean"], rel=1e-6)
        assert band["aaiP95"] == pytest.approx(1.4 * band["aaiMean"], rel=1e-6)
        assert len(band["distribution"]) == 25
        assert band["distribution"][0] == pytest.approx(band["aaiP5"])
        assert band["distribution"][-1] == pytest.approx(band["aaiP95"])
        assert band["sensitivity"] and band["sensitivityMethod"] == "sobol"
        assert band["presentAai"] is not None


def test_cost_benefit_run_with_default_measures(_session_dir: Path) -> None:
    sid = _seed()
    done = _run_to_done(sid, {"kind": "cost-benefit"})
    out = done["result"]
    assert out["kind"] == "cost-benefit"
    assert out["peril"] == "tropical_cyclone"  # portfolio scenario default
    assert out["totClimateRisk"] > 0
    assert len(out["measures"]) == 4  # the default measure set
    for m in out["measures"]:
        assert m["cost"] > 0
        assert 0 <= m["benefit"] <= out["totClimateRisk"]
        assert m["benefitCostRatio"] == pytest.approx(m["benefit"] / m["cost"], rel=1e-2)


def test_cost_benefit_run_with_explicit_measures(_session_dir: Path) -> None:
    sid = _seed()
    done = _run_to_done(
        sid,
        {
            "kind": "cost-benefit",
            "peril": "river_flood",
            "discountRate": 0.0,
            "measures": [{"name": "Sea wall", "cost": 1_000.0, "damageReduction": 0.5}],
        },
    )
    out = done["result"]
    assert out["peril"] == "river_flood"
    assert len(out["measures"]) == 1
    m = out["measures"][0]
    assert m["name"] == "Sea wall"
    assert m["benefit"] == pytest.approx(0.5 * out["totClimateRisk"], abs=0.02)


def test_supply_chain_run_sector_table(_session_dir: Path) -> None:
    sid = _seed()
    done = _run_to_done(sid, {"kind": "supply-chain", "perils": ["tropical_cyclone"]})
    out = done["result"]
    assert out["kind"] == "supply-chain"
    assert out["mriot"] == "WIOD16 2010"
    # All seeded assets are utilities-sector, so the direct loss lands there.
    assert [s["sector"] for s in out["bySector"]] == ["utilities"]
    assert out["totalDirect"] == pytest.approx(_TC_AAI_TOTAL)
    assert out["totalIndirect"] == pytest.approx(sum(s["indirect"] for s in out["bySector"]))
    assert out["amplification"] == pytest.approx(out["totalIndirect"] / out["totalDirect"], rel=1e-3)


def test_calibration_run_shape(_session_dir: Path) -> None:
    sid = _seed()
    done = _run_to_done(sid, {"kind": "calibration"})
    out = done["result"]
    assert out["kind"] == "calibration"
    assert out["param"] == "v_half"
    assert out["initial"] == pytest.approx(74.7)
    # Synthetic observed loss = 90% of modelled -> calibrated v_half moves up.
    assert out["calibrated"] > out["initial"]
    assert out["observedAnnualLoss"] == pytest.approx(0.9 * _TC_AAI_TOTAL, rel=1e-3)


def test_forecast_run_series_and_per_asset(_session_dir: Path) -> None:
    sid = _seed()
    done = _run_to_done(sid, {"kind": "forecast"})
    out = done["result"]
    assert out["kind"] == "forecast"
    assert out["nTracks"] > 0
    assert len(out["perAsset"]) == 2  # every asset covered
    assert out["totalImpact"] == pytest.approx(0.5 * _TC_AAI_TOTAL, rel=1e-3)
    assert len(out["series"]) == 5
    assert sum(p["value"] for p in out["series"]) == pytest.approx(out["totalImpact"], abs=0.1)
    assert all(p["label"] for p in out["series"])


def test_unknown_run_kind_is_400(_session_dir: Path) -> None:
    sid = _seed()
    resp = client.post(f"/api/physical-risk/session/{sid}/run", json={"kind": "litpop"})
    assert resp.status_code == 400


# ── report ─────────────────────────────────────────────────────────────────────


def test_report_bundles_latest_results_per_kind(_session_dir: Path) -> None:
    sid = _seed()
    _set_profile(sid, {"capex": 1_000_000.0, "annualEbitda": 200_000.0})
    _run_to_done(sid, {"perils": ["tropical_cyclone"]})
    _run_to_done(sid, {"kind": "forecast"})

    resp = client.get(f"/api/physical-risk/session/{sid}/report")
    assert resp.status_code == 200, resp.text
    rep = resp.json()

    assert rep["sessionId"] == sid
    assert rep["generatedAt"]
    assert rep["summary"]["assetCount"] == 2
    assert rep["summary"]["totalValue"] == pytest.approx(320_000.0 + 100_000_000.0)
    assert rep["portfolio"]["sessionId"] == sid

    results = rep["results"]
    assert set(results) == {
        "physical",
        "uncertainty",
        "costBenefit",
        "supplyChain",
        "calibration",
        "forecast",
    }
    assert results["physical"] is not None and results["physical"]["kind"] == "physical"
    assert results["forecast"] is not None and results["forecast"]["kind"] == "forecast"
    assert results["uncertainty"] is None  # never run in this session

    # Transition recomputed synchronously under the portfolio's NGFS scenario.
    assert rep["transition"]["scenario"] == "net_zero_2050"
    assert rep["transition"]["totalNpv"] > 0

    # Finance included because a CAPEX-bearing profile and a physical run exist.
    assert rep["finance"] is not None
    assert rep["finance"]["ratingMethod"] == "moodys_sp"
    assert rep["finance"]["portfolio"]["baseline"]["rating"] == "AAA"


def test_report_unknown_session_is_404(_session_dir: Path) -> None:
    resp = client.get("/api/physical-risk/session/does-not-exist/report")
    assert resp.status_code == 404
