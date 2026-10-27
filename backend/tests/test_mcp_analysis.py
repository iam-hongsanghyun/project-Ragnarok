"""Tests for backend/mcp/tools_analysis.py (WA7/WA8): read-only flags, the confirm
gate on the write tools, and the client's request paths (real httpx transport,
no backend)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from backend.mcp import server, tools_analysis
from backend.mcp.client import Config, RagnarokClient

READ_ONLY = {"compare_runs", "get_kpis", "compare_companies", "get_asset_details", "list_conversions"}
WRITE = {"snap_to_buses", "adjust_values", "revert_adjustments", "add_conversion", "merge_fragment"}


def _tools() -> dict[str, Any]:
    tools = asyncio.run(server.mcp.list_tools())
    return {t.name: t for t in tools}


def test_tools_registered_with_honest_hints() -> None:
    tools = _tools()
    for name in READ_ONLY:
        assert tools[name].annotations.readOnlyHint is True, name
    for name in WRITE:
        assert tools[name].annotations.readOnlyHint is False, name


class Recorder:
    """Stands in for RagnarokClient: records the body each write tool sends."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def forge_snap(self, **body: Any) -> dict:
        self.calls.append(("snap", body))
        return {"rows": [{"name": "g"}], "assigned": 1, "outside": [], "noCoords": 0, "anchors": ["bus"]}

    async def forge_adjust(self, body: dict, *, revert: bool = False) -> dict:
        self.calls.append(("revert" if revert else "adjust", body))
        return {"sheets": {"generators": [{"name": "g1"}, {"name": "g2"}]}, "changed": 2, "baseline": {"k": 1}}

    async def build_conversion(self, **body: Any) -> dict:
        self.calls.append(("conversion", body))
        return {"fragment": {"sheets": {"links": [{}]}}, "applied": body["apply"]}

    async def merge_fragment(self, fragment: dict, *, apply: bool = False) -> dict:
        self.calls.append(("merge", {"apply": apply}))
        return {"sheets": {"buses": 3}, "applied": apply, "model": {"buses": [1, 2, 3]}}

    async def compare_runs(self, runs: list[str], topics: list[str] | None = None) -> dict:
        self.calls.append(("compare", {"runs": runs, "topics": topics}))
        return {"items": [], "total": 0}


def _install(monkeypatch, autonomy: str = "guided") -> Recorder:
    rec = Recorder()
    monkeypatch.setattr(server, "_client", rec)
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", autonomy)
    return rec


def test_write_tools_preview_without_confirm_then_apply(monkeypatch) -> None:
    rec = _install(monkeypatch)
    out = asyncio.run(tools_analysis.snap_to_buses("generators"))
    assert out["status"] == "preview" and "rows" not in out and rec.calls[-1][1]["apply"] is False
    out = asyncio.run(tools_analysis.snap_to_buses("generators", confirm=True))
    assert out["assigned"] == 1 and rec.calls[-1][1]["apply"] is True

    adj = [{"sheet": "generators", "attribute": "p_nom", "action": "multiply", "amount": 50, "filters": []}]
    out = asyncio.run(tools_analysis.adjust_values(adj))
    assert out["status"] == "preview" and out["sheets"] == {"generators": 2}  # counts, not rows
    assert rec.calls[-1][1]["apply"] is False
    out = asyncio.run(tools_analysis.adjust_values(adj, confirm=True))
    assert out["baseline"] == {"k": 1} and rec.calls[-1][1]["apply"] is True
    asyncio.run(tools_analysis.revert_adjustments(adj, {"k": 1}, confirm=True))
    assert rec.calls[-1][0] == "revert"

    out = asyncio.run(tools_analysis.add_conversion("electrolyser"))
    assert out["status"] == "preview" and rec.calls[-1][1]["apply"] is False
    out = asyncio.run(tools_analysis.merge_fragment({"sheets": {}}))
    assert out["status"] == "preview" and "model" not in out


def test_auto_autonomy_applies_immediately(monkeypatch) -> None:
    rec = _install(monkeypatch, "auto")
    asyncio.run(tools_analysis.add_conversion("ccgt"))
    assert rec.calls[-1][1]["apply"] is True


def test_compare_runs_forwards_names_and_topics(monkeypatch) -> None:
    rec = _install(monkeypatch)
    asyncio.run(tools_analysis.compare_runs(["a", "b"], ["kpi"]))
    assert rec.calls[-1] == ("compare", {"runs": ["a", "b"], "topics": ["kpi"]})


def test_client_paths_and_bodies() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    async def run() -> None:
        client = RagnarokClient(
            Config(api_base="http://x", session_id="s1", timeout=5), transport=httpx.MockTransport(handler)
        )
        await client.compare_runs(["a", "b"], ["kpi", "cost"])
        await client.get_kpis("r1")
        await client.get_asset_details("r1", kind="generators", names="g1,g2", series=None, limit=5)
        await client.apply_fragment({"sheets": {}})
        await client.aclose()

    asyncio.run(run())
    assert seen[0].url.path == "/api/results/compare" and seen[0].url.params["runs"] == "a,b"
    assert seen[0].url.params["topics"] == "kpi,cost"
    assert seen[1].url.path == "/api/runs/r1/kpis"
    assert seen[2].url.params["names"] == "g1,g2" and "series" not in seen[2].url.params
    assert seen[3].url.path == "/api/session/merge-fragment"
    assert json.loads(seen[3].content) == {"fragment": {"sheets": {}}, "apply": True, "sessionId": "s1"}
