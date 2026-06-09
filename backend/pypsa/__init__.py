"""PyPSA optimisation backend (engine implementation).

This package is the reference backend adapter and everything PyPSA-specific:

- ``adapter``: ``PypsaBackend`` — implements the host's ``Backend`` protocol by
  delegating to ``results.run_pypsa``.
- ``network``: schema-driven ``pypsa.Network`` builder (``build_network``) and
  dry-run validation.
- ``results``: solve + analytics result assembly (``run_pypsa``) and the
  schema-driven solved-output cache (``full_outputs``).
- ``pathway`` / ``rolling`` / ``stochastic`` / ``carbon_price``: optimisation
  mode helpers.
- ``constants`` / ``pypsa_schema`` / ``utils``: PyPSA-facing helpers shared
  across the builder and extractors.

It depends on the host (``backend.app``) only for engine-agnostic services:
config loading, the ``RunPayload`` model, and the plugin host. A second backend
would live as a sibling package (e.g. ``backend.<engine>``) implementing the
same ``Backend`` protocol.
"""
from __future__ import annotations

# Force NumPy/object strings before any pypsa.Network is built (pyarrow is
# installed for the session store's Parquet engine, which would otherwise flip
# pandas 3.0 to Arrow strings that xarray<2026 rejects). See
# backend.app._pandas_compat. Solver tests import this engine package directly,
# so the shim must live here too, not only in the API host.
from ..app._pandas_compat import ensure_object_strings as _ensure_object_strings

_ensure_object_strings()
