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


def _install(monkeypatch, autonomy: str = "guided") -> FakeClient:
    fake = FakeClient()
    monkeypatch.setattr(server, "_client", fake)
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", autonomy)
    return fake


# ── catalog / annotations ──────────────────────────────────────────────────────
def test_tool_catalog_and_annotations() -> None:
    tools = asyncio.run(mcp.list_tools())
    by_name = {t.name: t for t in tools}
    assert len(tools) == 27, f"expected 27 tools, got {len(tools)}"
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
    }


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
