"""Discover the registered database modules and expose their metadata.

Each module under ``databases/<id>/`` provides a ``build()`` factory
returning a ``Database``. The registry imports them, instantiates once,
and serves the merged metadata to ``GET /api/import/databases``.

Adding a database = drop a new ``databases/<id>/`` package and add its
``build`` import to ``_MODULE_FACTORIES`` below. No endpoint changes.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

from .protocol import Database


def _factories() -> list[Callable[[], Database]]:
    # Local imports so a broken module surfaces lazily (and tests can
    # import the registry without every dataset's deps loaded).
    from .databases.osm import build as build_osm
    from .databases.wri_gppd import build as build_wri
    from .databases.worldbank_demand import build as build_wb
    from .databases.kpg193 import build as build_kpg
    from .databases.eia_demand import build as build_eia

    return [build_osm, build_wri, build_wb, build_kpg, build_eia]


@lru_cache(maxsize=1)
def registered_databases() -> dict[str, Database]:
    out: dict[str, Database] = {}
    for factory in _factories():
        db = factory()
        out[db.meta.id] = db
    return out


def get_database(database_id: str) -> Database:
    db = registered_databases().get(database_id)
    if db is None:
        raise KeyError(f"unknown database id: {database_id!r}")
    return db


def available_databases() -> list[dict[str, Any]]:
    """JSON-serialisable registry view for ``GET /api/import/databases``."""
    return [db.meta.to_json() for db in registered_databases().values()]


def reset_cache() -> None:
    registered_databases.cache_clear()
