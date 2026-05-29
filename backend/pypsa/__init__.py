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
