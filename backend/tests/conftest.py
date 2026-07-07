"""Pytest configuration for backend tests.

Adds the repository root to ``sys.path`` so tests can ``from backend.app...``
and ``from backend.pypsa...``
when invoked from any working directory.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture(autouse=True)
def _pin_climada_worker_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the physical-risk STUB engine in tests by default.

    Worker selection defaults to ``auto`` (use the real CLIMADA conda worker
    when ``.climada-env`` exists). Once that env is built on a dev/CI machine,
    every physical-run test would otherwise spawn the real worker — minutes of
    compute + network downloads — making the suite slow and flaky. Pin it off
    here; the worker-seam tests re-enable it explicitly with their own
    ``monkeypatch.setenv`` (which runs after this autouse fixture and wins).
    """
    if not os.environ.get("RAGNAROK_CLIMADA_WORKER_TEST_REAL"):
        monkeypatch.setenv("RAGNAROK_CLIMADA_WORKER", "off")
