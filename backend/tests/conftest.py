"""Pytest configuration for backend tests.

Adds the repository root to ``sys.path`` so tests can ``from backend.app...``
and ``from backend.pypsa...``
when invoked from any working directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
