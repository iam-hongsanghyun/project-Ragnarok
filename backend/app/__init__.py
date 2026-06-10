"""Ragnarok backend host (engine-agnostic).

This package is the FastAPI application and everything that does *not* depend on
a specific optimisation engine:

- ``main``: the FastAPI app, run lifecycle (job store, subprocess worker), and
  the PyPSA-format file converter endpoints.
- ``models``: request/response pydantic models (``RunPayload``).
- ``config``: loads ``backend/config/*.json`` (system defaults).
- ``backends``: the pluggable-backend seam (``Backend`` protocol + registry).

Plugins are intentionally a frontend-only concern: the backend never discovers,
loads, or executes plugin code. It only ever receives ``{model, scenario,
options}`` and solves.

The engine that actually builds and solves a network lives in a sibling package
(``backend.pypsa`` today). The host selects it via ``options["backend"]`` and
never imports engine internals directly except through the registry and the
file-converter endpoints.
"""
from __future__ import annotations

# Keep pandas on NumPy/object strings even though pyarrow (our Parquet engine)
# is installed; otherwise pandas 3.0 defaults to Arrow strings that the pinned
# xarray<2026 / PyPSA cannot consume. See _pandas_compat for the full rationale.
from ._pandas_compat import ensure_object_strings as _ensure_object_strings

_ensure_object_strings()
