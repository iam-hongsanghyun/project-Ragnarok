"""Request-scoped actor context — who is mutating the session, via which endpoint.

A tiny ASGI middleware stamps every HTTP request with a :class:`RequestContext`
(held in a ``contextvars.ContextVar``, so it propagates into FastAPI's
threadpool for sync endpoints). The journal (:mod:`backend.app.journal`) reads
it at mutation time to tag entries with an actor and to group multiple store
writes made by one request.

Actor comes from the ``X-Ragnarok-Actor`` header — absent means a human in the
browser (``user``). The MCP client sends ``mcp`` (or ``agent`` when driven by
the embedded agent), see :mod:`backend.mcp.client`. ``X-Ragnarok-Conversation``
optionally carries the embedded-agent conversation id so chat tool-calls can be
joined to their journal entries.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass

_ALLOWED_ACTORS = {"user", "mcp", "agent"}


@dataclass(frozen=True)
class RequestContext:
    """Identity of the request currently executing (immutable)."""

    actor: str = "user"
    endpoint: str = ""
    request_id: str = ""
    conversation_id: str | None = None


_current: ContextVar[RequestContext | None] = ContextVar("ragnarok_request_context", default=None)


def current() -> RequestContext:
    """The active request's context, or a ``system`` context outside a request
    (startup hooks, background tasks)."""
    ctx = _current.get()
    return ctx if ctx is not None else RequestContext(actor="system")


def _header(scope: dict, name: bytes) -> str:
    for k, v in scope.get("headers") or []:
        if k == name:
            return v.decode("latin-1").strip()
    return ""


class ActorContextMiddleware:
    """Pure ASGI middleware (streaming-safe — no response buffering) that sets
    the request context for the duration of each HTTP request."""

    def __init__(self, app) -> None:  # noqa: ANN001 — ASGI app
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        actor = _header(scope, b"x-ragnarok-actor").lower() or "user"
        if actor not in _ALLOWED_ACTORS:
            actor = "user"
        ctx = RequestContext(
            actor=actor,
            endpoint=f"{scope.get('method', '')} {scope.get('path', '')}",
            request_id=uuid.uuid4().hex,
            conversation_id=_header(scope, b"x-ragnarok-conversation") or None,
        )
        token = _current.set(ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)
