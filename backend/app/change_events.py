"""Tell every open screen that something on the server changed, whoever changed it.

The model and the project's settings already announce themselves (``session.version`` from the journal,
``session.appState`` from the app-state writers). Everything else an agent can change over MCP - installed
tab modules, plugins, runs and the solve queue, a module's uploaded datasets - had no event, so an open
browser showed it only after a reload.

:class:`ChangeEventsMiddleware` closes that gap in one place instead of in every endpoint: after any
successful ``POST`` / ``PUT`` / ``PATCH`` / ``DELETE`` under ``/api/``, it publishes ``server.changed`` to
every open session channel (:func:`backend.app.events_bus.publish_all`)::

    {"area": "modules", "path": "/api/modules/install-path", "method": "POST", "actor": "mcp"}

``area`` is the first path segment after ``/api/``; the browser re-reads what it shows for that area and
ignores areas it does not show. Requests whose path says they only read (a preview, a validation, an
export) are not announced, so an agent's look-ups do not make every screen re-fetch.
"""
from __future__ import annotations

import logging
from typing import Any

from . import actor_context, events_bus

logger = logging.getLogger("pypsa_gui.change_events")

EVENT = "server.changed"
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: Path segments that mark a POST as a read (it carries a body but changes nothing).
READ_ONLY_SEGMENTS = frozenset({
    "preview", "validate", "values", "query", "search", "statistics", "analysis", "model-check", "check",
    "estimate", "export", "download", "describe", "diagnose", "explain", "log", "events", "health",
})
#: Areas that already publish their own event (the journal, the app-state writers).
SELF_ANNOUNCED_AREAS = frozenset({"events", "session"})


def change_area(method: str, path: str) -> str | None:
    """The area a request changed, or ``None`` when it is not a write worth announcing."""
    if method.upper() not in _WRITE_METHODS or not path.startswith("/api/"):
        return None
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return None
    area = parts[1]
    if area in SELF_ANNOUNCED_AREAS or any(p in READ_ONLY_SEGMENTS for p in parts[1:]):
        return None
    return area


class ChangeEventsMiddleware:
    """Pure ASGI middleware: announce each successful write after its response has been sent."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        area = change_area(method, path)
        if area is None:
            await self.app(scope, receive, send)
            return
        status: dict[str, int] = {}

        async def send_wrapper(message: dict) -> None:
            if message.get("type") == "http.response.start":
                status["code"] = int(message.get("status", 500))
            await send(message)

        await self.app(scope, receive, send_wrapper)
        if status.get("code", 500) >= 400:
            return
        try:
            actor = actor_context.current().actor
        except Exception:  # noqa: BLE001 - the context is best-effort here
            actor = "user"
        data = {"area": area, "path": path, "method": method, "actor": actor}
        logger.debug("server.changed area=%s method=%s actor=%s", area, method, actor)
        events_bus.publish_all(EVENT, data)
