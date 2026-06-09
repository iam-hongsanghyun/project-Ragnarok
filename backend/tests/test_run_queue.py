"""Tests for the disk-backed serial run queue (backend/app/main.py).

Covers enqueue ordering / position, payload retention, cancellation, rerun, and
explicit deletion. The actual subprocess execution is exercised by the
``_solve_worker`` test in test_run_store.py — here we test the queue bookkeeping
without spawning real solves.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.app import main, session_store
from backend.app.models import RunPayload


def _payload(label: str = "A", snaps: int = 10) -> RunPayload:
    return RunPayload(
        model={"buses": [{"name": "n1"}]},
        scenario={"label": label},
        options={
            "snapshotStart": 0,
            "snapshotEnd": snaps,
            "snapshotWeight": 1,
            "solverType": "auto",
            "filename": "case.xlsx",
        },
    )


@pytest.fixture(autouse=True)
def _clear_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_QUEUE_DIR", tmp_path / "queue")
    main._run_queue.clear()
    yield
    main._run_queue.clear()


def test_enqueue_appends_in_order_with_positions() -> None:
    r1 = asyncio.run(main.enqueue_run(_payload("A", 10)))
    r2 = asyncio.run(main.enqueue_run(_payload("B", 24)))
    assert r1["status"] == "queued" and r1["position"] == 1
    assert r2["position"] == 2

    jobs = main.get_queue()["jobs"]
    assert [j["label"] for j in jobs] == ["A", "B"]
    # The display summary is carried through.
    assert jobs[0]["snapshots"] == 10 and jobs[0]["snapshotWeight"] == 1
    assert jobs[1]["snapshots"] == 24
    assert jobs[0]["status"] == "queued"
    assert jobs[0]["payloadAvailable"] is True
    assert main._queue_payload_path(r1["id"]).exists()


def test_cancel_queued_marks_cancelled() -> None:
    r = asyncio.run(main.enqueue_run(_payload("A")))
    res = asyncio.run(main.cancel_queued(r["id"]))
    assert res["status"] == "cancelled"
    assert main.get_queue()["jobs"][0]["status"] == "cancelled"
    assert main._queue_payload_path(r["id"]).exists()


def test_cancel_unknown_is_not_found() -> None:
    assert asyncio.run(main.cancel_queued("does-not-exist"))["status"] == "not_found"


def test_rerun_queued_creates_new_item_from_retained_payload() -> None:
    r = asyncio.run(main.enqueue_run(_payload("Stopped", 12)))
    asyncio.run(main.cancel_queued(r["id"]))

    rerun = asyncio.run(main.rerun_queued(r["id"]))

    assert rerun["status"] == "queued"
    assert rerun["position"] == 1
    jobs = main.get_queue()["jobs"]
    assert [job["status"] for job in jobs] == ["cancelled", "queued"]
    assert [job["label"] for job in jobs] == ["Stopped", "Stopped"]
    assert main._queue_payload_path(rerun["id"]).exists()


def test_delete_queue_item_removes_payload_files() -> None:
    r = asyncio.run(main.enqueue_run(_payload("A")))
    payload_path = main._queue_payload_path(r["id"])
    assert payload_path.exists()

    res = asyncio.run(main.delete_queue_item(r["id"]))

    assert res["deleted"] is True
    assert main.get_queue()["jobs"] == []
    assert not payload_path.exists()


def _session_model() -> dict:
    return {
        "buses": [{"name": "n1", "v_nom": 380.0}],
        "snapshots": [{"snapshot": f"2030-01-01T{h:02d}:00:00"} for h in range(6)],
        "generators-p_max_pu": [
            {"snapshot": f"2030-01-01T{h:02d}:00:00", "g": float(h)} for h in range(6)
        ],
    }


@pytest.fixture()
def _session_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")


def test_enqueue_with_session_id_snapshots_model(_session_dir) -> None:
    # A thin client submits only a sessionId; the backend must snapshot the
    # session's model into the persisted payload so a later edit can't change it.
    session_store.save_model("default", _session_model(), filename="case.xlsx", scenario_name="ref")
    payload = RunPayload(
        scenario={"label": "ref"},
        options={"snapshotStart": 0, "snapshotEnd": 6},
        sessionId="default",
    )
    r = asyncio.run(main.enqueue_run(payload))
    assert r["status"] == "queued"
    stored = main._read_queue_payload(main._queue_payload_path(r["id"]))
    assert stored.model is not None
    assert stored.model["buses"][0]["name"] == "n1"
    assert "generators-p_max_pu" in stored.model


def test_enqueue_without_model_or_session_is_400(_session_dir) -> None:
    payload = RunPayload(scenario={}, options={})
    with pytest.raises(main.HTTPException) as exc:
        asyncio.run(main.enqueue_run(payload))
    assert exc.value.status_code == 400


def test_enqueue_with_unknown_session_is_400(_session_dir) -> None:
    payload = RunPayload(options={}, sessionId="ghost")
    with pytest.raises(main.HTTPException) as exc:
        asyncio.run(main.enqueue_run(payload))
    assert exc.value.status_code == 400


def test_load_queue_from_disk_marks_interrupted_running_job_cancelled() -> None:
    r = asyncio.run(main.enqueue_run(_payload("A")))
    item = main._run_queue[0]
    item.status = "running"
    item.started_at = main._now_iso()
    main._persist_queue_meta(item)

    main._run_queue.clear()
    main._load_queue_from_disk()

    jobs = main.get_queue()["jobs"]
    assert jobs[0]["id"] == r["id"]
    assert jobs[0]["status"] == "cancelled"
    assert "Backend stopped" in jobs[0]["error"]
