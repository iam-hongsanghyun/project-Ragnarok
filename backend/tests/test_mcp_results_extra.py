"""MCP ``compare_run_statistics`` forwards to GET /api/results/compare?topics=statistics;
``get_metric_options`` to GET /api/runs/{name}/metrics."""
from __future__ import annotations

import asyncio
from typing import Any

from backend.mcp import server, tools_results_extra


class _Stub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((path, params or {}))
        return {"ok": True}


def test_compare_run_statistics_builds_the_request(monkeypatch) -> None:
    stub = _Stub()
    monkeypatch.setattr(tools_results_extra, "get_client", lambda: stub)
    out = asyncio.run(tools_results_extra.compare_run_statistics(["a", "b"], ["supply", "capex"], "bus_carrier"))
    assert out == {"ok": True}
    assert stub.calls == [("/api/results/compare", {
        "runs": "a,b", "topics": "statistics", "metrics": "supply,capex", "groupby": "bus_carrier"})]
    asyncio.run(tools_results_extra.compare_run_statistics(["a", "b"]))
    assert stub.calls[-1][1]["metrics"] is None and stub.calls[-1][1]["groupby"] == "carrier"


def test_tool_is_registered_read_only() -> None:
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert tools["compare_run_statistics"].annotations.readOnlyHint is True
    assert tools["get_metric_options"].annotations.readOnlyHint is True


def test_get_metric_options_builds_the_request(monkeypatch) -> None:
    import httpx

    from backend.mcp.client import Config, RagnarokClient

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"run": "r1", "focus": "generator", "items": [], "total": 0})

    client = RagnarokClient(Config(api_base="http://x", session_id="s1", timeout=5), transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tools_results_extra, "get_client", lambda: client)

    async def run() -> Any:
        out = await tools_results_extra.get_metric_options(
            "r1", "generator", keys=["g1", "g2"], group_by="asset", carrier_filter=["wind"], period=2030, end=24,
        )
        await tools_results_extra.get_metric_options("r1", "bus")
        await client.aclose()
        return out

    assert asyncio.run(run())["total"] == 0
    first, second = seen[0].url, seen[1].url
    assert first.path == "/api/runs/r1/metrics"
    assert dict(first.params) == {
        "focus": "generator", "keys": "g1,g2", "groupBy": "asset", "carrierFilter": "wind", "period": "2030", "end": "24",
    }
    assert dict(second.params) == {"focus": "bus"}
