"""In-memory session + run store for the physical-risk capability.

Ported and simplified from climaterisk ``runs/store.py`` — SQLite persistence is
dropped for Phase 0, so this is a process-local dict store (Ragnarok is
single-user, one machine; the physical-risk session is transient scaffolding).

A run is created ``queued``, advances ``queued -> running -> done`` on poll, and
carries its :class:`PhysicalRunOutput` once ``done``. The stub engine is
instantaneous, so a run reaches ``done`` on its first poll after submission.
"""
from __future__ import annotations

import threading

from .engine import run_physical
from .entities import Portfolio, Run, RunStatus, Scenario


class _RunState:
    """Bookkeeping for a submitted run before/while the engine resolves it."""

    def __init__(self, run: Run, portfolio: Portfolio, perils: list[str], scenario: Scenario):
        self.run = run
        self.portfolio = portfolio
        self.perils = perils
        self.scenario = scenario


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

    def submit_run(self, session_id: str, perils: list[str], scenario: Scenario) -> Run | None:
        """Create a queued run for the session's portfolio. None if the session is unknown."""
        with self._lock:
            portfolio = self._sessions.get(session_id)
            if portfolio is None:
                return None
            run = Run(status=RunStatus.QUEUED.value)
            self._runs[run.id] = _RunState(run, portfolio, perils, scenario)
            return run

    def poll_run(self, run_id: str) -> Run | None:
        """Return a run, advancing it toward completion.

        The stub engine is synchronous, so the first poll after submission runs
        the engine and finalises the run to ``done`` (or ``error``).
        """
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                return None
            run = state.run
            if run.status in (RunStatus.DONE.value, RunStatus.ERROR.value):
                return run
            run.status = RunStatus.RUNNING.value
            try:
                run.result = run_physical(state.portfolio, state.perils, state.scenario)
                run.status = RunStatus.DONE.value
            except Exception as exc:  # noqa: BLE001 — surface any engine failure as run error
                run.status = RunStatus.ERROR.value
                run.error = str(exc)
            return run


# Process-wide singleton (mirrors Ragnarok's single-session model_store facade).
store = PhysicalRiskStore()
