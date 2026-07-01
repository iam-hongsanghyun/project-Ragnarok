"""``/api/transform/*`` — model-level transforms that rewrite the workbook.

Currently: **network clustering** (spatial reduction). A transform reads the
session's full working model, builds the PyPSA network, runs the reduction, and
returns the reduced model (plus a busmap) for the frontend to preview on the map
and apply by replacing the working model.

Methods:
  • ``modularity`` — greedy network-modularity clustering (graph/topology based,
    no extra dependency, no bus coordinates needed). The robust default.
  • ``kmeans`` — spatial k-means on bus x/y (needs scikit-learn and distinct
    coordinates); degrades to a clear error when unavailable.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pypsa
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import model_store
from ..importers.databases.openmeteo_renewable.attach import (
    build_profile_rows,
    merge_profile_rows,
    point_key,
    resolve_targets,
)
from ..importers.databases.openmeteo_renewable.cache import snap
from ..importers.databases.openmeteo_renewable.fetch import fetch_point
from ..importers.http import AsyncClientWrapper
from ...pypsa.network import build_network
from ...pypsa.network.serialize import network_to_model

router = APIRouter(prefix="/api/transform", tags=["transform"])

_DEFAULT_DISCOUNT_RATE = 0.05


class ClusterRequest(BaseModel):
    sessionId: str
    nClusters: int
    method: str = "modularity"
    # When true (default), buses/lines whose text attributes (carrier, unit, …)
    # disagree within a cluster are merged by keeping the most common value,
    # instead of failing. Turn off to enforce strict agreement.
    resolveConflicts: bool = True
    scenario: dict[str, Any] | None = None
    options: dict[str, Any] | None = None


# Bus-reference columns are remapped by clustering itself — never "resolve" them.
_BUS_REFS = {"bus", "bus0", "bus1", "bus2", "bus3", "bus4"}


def _majority(x: "pd.Series") -> Any:
    """Aggregation that keeps the most common non-null value (ties → first).

    Replaces PyPSA's strict ``make_consense`` (which raises when a cluster's
    values disagree) so clustering can merge, e.g., AC+DC buses or mixed voltage
    units by keeping the dominant value.
    """
    s = x.dropna()
    if s.empty:
        return x.iloc[0] if len(x) else None
    m = s.mode()
    return m.iloc[0] if len(m) else s.iloc[0]


def _object_strategies(df: "pd.DataFrame") -> dict[str, Any]:
    """A majority strategy for every text (object) attribute of a component."""
    return {
        col: _majority
        for col in df.columns
        if col not in _BUS_REFS and df[col].dtype == object
    }


def _bus_conflicts(network: pypsa.Network, busmap: "pd.Series") -> list[str]:
    """Text bus attributes that disagree within at least one cluster."""
    buses = network.buses
    out: list[str] = []
    for col in buses.columns:
        if col in _BUS_REFS or buses[col].dtype != object:
            continue
        if buses.groupby(busmap)[col].nunique(dropna=True).gt(1).any():
            out.append(col)
    return out


def _counts(network: pypsa.Network) -> dict[str, int]:
    return {
        "buses": len(network.buses),
        "lines": len(network.lines),
        "transformers": len(network.transformers),
        "links": len(network.links),
        "generators": len(network.generators),
        "loads": len(network.loads),
        "storageUnits": len(network.storage_units),
    }


def cluster_model(
    model: dict[str, list[dict[str, Any]]],
    *,
    n_clusters: int,
    method: str = "modularity",
    resolve_conflicts: bool = True,
    scenario: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reduce a workbook model to ``n_clusters`` buses. Pure (no I/O) so it is
    unit-testable; the endpoint is a thin session-loading wrapper.

    Returns ``{model, busmap, method, before, after}`` where ``model`` is the
    reduced workbook model and ``busmap`` maps each original bus to its cluster.
    """
    scenario = dict(scenario or {})
    scenario.setdefault("discountRate", _DEFAULT_DISCOUNT_RATE)
    network, _notes = build_network(model, scenario, options or {})

    n_buses = len(network.buses)
    if n_buses < 2:
        raise HTTPException(
            status_code=400,
            detail="Network has fewer than 2 buses — nothing to cluster.",
        )
    if n_clusters < 1 or n_clusters >= n_buses:
        raise HTTPException(
            status_code=400,
            detail=f"Target clusters must be between 1 and {n_buses - 1} (network has {n_buses} buses).",
        )

    method = method.lower()
    try:
        if method == "kmeans":
            if network.buses[["x", "y"]].drop_duplicates().shape[0] < 2:
                raise HTTPException(
                    status_code=400,
                    detail="k-means needs distinct bus coordinates (x/y). Use the 'modularity' method, or import spatial data first.",
                )
            weightings = pd.Series(1, index=network.buses.index)
            busmap = network.cluster.spatial.busmap_by_kmeans(
                bus_weightings=weightings, n_clusters=n_clusters
            )
        elif method == "modularity":
            busmap = network.cluster.spatial.busmap_by_greedy_modularity(
                n_clusters=n_clusters
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown clustering method '{method}'. Use 'modularity' or 'kmeans'.",
            )

        # Which text bus attributes disagree within a cluster (for the report /
        # a clear error). Merging AC+DC buses or mixed units is a real change, so
        # it's surfaced either way.
        conflicts = _bus_conflicts(network, busmap)
        if conflicts and not resolve_conflicts:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Buses in a cluster disagree on: " + ", ".join(conflicts)
                    + ". Enable “Merge conflicting attributes” to cluster anyway "
                    "(keeps the most common value per cluster)."
                ),
            )

        strategies: dict[str, Any] = {}
        if resolve_conflicts:
            strategies = {
                "bus_strategies": _object_strategies(network.buses),
                "line_strategies": _object_strategies(network.lines),
            }
        clustered = network.cluster.spatial.cluster_by_busmap(busmap, **strategies)
        clustered = getattr(clustered, "n", clustered)  # Clustering wrapper vs Network
    except HTTPException:
        raise
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"This clustering method needs an optional dependency that isn't installed ({exc}). Try the 'modularity' method.",
        ) from exc
    except Exception as exc:  # noqa: BLE001 — surface as a 400, not a 500
        raise HTTPException(
            status_code=400, detail=f"Clustering failed: {exc}"
        ) from exc

    return {
        "model": network_to_model(clustered),
        "busmap": {str(k): str(v) for k, v in busmap.to_dict().items()},
        "method": method,
        "before": _counts(network),
        "after": _counts(clustered),
        "resolvedConflicts": conflicts if resolve_conflicts else [],
    }


@router.post("/cluster")
async def cluster_network(req: ClusterRequest) -> dict[str, Any]:
    """Cluster the session's working model and return the reduced model."""
    model = model_store.load_full_model(req.sessionId)
    if not model:
        raise HTTPException(
            status_code=400, detail="No working model in this session to cluster."
        )
    return cluster_model(
        model,
        n_clusters=req.nClusters,
        method=req.method,
        resolve_conflicts=req.resolveConflicts,
        scenario=req.scenario,
        options=req.options,
    )


class RenewableProfilesRequest(BaseModel):
    sessionId: str
    dateFrom: str = "2022-01-01"
    dateTo: str = "2022-01-31"
    performanceRatio: float = 0.9
    # Optional explicit carrier→tech mapping; otherwise names are classified by hint.
    solarCarriers: list[str] | None = None
    windCarriers: list[str] | None = None


@router.post("/renewable-profiles")
async def attach_renewable_profiles(req: RenewableProfilesRequest) -> dict[str, Any]:
    """Attach Open-Meteo weather-derived profiles to the session's existing
    renewable fleet by coordinate (I4). Fetches once per unique 0.1° grid cell
    (cached), returns ``generators-p_max_pu`` + a summary for the frontend to
    merge into the working model.
    """
    model = model_store.load_full_model(req.sessionId)
    if not model:
        raise HTTPException(status_code=400, detail="No working model in this session.")

    targets, skipped = resolve_targets(model, req.solarCarriers, req.windCarriers)
    if not targets:
        raise HTTPException(
            status_code=400,
            detail="No renewable generators with a resolvable coordinate found "
                   "(need a solar/wind carrier and x/y on the generator or its bus).",
        )

    # Dedup fetches by grid cell — many generators can share one weather point.
    uniq: dict[str, tuple[float, float]] = {}
    for _name, _kind, lat, lon in targets:
        uniq[point_key(lat, lon)] = (snap(lat), snap(lon))

    http = AsyncClientWrapper()
    try:
        keys = list(uniq)
        fetched = await asyncio.gather(
            *[fetch_point(http, lat, lon, req.dateFrom, req.dateTo) for lat, lon in uniq.values()],
            return_exceptions=True,
        )
    finally:
        await http.aclose()

    point_by_key: dict[str, dict[str, Any]] = {}
    failed = 0
    for key, res in zip(keys, fetched):
        if isinstance(res, Exception):
            failed += 1
            continue
        point_by_key[key] = res
    if not point_by_key:
        raise HTTPException(status_code=502, detail="Weather fetch failed for every point.")

    rows, snapshots, attached = build_profile_rows(targets, point_by_key, req.performanceRatio)
    if not attached:
        raise HTTPException(status_code=502, detail="No profiles could be built from the weather data.")

    # Return the COMPLETE merged sheet (existing server-side profiles + newly
    # attached columns) so the frontend can apply it with a clean replace.
    existing = model.get("generators-p_max_pu") or []
    merged = merge_profile_rows(existing, rows)

    return {
        "sheets": {"generators-p_max_pu": merged},
        "snapshots": snapshots,
        "attached": attached,
        "skipped": skipped,
        "sites": len(point_by_key),
        "failedSites": failed,
    }
