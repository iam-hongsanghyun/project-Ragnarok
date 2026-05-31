"""Backend startup status — what the server is doing before it's ready.

The frontend polls ``GET /api/status`` while showing a progress screen,
so the user sees the backend warming up (importing PyPSA, building the
component schema, …) instead of a blank page or a failed fetch.

Lifecycle:

  1. Process starts. ``import pypsa`` and the rest of ``main.py``'s
     top-level imports run BEFORE uvicorn binds the port — so while that
     happens the frontend simply can't connect yet and shows
     "Starting backend…".
  2. Once the port is bound, FastAPI's lifespan startup kicks off
     ``warm()`` as a background task. The server is already accepting
     requests, so ``GET /api/status`` reports live progress through the
     build steps.
  3. When the bundle is built, status flips to ``ready`` and the
     frontend fetches ``GET /api/config`` and renders the app.

State is a single module-global dict guarded for the single-process
uvicorn worker we run. Multi-worker deployments would each warm their
own copy — which is correct, since each worker has its own in-memory
bundle cache.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .config_provider import BUILD_STEPS, load_bundle


# ── State ────────────────────────────────────────────────────────────────────

# phase: "starting" → "loading" → "ready" | "error"
_status: dict[str, Any] = {
    "phase": "starting",
    "detail": "Starting backend…",
    "ready": False,
    "error": None,
    "build_id": None,
    # One entry per BUILD_STEPS item, plus the implicit "server online"
    # step which is true by definition once /api/status responds.
    "steps": [
        {"key": key, "label": label, "done": False}
        for key, label in BUILD_STEPS
    ],
}


def _total_steps() -> int:
    return len(_status["steps"])


def _progress_fraction() -> float:
    done = sum(1 for s in _status["steps"] if s["done"])
    total = _total_steps()
    return (done / total) if total else 1.0


def snapshot() -> dict[str, Any]:
    """JSON-serialisable view of the current startup status."""
    return {
        "phase": _status["phase"],
        "detail": _status["detail"],
        "ready": _status["ready"],
        "error": _status["error"],
        "build_id": _status["build_id"],
        "progress": round(_progress_fraction(), 3),
        "steps": [dict(s) for s in _status["steps"]],
    }


def _mark_step(key: str, label: str) -> None:
    """Progress callback handed to ``load_bundle`` — mark a step running.

    We flip the *current* step to done as the NEXT step begins (and the
    last one is closed by ``warm`` on success), so the detail line always
    names what's happening right now.
    """
    _status["phase"] = "loading"
    _status["detail"] = f"{label}…"
    # Mark every step before this one as done (defensive — steps run in
    # order so by the time `key` starts, all earlier ones are complete).
    seen = False
    for step in _status["steps"]:
        if step["key"] == key:
            seen = True
            break
        step["done"] = True
    if not seen:
        # Unknown key — no-op beyond the detail line.
        return


async def warm() -> None:
    """Build the config bundle in a worker thread, updating status.

    Called once from the FastAPI lifespan startup. Runs the (blocking)
    bundle build off the event loop so ``GET /api/status`` stays
    responsive throughout.
    """
    loop = asyncio.get_running_loop()
    try:
        bundle = await loop.run_in_executor(None, lambda: load_bundle(_mark_step))
        for step in _status["steps"]:
            step["done"] = True
        _status["phase"] = "ready"
        _status["detail"] = "Ready."
        _status["ready"] = True
        _status["build_id"] = bundle.build_id
    except Exception as exc:  # noqa: BLE001 — surface any startup failure
        _status["phase"] = "error"
        _status["detail"] = "Backend failed to start."
        _status["error"] = str(exc)
        _status["ready"] = False


def reset() -> None:
    """Reset status to the pre-warm state (tests / reload)."""
    _status["phase"] = "starting"
    _status["detail"] = "Starting backend…"
    _status["ready"] = False
    _status["error"] = None
    _status["build_id"] = None
    for step in _status["steps"]:
        step["done"] = False


def mark_ready(build_id: str) -> None:
    """Flip status straight to ready for an already-built bundle.

    Used by ``POST /api/config/reload``, which rebuilds synchronously and
    has the new ``build_id`` in hand — there's no background warm to wait
    on, so we just publish the terminal state.
    """
    for step in _status["steps"]:
        step["done"] = True
    _status["phase"] = "ready"
    _status["detail"] = "Ready."
    _status["ready"] = True
    _status["error"] = None
    _status["build_id"] = build_id
