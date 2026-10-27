"""MCP piecewise tools against the REAL FastAPI app (in-process ASGI transport).

No fake client: ``RagnarokClient`` is wired to ``backend.app.main.app`` so the
set / get / clear tools exercise the real session store, the ``-pw`` sheet
classification and the curve check endpoint.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.app import main, session_store
from backend.mcp import server, tools_piecewise as tp
from backend.mcp.client import Config, RagnarokClient

SHEET = "generators-marginal_cost-pw"


@pytest.fixture()
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RagnarokClient:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "auto")
    client = RagnarokClient(
        Config(api_base="http://test", session_id="default", timeout=60.0),
        transport=httpx.ASGITransport(app=main.app),
    )
    monkeypatch.setattr(server, "_client", client)
    return client


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_tools_are_registered() -> None:
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"describe_piecewise", "get_piecewise_curve", "set_piecewise_curve",
            "clear_piecewise_curve", "check_piecewise_options"} <= names


def test_set_get_clear_round_trip(wired: RagnarokClient) -> None:
    async def go() -> None:
        ref = await tp.describe_piecewise()
        assert ref["optionKey"] == "options.piecewiseOptions"
        assert any(c["sheet"] == SHEET for c in ref["curves"])

        res = await tp.set_piecewise_curve(
            "Generator", "g1", "marginal_cost", [{"x": 0, "y": 0}, {"x": 0.5, "y": 10}, {"x": 1, "y": 40}], confirm=True
        )
        assert res["status"] == "set" and res["shape"] == "convex" and res["isMip"] is False
        got = await tp.get_piecewise_curve("generators", name="g1")
        assert got["count"] == 1
        curve = got["curves"][0]
        assert curve["sheet"] == SHEET and curve["shape"] == "convex"
        assert curve["breakpoints"] == [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 10.0}, {"x": 1.0, "y": 40.0}]

        # replacing keeps ONE curve, now non-convex (-> MIP)
        res2 = await tp.set_piecewise_curve(
            "Generator", "g1", "marginal_cost", [[0, 0], [0.5, 40], [1, 10]], confirm=True
        )
        assert res2["isMip"] is True
        got2 = await tp.get_piecewise_curve("Generator", name="g1", attribute="marginal_cost")
        assert [b["y"] for b in got2["curves"][0]["breakpoints"]] == [0.0, 40.0, 10.0]

        cleared = await tp.clear_piecewise_curve("Generator", "g1", "marginal_cost", confirm=True)
        assert cleared["status"] == "cleared"
        assert (await tp.get_piecewise_curve("Generator", name="g1"))["count"] == 0
        assert (await tp.clear_piecewise_curve("Generator", "g1", "marginal_cost", confirm=True))["status"] == "nothing to clear"

    run(go())


def test_invalid_input_is_reported_not_written(wired: RagnarokClient) -> None:
    async def go() -> None:
        assert "error" in await tp.set_piecewise_curve("Bus", "b", "marginal_cost", [[0, 0], [1, 1]], confirm=True)
        assert "error" in await tp.set_piecewise_curve("Generator", "g1", "p_nom", [[0, 0], [1, 1]], confirm=True)
        dup = await tp.set_piecewise_curve("Generator", "g1", "marginal_cost", [[0, 0], [0, 5], [1, 9]], confirm=True)
        assert "duplicate" in dup["error"]
        one = await tp.set_piecewise_curve("Generator", "g1", "marginal_cost", [[0, 0]], confirm=True)
        assert "at least 2" in one["error"]
        assert (await tp.get_piecewise_curve("Generator"))["count"] == 0

    run(go())


def test_run_option_key_is_validated_and_normalised(wired: RagnarokClient) -> None:
    async def go() -> None:
        out = await tp.check_piecewise_options(
            [{"component": "Generator", "attribute": "marginal_cost", "method": "sos2", "name": ["g1"]}]
        )
        assert out == {
            "piecewiseOptions": [
                {"component": "Generator", "attribute": "marginal_cost", "sign": ">=", "method": "sos2", "name": ["g1"]}
            ]
        }
        with pytest.raises(Exception):  # 400 from the backend surfaces as RagnarokAPIError
            await tp.check_piecewise_options([{"component": "Generator", "attribute": "bogus"}])

    run(go())
