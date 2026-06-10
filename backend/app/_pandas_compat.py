"""pandas 3.0 / pyarrow / xarray compatibility shim.

We depend on **pyarrow** as the Parquet engine for the server-side session store
(``session_store.py``). But pandas 3.0 changes its *default string dtype* to an
Arrow-backed string (``ArrowStringArray``) the moment pyarrow is importable —
and the pinned ``xarray<2026`` that PyPSA requires cannot consume Arrow-backed
arrays (``TypeError: Invalid array type: ArrowStringArray`` when PyPSA builds the
network's xarray coordinates).

So merely *installing* pyarrow would break every solve. The documented, surgical
fix is to keep pandas' legacy NumPy/object string inference
(``future.infer_string = False``). Parquet I/O still uses pyarrow; only the
in-memory string dtype reverts to what PyPSA/xarray expect. The records boundary
in ``session_store`` (``DataFrame.to_dict(orient="records")``) already launders
any Arrow scalars read back from Parquet into plain ``str``, so model data that
flows into PyPSA is never Arrow-typed.

Call :func:`ensure_object_strings` at import time of every backend package that
may construct PyPSA networks — in the API process *and* in the spawned solver
worker (multiprocessing "spawn" re-imports modules, so an import-time call covers
the child too). It is idempotent.
"""
from __future__ import annotations

import pandas as pd


def ensure_object_strings() -> None:
    """Force pandas to use NumPy/object strings, not Arrow-backed strings.

    Idempotent; safe to call from multiple package ``__init__`` modules and in
    re-imported subprocesses.
    """
    try:
        pd.set_option("future.infer_string", False)
    except (KeyError, ValueError):
        # Option absent on this pandas build → its default already matches.
        pass
