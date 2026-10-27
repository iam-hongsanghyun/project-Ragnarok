"""WA6: scenario presets, the carbon library and the DSL sheet resolved on the backend.

``fixtures/scenario_parity.json`` is the golden file shared with the browser's
``features/scenario/backendParity.test.ts``: this test proves the Python port equals it, the
jest test proves the TypeScript equals it, so the two cannot drift apart silently.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import main, model_store
from backend.app import scenario_presets as sp

FIXTURE = Path(__file__).parent / "fixtures" / "scenario_parity.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def _roundtrip(value: Any) -> Any:
    return json.loads(json.dumps(value))


@pytest.fixture(params=CASES, ids=[c["name"] for c in CASES])
def case(request: pytest.FixtureRequest) -> dict[str, Any]:
    return request.param


# ── golden parity with scenarios.ts / buildRunPayload.ts / carbonLibrary.ts / custom.ts ──


def test_catalog_equals_the_golden_file(case: dict[str, Any]) -> None:
    catalog = sp.read_scenario_catalog(case["model"])
    got = {"activeScenarioId": catalog["activeScenarioId"], "scenarios": catalog["scenarios"]}
    assert _roundtrip(got) == case["expected"]["catalog"]


def test_carbon_library_equals_the_golden_file(case: dict[str, Any]) -> None:
    assert _roundtrip(sp.read_carbon_library(case["model"])) == case["expected"]["carbon"]


def test_dsl_sheet_equals_the_golden_file(case: dict[str, Any]) -> None:
    text = sp.read_custom_dsl(case["model"])
    assert text == case["expected"]["dsl"]["text"]
    lines = sp.parse_constraint_dsl(text)
    assert _roundtrip(lines) == case["expected"]["dsl"]["lines"]
    assert _roundtrip(sp.dsl_to_specs(text)) == case["expected"]["dsl"]["specs"]
    assert sp.generator_carriers(case["model"]) == case["expected"]["generatorCarriers"]


def test_run_bodies_equal_the_golden_file(case: dict[str, Any]) -> None:
    catalog = sp.read_scenario_catalog(case["model"])
    specs = sp.dsl_to_specs(sp.read_custom_dsl(case["model"]))
    bodies = {
        s["id"]: sp.build_run_payload(s, {**sp.UI_RUN_DEFAULTS, **case["uiOptions"], "scenarioLabel": s["label"]}, specs)
        for s in catalog["scenarios"]
    }
    assert _roundtrip(bodies) == case["expected"]["runBodies"]


# ── what the browser silently does, made visible ─────────────────────────────


def test_rows_the_browser_drops_are_reported_with_a_reason() -> None:
    model = CASES[0]["model"]
    catalog = sp.read_scenario_catalog(model)
    unreadable = {u["id"]: u["reason"] for u in catalog["unreadable"]}
    assert "scenario-broken" in unreadable and "scenario-noperiods" in unreadable
    assert any("no string id" in r for r in unreadable.values())
    assert [s["id"] for s in catalog["scenarios"]] == ["scenario-base", "scenario-rich", "scenario-legacy"]


def test_active_row_wins_else_the_first_scenario() -> None:
    model = {"RAGNAROK_Scenarios": [{"id": "a", "label": "A", "json": "{}"}, {"id": "b", "label": "B", "json": "{}"}]}
    assert sp.read_scenario_catalog(model)["activeScenarioId"] == "a"
    model["RAGNAROK_Scenarios"][1]["active"] = True
    assert sp.read_scenario_catalog(model)["activeScenarioId"] == "b"
    assert sp.read_scenario_catalog({})["scenarios"] == []


def test_legacy_owner_column_and_label_trim() -> None:
    by_id = {s["id"]: s for s in sp.read_scenario_catalog(CASES[0]["model"])["scenarios"]}
    assert by_id["scenario-legacy"]["ownerColumn"] == "company"
    assert by_id["scenario-rich"]["label"] == "Rich"
    assert by_id["scenario-base"]["ownerColumn"] == "owner"


def test_normalisers_clamp_like_the_ui() -> None:
    rolling = sp.normalize_rolling_config({"enabled": True, "horizonSnapshots": 10, "overlapSnapshots": 50})
    assert (rolling["horizonSnapshots"], rolling["overlapSnapshots"], rolling["stepSnapshots"]) == (10, 9, 1)
    sampling = sp.normalize_sampling_config({"enabled": True, "mode": "x", "blockSize": 0, "blockCount": "7", "gapSnapshots": -1})
    assert sampling == {"enabled": True, "mode": "count", "blockSize": 168, "blockCount": 7, "gapSnapshots": 0}
    assert sp.get_default_selected_period({"periods": [{"period": 2030}, {"period": 2035}], "selectedPeriod": 2040}) == 2030
    assert sp.get_default_selected_period({"periods": []}) is None


# ── resolve_scenario_run ─────────────────────────────────────────────────────


def _model_with_valid_dsl() -> dict[str, Any]:
    model = json.loads(json.dumps(CASES[0]["model"]))
    model["RAGNAROK_CustomDSL"] = [{"text": "gen(coal) <= 1000\n# note\ncap(solar & wind) >= 500"}]
    return model


def test_resolve_builds_the_batch_runner_body() -> None:
    body = sp.resolve_scenario_run(_model_with_valid_dsl(), "scenario-rich", ui_options={"filename": "x.xlsx"}, run_label="Rich #2")
    assert body["scenario"]["constraints"] == [c for c in body["scenario"]["constraints"] if c["enabled"]]
    assert len(body["scenario"]["constraints"]) == 1  # the disabled row is not sent
    assert len(body["scenario"]["constraintSpecs"]) == 2
    opts = body["options"]
    assert opts["snapshotCount"] == 48 and opts["scenarioLabel"] == "Rich" and opts["runLabel"] == "Rich #2"
    assert opts["filename"] == "x.xlsx" and opts["solverType"] == "auto" and opts["objectiveAutoScale"] is True
    assert opts["pathwayConfig"]["selectedPeriod"] == 2030
    assert opts["essConfig"]["capitalCostPerMWh"] == 9000
    assert opts["modelOverrides"] == [{"sheet": "generators", "name": "g1", "column": "p_nom", "value": 500}, {"sheet": "generators", "name": "g2", "column": "p_nom"}]
    assert body["scenarioId"] == "scenario-rich"


def test_a_plain_scenario_carries_no_model_overrides_key() -> None:
    body = sp.resolve_scenario_run(_model_with_valid_dsl(), "scenario-base")
    assert "modelOverrides" not in body["options"]
    assert body["options"]["snapshotCount"] == 24 and body["options"]["loadSheddingCost"] == 1000


def test_carbon_schedule_profile_replaces_the_preset_schedule() -> None:
    body = sp.resolve_scenario_run(_model_with_valid_dsl(), "scenario-rich", carbon_schedule_id="carbon-a")
    assert body["options"]["carbonPriceSchedule"] == [{"year": 2030, "price": 60}, {"year": 2035, "price": 0}, {"year": 2040, "price": 120}]


def test_options_patch_and_unknown_ids_give_actionable_errors() -> None:
    model = _model_with_valid_dsl()
    patched = sp.resolve_scenario_run(model, "scenario-base", options_patch={"forceLp": True})
    assert patched["options"]["forceLp"] is True
    with pytest.raises(sp.ScenarioResolveError, match=r'unknown scenario "nope"; saved scenarios: "scenario-base" \(Base case\)'):
        sp.resolve_scenario_run(model, "nope")
    with pytest.raises(sp.ScenarioResolveError, match=r'unknown carbon schedule "zzz"; library: "carbon-a" \(NGFS\)'):
        sp.resolve_scenario_run(model, "scenario-base", carbon_schedule_id="zzz")


def test_a_broken_dsl_sheet_blocks_the_build() -> None:
    with pytest.raises(sp.ScenarioResolveError, match=r"line 7: missing comparator"):
        sp.resolve_scenario_run(CASES[0]["model"], "scenario-base")  # the fixture sheet has bad lines


def test_summary_row_lists_enabled_modes() -> None:
    by_id = {s["id"]: s for s in sp.read_scenario_catalog(CASES[0]["model"])["scenarios"]}
    row = sp.summarize_preset(by_id["scenario-rich"])
    assert {"pathwayConfig", "rollingConfig", "samplingConfig", "essConfig", "stochasticConfig"} <= set(row["enabledModes"])
    assert row["constraintsEnabled"] == 1 and row["modelOverrides"] == 2
    assert sp.summarize_preset(by_id["scenario-base"])["enabledModes"] == []


# ── the HTTP surface ─────────────────────────────────────────────────────────


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    model = _model_with_valid_dsl()
    monkeypatch.setattr(model_store, "load_full_model", lambda sid: model if sid == "s" else {})
    return TestClient(main.app)


def test_list_endpoint(api: TestClient) -> None:
    data = api.get("/api/scenarios", params={"session_id": "s"}).json()
    assert data["activeScenarioId"] == "scenario-rich"
    assert [s["id"] for s in data["scenarios"]] == ["scenario-base", "scenario-rich", "scenario-legacy"]
    assert {u["id"] for u in data["unreadable"]} >= {"scenario-broken"}


def test_get_carbon_dsl_and_one_scenario(api: TestClient) -> None:
    assert [p["id"] for p in api.get("/api/scenarios/carbon-schedules", params={"session_id": "s"}).json()["schedules"]] == ["carbon-a", "carbon-b"]
    dsl = api.get("/api/scenarios/dsl", params={"session_id": "s"}).json()
    assert dsl["errors"] == [] and len(dsl["lines"]) == 2 and "coal" in dsl["generatorCarriers"]
    got = api.get("/api/scenarios/scenario-rich", params={"session_id": "s"}).json()
    assert got["active"] is True and got["scenario"]["essConfig"]["lifetimeYears"] == 12
    missing = api.get("/api/scenarios/zzz", params={"session_id": "s"})
    assert missing.status_code == 404 and "scenario-base" in missing.json()["detail"]


def test_resolve_endpoint_and_its_errors(api: TestClient) -> None:
    ok = api.post("/api/scenarios/resolve", json={"sessionId": "s", "scenarioId": "scenario-base", "runLabel": "L"})
    assert ok.status_code == 200 and ok.json()["options"]["runLabel"] == "L"
    bad_patch = api.post("/api/scenarios/resolve", json={"sessionId": "s", "scenarioId": "scenario-base", "optionsPatch": {"forceLP": 1}})
    assert bad_patch.status_code == 400 and "valid options keys" in bad_patch.json()["detail"]
    bad_id = api.post("/api/scenarios/resolve", json={"sessionId": "s", "scenarioId": "zzz"})
    assert bad_id.status_code == 400 and "unknown scenario" in bad_id.json()["detail"]
    no_model = api.get("/api/scenarios", params={"session_id": "empty"})
    assert no_model.status_code == 400 and "No model loaded" in no_model.json()["detail"]


def test_run_options_endpoint(api: TestClient) -> None:
    index = api.get("/api/run-options").json()
    assert any(r["key"] == "options.essConfig" for r in index["index"])
    ess = api.get("/api/run-options", params={"key": "options.essConfig"}).json()
    assert any(f["path"].endswith("standingLoss") for f in ess["fields"])
    bad = api.get("/api/run-options", params={"key": "options.nope"})
    assert bad.status_code == 400 and "valid" in bad.json()["detail"]


def test_a_resolved_scenario_passes_the_run_guards(api: TestClient) -> None:
    """submit path: resolve -> _resolve_payload_model -> _refuse_invalid_model (no queue)."""
    from backend.app.models import RunPayload

    body = api.post("/api/scenarios/resolve", json={"sessionId": "s", "scenarioId": "scenario-base"}).json()
    model = _model_with_valid_dsl()
    model["snapshots"] = [{"snapshot": f"2030-01-01T{h:02d}:00:00"} for h in range(24)]
    model["buses"] = [{"name": "b"}]
    model["loads"] = [{"name": "L", "bus": "b", "p_set": 10}]
    model["generators"] = [{"name": "g", "bus": "b", "carrier": "coal", "p_nom": 50, "marginal_cost": 1}]
    resolved = main._resolve_payload_model(RunPayload(model=model, scenario=body["scenario"], options=body["options"]))
    main._refuse_invalid_model(resolved)
