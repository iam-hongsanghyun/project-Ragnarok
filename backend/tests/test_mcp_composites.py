"""MCP composite tools: place on several buses, detach, templates (list / save / delete), sync. Gated writes + one recoverable error each."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import main, run_store, session_store
from backend.mcp import server, tools_plants
from backend.mcp.client import Config, RagnarokClient

from ._plants_fixtures import grid

SID = "composites-mcp"
NEW_TOOLS = {
    "place_composite": False, "detach_composite": False, "save_composite_template": False,
    "delete_composite_template": False, "sync_composites": False, "list_composite_templates": True,
}


@pytest.fixture()
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[RagnarokClient, TestClient]:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("RAGNAROK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "guided")
    http = TestClient(main.app)
    model = grid()
    model["buses"] = [*model["buses"], {"name": "KR-1", "carrier": "AC"}, {"name": "KR-2", "carrier": "AC"}]
    assert http.post("/api/session/model", json={"model": model, "sessionId": SID}).status_code == 200
    c = RagnarokClient(Config(api_base="http://test", session_id=SID, timeout=60.0), transport=httpx.ASGITransport(app=main.app))
    monkeypatch.setattr(server, "_client", c)
    return c, http


def _rows(http: TestClient, sheet: str) -> list[dict[str, Any]]:
    """Rows of a sheet of the session model, read straight from the session store (the same store the routes write)."""
    from backend.app import model_store

    return (model_store.load_full_model(SID, static_only=True) or {}).get(sheet, [])


def test_tools_registered_in_composites_area_with_flags() -> None:
    from backend.mcp.catalogue import TOOL_AREA

    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    for name, read_only in NEW_TOOLS.items():
        assert name in tools and tools[name].annotations.readOnlyHint is read_only
        assert TOOL_AREA[name] == "composites"


def test_template_lifecycle_and_place_on_several_buses(wired: tuple[RagnarokClient, TestClient]) -> None:
    _, http = wired

    async def go() -> None:
        await tools_plants.add_plant("ccgt", {"plantId": "unit1", "bus": "grid", "pNom": 100}, confirm=True)
        # save: preview first, then apply
        prev = await tools_plants.save_composite_template("unit1")
        assert prev["status"] == "preview" and prev["wouldSend"]["template"] == "unit1_template"
        assert _rows(http, "RAGNAROK_CompositeTemplates") == []
        saved = await tools_plants.save_composite_template("unit1", confirm=True)
        assert saved["applied"] is True and saved["template"] == "unit1_template"
        listed = await tools_plants.list_composite_templates()
        assert listed["total"] == 1 and listed["templates"][0]["type"] == "ccgt" and listed["templates"][0]["spec"]["pNom"] == 100
        assert "bus" not in listed["templates"][0]["spec"] and "plantId" not in listed["templates"][0]["spec"]
        # re-saving replaces rather than duplicates
        again = await tools_plants.save_composite_template("unit1", confirm=True)
        assert again["replaced"] is True and (await tools_plants.list_composite_templates())["total"] == 1
        # place the template on two buses
        prev = await tools_plants.place_composite(["KR-1", "KR-2"], template="unit1_template")
        assert prev["status"] == "preview" and prev["wouldSend"]["plantIds"] == ["unit1_KR_1", "unit1_KR_2"]
        placed = await tools_plants.place_composite(["KR-1", "KR-2"], template="unit1_template", confirm=True)
        assert placed["applied"] is True and placed["plantIds"] == ["unit1_KR_1", "unit1_KR_2"]
        assert {r["name"] for r in _rows(http, "RAGNAROK_Composites")} >= {"unit1", "unit1_KR_1", "unit1_KR_2"}
        # delete the template; the placed composites stay
        assert (await tools_plants.delete_composite_template("unit1_template"))["status"] == "preview"
        assert (await tools_plants.delete_composite_template("unit1_template", confirm=True))["applied"] is True
        assert (await tools_plants.list_composite_templates())["total"] == 0
        assert "unit1_KR_1" in {r["name"] for r in _rows(http, "RAGNAROK_Composites")}

    asyncio.run(go())


def test_place_from_existing_composite_and_explicit_type(wired: tuple[RagnarokClient, TestClient]) -> None:
    _, http = wired

    async def go() -> None:
        await tools_plants.add_plant("bess", {"plantId": "bat", "bus": "grid", "pNom": 10}, confirm=True)
        by_copy = await tools_plants.place_composite(["KR-1"], from_plant="bat", confirm=True)
        assert by_copy["plantIds"] == ["bat_KR_1"]
        by_type = await tools_plants.place_composite(["KR-2"], type="ocgt", spec={"pNom": 50}, prefix="peaker", confirm=True)
        assert by_type["plantIds"] == ["peaker_KR_2"]
        assert {"bat_KR_1", "peaker_KR_2"} <= {r["name"] for r in _rows(http, "RAGNAROK_Composites")}

    asyncio.run(go())


def test_place_errors_are_recoverable_sentences(wired: tuple[RagnarokClient, TestClient]) -> None:
    async def go() -> None:
        for kwargs, needle in (
            ({"buses": ["KR-1"], "template": "ghost"}, "No template 'ghost'"),
            ({"buses": ["KR-1"]}, "exactly one source"),
            ({"buses": ["KR-1"], "type": "ccgt", "template": "x"}, "exactly one source"),
            ({"buses": [], "type": "ccgt"}, "at least one bus"),
        ):
            with pytest.raises(Exception, match=needle):
                await tools_plants.place_composite(**kwargs, confirm=True)

    asyncio.run(go())


def test_detach_then_unknown_composite_error(wired: tuple[RagnarokClient, TestClient]) -> None:
    _, http = wired

    async def go() -> None:
        await tools_plants.add_plant("ccgt", {"plantId": "unit1", "bus": "grid", "pNom": 100}, confirm=True)
        prev = await tools_plants.detach_composite("unit1")
        assert prev["status"] == "preview" and prev["wouldSend"]["released"] >= 1
        assert "unit1" in {r["name"] for r in _rows(http, "RAGNAROK_Composites")}
        done = await tools_plants.detach_composite("unit1", confirm=True)
        assert done["applied"] is True
        assert "unit1" not in {r["name"] for r in _rows(http, "RAGNAROK_Composites")}
        assert any(r["name"] == "unit1" for r in _rows(http, "links")), "children stay as plain rows"
        with pytest.raises(Exception, match="No composite 'unit1'"):
            await tools_plants.detach_composite("unit1", confirm=True)

    asyncio.run(go())


def test_save_and_delete_template_errors(wired: tuple[RagnarokClient, TestClient]) -> None:
    async def go() -> None:
        with pytest.raises(Exception, match="No editable composite 'nope'"):
            await tools_plants.save_composite_template("nope", confirm=True)
        with pytest.raises(Exception, match="saved templates: none"):
            await tools_plants.delete_composite_template("nope", confirm=True)

    asyncio.run(go())


def test_sync_composites_follows_an_edited_sheet_row(wired: tuple[RagnarokClient, TestClient]) -> None:
    client, http = wired

    async def go() -> None:
        await tools_plants.add_plant("ccgt", {"plantId": "unit1", "bus": "grid", "pNom": 100}, confirm=True)
        assert (await tools_plants.sync_composites(confirm=True))["plantIds"] == []          # untouched sheet: nothing to do
        model = await client.load_full_model()
        next(r for r in model["RAGNAROK_Composites"] if r["name"] == "unit1")["p_nom"] = 150
        await client.save_model(model)
        prev = await tools_plants.sync_composites()
        assert prev["status"] == "preview" and prev["wouldSend"]["plantIds"] == ["unit1"]
        done = await tools_plants.sync_composites(confirm=True)
        assert done["applied"] is True and done["plantIds"] == ["unit1"]
        link = next(r for r in _rows(http, "links") if r["name"] == "unit1")
        assert link["p_nom"] == pytest.approx(150 / link["efficiency"])

    asyncio.run(go())
