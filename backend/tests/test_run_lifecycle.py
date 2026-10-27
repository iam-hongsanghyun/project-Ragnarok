"""Run lifecycle fixes from the 2026-10-27 review (RS3, RS6) and RI5.

Covers the queue's stale-attempt guard, orphan pid identity, the pre-run
``validate_model`` gate and the examples directory.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

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
