"""P2X routes and MCP tools against the real FastAPI app (technologies, chain preview / apply, RFNBO settings, results)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import main, run_store, session_store
from backend.app.routers import results_derived as rd_router
from backend.mcp import server, tools_p2x
from backend.mcp.client import Config, RagnarokClient
from backend.pypsa.results import run_pypsa

from ._p2x_fixtures import H2_SPEC, SCENARIO, night_gas_network, with_chain


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("RAGNAROK_DATA_DIR", str(tmp_path / "data"))
    from backend.app import data_root  # noqa: F401  (the store reads the env at call time)

    rd_router._BUNDLE_CACHE.clear()
    return TestClient(main.app)


def _load(client: TestClient, sid: str, model: dict[str, Any]) -> None:
    assert client.post("/api/session/model", json={"model": model, "sessionId": sid}).status_code == 200


def test_technologies_and_defaults_endpoints(client: TestClient) -> None:
    t = client.get("/api/p2x/technologies").json()
    assert t["sources"]["technology-data"]["version"] == "v0.15.0"
    p = t["technologies"]["haber_bosch"]["parameters"]["h2_input"]
    assert p["unit"] == "MWh_H2/MWh_NH3" and p["source"]["locator"] and p["default"] == p["value"]
    _load(client, "p2x-d", night_gas_network())
    d = client.get("/api/p2x/chain/defaults", params={"session_id": "p2x-d"}).json()
    assert d["defaultAnchorBus"] == "grid" and d["products"] == ["H2", "NH3", "MeOH", "eFuel"]
    assert d["spec"]["electrolyser"]["tech"] == "aec"


def test_chain_preview_does_not_write_and_apply_does(client: TestClient) -> None:
    sid = "p2x-c"
    _load(client, sid, night_gas_network())
    body = {"sessionId": sid, "spec": H2_SPEC}
    prev = client.post("/api/p2x/chain", json=body).json()
    assert prev["applied"] is False and prev["rowCounts"]["links"] == 1
    links_before = client.get("/api/session/sheet/links", params={"session_id": sid})
    assert links_before.status_code == 404 or links_before.json()["rows"] == []
    done = client.post("/api/p2x/chain", json={**body, "apply": True}).json()
    assert done["applied"] is True
    rows = client.get("/api/session/sheet/links", params={"session_id": sid}).json()["rows"]
    assert [r["name"] for r in rows] == ["p2x_electrolyser"]
    reg = client.get("/api/session/sheet/RAGNAROK_P2X", params={"session_id": sid}).json()["rows"]
    assert reg[0]["name"] == "p2x" and "p2x_electrolyser" in reg[0]["json"]
    # a second chain with the same id is refused with a sentence
    again = client.post("/api/p2x/chain", json={**body, "apply": True})
    assert again.status_code == 400 and "already exists" in again.json()["detail"]
    bad = client.post("/api/p2x/chain", json={"sessionId": sid, "spec": {"chainId": "q", "products": ["XX"]}})
    assert bad.status_code == 400 and "Unknown product" in bad.json()["detail"]


def test_chain_with_an_uploaded_profile_merges_the_series(client: TestClient) -> None:
    sid = "p2x-p"
    base = night_gas_network(hours=4)
    base["loads-p_set"] = [{"snapshot": s["snapshot"], "demand": 20.0} for s in base["snapshots"]]
    _load(client, sid, base)
    spec = {"chainId": "q", "products": ["H2"], "offtake": {"H2": {"mode": "profile", "mw": 4.0, "profile": [1, 2, 3, 2]}}}
    out = client.post("/api/p2x/chain", json={"sessionId": sid, "spec": spec, "apply": True}).json()
    assert out["applied"] is True
    rows = client.get("/api/session/sheet/loads-p_set", params={"session_id": sid}).json()["rows"]
    assert [r["demand"] for r in rows] == [20.0] * 4 and [r["q_load_H2"] for r in rows] == [2.0, 4.0, 6.0, 4.0]


def test_rfnbo_settings_checks_and_the_submit_hook(client: TestClient) -> None:
    sid = "p2x-r"
    model, _ = with_chain(night_gas_network(build_year=2026), H2_SPEC)
    _load(client, sid, model)
    assert client.get("/api/p2x/rfnbo/config", params={"session_id": sid}).json()["config"] is None
    put = client.put("/api/p2x/rfnbo/config", json={"sessionId": sid, "config": {"enabled": True, "temporal": "monthly", "enforceAdditionality": True}})
    assert put.json()["config"]["temporal"] == "monthly"
    assert client.put("/api/p2x/rfnbo/config", json={"sessionId": sid, "config": {"temporal": "weekly"}}).status_code == 400
    chk = client.post("/api/p2x/rfnbo/checks", json={"sessionId": sid}).json()
    assert chk["additionality"][0]["status"] == "fail" and chk["dropped"][0]["generator"] == "wind"
    assert chk["willBeRefused"] is True and {a["article"] for a in chk["attest"]} >= {"Art. 5(b)", "Art. 4"}
    # the stored settings ride with a run that sets none; an explicit option wins (even disabled)
    resolved = main._resolve_payload_model(main.RunPayload(sessionId=sid, scenario={}, options={}))
    assert resolved.options["rfnboConfig"]["temporal"] == "monthly"
    explicit = main._resolve_payload_model(main.RunPayload(sessionId=sid, scenario={}, options={"rfnboConfig": {"enabled": False}}))
    assert explicit.options["rfnboConfig"] == {"enabled": False}


def test_results_endpoint_reads_a_stored_run(client: TestClient) -> None:
    model, _ = with_chain(night_gas_network(hours=24), H2_SPEC)
    opts = {"rfnboConfig": {"enabled": True, "temporal": "hourly"}}
    res = run_pypsa(model, SCENARIO, opts)
    meta = run_store.store_run(model, dict(SCENARIO), opts, res)
    name = meta["name"]
    out = client.get(f"/api/p2x/results/{name}").json()
    assert out["chainId"] == "p2x" and out["lcoh"]["perKg"] > 0 and out["rfnbo"]["matchingEnabled"] is True
    assert out["rfnbo"]["compliance"]["hourly"]["compliantShareOfOperating"] == 1.0
    assert len(out["series"]["snapshots"]) == 24 and len(out["series"]["h2SocMwh"]) == 24
    ppa = client.get(f"/api/p2x/results/{name}", params={"electricity_cost": "ppa"}).json()
    assert ppa["electricityCost"] == "ppa"
    assert client.get("/api/p2x/results/nope").status_code == 404
    assert client.get(f"/api/p2x/results/{name}", params={"electricity_cost": "x"}).status_code == 400
    plain = run_store.store_run(night_gas_network(hours=4), dict(SCENARIO), {}, run_pypsa(night_gas_network(hours=4), SCENARIO, {}))
    assert client.get(f"/api/p2x/results/{plain['name']}").status_code == 400


# ── MCP ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def wired(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> RagnarokClient:
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "guided")
    c = RagnarokClient(Config(api_base="http://test", session_id="p2x-mcp", timeout=60.0), transport=httpx.ASGITransport(app=main.app))
    monkeypatch.setattr(server, "_client", c)
    _load(client, "p2x-mcp", night_gas_network())
    return c


def test_mcp_tools_registered_with_read_only_flags() -> None:
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    ro = {"list_p2x_technologies": True, "preview_p2x_chain": True, "get_p2x_results": True, "build_p2x_chain": False}
    for name, read_only in ro.items():
        assert name in tools
        assert tools[name].annotations.readOnlyHint is read_only


def test_mcp_preview_is_read_only_and_build_is_gated(wired: RagnarokClient, client: TestClient) -> None:
    async def go() -> None:
        techs = await tools_p2x.list_p2x_technologies("electrolyser_pem")
        assert list(techs["technologies"]) == ["electrolyser_pem"]
        assert "error" in await tools_p2x.list_p2x_technologies("nope")
        prev = await tools_p2x.preview_p2x_chain(H2_SPEC)
        assert prev["applied"] is False and any(r["role"] == "electrolyser" for r in prev["summary"])
        gated = await tools_p2x.build_p2x_chain(H2_SPEC)                 # guided autonomy: preview until confirm=true
        assert gated["status"] == "preview"
        before = client.get("/api/session/sheet/links", params={"session_id": "p2x-mcp"})
        assert before.status_code == 404 or before.json()["rows"] == []      # nothing written before confirm
        done = await tools_p2x.build_p2x_chain(H2_SPEC, confirm=True)
        assert done["applied"] is True and done["rowCounts"]["RAGNAROK_P2X"] == 1

    asyncio.run(go())
    rows = client.get("/api/session/sheet/links", params={"session_id": "p2x-mcp"}).json()["rows"]
    assert [r["name"] for r in rows] == ["p2x_electrolyser"]
