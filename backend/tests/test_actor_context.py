"""Actor-context middleware tests (Bifrost Phase 1)."""
from __future__ import annotations

from backend.app import actor_context


def _app_with_probe():
    from fastapi import FastAPI

    from backend.app.actor_context import ActorContextMiddleware

    app = FastAPI()
    app.add_middleware(ActorContextMiddleware)

    @app.get("/probe")
    def probe() -> dict:
        ctx = actor_context.current()
        return {
            "actor": ctx.actor,
            "endpoint": ctx.endpoint,
            "requestId": ctx.request_id,
            "conversationId": ctx.conversation_id,
        }

    return app


def test_default_actor_is_user() -> None:
    from fastapi.testclient import TestClient

    c = TestClient(_app_with_probe())
    body = c.get("/probe").json()
    assert body["actor"] == "user"
    assert body["endpoint"] == "GET /probe"
    assert len(body["requestId"]) == 32
    assert body["conversationId"] is None


def test_headers_map_to_actor_and_conversation() -> None:
    from fastapi.testclient import TestClient

    c = TestClient(_app_with_probe())
    body = c.get("/probe", headers={
        "X-Ragnarok-Actor": "agent",
        "X-Ragnarok-Conversation": "conv-42",
    }).json()
    assert body["actor"] == "agent"
    assert body["conversationId"] == "conv-42"


def test_unknown_actor_falls_back_to_user() -> None:
    from fastapi.testclient import TestClient

    c = TestClient(_app_with_probe())
    assert c.get("/probe", headers={"X-Ragnarok-Actor": "hacker"}).json()["actor"] == "user"


def test_outside_request_context_is_system() -> None:
    assert actor_context.current().actor == "system"


def test_request_ids_are_unique_per_request() -> None:
    from fastapi.testclient import TestClient

    c = TestClient(_app_with_probe())
    ids = {c.get("/probe").json()["requestId"] for _ in range(3)}
    assert len(ids) == 3
