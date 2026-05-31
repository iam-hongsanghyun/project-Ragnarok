"""Database registry — load ``databases.json`` and instantiate enabled modules.

Adding a new database = drop a directory under ``databases/<id>/`` with the
shape::

    backend/app/importers/databases/<id>/
        __init__.py       # exports a ``build()`` factory returning a Database
        config.json       # metadata + filter schema
        importer.py       # the actual class

…and append an entry to ``databases.json``::

    { "module": "<id>", "enabled": true, "order": 40 }

Registry behaviour:

- A missing ``config.json`` or a module that raises during import is logged
  and skipped — the rest of the registry stays usable.
- A database whose optional dependencies are absent is registered as
  ``available=false`` with a reason string so the frontend can grey it out
  instead of pretending it does not exist.
- Order is determined by the ``order`` field on each entry (lower first).
"""
from __future__ import annotations

import importlib
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from .protocol import Database, DatabaseMeta

_log = logging.getLogger(__name__)

_IMPORTERS_DIR = Path(__file__).resolve().parent
_DATABASES_INDEX = _IMPORTERS_DIR / "databases.json"
_DATABASES_PKG = "backend.app.importers.databases"


def _read_index() -> list[dict[str, Any]]:
    with _DATABASES_INDEX.open() as f:
        raw = json.load(f)
    entries = [e for e in raw.get("databases", []) if e.get("enabled", True)]
    entries.sort(key=lambda e: int(e.get("order", 0)))
    return entries


def _instantiate(module_id: str) -> Database | None:
    """Import and instantiate one database module.

    The module must expose ``build()`` returning an object satisfying the
    :class:`Database` protocol. We tolerate missing optional deps by letting
    the module raise during ``build`` and registering an ``available=False``
    placeholder upstream.
    """
    try:
        mod = importlib.import_module(f"{_DATABASES_PKG}.{module_id}")
    except Exception as exc:  # noqa: BLE001
        _log.warning("importer module %r failed to import: %s", module_id, exc)
        return None
    builder = getattr(mod, "build", None)
    if builder is None:
        _log.warning("importer module %r has no build() factory", module_id)
        return None
    try:
        instance = builder()
    except Exception as exc:  # noqa: BLE001
        _log.warning("importer module %r build() raised: %s", module_id, exc)
        return None
    if not isinstance(instance, Database):
        _log.warning(
            "importer module %r build() did not return a Database (got %r)",
            module_id,
            type(instance).__name__,
        )
        return None
    return instance


@lru_cache(maxsize=1)
def registered_databases() -> dict[str, Database]:
    """Return ``{id: Database}`` for every successfully-instantiated module.

    Cached for the process lifetime. Tests that need to reset the registry
    should call :func:`registered_databases.cache_clear`.
    """
    out: dict[str, Database] = {}
    for entry in _read_index():
        module_id = str(entry["module"])
        instance = _instantiate(module_id)
        if instance is None:
            continue
        out[instance.meta.id] = instance
    return out


def get_database(database_id: str) -> Database:
    db = registered_databases().get(database_id)
    if db is None:
        raise KeyError(f"unknown database: {database_id!r}")
    return db


def list_database_metas() -> list[DatabaseMeta]:
    return [db.meta for db in registered_databases().values()]


def available_databases() -> list[dict[str, Any]]:
    """JSON-serialisable view of the registry for ``GET /api/import/databases``."""
    return [m.to_json() for m in list_database_metas()]
