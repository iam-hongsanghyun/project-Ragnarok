"""Backend registry — selects the optimisation backend for a run.

A run picks its backend via ``options["backend"]`` (default ``"pypsa"``). This
module owns the mapping from that string to a concrete adapter instance, so
adding a future backend is a one-line :func:`register_backend` call and the
rest of the app keeps calling :func:`get_backend`.
"""
from __future__ import annotations

from typing import Any

from .base import Backend, BackendError
from .pypsa_backend import PypsaBackend

DEFAULT_BACKEND = "pypsa"

_BACKENDS: dict[str, Backend] = {}


def register_backend(backend: Backend) -> None:
    """Register a backend under its ``name`` (last writer wins)."""
    _BACKENDS[backend.name.lower()] = backend


# Reference adapter is always available.
register_backend(PypsaBackend())


def get_backend(name: str | None = None) -> Backend:
    """Return the backend for ``name``, defaulting to PyPSA.

    Raises:
        BackendError: if ``name`` is given but not registered.
    """
    key = (name or DEFAULT_BACKEND).strip().lower() or DEFAULT_BACKEND
    backend = _BACKENDS.get(key)
    if backend is None:
        available = ", ".join(sorted(_BACKENDS)) or "(none)"
        raise BackendError(f"Unknown backend '{name}'. Available: {available}.")
    return backend


def available_backends() -> list[dict[str, Any]]:
    """Return the capability descriptor of every registered backend."""
    return [b.capabilities() for b in _BACKENDS.values()]
