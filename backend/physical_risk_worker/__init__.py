"""CLIMADA worker — runs in a separate conda env (heavy geospatial stack).

Vendored from the standalone ``climaterisk`` project (GPL-3.0, same as this repo);
only the package name changed (``climaterisk_worker`` -> ``physical_risk_worker``).

The Ragnarok backend invokes this package as a subprocess:

    <env>/bin/python -m physical_risk_worker.run_job <run_dir>

It reads ``<run_dir>/request.json`` (snake_case shapes from climaterisk
``engines/base.py`` — see ``backend/app/physical_risk/worker.py`` for the
Ragnarok-side translation), runs CLIMADA, and writes ``<run_dir>/result.json``.
It must NOT import the Ragnarok backend package (different environment, older
numpy/pandas) — the JSON contract is the only coupling.
"""

__version__ = "0.1.0"
