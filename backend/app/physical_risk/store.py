"""Disk-persisted session + run store for the physical-risk capability.

Phase 0 was a process-local dict store with a SYNCHRONOUS run lifecycle: the
first poll executed the engine inline while holding the store lock. Both
properties broke once the real CLIMADA worker attached (runs take minutes, so
one running job would freeze every other physical-risk request, including
polls of other runs) and on backend restarts (portfolios and results vanished,
silently starving the outage-uplift injection in
:mod:`backend.app.physical_risk_uplift`).

This version keeps the same public surface (``create_session`` /
``get_session`` / ``save_session`` / ``submit_run`` / ``poll_run`` /
``latest_results`` / ``latest_run_portfolio``) with two structural changes:

**Async run manager.** ``submit_run`` creates the run ``queued``, freezes the
session portfolio into the run state (BEFORE dispatch, so a session PUT during
a run cannot skew its inputs), and hands execution to a small process-wide
``ThreadPoolExecutor`` (``RAGNAROK_PHYSICAL_RISK_WORKERS`` threads, default 2
— a fixed pool, so concurrency stays bounded no matter how many runs are
submitted). The executing thread calls ``engine.run_kind`` WITHOUT holding the
store lock and takes it only to write status transitions (queued -> running ->
done/error). ``poll_run`` is a PURE read. Because the stub engine is
near-instant, ``submit_run`` grace-joins the dispatched future for up to
``_STUB_GRACE_S`` seconds when the CLIMADA worker is NOT selected
(``worker.selected()``), so stub runs are already ``done`` by the caller's
first poll — the pre-async single-poll contract (tests and snappy UX) holds
unchanged. With the real worker selected, submit returns immediately and the
frontend polls through queued/running.

**Write-through JSON persistence.** Sessions and runs are mirrored to
:data:`DATA_DIR` (default ``backend/data/physical_risk/``, override with the
``RAGNAROK_PHYSICAL_RISK_DIR`` env var; tests monkeypatch the module attribute
exactly like ``session_store.SESSION_DIR``)::

    sessions/<session_id>.json   # the Portfolio document
    runs/<run_id>.json           # run + frozen portfolio + request params

A run doc is written once at submission (status ``queued``) and rewritten once
on reaching ``done``/``error`` — the transient ``running`` state stays
memory-only. The store loads lazily on first access (and reloads whenever the
resolved root changes, which is what makes the monkeypatch pattern work on the
process-wide singleton); any run found non-terminal on disk died with a
previous process and resurfaces as ``error`` ("backend restarted mid-run").
Run docs carry the frozen portfolio snapshot, so ``latest_run_portfolio`` —
the outage-uplift damage-ratio denominator source — survives restarts.
"""
from __future__ import annotations

import atexit
import concurrent.futures.thread as _cf_thread
import logging
import os
import re
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from . import worker
from .engine import run_kind
from .entities import Portfolio, Run, RunStatus, Scenario

logger = logging.getLogger(__name__)

# ``__file__`` is backend/app/physical_risk/store.py -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _default_data_dir() -> Path:
    """The persistence root: ``RAGNAROK_PHYSICAL_RISK_DIR`` env override first."""
    raw = os.environ.get("RAGNAROK_PHYSICAL_RISK_DIR", "").strip()
    return Path(raw).expanduser() if raw else _REPO_ROOT / "backend" / "data" / "physical_risk"


# Module-level so tests can monkeypatch it (mirrors session_store.SESSION_DIR).
# Stores without an explicit data_dir re-resolve this on EVERY access and
# reload when it changes, so patching it redirects the singleton too.
DATA_DIR = _default_data_dir()

# Grace window (seconds) submit_run waits on the dispatched future when the
# stub engine is selected: the stub is near-instant, so a stub run is 'done'
# by the time the caller's first poll lands (pre-async contract + snappy UX).
_STUB_GRACE_S = 0.5

# Error put on runs found non-terminal on disk at load: their executor thread
# belonged to a previous backend process and is gone.
_RESTART_ERROR = "backend restarted mid-run — submit the run again."

_TERMINAL = (RunStatus.DONE.value, RunStatus.ERROR.value)

# Session/run ids become file names — same traversal guard as session_store.
_ID_GUARD = re.compile(r"^[A-Za-z0-9._\-]+$")


def _max_workers() -> int:
    """Executor size from ``RAGNAROK_PHYSICAL_RISK_WORKERS`` (default 2, min 1)."""
    raw = os.environ.get("RAGNAROK_PHYSICAL_RISK_WORKERS", "").strip()
    try:
        n = int(raw) if raw else 2
    except ValueError:
        return 2
    return max(1, n)


# One process-wide executor shared by every store instance, created lazily on
# the first submit: total physical-risk compute concurrency stays bounded no
# matter how many store instances exist (tests create many).
def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (tmp file + os.replace).

    A crash/power-loss mid-write leaves only the ``.tmp`` partial; the prior
    contents of ``path`` stay intact. This matters because a run's terminal
    doc rewrites the same file as its ``queued`` submission record — a bare
    truncating write that dies half-done would drop the run entirely on
    restart (and silently disable the outage FOR-uplift) instead of letting
    the intact ``queued`` doc resurface as a "backend restarted mid-run" error.
    Mirrors ``main.py``'s ``_write_json_atomic``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class _DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor whose worker threads are daemon.

    A physical-risk job blocks its pool thread inside the (multi-minute) CLIMADA
    subprocess. The stdlib's non-daemon pool threads are JOINED at interpreter
    exit, so a Ctrl-C / ``uvicorn --reload`` / SIGTERM taken during a real run
    would hang shutdown for up to the worker timeout (default 900s). Daemon
    threads are not joined, so shutdown is immediate; the killed run's ``queued``
    doc resurfaces as an error on the next start. Overrides ``_adjust_thread_count``
    (CPython 3.11–3.13 internals: ``_worker(executor_reference, work_queue,
    initializer, initargs)`` + ``_threads_queues``), falling back to the default
    non-daemon behaviour if those internals ever change.
    """

    def _adjust_thread_count(self) -> None:
        try:
            if self._idle_semaphore.acquire(timeout=0):
                return

            def _weakref_cb(_: Any, q: Any = self._work_queue) -> None:
                q.put(None)

            num = len(self._threads)
            if num >= self._max_workers:
                return
            name = f"{self._thread_name_prefix or self}_{num}"
            t = threading.Thread(
                name=name,
                target=_cf_thread._worker,
                args=(weakref.ref(self, _weakref_cb), self._work_queue,
                      self._initializer, self._initargs),
                daemon=True,
            )
            t.start()
            self._threads.add(t)
            _cf_thread._threads_queues[t] = self._work_queue
        except (AttributeError, TypeError):  # stdlib internals changed — be safe
            super()._adjust_thread_count()


_EXECUTOR_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR  # noqa: PLW0603 — process-wide lazy singleton
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = _DaemonThreadPoolExecutor(
                max_workers=_max_workers(), thread_name_prefix="physical-risk-run"
            )
        return _EXECUTOR


def shutdown_executor() -> None:
    """Stop the run executor without waiting for in-flight jobs.

    Called from the FastAPI lifespan shutdown and registered with ``atexit`` so
    a clean stop cancels queued runs and returns promptly; daemon threads mean a
    job already inside the CLIMADA subprocess never holds up interpreter exit.
    """
    global _EXECUTOR  # noqa: PLW0603
    with _EXECUTOR_LOCK:
        ex, _EXECUTOR = _EXECUTOR, None
    if ex is not None:
        ex.shutdown(wait=False, cancel_futures=True)


atexit.register(shutdown_executor)


def _is_safe_id(doc_id: str) -> bool:
    return bool(doc_id) and ".." not in doc_id and bool(_ID_GUARD.match(doc_id))


def _jsonable(value: Any) -> Any:
    """Recursively convert pydantic models inside plain containers to dicts.

    Run options may carry model instances (e.g. cost-benefit ``MeasureSpec``
    lists); the persisted run doc needs plain JSON data.
    """
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class _RunDoc(BaseModel):
    """The persisted form of one run: the Run plus its frozen inputs.

    ``seq`` is a store-lineage-wide monotonic submission counter so that after
    a reload the "latest run wins" semantics of :meth:`~PhysicalRiskStore.
    latest_results` / :meth:`~PhysicalRiskStore.latest_run_portfolio` still
    follow submission order (filesystem listing order is arbitrary).
    ``portfolio`` is the snapshot the run was computed on (frozen at submit) —
    persisting it keeps the outage-uplift damage ratio (eai/value) correct
    across restarts even when the session portfolio is edited afterwards.
    ``perils``/``scenario``/``options`` are provenance only: a loaded run is
    never re-executed.
    """

    seq: int = 0
    sessionId: str
    perils: list[str] = Field(default_factory=list)
    scenario: Scenario = Field(default_factory=Scenario)
    options: dict[str, Any] = Field(default_factory=dict)
    portfolio: Portfolio
    run: Run


class _RunState:
    """In-memory bookkeeping for a submitted run."""

    def __init__(
        self,
        run: Run,
        session_id: str,
        portfolio: Portfolio,
        perils: list[str],
        scenario: Scenario,
        options: dict[str, Any],
        seq: int,
    ):
        self.run = run
        self.session_id = session_id
        self.portfolio = portfolio
        self.perils = perils
        self.scenario = scenario
        self.options = options
        self.seq = seq


class PhysicalRiskStore:
    """Disk-backed store of physical-risk sessions and their (async) runs.

    Args:
        data_dir: Explicit persistence root (tests pass a tmp dir). ``None``
            resolves the module-level :data:`DATA_DIR` on every access, so
            monkeypatching that attribute redirects the process-wide singleton.
        stub_grace_s: Submit-side grace-join budget override in seconds; tests
            pass ``0.0`` to observe the queued/running states of a gated fake
            engine. ``None`` uses :data:`_STUB_GRACE_S`.
    """

    def __init__(
        self, data_dir: Path | None = None, *, stub_grace_s: float | None = None
    ) -> None:
        self._data_dir = data_dir
        self._stub_grace_s = _STUB_GRACE_S if stub_grace_s is None else stub_grace_s
        self._sessions: dict[str, Portfolio] = {}
        self._runs: dict[str, _RunState] = {}
        self._next_seq = 1
        self._loaded_root: Path | None = None
        self._lock = threading.Lock()

    # ── persistence ─────────────────────────────────────────────────────────────

    def _root(self) -> Path:
        return self._data_dir if self._data_dir is not None else DATA_DIR

    def _ensure_loaded_locked(self) -> None:
        """Lazily hydrate the in-memory maps from ``_root()`` (caller holds the lock).

        Runs whenever the resolved root differs from the one last loaded — the
        first access after process start, and after a test monkeypatches
        :data:`DATA_DIR`. Runs found non-terminal on disk are finalised to
        ``error`` (their worker thread died with the previous process) and the
        correction is written back.
        """
        root = self._root()
        if self._loaded_root == root:
            return
        self._sessions.clear()
        self._runs.clear()
        self._next_seq = 1
        self._loaded_root = root

        sessions_dir = root / "sessions"
        if sessions_dir.is_dir():
            for path in sorted(sessions_dir.glob("*.json")):
                try:
                    portfolio = Portfolio.model_validate_json(path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001 — one bad doc must not block the rest
                    logger.exception("physical-risk store: unreadable session doc %s — skipped", path)
                    continue
                self._sessions[portfolio.sessionId] = portfolio

        docs: list[_RunDoc] = []
        runs_dir = root / "runs"
        if runs_dir.is_dir():
            for path in runs_dir.glob("*.json"):
                try:
                    docs.append(_RunDoc.model_validate_json(path.read_text(encoding="utf-8")))
                except Exception:  # noqa: BLE001 — one bad doc must not block the rest
                    logger.exception("physical-risk store: unreadable run doc %s — skipped", path)
        docs.sort(key=lambda d: d.seq)  # restore submission order (dicts keep insertion order)

        interrupted = 0
        for doc in docs:
            state = _RunState(
                doc.run,
                doc.sessionId,
                doc.portfolio,
                list(doc.perils),
                doc.scenario,
                dict(doc.options),
                seq=doc.seq,
            )
            if state.run.status not in _TERMINAL:
                state.run.status = RunStatus.ERROR.value
                state.run.error = _RESTART_ERROR
                self._persist_run_locked(state)
                interrupted += 1
            self._runs[state.run.id] = state
            self._next_seq = max(self._next_seq, doc.seq + 1)
        if interrupted:
            logger.warning(
                "physical-risk store: %d run(s) were in flight when the backend "
                "stopped — marked error", interrupted,
            )
        if self._sessions or self._runs:
            logger.info(
                "physical-risk store: loaded %d session(s), %d run(s) from %s",
                len(self._sessions), len(self._runs), root,
            )

    def _persist_session_locked(self, portfolio: Portfolio) -> None:
        """Write-through mirror of one session doc (caller holds the lock)."""
        sid = portfolio.sessionId
        if not _is_safe_id(sid):
            logger.warning("physical-risk store: unsafe session id %r — not persisted", sid)
            return
        path = self._root() / "sessions" / f"{sid}.json"
        try:
            _atomic_write_text(path, portfolio.model_dump_json())
        except OSError:
            logger.exception("physical-risk store: could not persist session %s", sid)

    def _persist_run_locked(self, state: _RunState) -> None:
        """Write-through mirror of one run doc (caller holds the lock)."""
        run_id = state.run.id
        if not _is_safe_id(run_id):
            logger.warning("physical-risk store: unsafe run id %r — not persisted", run_id)
            return
        doc = _RunDoc(
            seq=state.seq,
            sessionId=state.session_id,
            perils=list(state.perils),
            scenario=state.scenario,
            options=_jsonable(state.options),
            portfolio=state.portfolio,
            run=state.run,
        )
        path = self._root() / "runs" / f"{run_id}.json"
        try:
            _atomic_write_text(path, doc.model_dump_json())
        except OSError:
            logger.exception("physical-risk store: could not persist run %s", run_id)

    # ── sessions ────────────────────────────────────────────────────────────────

    def create_session(self, portfolio: Portfolio) -> Portfolio:
        """Store ``portfolio`` under its ``sessionId`` (overwriting any prior one)."""
        with self._lock:
            self._ensure_loaded_locked()
            self._sessions[portfolio.sessionId] = portfolio
            self._persist_session_locked(portfolio)
        return portfolio

    def get_session(self, session_id: str) -> Portfolio | None:
        with self._lock:
            self._ensure_loaded_locked()
            return self._sessions.get(session_id)

    def save_session(self, session_id: str, portfolio: Portfolio) -> Portfolio | None:
        """Replace the stored portfolio for a session (full-model sync). None if unknown.

        REPLACES (never mutates in place) the stored document, so a portfolio
        frozen into an in-flight run's state stays a stable snapshot of that
        run's inputs.
        """
        with self._lock:
            self._ensure_loaded_locked()
            if session_id not in self._sessions:
                return None
            portfolio.sessionId = session_id
            self._sessions[session_id] = portfolio
            self._persist_session_locked(portfolio)
            return portfolio

    # ── runs ────────────────────────────────────────────────────────────────────

    def submit_run(
        self,
        session_id: str,
        kind: str,
        perils: list[str],
        scenario: Scenario,
        options: dict[str, Any] | None = None,
    ) -> Run | None:
        """Create a queued run of ``kind`` and dispatch it to the executor.

        The session's portfolio is frozen into the run state HERE, before
        dispatch, so a session PUT during execution cannot alter the run's
        inputs. The returned Run is a snapshot taken at creation time (status
        ``queued``) — poll for progress. When the CLIMADA worker is NOT
        selected, the call grace-joins the future for up to ``stub_grace_s``
        seconds so the near-instant stub run is already ``done`` by the
        caller's first poll. Returns None if the session is unknown.
        """
        with self._lock:
            self._ensure_loaded_locked()
            portfolio = self._sessions.get(session_id)
            if portfolio is None:
                return None
            run = Run(kind=kind, status=RunStatus.QUEUED.value)
            state = _RunState(
                run,
                session_id,
                portfolio,
                list(perils),
                scenario,
                dict(options or {}),
                seq=self._next_seq,
            )
            self._next_seq += 1
            self._runs[run.id] = state
            # Submission record (status 'queued'): after a process death, this
            # is what resurfaces as "error: backend restarted mid-run".
            self._persist_run_locked(state)
            snapshot = run.model_copy(deep=True)
        future = _executor().submit(self._execute, run.id)
        if self._stub_grace_s > 0 and not worker.selected():
            try:  # stub engine: near-instant — join so the first poll sees 'done'
                future.result(timeout=self._stub_grace_s)
            except Exception:  # noqa: BLE001 — best-effort; poll reports the real state
                pass
        return snapshot

    def _execute(self, run_id: str) -> None:
        """Executor-thread body: run the engine WITHOUT holding the store lock.

        The lock is taken only to snapshot the frozen inputs and to write the
        status transitions, so a minutes-long CLIMADA run never blocks other
        store calls. Never raises — any engine failure lands on the run as
        status ``error``.
        """
        with self._lock:
            state = self._runs.get(run_id)
            if state is None or state.run.status != RunStatus.QUEUED.value:
                return  # reloaded away or already dispatched — nothing to do
            state.run.status = RunStatus.RUNNING.value  # memory-only; disk keeps 'queued'
            kind = state.run.kind
            portfolio = state.portfolio
            perils = list(state.perils)
            scenario = state.scenario
            options = dict(state.options)
        try:
            result = run_kind(kind, portfolio, perils, scenario, options)
        except Exception as exc:  # noqa: BLE001 — surface any engine failure as run error
            logger.warning("physical-risk run %s (%s) failed: %s", run_id, kind, exc)
            with self._lock:
                state.run.status = RunStatus.ERROR.value
                state.run.error = str(exc)
                self._persist_run_locked(state)
            return
        with self._lock:
            state.run.result = result
            state.run.status = RunStatus.DONE.value
            self._persist_run_locked(state)

    def poll_run(self, run_id: str, session_id: str | None = None) -> Run | None:
        """Return a snapshot of a run's current state — a PURE read, no compute.

        The run executes on a background thread (see :meth:`submit_run`);
        polling only snapshots status/result under the lock, so polls return
        promptly while a real CLIMADA run takes minutes. When ``session_id``
        is given, a run belonging to another session reads as unknown (None),
        mirroring climaterisk's session-scoped run routes. The snapshot is a
        deep copy, so response serialisation can never observe a half-written
        status transition.
        """
        with self._lock:
            self._ensure_loaded_locked()
            state = self._runs.get(run_id)
            if state is None:
                return None
            if session_id is not None and state.session_id != session_id:
                return None
            return state.run.model_copy(deep=True)

    def latest_results(self, session_id: str) -> dict[str, Any]:
        """Latest DONE result per run kind for a session (submission order decides).

        Only runs the background executor has finalised are included — a
        queued/running run has no result yet, and the report endpoint must not
        silently execute work.
        """
        with self._lock:
            self._ensure_loaded_locked()
            out: dict[str, Any] = {}
            for state in self._runs.values():  # dicts preserve insertion (submission) order
                run = state.run
                if (
                    state.session_id == session_id
                    and run.status == RunStatus.DONE.value
                    and run.result is not None
                ):
                    out[run.kind] = run.result
            return out

    def latest_run_portfolio(self, session_id: str, kind: str) -> Portfolio | None:
        """The portfolio snapshot the latest DONE run of ``kind`` was computed on.

        ``submit_run`` captures the session's portfolio object at submission
        time (before dispatch) and ``save_session`` / ``create_session``
        REPLACE (never mutate in place) the stored portfolio, so the captured
        reference is a stable snapshot of the run's inputs — and it is
        persisted inside the run doc, so it survives restarts. Selection
        mirrors :meth:`latest_results` (submission order, last DONE run wins),
        so the returned portfolio always belongs to the same run whose result
        ``latest_results`` reports for ``kind``. Returns None when the session
        has no completed run of that kind.
        """
        with self._lock:
            self._ensure_loaded_locked()
            out: Portfolio | None = None
            for state in self._runs.values():  # dicts preserve insertion (submission) order
                run = state.run
                if (
                    state.session_id == session_id
                    and run.kind == kind
                    and run.status == RunStatus.DONE.value
                    and run.result is not None
                ):
                    out = state.portfolio
            return out


# Process-wide singleton (mirrors Ragnarok's single-session model_store facade).
store = PhysicalRiskStore()
