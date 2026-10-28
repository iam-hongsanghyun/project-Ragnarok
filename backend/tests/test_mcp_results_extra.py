"""MCP ``compare_run_statistics`` forwards to GET /api/results/compare?topics=statistics;
``get_metric_options`` to GET /api/runs/{name}/metrics; ``get_period_results`` to
GET /api/runs/{name}/period/{period}, and ``get_kpis`` / ``compare_companies`` forward ``period``."""
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
    assert tools["get_period_results"].annotations.readOnlyHint is True
    assert tools["get_run_analysis"].annotations.readOnlyHint is True


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


def test_period_results_kpis_and_companies_forward_the_period(monkeypatch) -> None:
    import httpx

    from backend.mcp import tools_analysis
    from backend.mcp.client import Config, RagnarokClient

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = RagnarokClient(Config(api_base="http://x", session_id="s1", timeout=5), transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tools_results_extra, "get_client", lambda: client)
    monkeypatch.setattr(tools_analysis, "get_client", lambda: client)

    async def run() -> None:
        await tools_results_extra.get_period_results("r1", 2040)
        await tools_results_extra.get_period_results("r1", 2030, fields=["dispatchSeries"], currency="EUR")
        await tools_analysis.get_kpis("r1", period=2040)
        await tools_analysis.compare_companies("r1", period=2040)
        await tools_analysis.get_kpis("r1")
        await client.aclose()

    asyncio.run(run())
    compact, custom, kpis, companies, whole = (r.url for r in seen)
    assert compact.path == "/api/runs/r1/period/2040"
    # The default asks for the compact sections, not the per-snapshot series.
    assert set(dict(compact.params)["fields"].split(",")) == set(tools_results_extra._PERIOD_DEFAULT_FIELDS)
    assert dict(custom.params) == {"fields": "dispatchSeries", "currency": "EUR"}
    assert (kpis.path, dict(kpis.params)) == ("/api/runs/r1/kpis", {"period": "2040"})
    assert (companies.path, dict(companies.params)) == ("/api/runs/r1/companies", {"period": "2040"})
    assert dict(whole.params) == {}


def test_get_run_analysis_forwards_the_topic_and_its_parameters(monkeypatch) -> None:
    import httpx

    from backend.mcp.client import Config, RagnarokClient

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"run": "r1", "topic": "transition-risk"})

    client = RagnarokClient(Config(api_base="http://x", session_id="s1", timeout=5), transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tools_results_extra, "get_client", lambda: client)

    async def run() -> None:
        await tools_results_extra.get_run_analysis("r1", "transition-risk", period=2040, base_price=80.0, years=10)
        await client.aclose()

    asyncio.run(run())
    assert seen[0].url.path == "/api/runs/r1/analysis/transition-risk"
    query = dict(seen[0].url.params)
    assert query == {"period": "2040", "basePrice": "80.0", "years": "10"}  # unset arguments are not sent
