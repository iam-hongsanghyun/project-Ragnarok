"""Backend abstraction seam.

Ragnarok talks to exactly one optimisation backend per run. A *backend* is
anything that can take the in-memory workbook model plus run metadata and
return Ragnarok's result dict. PyPSA is the reference adapter
(:mod:`backend.pypsa.adapter`); the interface here is the only
contract a future backend has to satisfy.

The seam is intentionally a single method — ``run(model, scenario, options)``.
There is no separate "build" step in the public contract: building a native
network is an internal detail of whichever backend needs it (PyPSA's
``build_network`` is reused by the netCDF/HDF5 file converters, but that is not
part of this interface). The ``options`` dict is the "what to do" metadata —
it already carries pathway / rolling / stochastic / security-constrained /
force-LP flags, and ``options["backend"]`` selects the adapter.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class BackendError(Exception):
    """Raised when a requested backend is unknown or cannot fulfil a run."""


@runtime_checkable
class Backend(Protocol):
    """The contract every optimisation backend implements.

    Attributes:
        name: Stable machine identifier used in ``options["backend"]`` (e.g.
            ``"pypsa"``). Lower-case, no spaces.
        label: Human-readable name shown in the UI (e.g. ``"PyPSA"``).
    """

    name: str
    label: str

    def capabilities(self) -> dict[str, Any]:
        """Return a JSON-serialisable description of what this backend supports.

        Used by ``GET /api/backends`` so the frontend can show available
        backends and gate UI affordances (e.g. which study modes or run
        features a backend can honour).
        """
        ...

    def run(
        self,
        model: dict[str, list[dict[str, Any]]],
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build, solve, and extract results for one case.

        Args:
            model: The in-memory workbook as ``{sheet: rows[]}``.
            scenario: Constraints, carbon price, discount rate, etc.
            options: Run metadata describing *what to do* (planning mode,
                rolling horizon, stochastic, security-constrained, solver
                tuning, currency, enabled modules). The backend reads only the
                keys it understands.

        Returns:
            Ragnarok's result dict, including the schema-driven
            ``outputs.{static,series}`` cache the frontend derives everything
            from.
        """
        ...
