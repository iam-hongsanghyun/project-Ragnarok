"""Pluggable optimisation backends.

PyPSA is the reference adapter today; the registry lets a run select a backend
by ``options["backend"]`` without the frontend or API layer knowing which
engine ran.
"""
from __future__ import annotations

from .base import Backend, BackendError
from .registry import (
    DEFAULT_BACKEND,
    available_backends,
    get_backend,
    register_backend,
)

__all__ = [
    "Backend",
    "BackendError",
    "DEFAULT_BACKEND",
    "available_backends",
    "get_backend",
    "register_backend",
]
