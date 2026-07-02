"""W2 country starter-pack framework — recipe discovery + executor."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from backend.app import starter_packs


def test_list_recipes_finds_kor() -> None:
    packs = starter_packs.list_recipes()
    kor = next((p for p in packs if p["iso3"] == "KOR"), None)
    assert kor is not None
    assert kor["slots"] == ["network", "demand", "renewable_capacity", "renewable_profile"]


def test_load_recipe_and_missing() -> None:
    r = starter_packs.load_recipe("KOR", 2023)
    assert r is not None and r["iso3"] == "KOR"
    assert [s["datasets"][0] for s in r["steps"]][0] == "kpg193_network"
    assert starter_packs.load_recipe("ZZZ", 1999) is None


# ── Executor with a fake registry (offline) ─────────────────────────────────

class _FakeDB:
    def __init__(self, did: str) -> None:
        self._id = did

    async def fetch(self, region: Any, filters: dict, ctx: Any) -> dict:
        return {"id": self._id, "filters": filters}

    def preview(self, result: dict) -> str:
        return f"preview:{result['id']}"

    def to_sheets(self, result: dict, options: Any) -> str:
        return f"frag:{result['id']}"


def test_build_from_recipe_runs_every_step_in_order() -> None:
    recipe = {
        "iso3": "kor", "year": 2023,
        "steps": [
            {"slot": "network", "datasets": ["a"], "filters": {"v": 1}},
            {"slot": "demand", "datasets": ["b", "c"], "filters": {}},
        ],
    }
    dbs = {k: _FakeDB(k) for k in ("a", "b", "c")}
    region = SimpleNamespace(country_iso="KOR", country_name="South Korea")

    captured: dict[str, Any] = {}

    def fake_combine(frags, **kw):
        captured["frags"] = frags
        captured["kw"] = kw
        return SimpleNamespace(to_json=lambda: {"combined": frags})

    fragment, ids, previews = asyncio.run(starter_packs.build_from_recipe(
        recipe, dbs=dbs, region=region, ctx=None, options=None, combine=fake_combine,
    ))
    assert ids == ["a", "b", "c"]  # step order, datasets within a step preserved
    assert captured["frags"] == ["frag:a", "frag:b", "frag:c"]
    assert captured["kw"]["source_id"] == "starter:KOR"
    assert captured["kw"]["dataset_ids"] == ["a", "b", "c"]
    assert previews == ["preview:a", "preview:b", "preview:c"]
    assert fragment.to_json() == {"combined": ["frag:a", "frag:b", "frag:c"]}


def test_build_from_recipe_unknown_dataset_raises() -> None:
    recipe = {"iso3": "KOR", "year": 2023, "steps": [{"slot": "x", "datasets": ["missing"]}]}
    region = SimpleNamespace(country_iso="KOR", country_name="South Korea")
    try:
        asyncio.run(starter_packs.build_from_recipe(
            recipe, dbs={}, region=region, ctx=None, options=None, combine=lambda *a, **k: None,
        ))
        assert False, "expected KeyError"
    except KeyError as e:
        assert "missing" in str(e)


def test_list_endpoint() -> None:
    from fastapi.testclient import TestClient

    from backend.app.main import app

    c = TestClient(app)
    r = c.get("/api/import/starter-packs")
    assert r.status_code == 200
    assert any(p["iso3"] == "KOR" for p in r.json()["packs"])
