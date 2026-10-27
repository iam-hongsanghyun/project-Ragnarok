"""MCP run-spec tools (WA3-WA6), end to end through the real client and the real API app.

The tools call :class:`RagnarokClient`, which here talks to ``backend.app.main.app`` over an
in-process ASGI transport (no server, no ports); only the session read and the queue insert
are stubbed. So a tool call exercises tool -> client -> router -> scenario_presets ->
``_resolve_payload_model`` -> ``_refuse_invalid_model`` for real.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from backend.app import main, model_store
from backend.mcp import server, tools_runspec
from backend.mcp.client import Config, RagnarokAPIError, RagnarokClient

SNAPS = [f"2030-01-01T{h:02d}:00:00" for h in range(24)]


def _scenario_row(sid: str, label: str, **payload: Any) -> dict[str, Any]:
    return {"id": sid, "label": label, "active": sid == "s-base", "notes": "", "json": json.dumps(payload)}


MODEL: dict[str, list[dict[str, Any]]] = {
    "buses": [{"name": "b"}],
    "carriers": [{"name": "coal"}],
    "snapshots": [{"snapshot": s} for s in SNAPS],
    "loads": [{"name": "L", "bus": "b", "p_set": 10.0}],
    "loads-p_set": [{"snapshot": s, "L": 10.0} for s in SNAPS],
    "generators": [{"name": "g", "bus": "b", "carrier": "coal", "p_nom": 50.0, "marginal_cost": 5.0}],
    "RAGNAROK_Scenarios": [
        _scenario_row("s-base", "Base case"),
        _scenario_row("s-carbon", "High carbon", carbonPrice=90, snapshotEnd=12),
        _scenario_row("s-dup", "High carbon", carbonPrice=120),
        _scenario_row(
            "s-typo", "Typo", constraints=[{"id": "c", "enabled": True, "label": "cap", "metric": "carrier_max_gen", "carrier": "coall", "value": 5}]
        ),
    ],
    "RAGNAROK_CarbonSchedules": [{"id": "ngfs", "name": "NGFS", "json": json.dumps([{"year": 2030, "price": 50}])}],
    "RAGNAROK_CustomDSL": [{"text": "gen(coal) <= 100"}],
}


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    queued: list[Any] = []

    def fake_enqueue(payload):
        queued.append(payload)
        item = SimpleNamespace(id=f"job{len(queued)}", status="queued")
        return item, len(queued)

    monkeypatch.setattr(model_store, "load_full_model", lambda sid: MODEL)
    monkeypatch.setattr(main, "_enqueue_payload", fake_enqueue)
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "auto")
    client = RagnarokClient(
        Config(api_base="http://test", session_id="s", timeout=30),
        transport=httpx.ASGITransport(app=main.app),
    )
    monkeypatch.setattr(server, "_client", client)
    return queued


def _run(coro):
    return asyncio.run(coro)


def test_describe_run_options_returns_the_reference_and_capabilities(wired) -> None:
    out = _run(server.describe_run_options())
    keys = {row["key"] for row in out["reference"]["index"]}
    assert {"options.pathwayConfig", "options.essConfig", "options.marketSimConfig", "scenario.customDsl"} <= keys
    assert "capabilities" in out
    ess = _run(server.describe_run_options(key="options.essConfig"))
    assert "capabilities" not in ess and any(f["path"].endswith("lifetimeYears") for f in ess["reference"]["fields"])


def test_describe_run_options_unknown_key_is_an_actionable_error(wired) -> None:
    with pytest.raises(RagnarokAPIError) as exc:
        _run(server.describe_run_options(key="options.nope"))
    assert "unknown run-option key" in exc.value.detail and "essConfig" in exc.value.detail


def test_list_scenarios(wired) -> None:
    out = _run(tools_runspec.list_scenarios())
    assert [s["id"] for s in out["scenarios"]] == ["s-base", "s-carbon", "s-dup", "s-typo"]
    assert out["activeScenarioId"] == "s-base"
    assert out["carbonSchedules"] == [{"id": "ngfs", "name": "NGFS", "years": [2030]}]
    assert out["dsl"]["lineCount"] == 1 and out["dsl"]["errors"] == [] and out["dsl"]["generatorCarriers"] == ["coal"]


def test_describe_scenario_shows_the_exact_run_body(wired) -> None:
    out = _run(tools_runspec.describe_scenario("s-carbon", carbon_schedule_id="ngfs"))
    assert out["scenario"]["carbonPrice"] == 90
    body = out["runBody"]
    assert body["options"]["snapshotCount"] == 12 and body["options"]["carbonPriceSchedule"] == [{"year": 2030, "price": 50}]
    assert body["scenario"]["constraintSpecs"][0]["lhs"][0]["carrier"] == "coal"


def test_describe_scenario_unknown_id_names_the_saved_ones(wired) -> None:
    with pytest.raises(RagnarokAPIError) as exc:
        _run(tools_runspec.describe_scenario("nope"))
    assert exc.value.status == 404 and "s-base" in exc.value.detail


def test_submit_scenario_queues_the_resolved_body(wired) -> None:
    out = _run(tools_runspec.submit_scenario("s-carbon", wait=False))
    assert out["status"] == "submitted" and out["jobId"] == "job1" and out["scenarioId"] == "s-carbon"
    payload = wired[0]
    assert payload.sessionId == "s" and payload.options["scenarioLabel"] == "High carbon"
    assert payload.scenario["carbonPrice"] == 90 and payload.scenario["constraintSpecs"]


def test_submit_scenario_is_refused_by_the_guard_for_an_unresolved_carrier(wired) -> None:
    with pytest.raises(RagnarokAPIError) as exc:
        _run(tools_runspec.submit_scenario("s-typo", wait=False))
    assert "coall" in exc.value.detail and "Fix the carrier" in exc.value.detail
    assert wired == []


def test_submit_scenario_previews_under_guided_autonomy(wired, monkeypatch) -> None:
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "guided")
    out = _run(tools_runspec.submit_scenario("s-base", wait=False))
    assert out["status"] == "preview" and wired == []


def test_submit_scenarios_batch_gives_distinct_run_labels(wired) -> None:
    out = _run(tools_runspec.submit_scenarios(["s-base", "s-carbon", "s-dup"]))
    assert out["status"] == "submitted" and out["queued"] == 3
    assert [j["runLabel"] for j in out["jobs"]] == ["Base case", "High carbon", "High carbon #2"]
    assert [p.options["runLabel"] for p in wired] == ["Base case", "High carbon", "High carbon #2"]
    assert [p.options["scenarioLabel"] for p in wired] == ["Base case", "High carbon", "High carbon"]


def test_submit_scenarios_checks_everything_before_queueing_anything(wired) -> None:
    # a scenario the guards would refuse at submit time stops the whole batch...
    with pytest.raises(ValueError, match=r'nothing was queued.*"s-typo".*coall'):
        _run(tools_runspec.submit_scenarios(["s-base", "s-typo"]))
    assert wired == []
    # ...and so does an unknown id.
    with pytest.raises(ValueError, match=r"unknown scenario id\(s\) nope; saved scenarios"):
        _run(tools_runspec.submit_scenarios(["s-base", "nope"]))
    assert wired == []


def test_validate_model_preflight_reports_the_guard_problems(wired, monkeypatch) -> None:
    out = _run(server.validate_model())
    assert out["valid"] is True  # the sheet DSL parses, no scenario-level problems
    bad = json.loads(json.dumps(MODEL))
    bad["RAGNAROK_CustomDSL"] = [{"text": "gen(coal) 100"}]
    monkeypatch.setattr(model_store, "load_full_model", lambda sid: bad)
    out = _run(server.validate_model())
    assert out["valid"] is False and any("syntax errors" in e for e in out["errors"])


def test_submit_scenarios_with_no_ids_runs_all_saved(wired) -> None:
    with pytest.raises(ValueError, match='"s-typo"'):
        _run(tools_runspec.submit_scenarios(None))  # one bad scenario in the set: none queued
    assert wired == []


def test_distinct_run_labels_match_the_ui_rule() -> None:
    assert tools_runspec.distinct_run_labels(["a", "b", "a", "a"]) == ["a", "b", "a #2", "a #3"]


def test_tool_surface_flags() -> None:
    tools = {t.name: t for t in _run(server.mcp.list_tools())}
    for name in ("describe_run_options", "list_scenarios", "describe_scenario"):
        assert tools[name].annotations.readOnlyHint is True, name
    for name in ("submit_scenario", "submit_scenarios"):
        assert tools[name].annotations.readOnlyHint is False, name
    schema = tools["submit_scenarios"].inputSchema["properties"]
    assert {"scenario_ids", "carbon_schedule_id", "options_patch", "solver_options", "wait", "timeout_s", "confirm"} <= set(schema)
