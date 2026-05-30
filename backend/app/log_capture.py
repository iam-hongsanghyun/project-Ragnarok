"""In-process log capture for the Analytics → Log tab.

Attaches a single :class:`MemoryLogHandler` to the root Python logger so every
:mod:`logging` record (uvicorn access, application, exception tracebacks)
is mirrored into a thread-safe ring buffer. Surfaced via ``GET /api/log``.

What this **does** capture
--------------------------
* uvicorn HTTP access logs (``uvicorn.access`` logger).
* uvicorn errors / startup logs (``uvicorn.error``).
* Any application code that uses ``logging.getLogger(...)``.
* Unhandled exceptions routed through ``logging.exception()``.

What this **does not** capture (yet)
------------------------------------
* Solver C-stdout (HiGHS verbose dump). Capturing that needs file-descriptor-
  level ``os.dup2`` redirection on the run worker process. Listed as a
  follow-up — would require careful handling around the multiprocessing
  fork/spawn boundary so dev terminal output is not also swallowed.
* Direct ``print()`` calls in the backend. They go to stdout, not through
  ``logging``. The backend convention is to use ``logging.getLogger(...)``;
  any stray ``print()`` will be invisible to the Log tab.

Why a ring buffer
-----------------
The buffer is intentionally bounded (default 1000 lines) so a long-running
server cannot grow memory without bound. Oldest entries are silently
dropped as new ones arrive — the ``cursor`` field on each fetch lets a
client detect that drops occurred.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque


@dataclass(frozen=True)
class LogEntry:
    """One captured log line, serialised to the API as JSON."""

    ts: str              # ISO 8601 UTC ("2026-05-31T08:14:23.117Z")
    logger: str          # logger name, e.g. "uvicorn.access"
    level: str           # "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"
    message: str         # formatted message; may contain newlines


class MemoryLogHandler(logging.Handler):
    """Append every formatted record into a bounded deque."""

    def __init__(self, capacity: int) -> None:
        super().__init__()
        self.capacity = capacity
        self._lock = threading.Lock()
        self._buf: Deque[LogEntry] = deque(maxlen=capacity)
        # Monotonic count of *every* entry ever added (not capped by
        # capacity). Clients use this to detect drop-on-overflow.
        self._cursor: int = 0

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            # Include the standard traceback if record.exc_info is set.
            message = record.getMessage()
            if record.exc_info:
                message = f"{message}\n{logging.Formatter().formatException(record.exc_info)}"
            entry = LogEntry(
                ts=_iso_utc(record.created),
                logger=record.name,
                level=record.levelname,
                message=message,
            )
            with self._lock:
                self._buf.append(entry)
                self._cursor += 1
        except Exception:
            # A failing log handler must never break the calling code.
            self.handleError(record)

    def snapshot(self) -> tuple[list[LogEntry], int]:
        """Return a copy of the current buffer plus the monotonic cursor."""
        with self._lock:
            return list(self._buf), self._cursor


def _iso_utc(epoch_seconds: float) -> str:
    return (
        datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


# ── Module-level singleton ──────────────────────────────────────────────────
# A single handler is attached at import time; the FastAPI app reads from
# this singleton in its /api/log endpoint. Keeping it global lets every
# logger in the process (uvicorn, application, libraries) flow into the
# same buffer regardless of import order.

CAPACITY = 1000

_HANDLER = MemoryLogHandler(capacity=CAPACITY)
_HANDLER.setLevel(logging.DEBUG)
_HANDLER.setFormatter(logging.Formatter("%(message)s"))


class _DropPollLogger(logging.Filter):
    """Drop the DEBUG re-emits from the ``pypsa_gui.poll`` logger.

    main.py's access-log filter suppresses `/api/run/{id}` and `/api/log`
    polls from the INFO access stream and re-emits them on a separate
    ``pypsa_gui.poll`` logger at DEBUG level — so curious operators can
    still capture them with ``uvicorn --log-level debug``. Without this
    secondary filter on the memory handler, those DEBUG re-emits land
    right back in the in-memory ring buffer and the Log tab fills with
    the very poll noise we wanted to hide.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        return record.name != "pypsa_gui.poll"


_HANDLER.addFilter(_DropPollLogger())


def install() -> None:
    """Attach the capture handler to the root logger (idempotent)."""
    root = logging.getLogger()
    if _HANDLER not in root.handlers:
        root.addHandler(_HANDLER)
    # Uvicorn loggers default to propagate=True, so their records reach the
    # root logger and our handler. We do not need to attach separately.
    # Ensure root sees DEBUG so we capture everything; individual loggers
    # still control what they emit. The handler-level _DropPollLogger
    # filter prevents the poll-noise re-emits from flooding the buffer.
    if root.level == logging.NOTSET or root.level > logging.DEBUG:
        root.setLevel(logging.DEBUG)


def emit_solver_log(text: str, job_id: str) -> None:
    """Replay captured solver stdout into the in-process log buffer.

    Used by main.py after a run worker finishes — the worker dup'd its
    stdout fd to a temp file during the solve to catch C-level output
    from HiGHS / PyPSA / linopy, then shipped the captured text back to
    the parent. The parent calls this once to fan the captured lines
    into the buffer so the Log tab sees them alongside everything else.
    Each non-empty line becomes one INFO record on the ``pypsa.solver``
    logger; large captures are truncated to a sane prefix to avoid
    monopolising the bounded ring buffer.
    """
    if not text:
        return
    logger = logging.getLogger("pypsa.solver")
    lines = text.rstrip("\n").split("\n")
    # Cap how many lines a single solve can push into the buffer. The
    # buffer holds 1000 entries total; a verbose HiGHS run can emit
    # thousands. Keep the head + tail so the user can see the start
    # (parsing / pre-solve) and the end (final objective + status).
    MAX_LINES = 400
    if len(lines) > MAX_LINES:
        head = lines[: MAX_LINES // 2]
        tail = lines[-MAX_LINES // 2 :]
        dropped = len(lines) - len(head) - len(tail)
        lines = [*head, f"... [{dropped} solver lines dropped — full output too long for buffer] ...", *tail]
    logger.info("── solver output for job %s (%d lines) ──", job_id, len(lines))
    for line in lines:
        if line.strip():
            logger.info("%s", line)
    logger.info("── end solver output for job %s ──", job_id)


def get_snapshot() -> tuple[list[LogEntry], int, int]:
    """Return (entries, cursor, capacity) for the API endpoint."""
    entries, cursor = _HANDLER.snapshot()
    return entries, cursor, _HANDLER.capacity
