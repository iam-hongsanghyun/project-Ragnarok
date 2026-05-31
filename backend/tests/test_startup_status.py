"""Startup-status warm flow + GET /api/status contract.

The frontend polls /api/status while showing a progress screen, so the
shape here is load-bearing for the boot UX.
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from backend.app import startup_status
from backend.app.config_provider import BUILD_STEPS
from backend.app.main import app


def test_status_reaches_ready_under_lifespan():
    # TestClient as a context manager runs the FastAPI lifespan, which
    # kicks off the background warm task.
    with TestClient(app) as client:
        snap = None
        for _ in range(100):
            snap = client.get("/api/status").json()
            if snap["ready"]:
                break
            time.sleep(0.05)
        assert snap is not None
        assert snap["ready"] is True
        assert snap["phase"] == "ready"
        assert snap["progress"] == 1.0
        assert snap["error"] is None
        assert snap["build_id"]
        # Every declared build step is present and done.
        keys = {s["key"] for s in snap["steps"]}
        assert keys == {k for k, _ in BUILD_STEPS}
        assert all(s["done"] for s in snap["steps"])


def test_status_snapshot_shape_before_warm():
    startup_status.reset()
    snap = startup_status.snapshot()
    assert set(snap.keys()) == {
        "phase",
        "detail",
        "ready",
        "error",
        "build_id",
        "progress",
        "steps",
    }
    assert snap["phase"] == "starting"
    assert snap["ready"] is False
    assert snap["progress"] == 0.0
    # restore for any later test that relies on warmed state
    startup_status.reset()


def test_mark_step_advances_detail_and_progress():
    startup_status.reset()
    # Simulate the progress callback firing for the 3rd step.
    third_key = BUILD_STEPS[2][0]
    startup_status._mark_step(third_key, "Loading network-import policy")
    snap = startup_status.snapshot()
    assert snap["phase"] == "loading"
    assert "Loading network-import policy" in snap["detail"]
    # Steps before the 3rd are marked done; the 3rd onward are not yet.
    done = [s["done"] for s in snap["steps"]]
    assert done[0] is True and done[1] is True
    assert done[2] is False
    startup_status.reset()
