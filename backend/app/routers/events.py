"""``GET /api/events`` — the session's live event stream (SSE).

One EventSource per browser tab replaces model-state polling: the journal
publishes ``session.version`` on every mutation (any actor), and the embedded
agent will publish its chat/tool/approval events on the same channel. Replay
after reconnect via the standard ``Last-Event-ID`` header (or ``lastEventId``
query param for manual clients). See :mod:`backend.app.events_bus`.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from .. import events_bus

router = APIRouter(tags=["events"])


@router.get("/api/events")
async def events(
    session_id: str = Query("default", alias="session_id"),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    last_event_id_q: int | None = Query(None, alias="lastEventId", ge=0),
) -> StreamingResponse:
    """Stream session events as ``text/event-stream`` (never ends server-side)."""
    last: int | None = last_event_id_q
    if last_event_id is not None:
        try:
            last = int(last_event_id)
        except ValueError:
            last = last_event_id_q
    return StreamingResponse(
        events_bus.sse_stream(session_id, last),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # never proxy-buffer an event stream
        },
    )
