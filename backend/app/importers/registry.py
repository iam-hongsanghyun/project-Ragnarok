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
    from .databases.osm_powerplants import build as build_osm_pp
    from .databases.wri_gppd import build as build_wri
    from .databases.worldbank_demand import build as build_wb
    from .databases.kpg193 import build as build_kpg_network
    from .databases.kpg193_renewable_capacity import build as build_kpg_rencap
    from .databases.kpg193_demand_profile import build as build_kpg_demand
    from .databases.kpg193_renewable_profile import build as build_kpg_renprof
    from .databases.eia_demand import build as build_eia
    from .databases.entsoe_load import build as build_entsoe
    from .databases.entsoe_capacity import build as build_entsoe_cap
    from .databases.entsoe_generation_profile import build as build_entsoe_genprof
    from .databases.openmeteo_renewable import build as build_openmeteo
    from .databases.openmeteo_renewable import build_pvgis, build_nasa_power
    from .databases.openmeteo_demand import build as build_openmeteo_demand

    return [
        build_osm, build_osm_pp, build_wri, build_wb,
        build_kpg_network, build_kpg_rencap, build_kpg_demand, build_kpg_renprof,
        build_eia, build_entsoe, build_entsoe_cap, build_entsoe_genprof,
        build_openmeteo, build_pvgis, build_nasa_power, build_openmeteo_demand,
    ]


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


def available_sources() -> list[dict[str, Any]]:
    """Group the registered datasets by ``source_id`` for the Country →
    Database → Datasets UI.

    Each source carries its datasets and ``common_filters`` — the filters whose
    ``id`` is declared by ≥2 of the source's datasets (e.g. version /
    renewable_year / profile window for KPG193). The frontend renders those once
    as a shared "Common settings" group and each dataset's remaining filters
    (``filters`` minus ``common_filter_ids``) under that dataset's own group.
    Singletons get one dataset and no common filters.
    """
    datasets = available_databases()
    order: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for d in datasets:
        sid = d["source_id"]
        if sid not in grouped:
            grouped[sid] = []
            order.append(sid)
        grouped[sid].append(d)

    sources: list[dict[str, Any]] = []
    for sid in order:
        members = grouped[sid]
        # Count filter-id occurrences across the source's datasets, keeping the
        # first-seen filter json and first-seen ordering.
        first_seen: dict[str, dict[str, Any]] = {}
        seen_order: list[str] = []
        counts: dict[str, int] = {}
        for d in members:
            for f in d.get("filters", []):
                fid = f["id"]
                if fid not in first_seen:
                    first_seen[fid] = f
                    seen_order.append(fid)
                counts[fid] = counts.get(fid, 0) + 1
        common_ids = [fid for fid in seen_order if counts[fid] >= 2]

        # Union of country coverage across datasets.
        covs = [d["country_coverage"] for d in members]
        if all(c == "global" for c in covs):
            coverage: Any = "global"
        else:
            acc: set[str] = set()
            for c in covs:
                if isinstance(c, list):
                    acc.update(c)
            coverage = sorted(acc)

        sources.append({
            "source_id": sid,
            "source_label": members[0]["source_label"],
            "category": members[0]["category"],
            "categories": sorted({d["category"] for d in members}),
            "country_coverage": coverage,
            "common_filter_ids": common_ids,
            "common_filters": [first_seen[fid] for fid in common_ids],
            "datasets": members,
        })
    return sources


def reset_cache() -> None:
    registered_databases.cache_clear()
