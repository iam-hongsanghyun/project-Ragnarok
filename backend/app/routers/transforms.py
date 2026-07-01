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
from pypsa.clustering.spatial import (
    DEFAULT_BUS_STRATEGIES as _DEFAULT_BUS_STRATEGIES,
    DEFAULT_LINE_STRATEGIES as _DEFAULT_LINE_STRATEGIES,
)
import pandas.api.types  # noqa: F401  (ensures pd.api.types is importable)

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
    # When true (default), buses/lines whose attributes disagree within a cluster
    # are merged instead of failing. Turn off to enforce strict agreement.
    resolveConflicts: bool = True
    # How to merge a NUMERIC conflicting attribute (e.g. v_mag_pu_set): the
    # cluster's mean / max / min, zero, or the attribute's schema default. Text
    # attributes (carrier, unit) always merge to the most common value.
    conflictStrategy: str = "mean"
    scenario: dict[str, Any] | None = None
    options: dict[str, Any] | None = None


# Bus-reference columns are remapped by clustering itself — never "resolve" them.
_BUS_REFS = {"bus", "bus0", "bus1", "bus2", "bus3", "bus4"}
_NUMERIC_STRATEGIES = ("mean", "max", "min", "zero", "default")


def _majority(x: "pd.Series") -> Any:
    """Keep the most common non-null value (ties → first). For text attributes."""
    s = x.dropna()
    if s.empty:
        return x.iloc[0] if len(x) else None
    m = s.mode()
    return m.iloc[0] if len(m) else s.iloc[0]


def _numeric_strategy(kind: str, default_value: Any) -> Any:
    """A pandas-agg strategy for a numeric attribute per the user's choice."""
    if kind in ("mean", "max", "min"):
        return kind
    if kind == "zero":
        return lambda _x: 0.0
    # "default" (or anything unknown) → the attribute's schema default value
    return lambda _x, _d=default_value: _d


def _component_defaults(component: str) -> "pd.Series":
    """Schema default values for a component's attributes (from a fresh add)."""
    probe = pypsa.Network()
    probe.add(component, "_probe")
    static = getattr(probe, {"Bus": "buses", "Line": "lines"}[component])
    return static.loc["_probe"]


def _conflict_strategies(
    df: "pd.DataFrame", defaults_keys: set[str], component: str, numeric_kind: str
) -> dict[str, Any]:
    """Aggregation strategies for attributes PyPSA has no default for (which
    otherwise raise on disagreement): the chosen strategy for numeric columns,
    most-common for text.
    """
    gap = [c for c in df.columns if c not in _BUS_REFS and c not in defaults_keys]
    if not gap:
        return {}
    schema_defaults = _component_defaults(component) if numeric_kind == "default" else None
    out: dict[str, Any] = {}
    for col in gap:
        if pd.api.types.is_numeric_dtype(df[col]):
            dv = float(schema_defaults[col]) if (schema_defaults is not None and col in schema_defaults.index) else 0.0
            out[col] = _numeric_strategy(numeric_kind, dv)
        else:
            out[col] = _majority
    return out


def _conflicting_attrs(df: "pd.DataFrame", groups: "pd.Series", defaults_keys: set[str]) -> list[str]:
    """Attributes (outside PyPSA's defaults) that disagree within a cluster."""
    out: list[str] = []
    for col in df.columns:
        if col in _BUS_REFS or col in defaults_keys:
            continue
        if df.groupby(groups)[col].nunique(dropna=True).gt(1).any():
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
    conflict_strategy: str = "mean",
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

        # Bus attributes that disagree within a cluster and have no PyPSA default
        # aggregation (these are what raise). Surfaced either way — merging
        # AC+DC buses or averaging voltage setpoints is a real change.
        bus_keys = set(_DEFAULT_BUS_STRATEGIES)
        conflicts = _conflicting_attrs(network.buses, busmap, bus_keys)
        if conflicts and not resolve_conflicts:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Buses in a cluster disagree on: " + ", ".join(conflicts)
                    + ". Enable “Merge conflicting attributes” to cluster anyway."
                ),
            )

        strategies: dict[str, Any] = {}
        if resolve_conflicts:
            kind = conflict_strategy if conflict_strategy in _NUMERIC_STRATEGIES else "mean"
            strategies = {
                "bus_strategies": _conflict_strategies(network.buses, bus_keys, "Bus", kind),
                "line_strategies": _conflict_strategies(
                    network.lines, set(_DEFAULT_LINE_STRATEGIES), "Line", kind
                ),
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
        conflict_strategy=req.conflictStrategy,
        scenario=req.scenario,
        options=req.options,
    )


class RenewableProfilesRequest(BaseModel):
    sessionId: str
    dateFrom: str = "2022-01-01"
    dateTo: str = "2022-01-31"
    performanceRatio: float = 0.9
    source: str = "open-meteo"
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
            *[fetch_point(http, lat, lon, req.dateFrom, req.dateTo, req.source) for lat, lon in uniq.values()],
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
