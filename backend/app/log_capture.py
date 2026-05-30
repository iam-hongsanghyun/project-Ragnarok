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


def install() -> None:
    """Attach the capture handler to the root logger (idempotent)."""
    root = logging.getLogger()
    if _HANDLER not in root.handlers:
        root.addHandler(_HANDLER)
    # Uvicorn loggers default to propagate=True, so their records reach the
    # root logger and our handler. We do not need to attach separately.
    # Ensure root sees DEBUG so we capture everything; individual loggers
    # still control what they emit.
    if root.level == logging.NOTSET or root.level > logging.DEBUG:
        root.setLevel(logging.DEBUG)


def get_snapshot() -> tuple[list[LogEntry], int, int]:
    """Return (entries, cursor, capacity) for the API endpoint."""
    entries, cursor = _HANDLER.snapshot()
    return entries, cursor, _HANDLER.capacity
