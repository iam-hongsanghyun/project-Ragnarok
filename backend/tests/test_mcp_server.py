"""Tests for the Bifrost MCP server (backend/mcp).

No running backend needed: the shared :class:`RagnarokClient` is replaced with a
recording fake, and the ``@mcp.tool``-decorated functions (still plain
coroutines) are called directly. Mirrors the repo's ``asyncio.run`` style
(see ``test_run_queue.py``) rather than depending on pytest-asyncio.
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.mcp import server
from backend.mcp.server import mcp


class FakeClient:
    """Records calls; returns minimal shapes matching the real API responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    async def get_meta(self) -> dict:
        self.calls.append(("get_meta",))
        return {"buses": 3, "carriers": ["wind", "solar"], "snapshots": 24}

    async def patch_sheet(self, name: str, ops: list[dict]) -> dict:
        self.calls.append(("patch_sheet", name, ops))
        return {"rows": 3}

    async def import_dataset(
        self, country_iso: str, dataset_ids: list[str], filters: dict | None = None
    ) -> dict:
        self.calls.append(("import_dataset", country_iso, dataset_ids))
        return {
            "fragment": {"sheets": {"buses": [{"name": "b1"}]}},
            "source_id": "osm",
            "dataset_ids": dataset_ids,
            "country_iso": country_iso,
            "preview": {},
        }

    async def merge_sheets(self, sheets: dict) -> dict:
        self.calls.append(("merge_sheets", sorted(sheets)))
        return {}

    async def submit_solve(self, scenario=None, options=None) -> dict:
        self.calls.append(("submit_solve", scenario, options))
        return {"id": "job1", "status": "queued"}

    async def add_row(self, sheet: str, values: dict) -> dict:
        self.calls.append(("add_row", sheet, values))
        return {"rows": 1}

    async def resolve_sheet(self, component: str) -> str:
        self.calls.append(("resolve_sheet", component))
        return {"Generator": "generators", "Link": "links"}.get(
            component, component.lower()
        )

    async def set_component(self, sheet: str, name: str, attributes: dict) -> dict:
        self.calls.append(("set_component", sheet, name, attributes))
        return {"rows": 1}

    async def delete_components(self, sheet: str, names: list) -> dict:
        self.calls.append(("delete_components", sheet, names))
        return {"deleted": len(names)}

    # ── coverage-audit tool expansion ─────────────────────────────────────────
    async def validate_case(self) -> dict:
        self.calls.append(("validate_case",))
        return {"ok": True, "issues": []}

    async def get_run_series(self, name, sheet, start=0, end=None, columns=None, max_points=None, agg="mean") -> dict:
        self.calls.append(("get_run_series", name, sheet, columns, max_points))
        return {"columns": ["gen1"], "rows": [[1.0]], "indexCol": "snapshot"}

    async def get_series_window(self, name, start=0, end=None, columns=None, max_points=None, agg="mean") -> dict:
        self.calls.append(("get_series_window", name, columns, max_points))
        return {"columns": ["load1"], "rows": [[10.0]]}

    async def get_sheet_stats(self, name, columns=None) -> dict:
        self.calls.append(("get_sheet_stats", name, columns))
        return {"columns": {"p_nom": {"mean": 100.0}}}

    async def get_journal(self, limit=50, before=None) -> dict:
        self.calls.append(("get_journal", limit, before))
        return {"version": 3, "entries": [{"id": 3, "kind": "patch"}]}

    async def get_journal_diff(self, entry_id) -> dict:
        self.calls.append(("get_journal_diff", entry_id))
        return {"id": entry_id, "detail": {}}

    async def undo_journal_entry(self, entry_id) -> dict:
        self.calls.append(("undo_journal_entry", entry_id))
        return {"undone": entry_id}

    async def revert_session(self, to_version) -> dict:
        self.calls.append(("revert_session", to_version))
        return {"undone": [4, 3]}

    async def get_master_meta(self) -> dict:
        self.calls.append(("get_master_meta",))
        return {"years": [2030, 2040]}

    async def derive_from_master(self, years=None, filters=None, mode="deactivate") -> dict:
        self.calls.append(("derive_from_master", years, mode))
        return {"meta": {}, "report": {}}

    async def run_plugin_analyze(self, plugin_id, config=None, result=None, runs=None) -> dict:
        self.calls.append(("run_plugin_analyze", plugin_id, runs))
        return {"data": {}}

    async def run_plugin_transform(self, plugin_id, config=None) -> dict:
        self.calls.append(("run_plugin_transform", plugin_id))
        return {"buses": 3}

    async def run_plugin_contribute(self, plugin_id, config=None) -> dict:
        self.calls.append(("run_plugin_contribute", plugin_id))
        return {"buses": 3}

    async def optimize_procurement(self, req) -> dict:
        self.calls.append(("optimize_procurement", req))
        return {"mix": {}, "frontier": []}

    async def forge_query(self, apply, req) -> dict:
        self.calls.append(("forge_query", apply, req.get("target")))
        return {"matched": 5, "changed": 5} if apply else {"matched": 5, "sample": [], "warnings": []}

    async def promote_run(self, name) -> dict:
        self.calls.append(("promote_run", name))
        return {"buses": 3}

    async def rename_run(self, name, new_name) -> dict:
        self.calls.append(("rename_run", name, new_name))
        return {"name": new_name}

    async def delete_run(self, name) -> dict:
        self.calls.append(("delete_run", name))
        return {"deleted": True}

    async def cancel_queue_item(self, item_id) -> dict:
        self.calls.append(("cancel_queue_item", item_id))
        return {"id": item_id, "status": "cancelled"}

    async def rerun_queue_item(self, item_id) -> dict:
        self.calls.append(("rerun_queue_item", item_id))
        return {"id": item_id, "status": "queued"}

    async def delete_queue_item(self, item_id) -> dict:
        self.calls.append(("delete_queue_item", item_id))
        return {"deleted": True}

    async def set_queue_concurrency(self, value) -> dict:
        self.calls.append(("set_queue_concurrency", value))
        return {"concurrency": value}

    # ── file export / import (workbook I/O) ────────────────────────────────────
    async def download_run(self, name, *, kind, parts=None) -> tuple[bytes, str]:
        self.calls.append(("download_run", name, kind, parts))
        return b"PK\x03\x04run-bytes", f"{name}.{'zip' if kind == 'package' else 'xlsx'}"

    async def export_model_file(
        self, fmt, *, result=None, scenario=None, options=None
    ) -> tuple[bytes, str | None]:
        self.calls.append(("export_model_file", fmt, result, scenario, options))
        return b"\x89model-bytes", None

    async def import_network_file(self, fmt, data, filename) -> dict:
        self.calls.append(("import_network_file", fmt, filename, len(data)))
        return {"buses": [{"name": "b1"}], "generators": [{"name": "g1"}]}

    async def import_project_file(self, data, filename, *, persist) -> dict:
        self.calls.append(("import_project_file", filename, persist))
        if persist:
            return {"name": "imported_run", "meta": {"name": "imported_run"}}
        return {"model": {"buses": [{"name": "b1"}]}, "filename": filename}

    async def save_model(self, model) -> dict:
        self.calls.append(("save_model", sorted(model)))
        return {}

    # ── parameter-gap fixes (audit round 2) ───────────────────────────────────
    async def transform_series(self, sheet, op, **params) -> dict:
        self.calls.append(("transform_series", sheet, op, params))
        return {"rows": 24}

    async def attach_renewable_profiles(self, **kw) -> dict:
        self.calls.append(("attach_renewable_profiles", kw))
        # The real endpoint returns a snapshot axis alongside the sheets.
        return {
            "sheets": {"generators-p_max_pu": [{"snapshot": "2019-01-01 00:00"}]},
            "snapshots": ["2019-01-01 00:00", "2019-01-01 01:00"],
            "attached": ["solar1"],
            "skipped": [],
            "sites": 1,
            "failedSites": 0,
        }

    async def attach_hydro_inflow(self, **kw) -> dict:
        self.calls.append(("attach_hydro_inflow", kw))
        return {
            "sheets": {"storage_units-inflow": [{"snapshot": "2019-01-01 00:00"}]},
            "snapshots": ["2019-01-01 00:00", "2019-01-01 01:00"],
            "attached": ["hydro1"],
            "skipped": [],
            "sites": 1,
            "failedSites": 0,
            "notes": [],
        }

    async def cluster_network(self, n_clusters, **kw) -> dict:
        self.calls.append(("cluster_network", n_clusters, kw))
        return {"model": {"buses": []}, "method": kw.get("method"), "before": 9, "after": 3}

    async def ev_reshape_demand(self, fleet_size, **kw) -> dict:
        self.calls.append(("ev_reshape_demand", fleet_size, kw))
        return {"rows": 24}

    async def driver_forecast(self, from_year, to_year, **kw) -> dict:
        self.calls.append(("driver_forecast", from_year, to_year, kw))
        return {"rows": 24}


def _install(monkeypatch, autonomy: str = "guided") -> FakeClient:
    fake = FakeClient()
    monkeypatch.setattr(server, "_client", fake)
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", autonomy)
    return fake


# ── catalog / annotations ──────────────────────────────────────────────────────
def test_tool_catalog_and_annotations() -> None:
    tools = asyncio.run(mcp.list_tools())
    by_name = {t.name: t for t in tools}
    assert len(tools) == 77, f"expected 77 tools, got {len(tools)}"
    # adjust_carrier_capacity is a gated (destructive) transform tool
    assert "adjust_carrier_capacity" in by_name
    assert by_name["adjust_carrier_capacity"].annotations.readOnlyHint is False
    assert by_name["adjust_carrier_capacity"].annotations.destructiveHint is True
    # low-level builder tools (pypsa-mcp-style) are present
    for t in (
        "add_bus",
        "add_generator",
        "add_load",
        "add_line",
        "add_storage",
        "set_snapshots",
    ):
        assert t in by_name, f"missing builder tool {t}"
        assert by_name[t].annotations.readOnlyHint is False

    # A read-only tool is annotated read-only...
    assert by_name["get_world_state"].annotations.readOnlyHint is True
    # ...and a live-network import is not read-only and is open-world.
    imp = by_name["import_dataset"].annotations
    assert imp.readOnlyHint is False
    assert imp.openWorldHint is True
    # A destructive replace is flagged destructive.
    assert by_name["one_click_model"].annotations.destructiveHint is True

    ro = {t.name for t in tools if t.annotations and t.annotations.readOnlyHint}
    assert ro == {
        "list_importers",
        "source_health",
        "get_world_state",
        "get_sheet_page",
        "derive_series",
        "list_runs",
        "get_analytics",
        "get_derived",
        "get_queue",
        "list_components",
        "describe_component",
        "describe_run_options",
        "list_plugins",
        "describe_analytics",
        "physical_risk_libraries",
        "physical_risk_get_portfolio",
        "physical_risk_get_run",
        "physical_risk_report",
        # Deep reads + pre-flight from the coverage-audit tool expansion.
        "validate_model",
        "get_sheet_stats",
        "get_series_window",
        "get_run_series",
        "get_journal",
        "get_journal_diff",
        "get_master_meta",
        "run_plugin_analysis",
        "optimize_procurement",
        # Tab-modules (a whole tab, not a plugin — docs/module.md). Only the
        # listing is read-only; install/enable/remove are gated writes.
        "list_tab_modules",
    }


def test_tab_module_tools_are_registered_and_gated() -> None:
    """A module adds a TAB, so the mutating tools must not be read-only, and
    uninstalling must be flagged destructive (it deletes the package)."""
    by_name = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name in ("list_tab_modules", "install_tab_module", "set_tab_module_enabled", "remove_tab_module"):
        assert name in by_name, f"missing tab-module tool {name}"
    assert by_name["list_tab_modules"].annotations.readOnlyHint is True
    assert by_name["install_tab_module"].annotations.readOnlyHint is False
    assert by_name["set_tab_module_enabled"].annotations.readOnlyHint is False
    assert by_name["remove_tab_module"].annotations.destructiveHint is True


# ── read-only tools return data ────────────────────────────────────────────────
def test_readonly_tool_returns_data(monkeypatch) -> None:
    _install(monkeypatch)
    out = asyncio.run(server.get_world_state())
    assert out["buses"] == 3 and out["carriers"] == ["wind", "solar"]


# ── guard: preview vs confirm on a non-cheap GATE tool ─────────────────────────
def test_gate_previews_without_confirm(monkeypatch) -> None:
    fake = _install(monkeypatch, "guided")
    out = asyncio.run(server.import_dataset(country_iso="KR", dataset_ids=["osm_grid"]))
    assert out["status"] == "preview"
    assert out["autonomy"] == "guided"
    assert not fake.called("import_dataset"), "preview must not hit the backend"
    assert not fake.called("merge_sheets")


def test_gate_executes_with_confirm(monkeypatch) -> None:
    fake = _install(monkeypatch, "guided")
    out = asyncio.run(
        server.import_dataset(country_iso="KR", dataset_ids=["osm_grid"], confirm=True)
    )
    assert out["status"] == "applied"
    assert out["source_id"] == "osm"
    assert fake.called("import_dataset") and fake.called("merge_sheets")


# ── guard: cheap edit runs under guided but is gated under manual ───────────────
def test_cheap_edit_runs_in_guided(monkeypatch) -> None:
    fake = _install(monkeypatch, "guided")
    ops = [{"op": "set", "row": 0, "column": "v_nom", "value": 380}]
    out = asyncio.run(server.edit_sheet(name="buses", ops=ops))
    assert out.get("status") != "preview"
    assert fake.called("patch_sheet")


def test_manual_gates_cheap_edit(monkeypatch) -> None:
    fake = _install(monkeypatch, "manual")
    ops = [{"op": "deleteRows", "rows": [1, 2]}]
    out = asyncio.run(server.edit_sheet(name="buses", ops=ops))
    assert out["status"] == "preview"
    assert not fake.called("patch_sheet")


# ── guard: auto runs everything without confirm ────────────────────────────────
def test_auto_skips_the_gate(monkeypatch) -> None:
    fake = _install(monkeypatch, "auto")
    out = asyncio.run(server.import_dataset(country_iso="KR", dataset_ids=["osm_grid"]))
    assert out["status"] == "applied"
    assert fake.called("import_dataset")


# ── solve is gated too (preview under guided without confirm) ───────────────────
def test_submit_solve_previews_without_confirm(monkeypatch) -> None:
    fake = _install(monkeypatch, "guided")
    out = asyncio.run(server.submit_solve(scenario={"carbonPrice": 50}))
    assert out["status"] == "preview"
    assert not fake.called("submit_solve")


# ── builder tools: cheap edits run under guided, drop None, keep extras ─────────
def test_add_generator_appends_row_under_guided(monkeypatch) -> None:
    fake = _install(monkeypatch, "guided")
    out = asyncio.run(
        server.add_generator(
            name="G1", bus="b", carrier="gas", p_nom=200, extra={"committable": True}
        )
    )
    assert out.get("status") != "preview"
    call = next(c for c in fake.calls if c[0] == "add_row")
    assert call[1] == "generators"
    row = call[2]
    assert row == {
        "name": "G1",
        "bus": "b",
        "carrier": "gas",
        "p_nom": 200,
        "committable": True,
    }
    assert "marginal_cost" not in row  # None fields dropped


def test_add_bus_previews_under_manual(monkeypatch) -> None:
    fake = _install(monkeypatch, "manual")
    out = asyncio.run(server.add_bus(name="b", v_nom=380))
    assert out["status"] == "preview"
    assert not fake.called("add_row")


# ── generic component tools: resolve any component + append via the registry ────
def test_add_component_generic_resolves_and_appends(monkeypatch) -> None:
    fake = _install(monkeypatch, "guided")
    out = asyncio.run(
        server.add_component(
            component="Link",
            name="L1",
            attributes={"bus0": "a", "bus1": "b", "p_nom": 100},
        )
    )
    assert out.get("status") != "preview"
    add = next(c for c in fake.calls if c[0] == "add_row")
    assert add[1] == "links"  # resolved Link -> links sheet
    assert add[2] == {"name": "L1", "bus0": "a", "bus1": "b", "p_nom": 100}


def test_remove_component_gated_under_guided(monkeypatch) -> None:
    fake = _install(monkeypatch, "guided")  # remove is destructive -> not cheap
    out = asyncio.run(server.remove_component(component="Generator", names=["G1"]))
    assert out["status"] == "preview"
    assert not fake.called("delete_components")


# ══════════════════════════════════════════════════════════════════════════════
# Coverage-audit tool expansion — deep reads, bulk edit, run/queue control.
# ══════════════════════════════════════════════════════════════════════════════
def test_new_read_tools_pass_through(monkeypatch) -> None:
    fake = _install(monkeypatch, "manual")  # even under manual, reads never gate
    assert asyncio.run(server.validate_model())["ok"] is True
    assert asyncio.run(server.get_run_series("run7", "generators-p"))["columns"] == ["gen1"]
    assert asyncio.run(server.get_series_window("loads-p_set"))["columns"] == ["load1"]
    assert asyncio.run(server.get_sheet_stats("generators"))["columns"]["p_nom"]["mean"] == 100.0
    assert asyncio.run(server.get_journal(limit=10))["version"] == 3
    assert asyncio.run(server.get_journal_diff(3))["id"] == 3
    assert asyncio.run(server.get_master_meta())["years"] == [2030, 2040]
    assert asyncio.run(server.run_plugin_analysis("p1"))["data"] == {}
    assert asyncio.run(server.optimize_procurement(prices=[1.0, 2.0], load_mw=50))["mix"] == {}
    for name in ("validate_case", "get_run_series", "get_series_window",
                 "get_sheet_stats", "get_journal", "get_master_meta",
                 "run_plugin_analyze", "optimize_procurement"):
        assert fake.called(name), f"{name} not reached"


def test_forge_query_previews_then_applies(monkeypatch) -> None:
    fake = _install(monkeypatch, "guided")  # bulk edit is non-cheap -> gated
    pv = asyncio.run(server.forge_query(
        target="generators", attribute="marginal_cost",
        edit={"op": "multiply", "amount": 1.2},
        filters=[{"column": "carrier", "op": "eq", "value": "coal"}],
    ))
    assert pv["status"] == "preview"
    assert pv["matched"] == 5  # the REAL forge preview (match count), not a stub
    assert ("forge_query", False, "generators") in fake.calls  # /preview
    assert ("forge_query", True, "generators") not in fake.calls  # /apply not hit

    ap = asyncio.run(server.forge_query(
        target="generators", attribute="marginal_cost",
        edit={"op": "multiply", "amount": 1.2}, confirm=True,
    ))
    assert ap["changed"] == 5
    assert ("forge_query", True, "generators") in fake.calls


def test_cancel_solve_never_gates(monkeypatch) -> None:
    # A safety action: it must execute even under the strictest autonomy, with no
    # confirm parameter at all.
    fake = _install(monkeypatch, "manual")
    out = asyncio.run(server.cancel_solve(item_id="job9"))
    assert out["status"] == "cancelled"
    assert fake.called("cancel_queue_item")


def test_delete_run_always_gates(monkeypatch) -> None:
    # Permanent deletion gates even at auto (mirrors ALWAYS_GATED).
    fake = _install(monkeypatch, "auto")
    out = asyncio.run(server.delete_run(name="run7"))
    assert out["status"] == "preview"
    assert not fake.called("delete_run")
    out2 = asyncio.run(server.delete_run(name="run7", confirm=True))
    assert out2["deleted"] is True
    assert fake.called("delete_run")


def test_promote_and_derive_are_gated_transforms(monkeypatch) -> None:
    fake = _install(monkeypatch, "guided")
    assert asyncio.run(server.promote_run(run_name="run7"))["status"] == "preview"
    assert not fake.called("promote_run")
    assert asyncio.run(server.promote_run(run_name="run7", confirm=True))["buses"] == 3
    assert asyncio.run(server.derive_from_master(years=[2030]))["status"] == "preview"
    assert asyncio.run(server.derive_from_master(years=[2030], confirm=True))["report"] == {}


# ── file export / import (workbook I/O) ─────────────────────────────────────────
def test_export_run_writes_file_and_never_gates(monkeypatch, tmp_path) -> None:
    # Exports produce a local artefact but never mutate the model → run freely,
    # even under manual, with no confirm.
    fake = _install(monkeypatch, "manual")
    dest = tmp_path / "run7.zip"
    out = asyncio.run(server.export_run(run_name="run7", kind="package", dest=str(dest)))
    assert out["status"] == "exported"
    assert out["bytes"] > 0
    assert dest.read_bytes().startswith(b"PK")
    assert ("download_run", "run7", "package", None) in fake.calls


def test_export_run_rejects_bad_kind(monkeypatch, tmp_path) -> None:
    _install(monkeypatch)
    out = asyncio.run(server.export_run(run_name="r", kind="pdf", dest=str(tmp_path / "x")))
    assert "error" in out


def test_export_model_formats(monkeypatch, tmp_path) -> None:
    fake = _install(monkeypatch, "manual")
    dest = tmp_path / "net.nc"
    out = asyncio.run(server.export_model(format="nc", dest=str(dest)))
    assert out["status"] == "exported" and out["format"] == "netcdf"
    assert dest.exists()
    # netCDF/HDF5 go through build_network, which 400s without a discountRate —
    # the tool must always send a scenario carrying one.
    call = next(c for c in fake.calls if c[0] == "export_model_file")
    assert call[1] == "netcdf"
    assert call[3] == {}, "no scenario override → client fills the default"
    out2 = asyncio.run(
        server.export_model(format="hdf5", dest=str(tmp_path / "n.h5"), discount_rate=0.07, carbon_price=50)
    )
    assert out2["format"] == "hdf5"
    call2 = [c for c in fake.calls if c[0] == "export_model_file"][-1]
    assert call2[3] == {"discountRate": 0.07, "carbonPrice": 50}
    assert "error" in asyncio.run(server.export_model(format="bogus", dest=str(tmp_path / "y")))


def test_import_network_gates_then_replaces(monkeypatch, tmp_path) -> None:
    fake = _install(monkeypatch, "guided")
    src = tmp_path / "grid.nc"
    src.write_bytes(b"\x89HDF-or-nc")
    pv = asyncio.run(server.import_network(path=str(src)))
    assert pv["status"] == "preview"
    assert not fake.called("import_network_file")
    ap = asyncio.run(server.import_network(path=str(src), confirm=True))
    assert ap["status"] == "applied" and ap["mode"] == "replace"
    assert fake.called("import_network_file")
    assert fake.called("save_model")  # replace → whole-model swap


def test_import_network_merge_uses_merge_sheets(monkeypatch, tmp_path) -> None:
    fake = _install(monkeypatch, "auto")  # auto skips the gate
    src = tmp_path / "grid.h5"
    src.write_bytes(b"\x89HDF")
    out = asyncio.run(server.import_network(path=str(src), replace=False))
    assert out["mode"] == "merge"
    assert fake.called("merge_sheets") and not fake.called("save_model")


def test_import_network_unknown_extension(monkeypatch, tmp_path) -> None:
    _install(monkeypatch, "auto")
    src = tmp_path / "grid.txt"
    src.write_bytes(b"nope")
    assert "error" in asyncio.run(server.import_network(path=str(src)))


def test_import_network_missing_file(monkeypatch, tmp_path) -> None:
    _install(monkeypatch, "auto")
    assert "error" in asyncio.run(server.import_network(path=str(tmp_path / "absent.nc")))


def test_import_project_load_vs_persist(monkeypatch, tmp_path) -> None:
    fake = _install(monkeypatch, "auto")
    src = tmp_path / "proj.zip"
    src.write_bytes(b"PK\x03\x04")
    loaded = asyncio.run(server.import_project(path=str(src)))
    assert loaded["status"] == "loaded"
    assert fake.called("save_model")  # loaded into the working model
    stored = asyncio.run(server.import_project(path=str(src), persist=True))
    assert stored["status"] == "stored" and stored["run"] == "imported_run"


# ── parameter-gap fixes (audit round 2) ─────────────────────────────────────────
def test_transform_series_set_requires_value(monkeypatch) -> None:
    # The endpoint defaults value=0.0, so a valueless op="set" would silently
    # zero the whole series. The tool must refuse instead.
    fake = _install(monkeypatch, "auto")
    out = asyncio.run(server.transform_series(sheet="loads-p_set", op="set"))
    assert "error" in out
    assert not fake.called("transform_series")
    ok = asyncio.run(server.transform_series(sheet="loads-p_set", op="set", value=0.85))
    assert ok["rows"] == 24
    call = next(c for c in fake.calls if c[0] == "transform_series")
    assert call[3]["value"] == 0.85


def test_transform_series_other_ops_unaffected(monkeypatch) -> None:
    fake = _install(monkeypatch, "auto")
    asyncio.run(server.transform_series(sheet="loads-p_set", op="scale", factor=1.1))
    call = next(c for c in fake.calls if c[0] == "transform_series")
    assert call[2] == "scale" and call[3]["factor"] == 1.1


def test_attach_profiles_applies_snapshot_axis(monkeypatch) -> None:
    # The endpoint returns `snapshots` beside `sheets`; dropping it leaves the new
    # profile spanning a window the snapshots sheet doesn't cover.
    fake = _install(monkeypatch, "auto")
    out = asyncio.run(server.attach_renewable_profiles())
    assert out["status"] == "applied" and out["snapshotCount"] == 2
    merged = next(c for c in fake.calls if c[0] == "merge_sheets")
    assert "snapshots" in merged[1], "snapshot axis must be merged with the sheets"


def test_attach_hydro_applies_snapshot_axis(monkeypatch) -> None:
    fake = _install(monkeypatch, "auto")
    out = asyncio.run(server.attach_hydro_inflow())
    assert out["snapshotCount"] == 2
    merged = next(c for c in fake.calls if c[0] == "merge_sheets")
    assert "snapshots" in merged[1]


def test_attach_profiles_source_selectable(monkeypatch) -> None:
    fake = _install(monkeypatch, "auto")
    asyncio.run(server.attach_renewable_profiles(source="pvgis"))
    call = next(c for c in fake.calls if c[0] == "attach_renewable_profiles")
    assert call[1]["source"] == "pvgis"


def test_cluster_conflict_knobs_reach_the_api(monkeypatch) -> None:
    fake = _install(monkeypatch, "auto")
    asyncio.run(server.cluster_network(
        n_clusters=3, resolve_conflicts=False, conflict_strategy="max",
    ))
    call = next(c for c in fake.calls if c[0] == "cluster_network")
    assert call[2]["resolveConflicts"] is False
    assert call[2]["conflictStrategy"] == "max"


def test_procurement_cvar_budget_reaches_the_api(monkeypatch) -> None:
    # The tool is described as CVaR-CONSTRAINED; without cvarBudget it could only
    # ever return the min-CVaR portfolio.
    fake = _install(monkeypatch, "manual")
    asyncio.run(server.optimize_procurement(
        prices=[1.0, 2.0], load_mw=50, cvar_budget=1000.0, bootstrap=500, block_hours=48,
    ))
    req = next(c for c in fake.calls if c[0] == "optimize_procurement")[1]
    assert req["cvarBudget"] == 1000.0
    assert req["bootstrap"] == 500 and req["blockHours"] == 48
    # Omitted knobs must not be sent as nulls (the endpoint has its own defaults).
    asyncio.run(server.optimize_procurement(prices=[1.0], load_mw=10))
    req2 = [c for c in fake.calls if c[0] == "optimize_procurement"][-1][1]
    assert "cvarBudget" not in req2 and "bootstrap" not in req2


def test_ev_region_shares_reach_the_api(monkeypatch) -> None:
    # home/work shares ARE the inter-region shift the tool advertises.
    fake = _install(monkeypatch, "auto")
    asyncio.run(server.ev_reshape_demand(
        fleet_size=1e6, home_shares={"north": 0.6}, work_shares={"south": 0.4},
        snapshot_weight=3.0,
    ))
    call = next(c for c in fake.calls if c[0] == "ev_reshape_demand")
    assert call[2]["homeShares"] == {"north": 0.6}
    assert call[2]["workShares"] == {"south": 0.4}
    assert call[2]["snapshotWeight"] == 3.0


def test_driver_forecast_grow_sheets_and_weight(monkeypatch) -> None:
    fake = _install(monkeypatch, "auto")
    asyncio.run(server.driver_forecast(
        from_year=2024, to_year=2030, grow_sheets=["loads-p_set", "loads-p_min_pu"],
        snapshot_weight=3.0,
    ))
    call = next(c for c in fake.calls if c[0] == "driver_forecast")
    assert call[3]["growSheets"] == ["loads-p_set", "loads-p_min_pu"]
    assert call[3]["snapshotWeight"] == 3.0
