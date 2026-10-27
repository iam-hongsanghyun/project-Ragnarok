"""Bifrost conversation sidecar: ``/api/export/project`` embeds it, ``/api/import/project/load`` returns it."""
from __future__ import annotations

import io
import zipfile
from typing import Any

from fastapi.testclient import TestClient

from backend.app.main import app

_MODEL = {
    "buses": [{"name": "n1", "v_nom": 380.0}],
    "generators": [{"name": "wind", "bus": "n1", "p_nom": 100.0, "carrier": "wind"}],
    "loads": [{"name": "load1", "bus": "n1", "p_set": 80.0}],
}
_CONVERSATION: dict[str, Any] = {
    "events": [
        {"type": "user", "text": "add a 50 MW gas unit"},
        {"type": "tool", "name": "add_generator", "ok": True},
    ],
    "model": "claude-sonnet-5-5",
    "autonomy": "approve-writes",
}


def _export(**extra: Any) -> bytes:
    resp = TestClient(app).post(
        "/api/export/project", json={"model": _MODEL, "scenario": {"carbonPrice": 10.0}, **extra},
    )
    assert resp.status_code == 200, resp.text
    return resp.content


def _load(data: bytes) -> dict[str, Any]:
    resp = TestClient(app).post(
        "/api/import/project/load", files={"file": ("p.zip", io.BytesIO(data), "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_conversation_round_trips_through_package() -> None:
    data = _export(conversation=_CONVERSATION)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert any(n.endswith(".conversation.json") for n in zf.namelist())
    body = _load(data)
    assert body["conversation"] == _CONVERSATION
    # the rest of the bundle is untouched by the sidecar
    assert {g["name"] for g in body["model"]["generators"]} == {"wind"}
    assert body["scenario"]["carbonPrice"] == 10.0


def test_no_conversation_means_no_sidecar_and_null_key() -> None:
    data = _export()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert not any(n.endswith(".conversation.json") for n in zf.namelist())
    body = _load(data)
    assert "conversation" in body and body["conversation"] is None
