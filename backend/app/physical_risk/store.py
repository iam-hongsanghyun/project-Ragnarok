"""In-memory session + run store for the physical-risk capability.

Ported and simplified from climaterisk ``runs/store.py`` — SQLite persistence is
dropped, so this is a process-local dict store (Ragnarok is single-user, one
machine; the physical-risk session is transient scaffolding).

A run is created ``queued``, advances ``queued -> running -> done`` on poll, and
carries its per-kind result once ``done``. The stub engine is instantaneous, so a
run reaches ``done`` on its first poll after submission. Runs are session-scoped
and tagged with their ``kind`` so the report can bundle the latest result per kind.
"""
from __future__ import annotations

import threading
from typing import Any

from .engine import run_kind
from .entities import Portfolio, Run, RunStatus, Scenario


class _RunState:
    """Bookkeeping for a submitted run before/while the engine resolves it."""

    def __init__(
        self,
        run: Run,
        session_id: str,
        portfolio: Portfolio,
        perils: list[str],
        scenario: Scenario,
        options: dict[str, Any],
    ):
        self.run = run
        self.session_id = session_id
        self.portfolio = portfolio
        self.perils = perils
        self.scenario = scenario
        self.options = options


class PhysicalRiskStore:
    """Process-local store of physical-risk sessions and their runs."""

    def __init__(self) -> None:
        self._sessions: dict[str, Portfolio] = {}
        self._runs: dict[str, _RunState] = {}
        self._lock = threading.Lock()

    # ── sessions ────────────────────────────────────────────────────────────────

    def create_session(self, portfolio: Portfolio) -> Portfolio:
        """Store ``portfolio`` under its ``sessionId`` (overwriting any prior one)."""
        with self._lock:
            self._sessions[portfolio.sessionId] = portfolio
        return portfolio

    def get_session(self, session_id: str) -> Portfolio | None:
        with self._lock:
            return self._sessions.get(session_id)

    def save_session(self, session_id: str, portfolio: Portfolio) -> Portfolio | None:
        """Replace the stored portfolio for a session (full-model sync). None if unknown."""
        with self._lock:
            if session_id not in self._sessions:
                return None
            portfolio.sessionId = session_id
            self._sessions[session_id] = portfolio
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
        """Create a queued run of ``kind`` for the session's portfolio. None if unknown."""
        with self._lock:
            portfolio = self._sessions.get(session_id)
            if portfolio is None:
                return None
            run = Run(kind=kind, status=RunStatus.QUEUED.value)
            self._runs[run.id] = _RunState(
                run, session_id, portfolio, perils, scenario, options or {}
            )
            return run

    def poll_run(self, run_id: str, session_id: str | None = None) -> Run | None:
        """Return a run, advancing it toward completion.

        The stub engine is synchronous, so the first poll after submission runs
        the engine and finalises the run to ``done`` (or ``error``). When
        ``session_id`` is given, a run belonging to another session reads as
        unknown (None), mirroring climaterisk's session-scoped run routes.
        """
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                return None
            if session_id is not None and state.session_id != session_id:
                return None
            run = state.run
            if run.status in (RunStatus.DONE.value, RunStatus.ERROR.value):
                return run
            run.status = RunStatus.RUNNING.value
            try:
                run.result = run_kind(
                    run.kind, state.portfolio, state.perils, state.scenario, state.options
                )
                run.status = RunStatus.DONE.value
            except Exception as exc:  # noqa: BLE001 — surface any engine failure as run error
                run.status = RunStatus.ERROR.value
                run.error = str(exc)
            return run

    def latest_results(self, session_id: str) -> dict[str, Any]:
        """Latest DONE result per run kind for a session (submission order decides).

        Only runs already finalised by a poll are included — a queued run has no
        result yet, and the report endpoint must not silently execute work.
        """
        with self._lock:
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

        ``submit_run`` captures the session's portfolio object at submission time
        and ``save_session`` / ``create_session`` REPLACE (never mutate in place)
        the stored portfolio, so the captured reference is a stable snapshot of
        the run's inputs. Selection mirrors :meth:`latest_results` (submission
        order, last DONE run wins), so the returned portfolio always belongs to
        the same run whose result ``latest_results`` reports for ``kind``.
        Returns None when the session has no completed run of that kind.
        """
        with self._lock:
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
