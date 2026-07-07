"""Async run-manager + disk-persistence tests for the physical-risk store.

Design under test (backend/app/physical_risk/store.py):

* ``submit_run`` returns a ``queued`` snapshot and dispatches execution to a
  background thread; ``poll_run`` is a PURE read (no compute in the request
  path) — proven with an Event-gated fake engine that would have deadlocked
  the old synchronous poll-executes design.
* Submit grace-joins the near-instant stub run (``worker.selected()`` False),
  preserving the pre-async single-poll contract the older tests rely on.
* Write-through JSON persistence under ``DATA_DIR``: sessions and terminal
  runs survive a "restart" (a fresh store instance on the same directory); a
  run still in flight when the process died resurfaces as ``error``.
* The outage-uplift path (``latest_results`` + ``latest_run_portfolio`` with
  the run-time frozen portfolio snapshot) keeps working after a restart.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from backend.app.physical_risk import store as store_module
from backend.app.physical_risk.entities import (
    Asset,
    PhysicalRunOutput,
    Portfolio,
    Run,
    Scenario,
)
from backend.app.physical_risk.store import PhysicalRiskStore
from backend.app.physical_risk_uplift import compute_for_rate_uplift

# Stub-engine tropical-cyclone EAI factor (engine.py::_PERIL_FACTOR) —
# duplicated, not imported, so an upstream factor change fails loudly here.
_TC_FACTOR = 0.0120

_VALUE = 1_000_000.0


@pytest.fixture(autouse=True)
def _stub_engine_and_isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the deterministic stub engine (a local .climada-env would route
    runs to real CLIMADA) and keep persistence out of backend/data."""
    monkeypatch.setenv("RAGNAROK_CLIMADA_WORKER", "0")
    monkeypatch.setattr(store_module, "DATA_DIR", tmp_path / "physical_risk")


def _portfolio(value: float = _VALUE) -> Portfolio:
    return Portfolio(
        assets=[Asset(name="g0", kind="generator", lat=37.5, lon=127.0, value=value)]
    )


def _wait_for_terminal(
    store: PhysicalRiskStore, sid: str, rid: str, timeout: float = 5.0
) -> Run:
    """Poll until the run reaches done/error (the async replacement for the old
    execute-on-first-poll contract)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = store.poll_run(rid, session_id=sid)
        assert run is not None
        if run.status in ("done", "error"):
            return run
        time.sleep(0.02)
    pytest.fail(f"run {rid} did not reach a terminal state within {timeout}s")


class _GatedEngine:
    """A fake engine that blocks until released — a stand-in for a minutes-long
    CLIMADA run, without wall-clock sleeps."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(
        self,
        kind: str,
        portfolio: Portfolio,
        perils: list[str],
        scenario: Scenario,
        options: dict[str, Any],
    ) -> PhysicalRunOutput:
        self.started.set()
        assert self.release.wait(timeout=30.0), "gated engine was never released"
        return PhysicalRunOutput(currency="USD", perils=[])


# ── async lifecycle ─────────────────────────────────────────────────────────────


def test_submit_returns_queued_and_polling_reaches_done(tmp_path: Path) -> None:
    store = PhysicalRiskStore(data_dir=tmp_path / "pr", stub_grace_s=0.0)
    pf = _portfolio()
    store.create_session(pf)

    run = store.submit_run(pf.sessionId, "physical", ["tropical_cyclone"], Scenario())
    assert run is not None
    assert run.status == "queued"  # the submit snapshot never blocks on the engine
    assert run.result is None

    done = _wait_for_terminal(store, pf.sessionId, run.id)
    assert done.status == "done"
    assert isinstance(done.result, PhysicalRunOutput)
    # Single asset at index 0 (spread 1.0): eai = value * tc factor.
    assert done.result.perils[0].aaiAgg == pytest.approx(_VALUE * _TC_FACTOR)


def test_grace_join_keeps_stub_runs_done_by_first_poll(tmp_path: Path) -> None:
    """Default stores grace-join the dispatched stub run, so the pre-async
    contract (submit, then ONE poll sees 'done') holds for the older tests
    and for snappy stub UX."""
    store = PhysicalRiskStore(data_dir=tmp_path / "pr")  # default grace
    pf = _portfolio()
    store.create_session(pf)

    run = store.submit_run(pf.sessionId, "physical", ["tropical_cyclone"], Scenario())
    assert run is not None
    assert run.status == "queued"

    first_poll = store.poll_run(run.id, session_id=pf.sessionId)
    assert first_poll is not None
    assert first_poll.status == "done"


def test_poll_is_a_pure_read_while_the_engine_is_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old store executed the engine inside poll_run under the store lock;
    with a gated engine that design would hang here forever. The async store
    must return 'running' promptly instead."""
    engine = _GatedEngine()
    monkeypatch.setattr(store_module, "run_kind", engine)
    store = PhysicalRiskStore(data_dir=tmp_path / "pr", stub_grace_s=0.0)
    pf = _portfolio()
    store.create_session(pf)
    run = store.submit_run(pf.sessionId, "physical", ["tropical_cyclone"], Scenario())
    assert run is not None
    try:
        assert engine.started.wait(timeout=5.0)  # the engine is genuinely mid-run
        t0 = time.monotonic()
        mid = store.poll_run(run.id, session_id=pf.sessionId)
        elapsed = time.monotonic() - t0
        assert mid is not None
        assert mid.status == "running"
        assert mid.result is None
        assert elapsed < 1.0  # no compute in the request path
    finally:
        engine.release.set()
    done = _wait_for_terminal(store, pf.sessionId, run.id)
    assert done.status == "done"


def test_concurrent_runs_and_mid_run_session_put_use_frozen_portfolios(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two in-flight runs on one session plus a session PUT mid-run: polls stay
    independent and prompt, and the run keeps the portfolio frozen at ITS
    submit — the PUT (which zeroes the asset value) must not leak into it."""
    engine = _GatedEngine()
    monkeypatch.setattr(store_module, "run_kind", engine)
    store = PhysicalRiskStore(data_dir=tmp_path / "pr", stub_grace_s=0.0)
    pf = _portfolio(value=_VALUE)
    store.create_session(pf)
    sid = pf.sessionId
    try:
        run_a = store.submit_run(sid, "physical", ["tropical_cyclone"], Scenario())
        run_b = store.submit_run(sid, "physical", ["river_flood"], Scenario())
        assert run_a is not None and run_b is not None
        assert engine.started.wait(timeout=5.0)

        # Full-document session PUT while both runs are in flight.
        edited = Portfolio(
            sessionId=sid,
            assets=[pf.assets[0].model_copy(update={"value": 0.0})],
            scenario=pf.scenario,
        )
        assert store.save_session(sid, edited) is not None

        for rid in (run_a.id, run_b.id):  # both poll promptly, non-terminal
            polled = store.poll_run(rid, session_id=sid)
            assert polled is not None
            assert polled.status in ("queued", "running")
    finally:
        engine.release.set()

    assert _wait_for_terminal(store, sid, run_a.id).status == "done"
    assert _wait_for_terminal(store, sid, run_b.id).status == "done"
    # The frozen snapshot (value 1e6), not the zeroed PUT, is the run's input record.
    frozen = store.latest_run_portfolio(sid, "physical")
    assert frozen is not None
    assert frozen.assets[0].value == pytest.approx(_VALUE)
    # The session document itself DID take the edit.
    current = store.get_session(sid)
    assert current is not None
    assert current.assets[0].value == pytest.approx(0.0)


def test_worker_pool_size_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGNAROK_PHYSICAL_RISK_WORKERS", "4")
    assert store_module._max_workers() == 4
    monkeypatch.setenv("RAGNAROK_PHYSICAL_RISK_WORKERS", "0")
    assert store_module._max_workers() == 1  # clamped to at least one thread
    monkeypatch.setenv("RAGNAROK_PHYSICAL_RISK_WORKERS", "not-a-number")
    assert store_module._max_workers() == 2
    monkeypatch.delenv("RAGNAROK_PHYSICAL_RISK_WORKERS")
    assert store_module._max_workers() == 2


# ── restart persistence ─────────────────────────────────────────────────────────


def test_sessions_and_done_runs_survive_restart(tmp_path: Path) -> None:
    root = tmp_path / "pr"
    first = PhysicalRiskStore(data_dir=root)
    pf = _portfolio()
    first.create_session(pf)
    run = first.submit_run(pf.sessionId, "physical", ["tropical_cyclone"], Scenario())
    assert run is not None
    assert _wait_for_terminal(first, pf.sessionId, run.id).status == "done"

    reborn = PhysicalRiskStore(data_dir=root)  # fresh instance = restarted backend
    session = reborn.get_session(pf.sessionId)
    assert session is not None
    assert [a.name for a in session.assets] == ["g0"]
    assert session.assets[0].value == pytest.approx(_VALUE)

    loaded = reborn.poll_run(run.id, session_id=pf.sessionId)
    assert loaded is not None
    assert loaded.status == "done"
    assert isinstance(loaded.result, PhysicalRunOutput)  # union rehydrates typed
    assert loaded.result.perils[0].aaiAgg == pytest.approx(_VALUE * _TC_FACTOR)

    latest = reborn.latest_results(pf.sessionId)
    assert set(latest) == {"physical"}


def test_error_runs_survive_restart_with_their_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(
        kind: str,
        portfolio: Portfolio,
        perils: list[str],
        scenario: Scenario,
        options: dict[str, Any],
    ) -> PhysicalRunOutput:
        raise ValueError("engine exploded")

    monkeypatch.setattr(store_module, "run_kind", _boom)
    root = tmp_path / "pr"
    first = PhysicalRiskStore(data_dir=root)
    pf = _portfolio()
    first.create_session(pf)
    run = first.submit_run(pf.sessionId, "physical", ["tropical_cyclone"], Scenario())
    assert run is not None
    failed = _wait_for_terminal(first, pf.sessionId, run.id)
    assert failed.status == "error"
    assert "engine exploded" in (failed.error or "")

    reborn = PhysicalRiskStore(data_dir=root)
    loaded = reborn.poll_run(run.id, session_id=pf.sessionId)
    assert loaded is not None
    assert loaded.status == "error"
    assert "engine exploded" in (loaded.error or "")
    assert reborn.latest_results(pf.sessionId) == {}  # error runs carry no result


def test_mid_flight_run_resurfaces_as_error_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run whose process dies mid-compute is 'queued' on disk (running is
    memory-only); the next store lineage must surface it as an explicit error,
    not poll it as running forever."""
    engine = _GatedEngine()
    monkeypatch.setattr(store_module, "run_kind", engine)
    root = tmp_path / "pr"
    first = PhysicalRiskStore(data_dir=root, stub_grace_s=0.0)
    pf = _portfolio()
    first.create_session(pf)
    try:
        run = first.submit_run(pf.sessionId, "physical", ["tropical_cyclone"], Scenario())
        assert run is not None
        assert engine.started.wait(timeout=5.0)  # genuinely mid-run

        reborn = PhysicalRiskStore(data_dir=root)  # 'restart' while still in flight
        loaded = reborn.poll_run(run.id, session_id=pf.sessionId)
        assert loaded is not None
        assert loaded.status == "error"
        assert "restarted mid-run" in (loaded.error or "")
        assert reborn.latest_results(pf.sessionId) == {}
    finally:
        engine.release.set()  # let the first lineage's thread finish cleanly


def test_latest_results_follow_submission_order_across_restart(tmp_path: Path) -> None:
    """'Latest done run wins' must survive a reload: run docs are re-ordered by
    their persisted submission counter, not by filesystem listing order."""
    root = tmp_path / "pr"
    first = PhysicalRiskStore(data_dir=root)
    pf = _portfolio()
    first.create_session(pf)
    sid = pf.sessionId
    run_a = first.submit_run(sid, "physical", ["tropical_cyclone"], Scenario())
    run_b = first.submit_run(sid, "physical", ["tropical_cyclone", "river_flood"], Scenario())
    assert run_a is not None and run_b is not None
    assert _wait_for_terminal(first, sid, run_a.id).status == "done"
    assert _wait_for_terminal(first, sid, run_b.id).status == "done"

    reborn = PhysicalRiskStore(data_dir=root)
    result = reborn.latest_results(sid)["physical"]
    assert [b.peril for b in result.perils] == ["tropical_cyclone", "river_flood"]  # run B


# ── the outage-uplift path after a restart ──────────────────────────────────────


def test_uplift_still_computes_after_restart(tmp_path: Path) -> None:
    """The forced-outage uplift injection reads latest_results +
    latest_run_portfolio; both must survive a backend restart (before disk
    persistence this was the silent data loss). The denominator must stay the
    run-time frozen value even when a session edit and the read straddle the
    restart."""
    root = tmp_path / "pr"
    first = PhysicalRiskStore(data_dir=root)
    pf = _portfolio(value=_VALUE)
    first.create_session(pf)
    run = first.submit_run(pf.sessionId, "physical", ["tropical_cyclone"], Scenario())
    assert run is not None
    assert _wait_for_terminal(first, pf.sessionId, run.id).status == "done"

    # Zero the asset AFTER the run completed (full-document PUT).
    current = first.get_session(pf.sessionId)
    assert current is not None
    edited = Portfolio(
        sessionId=pf.sessionId,
        assets=[current.assets[0].model_copy(update={"value": 0.0})],
        scenario=current.scenario,
    )
    assert first.save_session(pf.sessionId, edited) is not None

    reborn = PhysicalRiskStore(data_dir=root)
    uplift, note = compute_for_rate_uplift(reborn, pf.sessionId)
    assert uplift == pytest.approx({"g0": _TC_FACTOR})  # frozen 1e6 value, not the zeroed edit
    assert pf.sessionId in note
    assert "tropical_cyclone" in note


def test_pool_threads_are_daemon(tmp_path: Path) -> None:
    """Executor worker threads must be daemon so a run stuck in the CLIMADA
    subprocess never blocks interpreter/uvicorn shutdown (review regression)."""
    ex = store_module._executor()
    fut = ex.submit(lambda: None)
    fut.result(timeout=5)
    assert ex._threads, "no worker thread spawned"
    assert all(t.daemon for t in ex._threads)
    store_module.shutdown_executor()  # resets the singleton
    store_module.shutdown_executor()  # idempotent


def test_atomic_write_preserves_prior_on_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash mid terminal-write must leave the prior doc intact, not a
    truncated file — so a run's queued doc survives and resurfaces as a
    restart-error instead of vanishing (review regression)."""
    path = tmp_path / "runs" / "x.json"
    store_module._atomic_write_text(path, '{"status": "queued"}')
    assert path.read_text(encoding="utf-8") == '{"status": "queued"}'

    def _boom(self: Path, target: Path) -> None:  # simulated power loss at rename
        raise OSError("crash during rename")

    monkeypatch.setattr(Path, "replace", _boom)
    with pytest.raises(OSError):
        store_module._atomic_write_text(path, '{"status": "done", "more": "data"}')
    monkeypatch.undo()

    # Prior content intact; no partial doc replaced it.
    assert path.read_text(encoding="utf-8") == '{"status": "queued"}'
