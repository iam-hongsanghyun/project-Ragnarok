"""Run lifecycle fixes from the 2026-10-27 review (RS3, RS6) and RI5.

Covers the direct ``/api/run`` job store, the queue's stale-attempt guard, orphan
pid identity, the pre-run ``validate_model`` gate and the examples directory.
"""
from __future__ import annotations

import asyncio
import os
import queue
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app import main
from backend.app.models import RunPayload


def _valid_model() -> dict:
    return {
        "snapshots": [{"snapshot": f"2025-01-01 {h:02d}:00"} for h in range(2)],
        "buses": [{"name": "b"}],
        "loads": [{"name": "L", "bus": "b", "p_set": 10}],
        "generators": [{"name": "g", "bus": "b", "p_nom": 20, "marginal_cost": 1}],
    }


# ── RS3: the run is refused when validate_model reports errors ───────────────


def test_a_model_with_validation_errors_is_refused() -> None:
    bad = RunPayload(model={"buses": [{"name": "b"}]}, scenario={}, options={})
    with pytest.raises(HTTPException) as exc:
        main._refuse_invalid_model(bad)
    assert exc.value.status_code == 400
    assert "validation errors" in exc.value.detail and "No loads defined" in exc.value.detail


def test_a_valid_model_passes_the_gate() -> None:
    main._refuse_invalid_model(RunPayload(model=_valid_model(), scenario={}, options={}))


def test_enqueue_refuses_an_invalid_model_without_writing_a_queue_item() -> None:
    before = len(main._run_queue)
    with pytest.raises(HTTPException):
        asyncio.run(main.enqueue_run(RunPayload(model={"buses": [{"name": "b"}]}, scenario={}, options={})))
    assert len(main._run_queue) == before


# ── RS6: direct run — crash is an error, pruning is by age ───────────────────


class _DeadProc:
    exitcode = -9

    def is_alive(self) -> bool:
        return False


def test_a_crashed_worker_is_an_error_not_a_cancellation() -> None:
    job = main._Job(id="crash", proc=_DeadProc(), result_queue=queue.Queue())  # type: ignore[arg-type]
    main._jobs["crash"] = job
    try:
        asyncio.run(main._collect_job("crash"))
        assert job.status == "error"
        assert "exit code -9" in (job.error or "")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main.poll_run("crash"))
        assert exc.value.status_code == 500  # not 499 "cancelled"
    finally:
        main._jobs.pop("crash", None)


def test_a_result_put_just_before_exit_is_not_lost() -> None:
    q: queue.Queue = queue.Queue()
    job = main._Job(id="late", proc=_DeadProc(), result_queue=q)  # type: ignore[arg-type]
    main._jobs["late"] = job
    real_get_nowait = q.get_nowait
    calls = {"n": 0}

    def late_get_nowait():  # the first poll sees an empty pipe, the result lands after
        calls["n"] += 1
        if calls["n"] == 1:
            q.put(("ok", {"x": 1}))
            raise queue.Empty
        return real_get_nowait()

    q.get_nowait = late_get_nowait  # type: ignore[method-assign]
    try:
        asyncio.run(main._collect_job("late"))
        assert job.status == "done" and job.result == {"x": 1}
    finally:
        main._jobs.pop("late", None)


def test_cancelled_jobs_stay_cancelled() -> None:
    job = main._Job(id="c", proc=_DeadProc(), result_queue=queue.Queue(), status="cancelled")  # type: ignore[arg-type]
    main._jobs["c"] = job
    try:
        asyncio.run(main._collect_job("c"))
        assert job.status == "cancelled"
    finally:
        main._jobs.pop("c", None)


def test_prune_keeps_unread_results_until_the_retention_window_passes() -> None:
    from backend.app.config import load_system_defaults

    keep_for = float(load_system_defaults()["simulation"]["direct_job_retention_seconds"])
    fresh = main._Job(id="fresh", proc=None, result_queue=None, status="done", finished_at=time.monotonic())  # type: ignore[arg-type]
    old = main._Job(id="old", proc=None, result_queue=None, status="done",  # type: ignore[arg-type]
                    finished_at=time.monotonic() - keep_for - 5)
    running = main._Job(id="run", proc=None, result_queue=None)  # type: ignore[arg-type]
    main._jobs.update({"fresh": fresh, "old": old, "run": running})
    try:
        main._prune_direct_jobs()
        assert "fresh" in main._jobs and "run" in main._jobs and "old" not in main._jobs
    finally:
        for k in ("fresh", "old", "run"):
            main._jobs.pop(k, None)


# ── RS6: queue races and orphan identity ─────────────────────────────────────


def test_a_stale_attempt_cannot_force_the_new_attempt_to_error(tmp_path: Path) -> None:
    item = main._QueueItem(
        id="q1", payload_path=tmp_path / "p.json", label="x", summary={}, submitted_at="t", status="running"
    )
    item.attempt = 2
    main._finalize_queue_item(item, attempt=1)  # the cancelled attempt's task unwinding
    assert item.status == "running"
    main._finalize_queue_item(item, attempt=2)
    assert item.status == "error"


def test_a_recycled_pid_is_not_mistaken_for_the_solver() -> None:
    """This test process is alive but is not a multiprocessing-spawn worker."""
    if os.name == "nt":
        pytest.skip("identity probe is POSIX-only")
    assert main._pid_alive(os.getpid())
    assert not main._pid_is_solver(os.getpid())
    assert not main._pid_is_solver(None)


def test_rerun_forgets_the_previous_attempts_history_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(main, "_refuse_invalid_model", lambda payload: None)
    r = asyncio.run(main.enqueue_run(RunPayload(model=_valid_model(), scenario={}, options={}), staged=True))
    item = main._find_queue_item(r["id"])
    item.status, item.run_name, item.pid = "done", "old_run", 4242
    asyncio.run(main.rerun_queued(r["id"]))
    assert item.status == "queued" and item.run_name is None and item.pid is None
    asyncio.run(main.delete_queue_item(r["id"]))


# ── RI5: bundled examples do not depend on the runtime data dir ──────────────


def test_examples_dir_is_the_checkouts_bundled_data_not_the_data_root() -> None:
    from backend.app.routers import examples

    repo_backend = Path(main.__file__).resolve().parents[1]
    assert examples.EXAMPLES_DIR == repo_backend / "data" / "examples"
    assert examples.EXAMPLES_DIR.is_dir()
    assert any((d / "project.db").exists() for d in examples.EXAMPLES_DIR.iterdir() if d.is_dir())


def test_examples_still_listed_when_the_data_dir_is_relocated(tmp_path, monkeypatch) -> None:
    from backend.app import session_store
    from backend.app.routers import examples

    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "elsewhere" / "session")
    assert len(examples.list_examples()["examples"]) >= 1
