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
  • ``single`` — collapse the whole network onto one bus. Topology- and
    coordinate-free, so it always reaches a single node where modularity (which
    floors out at the connected-component count) or k-means may not.
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
    DEFAULT_ONE_PORT_STRATEGIES as _DEFAULT_ONE_PORT_STRATEGIES,
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
    # When set, buses are grouped by this workbook column (e.g. "province",
    # "country") instead of by nClusters/method. Buses sharing a value merge;
    # blank-valued buses stay on their own. Read from the raw model — custom
    # columns are dropped by build_network.
    groupByColumn: str | None = None
    # PyPSA one-port components to additionally aggregate by carrier per merged
    # bus (e.g. ["Generator", "StorageUnit", "Store", "Load", "ShuntImpedance"]).
    # Empty/None ⇒ components are only reassigned to their new bus (legacy).
    aggregateComponents: list[str] | None = None
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

# One-port components the aggregation can collapse by carrier, mapped to their
# Network static-frame attribute. "Generator" is aggregated via the dedicated
# weighted path; the rest via ``aggregate_one_ports``.
_ONEPORT_ATTRS = {
    "Generator": "generators",
    "StorageUnit": "storage_units",
    "Store": "stores",
    "Load": "loads",
    "ShuntImpedance": "shunt_impedances",
}


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
    static_attr = {"Bus": "buses", "Line": "lines", **_ONEPORT_ATTRS}[component]
    # One-port probes need a host bus to attach to.
    if component in _ONEPORT_ATTRS:
        probe.add("Bus", "_bus")
        probe.add(component, "_probe", bus="_bus")
    else:
        probe.add(component, "_probe")
    static = getattr(probe, static_attr)
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
    schema_defaults = (
        _component_defaults(component) if numeric_kind == "default" else None
    )
    out: dict[str, Any] = {}
    for col in gap:
        if pd.api.types.is_numeric_dtype(df[col]):
            dv = (
                float(schema_defaults[col])
                if (schema_defaults is not None and col in schema_defaults.index)
                else 0.0
            )
            out[col] = _numeric_strategy(numeric_kind, dv)
        else:
            out[col] = _majority
    return out


def _conflicting_attrs(
    df: "pd.DataFrame", groups: "pd.Series", defaults_keys: set[str]
) -> list[str]:
    """Attributes (outside PyPSA's defaults) that disagree within a cluster."""
    out: list[str] = []
    for col in df.columns:
        if col in _BUS_REFS or col in defaults_keys:
            continue
        if df.groupby(groups)[col].nunique(dropna=True).gt(1).any():
            out.append(col)
    return out


def _busmap_by_column(
    model: dict[str, list[dict[str, Any]]], column: str
) -> "pd.Series":
    """Group buses by a workbook column (e.g. "province"). Buses sharing a value
    map to that value; a blank/missing value keeps the bus on its own (maps to
    its own name). Read from the raw model because ``build_network`` drops custom
    bus columns. Raises 400 if the column is absent everywhere or merges nothing.
    """
    buses = model.get("buses") or []
    mapping: dict[str, str] = {}
    seen_column = False
    for row in buses:
        name = row.get("name")
        if name is None:
            continue
        name = str(name)
        value = row.get(column)
        if column in row:
            seen_column = True
        # Blank / missing → own singleton (never merge unrelated buses).
        if (
            value is None
            or (isinstance(value, float) and pd.isna(value))
            or (isinstance(value, str) and value.strip() == "")
        ):
            mapping[name] = name
        else:
            mapping[name] = str(value)

    if not seen_column:
        raise HTTPException(
            status_code=400,
            detail=f"No bus has a '{column}' column to group by.",
        )
    if len(set(mapping.values())) >= len(mapping):
        raise HTTPException(
            status_code=400,
            detail=f"Grouping by '{column}' merges no buses — every bus has a distinct (or blank) value.",
        )
    return pd.Series(mapping)


def _component_strategies(
    network: pypsa.Network, components: set[str], numeric_kind: str
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Build aggregation strategies for the components being merged by carrier,
    covering custom columns PyPSA has no default for (which otherwise raise).

    Returns ``(generator_strategies, one_port_strategies)`` matching PyPSA's
    ``get_clustering_from_busmap`` contract: a flat ``{attr: strategy}`` for
    generators, and a nested ``{ComponentName: {attr: strategy}}`` for the rest.
    """
    oneport_keys = set(_DEFAULT_ONE_PORT_STRATEGIES)
    generator_strategies: dict[str, Any] = {}
    one_port_strategies: dict[str, dict[str, Any]] = {}
    for comp in components:
        df = getattr(network, _ONEPORT_ATTRS[comp])
        strat = _conflict_strategies(df, oneport_keys, comp, numeric_kind)
        if comp == "Generator":
            generator_strategies = strat
        elif strat:
            one_port_strategies[comp] = strat
    return generator_strategies, one_port_strategies


def _counts(network: pypsa.Network) -> dict[str, int]:
    return {
        "buses": len(network.buses),
        "lines": len(network.lines),
        "transformers": len(network.transformers),
        "links": len(network.links),
        "generators": len(network.generators),
        "loads": len(network.loads),
        "storageUnits": len(network.storage_units),
        "stores": len(network.stores),
        "shuntImpedances": len(network.shunt_impedances),
    }


def cluster_model(
    model: dict[str, list[dict[str, Any]]],
    *,
    n_clusters: int,
    method: str = "modularity",
    group_by_column: str | None = None,
    aggregate_components: list[str] | None = None,
    resolve_conflicts: bool = True,
    conflict_strategy: str = "mean",
    scenario: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reduce a workbook model to fewer buses. Pure (no I/O) so it is
    unit-testable; the endpoint is a thin session-loading wrapper.

    Buses are grouped either by ``group_by_column`` (merge buses sharing a
    workbook value, e.g. "province"), all onto one bus (``method="single"``), or
    by ``n_clusters`` using the ``method`` (modularity/kmeans). When
    ``aggregate_components`` is given, the named one-port components are
    additionally collapsed by carrier on each merged bus.

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

    method = method.lower()
    single = method == "single"
    by_column = (not single) and bool(group_by_column and str(group_by_column).strip())
    # "single" always targets one bus; column groups by a value — neither needs a
    # cluster count. The count is only validated for modularity/k-means.
    if not single and not by_column and (n_clusters < 1 or n_clusters >= n_buses):
        raise HTTPException(
            status_code=400,
            detail=f"Target clusters must be between 1 and {n_buses - 1} (network has {n_buses} buses).",
        )

    agg = {c for c in (aggregate_components or []) if c in _ONEPORT_ATTRS}
    try:
        if single:
            # Collapse the ENTIRE network onto one bus, independent of topology or
            # coordinates. Every bus maps to the first bus's name. Unlike
            # modularity (which floors out at the connected-component count) or
            # k-means (which needs distinct coordinates), this always reaches a
            # single node — the robust "1-bus" reduction.
            busmap = pd.Series(str(network.buses.index[0]), index=network.buses.index)
        elif by_column:
            column = str(group_by_column).strip()
            busmap = _busmap_by_column(model, column)
            method = f"column:{column}"
        elif method == "kmeans":
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
                detail=f"Unknown clustering method '{method}'. Use 'modularity', 'kmeans' or 'single'.",
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
                    "Buses in a cluster disagree on: "
                    + ", ".join(conflicts)
                    + ". Enable “Merge conflicting attributes” to cluster anyway."
                ),
            )

        kind = conflict_strategy if conflict_strategy in _NUMERIC_STRATEGIES else "mean"
        strategies: dict[str, Any] = {}
        if resolve_conflicts:
            strategies = {
                "bus_strategies": _conflict_strategies(
                    network.buses, bus_keys, "Bus", kind
                ),
                "line_strategies": _conflict_strategies(
                    network.lines, set(_DEFAULT_LINE_STRATEGIES), "Line", kind
                ),
            }

        # Optionally collapse one-port components by carrier on each merged bus.
        # Generators use the dedicated weighted path; the rest go through
        # aggregate_one_ports. Custom-column strategies avoid "no default" raises.
        if agg:
            gen_strat, oneport_strat = _component_strategies(network, agg, kind)
            if "Generator" in agg:
                strategies["aggregate_generators_weighted"] = True
                strategies["generator_strategies"] = gen_strat
            other = agg - {"Generator"}
            if other:
                strategies["aggregate_one_ports"] = other
                strategies["one_port_strategies"] = oneport_strat

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
        "groupByColumn": group_by_column if by_column else None,
        "aggregatedComponents": sorted(agg),
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
        group_by_column=req.groupByColumn,
        aggregate_components=req.aggregateComponents,
        resolve_conflicts=req.resolveConflicts,
        conflict_strategy=req.conflictStrategy,
        scenario=req.scenario,
        options=req.options,
    )


# ── Adjust a carrier's total capacity to a target ────────────────────────────
_SCALE_METHODS = ("proportional", "equal", "custom")
_SCALE_MODES = ("cap", "fix")


def scale_carrier_capacity(
    model: dict[str, list[dict[str, Any]]],
    *,
    carrier: str,
    target_mw: float,
    method: str = "proportional",
    mode: str = "cap",
    shares: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Distribute a carrier's total capacity to ``target_mw`` across its generators.

    Pure (no I/O) so it is unit-testable; the endpoint is a thin session wrapper.
    Only rows in the ``generators`` sheet whose ``carrier`` matches are touched;
    every other sheet is returned unchanged.

    Distribution ``method``:
      * ``proportional`` — each generator keeps its share of the current total,
        ``p_nom_i · target / Σ p_nom``. If the carrier currently sums to zero
        (nothing to scale), falls back to an equal split.
      * ``equal`` — ``target / n`` to each of the carrier's ``n`` generators.
      * ``custom`` — explicit per-generator MW from ``shares`` (keyed by
        generator name); the values must sum to ``target_mw``.

    Target ``mode`` (how the per-unit value is written):
      * ``cap`` — write ``p_nom_max`` and set ``p_nom_extendable=True``; the
        optimiser may build each unit *up to* its share, so the carrier's built
        capacity is bounded **at** the target.
      * ``fix`` — write ``p_nom`` and set ``p_nom_extendable=False``; the
        carrier's installed capacity **equals** the target exactly.

    Algorithm (proportional):
        $$p^{\\mathrm{new}}_i = p^{nom}_i \\cdot \\frac{T}{\\sum_j p^{nom}_j}$$
        ASCII: p_new[i] = p_nom[i] * T / sum(p_nom)   (T = target_mw, MW)

    Returns ``{model, carrier, targetMw, method, mode, before, after, perUnit,
    notes}``.
    """
    if method not in _SCALE_METHODS:
        raise HTTPException(status_code=400, detail=f"method must be one of {', '.join(_SCALE_METHODS)}")
    if mode not in _SCALE_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(_SCALE_MODES)}")
    if target_mw < 0:
        raise HTTPException(status_code=400, detail="targetMw must be ≥ 0.")

    gens = model.get("generators") or []
    cgens = [g for g in gens if str(g.get("carrier", "")) == carrier]
    if not cgens:
        raise HTTPException(status_code=400, detail=f"No generators with carrier '{carrier}'.")

    def _p(g: dict[str, Any]) -> float:
        try:
            return float(g.get("p_nom") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    current_total = sum(_p(g) for g in cgens)
    notes: list[str] = []

    # Resolve each generator's new MW.
    values: list[float] = [0.0] * len(cgens)
    if method == "custom":
        provided = {str(k): float(v) for k, v in (shares or {}).items()}
        names = {str(g.get("name")) for g in cgens}
        unknown = [k for k in provided if k not in names]
        if unknown:
            raise HTTPException(status_code=400, detail=f"shares reference unknown generators: {', '.join(unknown)}")
        missing = [n for n in names if n not in provided]
        if missing:
            raise HTTPException(status_code=400, detail=f"shares missing generators: {', '.join(missing)}")
        s = sum(provided.values())
        if target_mw > 0 and abs(s - target_mw) > 1e-6 * max(1.0, target_mw):
            raise HTTPException(status_code=400, detail=f"shares sum to {s:g} MW but target is {target_mw:g} MW.")
        values = [provided[str(g.get("name"))] for g in cgens]
    elif method == "equal" or current_total <= 0:
        if method == "proportional":
            notes.append("Carrier capacity is currently 0 — distributed equally.")
        share = target_mw / len(cgens)
        values = [share] * len(cgens)
    else:  # proportional
        values = [_p(g) * target_mw / current_total for g in cgens]

    per_unit: list[dict[str, Any]] = []
    for g, new_i in zip(cgens, values):
        before_i = _p(g)
        if mode == "cap":
            g["p_nom_max"] = new_i
            g["p_nom_extendable"] = True
            if before_i > new_i:  # keep the starting capacity ≤ the new ceiling
                g["p_nom"] = new_i
        else:  # fix
            g["p_nom"] = new_i
            g["p_nom_extendable"] = False
        per_unit.append({"name": g.get("name"), "before": before_i, "after": new_i})

    return {
        "model": model,
        "carrier": carrier,
        "targetMw": target_mw,
        "method": method,
        "mode": mode,
        "before": current_total,
        "after": sum(values),
        "perUnit": per_unit,
        "notes": notes,
    }


class ScaleCarrierCapacityRequest(BaseModel):
    sessionId: str
    carrier: str
    targetMw: float
    method: str = "proportional"  # proportional | equal | custom
    mode: str = "cap"             # cap → p_nom_max (extendable) | fix → p_nom
    shares: dict[str, float] | None = None


@router.post("/scale-carrier-capacity")
async def scale_carrier_capacity_endpoint(req: ScaleCarrierCapacityRequest) -> dict[str, Any]:
    """Adjust a carrier's total capacity to a target and return the new model."""
    model = model_store.load_full_model(req.sessionId)
    if not model:
        raise HTTPException(status_code=400, detail="No working model in this session.")
    return scale_carrier_capacity(
        model,
        carrier=req.carrier,
        target_mw=req.targetMw,
        method=req.method,
        mode=req.mode,
        shares=req.shares,
    )


class RenewableProfilesRequest(BaseModel):
    sessionId: str
    dateFrom: str = "2019-01-01"
    dateTo: str = "2019-01-31"
    performanceRatio: float = 0.9
    source: str = "open-meteo"
    # Shift snapshot labels from UTC to local time (e.g. 9 for Korea).
    utcOffset: int = 0
    # Optional explicit carrier→tech mapping; otherwise names are classified by hint.
    solarCarriers: list[str] | None = None
    windCarriers: list[str] | None = None


class HydroInflowRequest(BaseModel):
    sessionId: str
    dateFrom: str = "2019-01-01"
    dateTo: str = "2019-12-31"
    # Window-mean inflow per unit = targetCapacityFactor × p_nom.
    targetCapacityFactor: float = 0.35
    utcOffset: int = 0
    # Optional explicit hydro carriers; otherwise classified by name hint
    # (hydro/ror/reservoir/water; PHS/pumped excluded).
    hydroCarriers: list[str] | None = None


@router.post("/hydro-inflow")
async def attach_hydro_inflow(req: HydroInflowRequest) -> dict[str, Any]:
    """Attach GloFAS river-discharge-shaped inflow to the session's hydro
    storage units by coordinate (I4 remainder). Fetches once per unique 0.1°
    cell (cached forever — reanalysis archive), returns the COMPLETE merged
    ``storage_units-inflow`` sheet for a clean replace."""
    from ..importers.databases.openmeteo_renewable.inflow import (
        build_inflow_rows,
        fetch_discharge,
        resolve_hydro_targets,
    )

    model = model_store.load_full_model(req.sessionId)
    if not model:
        raise HTTPException(status_code=400, detail="No working model in this session.")
    targets, skipped = resolve_hydro_targets(model, req.hydroCarriers)
    if not targets:
        raise HTTPException(
            status_code=400,
            detail="No hydro storage units with a resolvable coordinate found "
            "(need a hydro-like carrier, p_nom > 0, and x/y on the unit or its bus).",
        )

    uniq: dict[str, tuple[float, float]] = {}
    for _name, _p_nom, lat, lon in targets:
        uniq[point_key(lat, lon)] = (snap(lat), snap(lon))

    http = AsyncClientWrapper()
    try:
        keys = list(uniq)
        fetched = await asyncio.gather(
            *[
                fetch_discharge(http, lat, lon, req.dateFrom, req.dateTo)
                for lat, lon in uniq.values()
            ],
            return_exceptions=True,
        )
    finally:
        await http.aclose()

    discharge_by_key: dict[str, Any] = {}
    failed = 0
    for key, res in zip(keys, fetched):
        if isinstance(res, Exception):
            failed += 1
            continue
        discharge_by_key[key] = res
    if not discharge_by_key:
        raise HTTPException(
            status_code=502, detail="Discharge fetch failed for every point."
        )

    rows, snapshots, attached, notes = build_inflow_rows(
        targets,
        discharge_by_key,
        target_cf=req.targetCapacityFactor,
        utc_offset=req.utcOffset,
    )
    if not attached:
        raise HTTPException(status_code=502, detail="No inflow series could be built.")

    existing = model.get("storage_units-inflow") or []
    merged = merge_profile_rows(existing, rows)
    return {
        "sheets": {"storage_units-inflow": merged},
        "snapshots": snapshots,
        "attached": attached,
        "skipped": skipped,
        "sites": len(discharge_by_key),
        "failedSites": failed,
        "notes": notes,
    }


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
            *[
                fetch_point(http, lat, lon, req.dateFrom, req.dateTo, req.source)
                for lat, lon in uniq.values()
            ],
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
        raise HTTPException(
            status_code=502, detail="Weather fetch failed for every point."
        )

    rows, snapshots, attached = build_profile_rows(
        targets, point_by_key, req.performanceRatio, req.utcOffset
    )
    if not attached:
        raise HTTPException(
            status_code=502, detail="No profiles could be built from the weather data."
        )

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
