"""MCP coverage: every HTTP operation, run option, module and study is reachable by an agent, or excluded here with a reason.

Four maps, each failing when a feature is added without a way for an agent to reach it:

1. **Operations.** Every ``/api`` operation in ``app.openapi()`` is reached by at least one MCP tool (static resolution in
   ``_mcp_reach.py``: client methods, helper functions, f-string paths) or listed in ``EXCLUDED`` with a one-line reason. A
   path built from a tool parameter (``/api/export/{fmt}``) is pinned in ``PARAMETERISED`` and re-checked by really calling the
   tools through a recording transport.
2. **Run options.** Every key registered in ``run_options_reference`` is served by ``describe_run_options`` (the tool reads
   ``GET /api/run-options``): the index lists its top-level key and a key lookup returns every field.
3. **Modules.** Every ``backend/app/<module>/hooks.py`` is in ``MODULES`` with the tools that write its inputs and read its
   preview / results; every study hook's payload key is in ``tools_studies.STUDIES``.
4. **Server-side input checks of the fuel-costs write tools** live in ``test_fuel_costs_edit.py``.

``-s`` prints the coverage numbers.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.app import module_hooks as mh
from backend.app import run_options_reference as ref
from backend.app.main import app
from backend.mcp import server, tools_studies
from backend.mcp.client import Config, RagnarokClient
from backend.mcp.server import mcp
from backend.tests import _mcp_reach as reach

Op = tuple[str, str]

#: Operations no tool wraps, each with the reason. Keep it short and honest: a reason is "the agent cannot use this", never
#: "not done yet". docs/bifrost-agent.md names the same set (one fact, linked from there).
EXCLUDED: dict[Op, str] = {
    ("GET", "/api/events"): "server-sent event stream for the browser's live updates; an MCP call is request / response (poll get_queue)",
    ("GET", "/api/exports/{job_id}"): "status poll of the browser's async export job; export_run returns the same bytes synchronously",
    ("POST", "/api/exports"): "starts the browser's async export job; export_run covers xlsx and package",
    ("GET", "/api/exports/{job_id}/download"): "download leg of the async export job (bytes to a browser tab); export_run writes the file",
    ("GET", "/api/import/boundaries/countries.geojson"): "country outline asset for the map tab; an agent reads countries with list_import_countries",
    ("GET", "/api/optimise/export-lp/file"): "the browser's Download of a file export_lp already wrote (its result gives the path)",
    ("GET", "/api/runs/{name}"): "the whole stored bundle (model + every output series), unbounded; get_analytics, get_run_series, get_study_result and export_run read it in parts",
    ("DELETE", "/api/log"): "empties the server's log buffer shown in the UI; get_server_log reads it and nothing needs it cleared",
    ("DELETE", "/api/session/journal"): "purges the journal that records the agent's own edits; an agent must not erase its audit trail (undo_journal_entry, revert_session cover recovery)",
    ("POST", "/api/session/migration/ack"): "dismisses the cost-basis migration banner for the human; the notice itself is in get_world_state",
    ("POST", "/api/session/model/static"): "the browser's thin-client sync of its static sheets before a run; tools edit through edit_sheet / save_model",
}

#: Operations reached through a path built from a tool parameter. The static map cannot name them, so they are listed with
#: the tool that takes the parameter, and ``test_parameterised_paths_are_really_hit`` calls those tools.
PARAMETERISED: dict[Op, str] = {
    ("POST", "/api/export/netcdf"): "export_model(format='netcdf')",
    ("POST", "/api/export/hdf5"): "export_model(format='hdf5')",
    ("POST", "/api/export/pypsa-excel"): "export_pypsa_native(kind='excel')",
    ("POST", "/api/export/pypsa-csv"): "export_pypsa_native(kind='csv')",
    ("POST", "/api/import/netcdf"): "import_network(path='x.nc')",
    ("POST", "/api/import/hdf5"): "import_network(path='x.h5')",
    ("POST", "/api/import/pypsa-excel"): "import_pypsa_native(kind='pypsa-excel')",
    ("POST", "/api/import/pypsa-csv"): "import_pypsa_native(kind='pypsa-csv')",
    ("POST", "/api/import/matpower"): "import_pypsa_native(kind='matpower')",
    ("POST", "/api/import/pandapower"): "import_pypsa_native(kind='pandapower')",
}

#: backend module package -> tools that write its inputs, and tools that read its preview / results.
MODULES: dict[str, dict[str, tuple[str, ...]]] = {
    "adequacy": {"inputs": ("submit_solve",), "reads": ("get_study_result", "describe_studies", "describe_analytics")},
    "annual_budgets": {"inputs": ("set_annual_budget", "apply_annual_budgets"), "reads": ("get_annual_budgets",)},
    "carbon_pricing": {"inputs": ("set_carbon_price", "save_scenario"), "reads": ("get_carbon_price",)},
    "company": {"inputs": ("submit_solve", "edit_sheet"), "reads": ("compare_companies", "get_study_result", "get_run_analysis")},
    "constraints": {"inputs": ("set_custom_dsl", "save_scenario", "edit_sheet"), "reads": ("list_scenarios", "describe_scenario")},
    "demand_response": {"inputs": ("apply_demand_response",), "reads": ("get_demand_response", "get_study_result")},
    "emissions": {"inputs": ("submit_solve",), "reads": ("get_study_result", "get_kpis")},
    "fuel_costs": {"inputs": ("set_fuel_price", "set_vom", "set_fuel_price_scenario"), "reads": ("get_fuel_inputs", "get_fuel_costs", "get_study_result")},
    "market_studies": {"inputs": ("submit_solve",), "reads": ("get_study_result", "describe_studies", "optimize_procurement")},
    "model_check": {"inputs": ("fill_discount_rate", "clean_placeholder_bounds"), "reads": ("check_model", "validate_model")},
    "p2x": {"inputs": ("build_p2x_chain", "set_rfnbo_config"), "reads": ("preview_p2x_chain", "check_rfnbo", "get_p2x_results")},
    "physical_risk": {"inputs": ("physical_risk_seed", "physical_risk_set_scenario", "physical_risk_run"), "reads": ("physical_risk_report",)},
    "plants": {"inputs": ("add_plant", "edit_plant", "remove_plant"), "reads": ("list_plants", "get_plant_results")},
    "reserves": {"inputs": ("submit_solve",), "reads": ("get_study_result",)},
    "scenario_overrides": {"inputs": ("save_scenario", "submit_scenario"), "reads": ("describe_scenario",)},
    "stochastic": {"inputs": ("submit_solve", "set_fuel_price_scenario"), "reads": ("get_study_result",)},
}

_APP = Path(reach.MCP_DIR).parent / "app"


def _tool_names() -> set[str]:
    return {t.name for t in mcp._tool_manager.list_tools()}


def _operations() -> set[Op]:
    out: set[Op] = set()
    for path, item in app.openapi()["paths"].items():
        if path.startswith("/api"):
            out |= {(m.upper(), path) for m in item if m in ("get", "post", "put", "patch", "delete")}
    return out


# ── 1. operations ──────────────────────────────────────────────────────────────────────────────────
def test_every_api_operation_is_reached_by_a_tool_or_excluded_with_a_reason(capsys: pytest.CaptureFixture[str]) -> None:
    ops = _operations()
    reach_map, _templates, unresolved = reach.analyse()
    assert not unresolved, f"request paths the analysis cannot resolve (use a literal or an f-string): {unresolved}"
    exact, loose = reach.match(reach_map, ops)
    uncovered = sorted(ops - set(exact) - set(loose) - set(EXCLUDED))
    assert not uncovered, (
        "HTTP operations no MCP tool reaches. Add a tool (or a parameter on an existing one) in backend/mcp, "
        f"or an EXCLUDED entry with the reason an agent cannot use it: {uncovered}"
    )
    with capsys.disabled():
        print(
            f"\nMCP coverage: {len(ops)} /api operations; {len(exact)} reached by a literal path, {len(PARAMETERISED)} through a "
            f"parameterised path, {len(EXCLUDED)} excluded with a reason, {len(uncovered)} uncovered; "
            f"{len({t for v in reach_map.values() for t in v})} of {len(_tool_names())} tools make HTTP calls"
        )


def test_exclusions_are_honest() -> None:
    ops = _operations()
    reach_map, _t, _u = reach.analyse()
    exact, loose = reach.match(reach_map, ops)
    stale = sorted(set(EXCLUDED) - ops)
    assert not stale, f"EXCLUDED names operations that no longer exist: {stale}"
    reached = sorted(set(EXCLUDED) & (set(exact) | set(loose)))
    assert not reached, f"EXCLUDED operations that a tool now reaches (delete the exclusion): {reached}"
    assert all(len(reason) > 25 for reason in EXCLUDED.values())
    assert len(EXCLUDED) <= 12, "keep the exclusion table short: wrap the operation instead"


def test_parameterised_table_matches_the_static_map() -> None:
    ops = _operations()
    reach_map, _t, _u = reach.analyse()
    exact, loose = reach.match(reach_map, ops)
    only_loose = {op for op in loose if op not in exact}
    assert only_loose == set(PARAMETERISED), (
        f"operations reached only through a parameterised path must be pinned in PARAMETERISED and exercised below: "
        f"missing {sorted(only_loose - set(PARAMETERISED))}, stale {sorted(set(PARAMETERISED) - only_loose)}"
    )


def _recording_client(calls: list[Op]) -> RagnarokClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"model": {}, "status": "ok", "sheets": {}}, headers={"content-disposition": 'attachment; filename="x.bin"'})

    return RagnarokClient(Config("http://test", "t", 5.0), transport=httpx.MockTransport(handler))


def test_parameterised_paths_are_really_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Instrumented run: call the real tools with every allowed value and record the HTTP paths they send."""
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "auto")
    calls: list[Op] = []
    monkeypatch.setattr(server, "_client", _recording_client(calls))
    from backend.mcp import tools_components

    async def go() -> None:
        for fmt in ("netcdf", "hdf5"):
            await server.export_model(format=fmt, dest=str(tmp_path / f"m.{fmt}"))
        for kind in ("excel", "csv"):
            await tools_components.export_pypsa_native(kind=kind, dest=str(tmp_path / f"p.{kind}"))
        for suffix in (".nc", ".h5"):
            f = tmp_path / f"in{suffix}"
            f.write_bytes(b"x")
            await server.import_network(path=str(f), confirm=True)
        for kind, suffix in (("pypsa-excel", ".xlsx"), ("pypsa-csv", ".zip"), ("matpower", ".m"), ("pandapower", ".json")):
            f = tmp_path / f"in{suffix}"
            f.write_bytes(b"x")
            await tools_components.import_pypsa_native(path=str(f), kind=kind, confirm=True)

    asyncio.run(go())
    hit = set(calls)
    missing = sorted(set(PARAMETERISED) - hit)
    assert not missing, f"tools did not send {missing}; sent {sorted(hit)}"
    asyncio.run(server._client.aclose())  # type: ignore[union-attr]


def test_reach_map_names_the_new_tools() -> None:
    reach_map, _t, _u = reach.analyse()
    wants = {
        ("POST", "/api/fuel-costs/price/set"): "set_fuel_price", ("POST", "/api/fuel-costs/price/remove"): "set_fuel_price",
        ("POST", "/api/fuel-costs/vom/set"): "set_vom", ("POST", "/api/fuel-costs/vom/remove"): "set_vom",
        ("POST", "/api/fuel-costs/scenario-price/set"): "set_fuel_price_scenario",
        ("POST", "/api/fuel-costs/scenario-price/remove"): "set_fuel_price_scenario",
        ("GET", "/api/fuel-costs/inputs"): "get_fuel_inputs", ("GET", "/api/build/plants"): "list_plants",
        ("GET", "/api/runs/{}/annual-budgets"): "get_annual_budgets", ("GET", "/api/runs/{}/derived"): "get_run_totals",
        ("PUT", "/api/p2x/rfnbo/config"): "set_rfnbo_config", ("POST", "/api/p2x/rfnbo/checks"): "check_rfnbo",
        ("POST", "/api/forge/fill-discount-rate"): "fill_discount_rate",
    }
    for op, tool in wants.items():
        assert tool in reach_map.get(op, set()), (op, sorted(reach_map.get(op, set())))


# ── 2. run options ─────────────────────────────────────────────────────────────────────────────────
def test_every_registered_run_option_is_served_by_describe_run_options() -> None:
    index = ref.build_reference(None)["index"]
    keys = {row["key"] for row in index}
    entries = ref.all_entries()
    assert len(entries) > 250
    missing = []
    for e in entries:
        top = re.match(r"((?:scenario|options)\.[A-Za-z0-9_]+)", e.path)
        assert top, e.path
        if top.group(1) not in keys:
            missing.append(e.path)
        assert e.meaning.strip(), f"{e.path} has no meaning text"
    assert not missing, f"options absent from the describe_run_options index: {missing[:10]}"
    # a key lookup returns the option's own fields (the second call an agent makes)
    for key in sorted(keys):
        got = ref.build_reference(key)
        assert got["fields"] and got["fields"][0]["meaning"], key
    with pytest.raises(KeyError, match="unknown run-option key"):
        ref.build_reference("options.nope")


def test_module_run_options_are_documented_in_the_reference() -> None:
    known = ref.top_level_keys()["options"]
    for study in tools_studies.STUDIES:
        key = study["optionKey"]
        if key:
            assert key in known, f"study {study['id']} names options.{key}, which describe_run_options does not document"


def test_describe_run_options_tool_serves_the_reference() -> None:
    tool = next(t for t in mcp._tool_manager.list_tools() if t.name == "describe_run_options")
    assert tool.annotations.readOnlyHint is True and "key" in tool.parameters["properties"]


# ── 3. modules and studies ─────────────────────────────────────────────────────────────────────────
def test_every_module_with_hooks_has_tools_for_its_inputs_and_results() -> None:
    packages = {p.parent.name for p in _APP.glob("*/hooks.py")}
    assert packages == set(MODULES), f"MODULES out of step with backend/app/*/hooks.py: missing {sorted(packages - set(MODULES))}, stale {sorted(set(MODULES) - packages)}"
    names = _tool_names()
    for module, tools in MODULES.items():
        assert tools["inputs"] and tools["reads"], module
        for t in tools["inputs"] + tools["reads"]:
            assert t in names, f"{module}: tool {t} is not registered"


def test_every_study_hook_payload_key_is_readable_through_get_study_result() -> None:
    declared = set(mh.declared_payload_keys())
    listed = {k for s in tools_studies.STUDIES for k in s["resultKeys"]}
    assert declared <= listed, f"study payload keys with no entry in tools_studies.STUDIES: {sorted(declared - listed)}"
    hook_ids = {h["id"] for h in mh.registered().get("study", [])} | {h["id"] for h in mh.registered().get("post_solve", []) if h["payloadKeys"]}
    for s in tools_studies.STUDIES:
        if s["hook"] is not None:
            assert s["hook"] in hook_ids, f"STUDIES entry {s['id']} names hook {s['hook']!r}, which is not registered"
    assert len({s["id"] for s in tools_studies.STUDIES}) == len(tools_studies.STUDIES)


def test_get_study_result_reads_one_study_and_caps_long_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    class Fake:
        async def get_analytics(self, name: str) -> dict[str, Any]:
            return {"result": {"outageMc": {"lole": 3.2, "members": list(range(500))}, "adequacy": None}}

        async def get_run_period(self, name: str, period: int, **kw: Any) -> dict[str, Any]:
            assert kw["fields"] == "reserve"
            return {"result": {"reserve": {"price": 4.0}}}

    monkeypatch.setattr(server, "_client", Fake())
    got = asyncio.run(tools_studies.get_study_result("r", "outage-mc", max_rows=10))
    assert got["ran"] is True and len(got["result"]["outageMc"]["members"]) == 10 and got["result"]["outageMc"]["lole"] == 3.2
    assert "outageMc.members (500 items)" in got["truncated"] and "max_rows" in got["truncated"]
    assert asyncio.run(tools_studies.get_study_result("r", "adequacy"))["ran"] is False
    assert asyncio.run(tools_studies.get_study_result("r", "reserves", period=2))["result"] == {"reserve": {"price": 4.0}}
    bad = asyncio.run(tools_studies.get_study_result("r", "power"))
    assert bad["error"].startswith('unknown study "power"; valid: adequacy, reserves')
    assert "optionKey" in asyncio.run(tools_studies.describe_studies("elcc"))["studies"][0]


def test_the_operation_check_has_teeth() -> None:
    """A route no tool calls, a wrong method on a covered path and a longer path under a wildcard template are all reported."""
    reach_map, _t, _u = reach.analyse()
    fake = {("POST", "/api/nope/never"), ("DELETE", "/api/fuel-costs/inputs"), ("POST", "/api/export/hdf5/extra")}
    exact, loose = reach.match(reach_map, fake)
    assert not exact and not loose
