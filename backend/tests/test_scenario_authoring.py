"""Authoring saved scenarios and the DSL sheet through the API and MCP (MCP-only modelling).

The writes must produce the same ``RAGNAROK_Scenarios`` rows the browser's
``writeScenarioCatalogToModel`` writes, so a preset saved by an agent reads back
identically in the web UI and resolves to the same run body.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import main, model_store
from backend.app import scenario_presets as sp

SNAPS = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]


def _model() -> dict[str, list[dict[str, Any]]]:
    return {
        "buses": [{"name": "b"}],
        "snapshots": [{"snapshot": s} for s in SNAPS],
        "generators": [{"name": "g", "bus": "b", "carrier": "coal", "p_nom": 50.0}],
        "RAGNAROK_Scenarios": [
            {"id": "base", "label": "Base", "active": True, "notes": "", "json": json.dumps({"carbonPrice": 10})},
        ],
    }


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    """An in-memory session: reads return it, static merges write into it."""
    state = _model()

    def load(_sid: str, static_only: bool = False) -> dict[str, Any]:
        return {k: [dict(r) for r in v] for k, v in state.items()}

    def merge(_sid: str, sheets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        state.update({k: [dict(r) for r in v] for k, v in sheets.items()})
        return {"sessionId": _sid}

    monkeypatch.setattr(model_store, "load_full_model", load)
    monkeypatch.setattr(model_store, "merge_static_model", merge)
    return state


def test_upsert_merges_over_the_stored_preset_and_keeps_others() -> None:
    rows, preset = sp.upsert_scenario(_model(), "base", {"discountRate": 0.07})
    assert preset["carbonPrice"] == 10 and preset["discountRate"] == 0.07
    rows, preset = sp.upsert_scenario({**_model(), sp.SCENARIO_SHEET: rows}, "hi", {"carbonPrice": 90}, activate=True)
    catalog = sp.read_scenario_catalog({sp.SCENARIO_SHEET: rows})
    assert [s["id"] for s in catalog["scenarios"]] == ["base", "hi"]
    assert catalog["activeScenarioId"] == "hi"
    # a new preset starts from the defaults, like the UI's "New scenario"
    assert preset["pathwayConfig"] == sp.CONFIG_BLOCKS["pathwayConfig"][0]()


def test_written_rows_read_back_identically() -> None:
    model = _model()
    catalog = sp.read_scenario_catalog(model)
    rows = sp.write_scenario_catalog(model, catalog)
    again = sp.read_scenario_catalog({sp.SCENARIO_SHEET: rows})
    assert again["scenarios"] == catalog["scenarios"]
    assert again["activeScenarioId"] == catalog["activeScenarioId"]


def test_unknown_field_and_blank_id_are_refused() -> None:
    with pytest.raises(sp.ScenarioResolveError, match="forceLP"):
        sp.upsert_scenario(_model(), "x", {"forceLP": True})
    with pytest.raises(sp.ScenarioResolveError):
        sp.upsert_scenario(_model(), "  ", {})


def test_api_save_activate_delete_round_trip(store: dict[str, Any]) -> None:
    client = TestClient(main.app)
    r = client.put("/api/scenarios/peak", json={"fields": {"label": "Peak", "snapshotEnd": 2}, "activate": True})
    assert r.status_code == 200 and r.json()["active"] is True
    listed = client.get("/api/scenarios").json()
    assert listed["activeScenarioId"] == "peak"
    assert {s["id"] for s in listed["scenarios"]} == {"base", "peak"}
    # the saved preset resolves to a run body like any UI-authored one
    body = client.post("/api/scenarios/resolve", json={"scenarioId": "peak"}).json()
    assert body["options"]["snapshotEnd"] == 2
    assert client.post("/api/scenarios/base/activate").json()["activeScenarioId"] == "base"
    gone = client.delete("/api/scenarios/peak").json()
    assert gone == {"removed": "peak", "activeScenarioId": "base"}
    assert client.delete("/api/scenarios/peak").status_code == 404
    assert client.put("/api/scenarios/x", json={"fields": {"nope": 1}}).status_code == 400


def test_api_dsl_refuses_lines_that_do_not_parse(store: dict[str, Any]) -> None:
    client = TestClient(main.app)
    bad = client.put("/api/scenarios/dsl", json={"text": 'gen("coal") < 5'})
    assert bad.status_code == 400 and "line 1" in bad.json()["detail"]
    assert sp.CUSTOM_DSL_SHEET not in store
    ok = client.put("/api/scenarios/dsl", json={"text": 'gen("coal") <= 5'})
    assert ok.status_code == 200 and ok.json()["errors"] == []
    assert store[sp.CUSTOM_DSL_SHEET] == [{"text": 'gen("coal") <= 5'}]
    assert client.put("/api/scenarios/dsl", json={"text": ""}).status_code == 200
    assert store[sp.CUSTOM_DSL_SHEET] == []
