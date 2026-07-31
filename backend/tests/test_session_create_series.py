"""Creating a time-series sheet that does not exist yet, over the real HTTP path.

The Model tab's "Import CSV" for a temporal sheet sends the parsed rows as
``addRow`` ops to ``PATCH /api/session/sheet/{name}`` — with no prior
``deleteRows``, because there is nothing to clear. If any link in
router → model_store → store refused an absent sheet, a model with no temporal
data could never be given any: importing a profile is the only way to create one,
and creating one is what the import does.

Covers both stores, since ``RAGNAROK_STORE=legacy`` is a supported escape hatch.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import session_store
from backend.app.main import app

client = TestClient(app)

SNAPS = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]


@pytest.fixture()
def _session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    return tmp_path


def _load_model_without_any_series() -> None:
    """A complete, runnable model that carries NO temporal sheet at all."""
    model = {
        "buses": [{"name": "b"}],
        "snapshots": [{"snapshot": s} for s in SNAPS],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
    }
    resp = client.post(
        "/api/session/model",
        json={"sessionId": "default", "model": model, "filename": "c.xlsx", "scenarioName": "ref"},
    )
    assert resp.status_code == 200, resp.text
    # Precondition: nothing temporal is present, so the tree has no populated leaf.
    sheets = {s["name"]: s for s in resp.json()["sheets"]}
    assert "loads-p_set" not in sheets


def _import_csv_rows() -> "object":
    """What `handleCsvFile` sends for a sheet with no current rows."""
    return client.patch(
        "/api/session/sheet/loads-p_set",
        json={
            "sessionId": "default",
            "ops": [
                {"op": "addRow", "values": {"snapshot": s, "L": float(h * 10)}}
                for h, s in enumerate(SNAPS)
            ],
        },
    )


def test_importing_a_profile_creates_the_absent_series_sheet(_session_dir: Path) -> None:
    _load_model_without_any_series()

    resp = _import_csv_rows()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "series"
    assert body["total"] == len(SNAPS)

    # Readable back through the same endpoint the grid uses.
    page = client.get("/api/session/sheet/loads-p_set", params={"limit": 100}).json()
    assert [r["L"] for r in page["rows"]] == [0.0, 10.0, 20.0, 30.0]
    assert [r["snapshot"] for r in page["rows"]] == SNAPS

    # And it now shows up as a POPULATED series sheet in the session meta — which
    # is what `seriesSheetCounts` reads to list the leaf in the sheet tree, so the
    # profile stays reachable after a reload without the "+ time series" reveal.
    meta = client.get("/api/session/meta", params={"session_id": "default"}).json()
    entry = next(s for s in meta["sheets"] if s["name"] == "loads-p_set")
    assert entry["kind"] == "series"
    assert entry["rowCount"] == len(SNAPS)

    # The full model carries it, so a run solves against the imported profile.
    full = client.get(
        "/api/session/model/full", params={"session_id": "default"}
    ).json()["model"]
    assert len(full["loads-p_set"]) == len(SNAPS)


def test_importing_a_profile_creates_it_on_the_legacy_store(
    _session_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app import model_store

    monkeypatch.setattr(model_store, "_impl", session_store)
    monkeypatch.setattr(model_store, "patch_sheet", session_store.patch_sheet)
    monkeypatch.setattr(model_store, "save_model", session_store.save_model)
    monkeypatch.setattr(model_store, "get_sheet_page", session_store.get_sheet_page)
    monkeypatch.setattr(model_store, "get_meta", session_store.get_meta)

    _load_model_without_any_series()
    resp = _import_csv_rows()

    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == len(SNAPS)
    page = client.get("/api/session/sheet/loads-p_set", params={"limit": 100}).json()
    assert [r["L"] for r in page["rows"]] == [0.0, 10.0, 20.0, 30.0]


def test_patch_still_404s_when_the_SESSION_is_missing(_session_dir: Path) -> None:
    """Create-on-write must not turn a bad session id into a silent success."""
    resp = client.patch(
        "/api/session/sheet/loads-p_set",
        json={"sessionId": "ghost", "ops": [{"op": "addRow", "values": {"snapshot": SNAPS[0]}}]},
    )
    assert resp.status_code == 404
