"""In-process per-session event bus + SSE plumbing (``GET /api/events``).

One pub/sub channel per model session carrying everything the GUI needs to stay
live without polling the model: ``session.version`` bumps from the journal now,
and the embedded agent's chat/tool/approval events later — a single EventSource
on the frontend, reconnect-safe via ``Last-Event-ID`` replay from a bounded
ring buffer.

Thread-safety: journal writes happen on FastAPI's worker threads while SSE
subscribers await on the event loop, so :func:`publish` is callable from any
thread — it appends to the ring under a lock and hands deliveries to the loop
with ``call_soon_threadsafe``. Publishing without a running loop (tests,
startup) still records to the ring; subscribers replay it on connect.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger("pypsa_gui.events_bus")

RING_SIZE = 500
HEARTBEAT_SECONDS = 15.0


@dataclass
class _Channel:
    next_id: int = 1
    ring: deque = field(default_factory=lambda: deque(maxlen=RING_SIZE))
    subscribers: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = field(default_factory=dict)
    next_sub: int = 0


_channels: dict[str, _Channel] = {}
_lock = threading.Lock()


def _channel(session_id: str) -> _Channel:
    with _lock:
        ch = _channels.get(session_id)
        if ch is None:
            ch = _channels[session_id] = _Channel()
        return ch


def publish(session_id: str, event: str, data: dict[str, Any]) -> int:
    """Publish one event to a session's channel; returns its monotonic id.

    Safe from any thread. Best-effort: a dead/full subscriber queue is dropped
    rather than blocking the publisher (the journal must never stall an edit).
    """
    ch = _channel(session_id)
    with _lock:
        event_id = ch.next_id
        ch.next_id += 1
        item = (event_id, event, data)
        ch.ring.append(item)
        subscribers = list(ch.subscribers.items())
    for sub_id, (loop, queue) in subscribers:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:  # loop closed — forget the subscriber
            with _lock:
                ch.subscribers.pop(sub_id, None)
    return event_id


def _register(
    session_id: str, last_id: int | None
) -> tuple[int, asyncio.Queue, list[tuple[int, str, dict[str, Any]]]]:
    """Register a subscriber; returns (sub_id, live queue, ring backlog).

    Registration + ring snapshot are atomic, so an event is delivered via
    exactly one path: the backlog (published before) or the queue (after).
    """
    ch = _channel(session_id)
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    with _lock:
        sub_id = ch.next_sub
        ch.next_sub += 1
        ch.subscribers[sub_id] = (loop, queue)
        backlog = [item for item in ch.ring if item[0] > last_id] if last_id is not None else []
    return sub_id, queue, backlog


def _unregister(session_id: str, sub_id: int) -> None:
    ch = _channel(session_id)  # outside the lock — _channel() takes it (non-reentrant)
    with _lock:
        ch.subscribers.pop(sub_id, None)


async def subscribe(
    session_id: str, last_id: int | None = None
) -> AsyncIterator[tuple[int, str, dict[str, Any]]]:
    """Yield ``(id, event, data)`` forever: ring replay after ``last_id``, then live."""
    sub_id, queue, backlog = _register(session_id, last_id)
    try:
        for item in backlog:
            yield item
        while True:
            yield await queue.get()
    finally:
        _unregister(session_id, sub_id)


def sse_frame(event_id: int, event: str, data: dict[str, Any]) -> str:
    """Format one event as a ``text/event-stream`` frame."""
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def sse_stream(session_id: str, last_id: int | None) -> AsyncIterator[str]:
    """The ``/api/events`` body: replay + live frames with heartbeat comments.

    Heartbeats keep proxies from idling the connection out; EventSource ignores
    comment frames. The timeout wraps ``queue.get()`` (cancellation-safe), NOT a
    generator's ``__anext__`` — cancelling an async generator's anext closes the
    generator and the next call raises StopAsyncIteration. The stream ends only
    when the client disconnects.
    """
    sub_id, queue, backlog = _register(session_id, last_id)
    try:
        for item in backlog:
            yield sse_frame(*item)
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": hb\n\n"
                continue
            yield sse_frame(*item)
    finally:
        _unregister(session_id, sub_id)
