"""Cancelling a run must actually kill the worker — even one ignoring SIGTERM.

Regression: a rolling-horizon run chains many native HiGHS solves in one
worker process and does not honour SIGTERM promptly. The old cancel sent only
SIGTERM, waited 3s, then dropped the job regardless — leaving an orphan that
kept grinding through the remaining windows in the background. ``cancel_run``
now escalates to SIGKILL, which cannot be caught or ignored.

The test uses the ``fork`` start method so the stubborn worker can be a local
closure-free function without spawn's re-import/pickling constraints; the
production code path uses ``spawn`` but ``cancel_run`` is start-method
agnostic — it only relies on ``Process.terminate()`` / ``.kill()``.
"""
from __future__ import annotations

import asyncio
import multiprocessing as mp
import signal
import time

from backend.app.main import _Job, _jobs, cancel_run


def _sigterm_ignoring_worker(q: "mp.Queue") -> None:
    """Ignore SIGTERM and busy-wait — mimics a worker stuck in a native solve
    that will not act on a graceful terminate."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    q.put("ready")
    while True:
        time.sleep(0.05)


def test_cancel_escalates_to_sigkill() -> None:
    ctx = mp.get_context("fork")
    q: mp.Queue = ctx.Queue()
    proc = ctx.Process(target=_sigterm_ignoring_worker, args=(q,), daemon=True)
    proc.start()
    try:
        # Wait until the child has installed the SIGTERM-ignoring handler, so
        # the subsequent terminate() is genuinely ignored.
        assert q.get(timeout=10) == "ready"
        assert proc.is_alive()

        job_id = "test-cancel-sigkill"
        _jobs[job_id] = _Job(id=job_id, proc=proc, result_queue=q)

        result = asyncio.run(cancel_run(job_id))

        assert result["status"] == "cancelled"
        # SIGTERM was ignored, so only the SIGKILL escalation can have stopped
        # it. Give the OS a moment to reap, then assert it is gone.
        proc.join(5)
        assert not proc.is_alive()
        assert job_id not in _jobs
    finally:
        if proc.is_alive():
            proc.kill()
            proc.join(5)
        _jobs.pop("test-cancel-sigkill", None)
