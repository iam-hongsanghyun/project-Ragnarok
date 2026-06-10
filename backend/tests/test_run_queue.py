"""Tests for the disk-backed serial run queue (backend/app/main.py).

Covers enqueue ordering / position, payload retention, cancellation, rerun, and
explicit deletion. The actual subprocess execution is exercised by the
``_solve_worker`` test in test_run_store.py — here we test the queue bookkeeping
without spawning real solves.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from backend.app import main, model_store, session_store
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


def test_rerun_reactivates_in_place_no_duplicate() -> None:
    r = asyncio.run(main.enqueue_run(_payload("Stopped", 12)))
    asyncio.run(main.cancel_queued(r["id"]))

    rerun = asyncio.run(main.rerun_queued(r["id"]))

    # Same card, flipped back to queued — no duplicate row, no duplicated model.
    assert rerun["status"] == "queued"
    assert rerun["id"] == r["id"]
    jobs = main.get_queue()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "queued" and jobs[0]["label"] == "Stopped"


def test_enqueue_staged_parks_without_running() -> None:
    r = asyncio.run(main.enqueue_run(_payload("Later", 10), staged=True))
    assert r["status"] == "staged"
    jobs = main.get_queue()["jobs"]
    assert jobs[0]["status"] == "staged"
    # The pump only picks "queued" items, so a staged item is never auto-run.
    nxt = next((it for it in main._run_queue if it.status == "queued"), None)
    assert nxt is None


def test_staged_then_run_activates_in_place() -> None:
    r = asyncio.run(main.enqueue_run(_payload("Later", 10), staged=True))
    res = asyncio.run(main.rerun_queued(r["id"]))
    assert res["status"] == "queued" and res["id"] == r["id"]
    assert len(main.get_queue()["jobs"]) == 1


def test_cancel_staged_marks_cancelled() -> None:
    r = asyncio.run(main.enqueue_run(_payload("Later", 10), staged=True))
    res = asyncio.run(main.cancel_queued(r["id"]))
    assert res["status"] == "cancelled"


def test_import_queue_item_loads_model_into_session(_session_dir) -> None:
    # Set up + assert via the model_store facade (the active store production uses).
    model_store.save_model("default", _session_model(), filename="case.xlsx", scenario_name="ref")
    payload = RunPayload(scenario={"label": "ref"}, options={"snapshotStart": 0, "snapshotEnd": 6}, sessionId="default")
    r = asyncio.run(main.enqueue_run(payload))
    # Clear the session, then import the queued item's snapshot back into it.
    model_store.clear("default")
    meta = asyncio.run(main.import_queue_item(r["id"]))
    assert meta["componentCounts"].get("buses") == 1
    assert model_store.get_meta("default") is not None


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


# ── Restart recovery: a backend restart must not lose a running solve ─────────


def _mark_running(item, pid: int | None = None) -> None:
    item.status = "running"
    item.started_at = main._now_iso()
    item.pid = pid
    main._persist_queue_meta(item)


def test_restart_recovery_dead_worker_is_error_not_cancelled() -> None:
    # No outcome on disk and the pid is gone → the job is reported as an ERROR
    # ("rerun"), never silently "cancelled" (the user didn't cancel anything).
    r = asyncio.run(main.enqueue_run(_payload("A")))
    _mark_running(main._run_queue[0], pid=2**22 + 12345)  # certainly not alive

    main._run_queue.clear()
    main._load_queue_from_disk()

    jobs = main.get_queue()["jobs"]
    assert jobs[0]["id"] == r["id"]
    assert jobs[0]["status"] == "error"
    assert "Rerun" in jobs[0]["error"]


def test_restart_recovery_adopts_finished_orphan_outcome() -> None:
    # The worker finished while the backend was down (outcome.json on disk) →
    # the restarted backend adopts it as DONE; the run is already in History.
    r = asyncio.run(main.enqueue_run(_payload("B")))
    item = main._run_queue[0]
    _mark_running(item)
    main._write_json_atomic(
        main._queue_outcome_path(item.id),
        {"status": "done", "runName": "b_2026-01-01T00-00-00", "error": None, "finishedAt": main._now_iso()},
    )

    main._run_queue.clear()
    main._load_queue_from_disk()

    jobs = main.get_queue()["jobs"]
    assert jobs[0]["id"] == r["id"]
    assert jobs[0]["status"] == "done"
    assert jobs[0]["error"] is None


def test_restart_recovery_keeps_live_orphan_running() -> None:
    # The worker is STILL solving (its pid is alive) → the card stays "running";
    # the lifespan watcher will flip it when outcome.json appears.
    asyncio.run(main.enqueue_run(_payload("C")))
    item = main._run_queue[0]
    _mark_running(item, pid=os.getpid())  # this test process: definitely alive

    main._run_queue.clear()
    main._load_queue_from_disk()

    jobs = main.get_queue()["jobs"]
    assert jobs[0]["status"] == "running"


def test_orphan_watcher_flips_running_to_done() -> None:
    # While "running" with a live pid, the watcher adopts outcome.json as soon
    # as the worker writes it.
    asyncio.run(main.enqueue_run(_payload("D")))
    item = main._run_queue[0]
    _mark_running(item, pid=os.getpid())

    async def run_watch() -> None:
        watch = asyncio.ensure_future(main._watch_orphan(item))
        await asyncio.sleep(0.05)
        main._write_json_atomic(
            main._queue_outcome_path(item.id),
            {"status": "done", "runName": "d_run", "error": None, "finishedAt": main._now_iso()},
        )
        await asyncio.wait_for(watch, timeout=10)

    asyncio.run(run_watch())
    assert item.status == "done"
    assert item.finished_at is not None
