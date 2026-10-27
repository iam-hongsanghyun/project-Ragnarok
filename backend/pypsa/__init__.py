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
# pandas 3 to Arrow strings, which PyPSA 1.4's spatial clustering cannot
# aggregate: `aggregatelines` raises "truediv not supported for dtype 'str'"). See
# backend.app._pandas_compat. Solver tests import this engine package directly,
# so the shim must live here too, not only in the API host.
from ..app._pandas_compat import ensure_object_strings as _ensure_object_strings

_ensure_object_strings()

import pypsa as _pypsa

# Pin PyPSA's string-dtype option explicitly. True = convert imported strings to
# NumPy object dtype (PyPSA's own historical behaviour, and what the shim above
# already gives every frame); left unset PyPSA 1.4 emits a FutureWarning on each
# import and flips the behaviour in v2.
_pypsa.options.api.legacy_string_dtype = True

# P33 — upstream noise: PyPSA 1.4's statistics grouper (`pypsa/statistics/grouping.py`)
# fills a float column with an ndarray, which pandas 3 flags as a Pandas4Warning once
# per grouped call (~500 times per example sweep). It is harmless today and PyPSA's to
# fix; filter exactly that message from exactly that module so every other pandas
# warning (including ours) stays visible.
import warnings as _warnings

import pandas as _pd

_warnings.filterwarnings(
    "ignore",
    message=".*'ndarray' is not supported as a fill value.*",
    category=getattr(_pd.errors, "Pandas4Warning", FutureWarning),
    module=r"pypsa\.statistics\.grouping",
)
