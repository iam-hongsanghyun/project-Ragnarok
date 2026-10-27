"""In-process tests for the component-coverage MCP tools (P11, P18, P41-P43)."""
from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

import httpx
import pytest

from backend.app import session_store
from backend.app.main import app
from backend.mcp import server, tools_components  # noqa: F401  (registers the tools)
from backend.mcp.client import Config, RagnarokClient
from backend.tests.test_pypsa_io import CASE_M


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RagnarokClient:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setattr(server, "_FILE_DIR", tmp_path)
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "auto")
    c = RagnarokClient(
        Config(api_base="http://testserver", session_id="t", timeout=30.0),
        transport=httpx.ASGITransport(app=app),
    )
    monkeypatch.setattr(server, "_client", c)
    return c


def test_import_matpower_then_maintenance_seasonal_export(client: RagnarokClient, tmp_path: Path) -> None:
    (tmp_path / "case3.m").write_text(CASE_M)

    async def go():
        out = await tools_components.import_pypsa_native("case3.m")
        assert out["status"] == "applied" and out["kind"] == "matpower"
        model = await client.load_full_model()
        gen = model["generators"][0]["name"]
        res = await tools_components.set_maintenance(
            "Generator", gen, maintenance_duration=2, maintenance_events=1, maintenance_pu=0.5
        )
        assert res is not None
        row = (await client.load_full_model())["generators"][0]
        assert row["maintainable"] in (True, "true", "True") and float(row["maintenance_pu"]) == 0.5
        bad = await tools_components.set_maintenance("Bus", "x")
        assert "error" in bad
        # seasonal rating needs datetime snapshots + a line
        model = await client.load_full_model()
        line = model["lines"][0]["name"]
        model["snapshots"] = [{"snapshot": f"2030-01-01T0{h}:00:00"} for h in range(4)]
        await client.save_model(model)
        r = await tools_components.apply_seasonal_rating(
            {line: {"summer": 50.0, "winter": 100.0}}, summer_months=[1], compose=False
        )
        assert r["status"] == "applied" and r["snapshots"] == 4
        series = (await client.load_full_model())["lines-s_max_pu"]
        assert len(series) == 4
        exp = await tools_components.export_pypsa_native("csv", export_standard_types=False)
        assert exp["status"] == "exported"
        assert "buses.csv" in zipfile.ZipFile(exp["path"]).namelist()
        caps = await tools_components.pypsa_io_capabilities()
        assert "matpower" in caps["import"]

    asyncio.run(go())
