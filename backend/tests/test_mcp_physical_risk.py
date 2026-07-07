"""In-process tests for the Bifrost MCP physical-risk + analytics tools.

Unlike ``test_mcp_server.py`` (which swaps in a recording ``FakeClient``), these
drive the REAL :class:`RagnarokClient` against the REAL FastAPI app mounted
in-process via ``httpx.ASGITransport`` — no network, no running uvicorn. The
client's httpx layer now accepts a ``transport`` (see ``client.py``), so the
same code path an agent uses in production runs here against the ASGI app.

The physical-risk store and the session store are redirected to temp dirs and
the CLIMADA worker is disabled (``RAGNAROK_CLIMADA_WORKER=0``) so runs execute
the deterministic stub engine — mirrors ``test_physical_risk.py``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from backend.app import session_store
from backend.app.main import app
from backend.app.physical_risk import store as physical_risk_store
from backend.mcp import server
from backend.mcp.client import Config, RagnarokClient


@pytest.fixture(autouse=True)
def _stub_engine_and_isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the deterministic stub engine and isolate the physical-risk store."""
    monkeypatch.setenv("RAGNAROK_CLIMADA_WORKER", "0")
    monkeypatch.setattr(physical_risk_store, "DATA_DIR", tmp_path / "physical_risk")
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")


@pytest.fixture()
def in_process_client(monkeypatch: pytest.MonkeyPatch) -> RagnarokClient:
    """A RagnarokClient whose httpx layer targets the FastAPI app in-process.

    Installed as the MCP server's shared client, so the ``@mcp.tool`` coroutines
    (called directly below) exercise the real REST endpoints via ASGI.
    """
    transport = httpx.ASGITransport(app=app)
    client = RagnarokClient(
        Config(api_base="http://testserver", session_id="default", timeout=30.0),
        transport=transport,
    )
    monkeypatch.setattr(server, "_client", client)
    # Guided autonomy is irrelevant here (physical_risk tools aren't gated), but
    # keep the env deterministic.
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "guided")
    return client


def _load_model(client: RagnarokClient) -> None:
    """Load a 2-bus model (one generator, one storage unit) into the session."""
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
    resp = asyncio.run(
        client._post(  # save via the same endpoint the frontend uses
            "/api/session/model",
            {"sessionId": "default", "model": model, "filename": "case.xlsx", "scenarioName": "ref"},
        )
    )
    assert resp is not None


# ── seed caches the session + returns assets ─────────────────────────────────
def test_seed_caches_session_and_returns_assets(in_process_client: RagnarokClient) -> None:
    _load_model(in_process_client)
    out = asyncio.run(server.physical_risk_seed(default_value_per_mw=1_000_000.0))
    assert out["sessionId"], out
    assert out["assetCount"] == 2
    names = {a["name"] for a in out["sampleAssets"]}
    assert names == {"gasCC", "battery1"}
    # The seed cached its session id on the shared client (defaulting works).
    assert in_process_client.physical_risk_session_id == out["sessionId"]

    # A tool with no session_id argument now resolves to the cached session.
    pf = asyncio.run(server.physical_risk_get_portfolio())
    assert pf["sessionId"] == out["sessionId"]
    assert len(pf["assets"]) == 2


def test_get_portfolio_without_seed_errors(in_process_client: RagnarokClient) -> None:
    out = asyncio.run(server.physical_risk_get_portfolio())
    assert "error" in out
    assert "physical_risk_seed" in out["error"]


# ── libraries ────────────────────────────────────────────────────────────────
def test_libraries_lists_perils_and_classes(in_process_client: RagnarokClient) -> None:
    libs = asyncio.run(server.physical_risk_libraries())
    peril_ids = {p["id"] for p in libs["perils"]}
    assert {"tropical_cyclone", "river_flood", "wildfire", "earthquake"} <= peril_ids
    class_ids = {c["id"] for c in libs["vulnerabilityClasses"]}
    assert {"thermal", "renewable", "hydro", "grid", "default"} <= class_ids


# ── set_scenario round-trips through GET + PUT ───────────────────────────────
def test_set_scenario_round_trips(in_process_client: RagnarokClient) -> None:
    _load_model(in_process_client)
    asyncio.run(server.physical_risk_seed())

    out = asyncio.run(
        server.physical_risk_set_scenario(
            perils=["river_flood", "wildfire"],
            climate="rcp85",
            horizon_year=2040,
            sector="utilities",
        )
    )
    scen = out["scenario"]
    assert scen["perils"] == ["river_flood", "wildfire"]
    assert scen["climate"] == "rcp85"
    assert scen["horizonYear"] == 2040

    # The change persisted: a fresh GET sees it.
    pf = asyncio.run(server.physical_risk_get_portfolio())
    assert pf["scenario"]["perils"] == ["river_flood", "wildfire"]
    assert pf["scenario"]["climate"] == "rcp85"
    assert pf["scenario"]["horizonYear"] == 2040


# ── run polls to done and returns a result (stub engine) ─────────────────────
def test_run_polls_to_done(in_process_client: RagnarokClient) -> None:
    _load_model(in_process_client)
    asyncio.run(server.physical_risk_seed())
    asyncio.run(server.physical_risk_set_scenario(perils=["tropical_cyclone", "river_flood"]))

    out = asyncio.run(server.physical_risk_run(poll_seconds=30.0))
    assert out["status"] == "done", out
    assert out["runId"]
    result = out["result"]
    assert result is not None
    assert result["currency"]
    result_perils = {block["peril"] for block in result["perils"]}
    assert result_perils == {"tropical_cyclone", "river_flood"}

    # The run is pollable by id via the dedicated tool.
    again = asyncio.run(server.physical_risk_get_run(out["runId"]))
    assert again["status"] == "done"


def test_run_perils_override_scenario(in_process_client: RagnarokClient) -> None:
    _load_model(in_process_client)
    asyncio.run(server.physical_risk_seed())
    asyncio.run(server.physical_risk_set_scenario(perils=["tropical_cyclone"]))

    out = asyncio.run(server.physical_risk_run(perils=["wildfire"], poll_seconds=30.0))
    assert out["status"] == "done", out
    result_perils = {block["peril"] for block in out["result"]["perils"]}
    assert result_perils == {"wildfire"}


# ── describe_analytics lists all seven optionKey -> resultKey pairs ──────────
def test_describe_analytics_lists_all_seven() -> None:
    out = asyncio.run(server.describe_analytics())
    assert "options.<optionKey>" in out["note"]
    pairs = {a["optionKey"]: a["resultKey"] for a in out["analytics"]}
    assert pairs == {
        "reserveConfig": "reserve",
        "outageMcConfig": "outageMc",
        "rampConfig": "ramp",
        "correlatedSamplingConfig": "correlatedSampling",
        "elccConfig": "elcc",
        "convergenceConfig": "convergenceSampling",
        "lmpDecompositionConfig": "lmpDecomposition",
    }
    # outageMc carries the physical-risk uplift bridge fields.
    outage = next(a for a in out["analytics"] if a["optionKey"] == "outageMcConfig")
    assert "physicalRiskUplift" in outage["config"]
    assert "physicalRiskSessionId" in outage["config"]
    # Every entry has a purpose and non-empty config.
    for a in out["analytics"]:
        assert a["purpose"]
        assert a["config"]
