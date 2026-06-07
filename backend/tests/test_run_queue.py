"""Tests for the in-memory serial run queue (backend/app/main.py).

Covers enqueue ordering / position, the display summary, cancellation, and
pruning of stale terminal items. The actual subprocess execution is exercised
by the ``_solve_worker`` test in test_run_store.py — here we test the queue
bookkeeping without spawning real solves.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.app import main
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
def _clear_queue():
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


def test_cancel_queued_marks_cancelled() -> None:
    r = asyncio.run(main.enqueue_run(_payload("A")))
    res = asyncio.run(main.cancel_queued(r["id"]))
    assert res["status"] == "cancelled"
    assert main.get_queue()["jobs"][0]["status"] == "cancelled"


def test_cancel_unknown_is_not_found() -> None:
    assert asyncio.run(main.cancel_queued("does-not-exist"))["status"] == "not_found"


def test_prune_drops_old_terminal_items_only() -> None:
    fresh = main._QueueItem(
        id="fresh", payload=_payload(), label="fresh", summary={}, submitted_at=main._now_iso(),
        status="done", finished_at=main._now_iso(),
    )
    stale = main._QueueItem(
        id="stale", payload=_payload(), label="stale", summary={}, submitted_at=main._now_iso(),
        status="done",
        finished_at=(datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
    )
    queued = main._QueueItem(
        id="queued", payload=_payload(), label="queued", summary={}, submitted_at=main._now_iso(),
    )
    main._run_queue.extend([fresh, stale, queued])
    main._prune_queue()
    ids = [it.id for it in main._run_queue]
    assert "stale" not in ids  # old terminal pruned
    assert "fresh" in ids and "queued" in ids  # recent terminal + active kept
