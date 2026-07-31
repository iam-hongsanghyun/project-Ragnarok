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
from ...pypsa.pypsa_schema import component_sheets

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
# weighted path; the rest via ``aggregate_one_ports``. "Link" (a branch, not a
# one-port) is additionally accepted and handled by ``_merge_parallel_links``.
_ONEPORT_ATTRS = {
    "Generator": "generators",
    "StorageUnit": "storage_units",
    "Store": "stores",
    "Load": "loads",
    "ShuntImpedance": "shunt_impedances",
}

# Link attributes that are MW quantities and therefore SUM when parallel links
# merge; every other numeric attribute takes the capacity-weighted mean.
_LINK_SUM_ATTRS = {"p_nom", "p_nom_max", "p_nom_min", "p_nom_opt", "p_set"}


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
        # Booleans FIRST: pandas reports bool dtype as numeric, so without this
        # the flags PyPSA has no one-port default for — p_nom_extendable,
        # e_nom_extendable, committable, active — would merge through the
        # numeric strategy: "mean" turns a mixed cluster into 0.5, and
        # zero/min/default silently clear extendability for the whole cluster,
        # so the reduced model can no longer expand capacity. Use "any", which
        # is what PyPSA itself uses for `s_nom_extendable` on lines.
        if pd.api.types.is_bool_dtype(df[col]):
            out[col] = "any"
        elif pd.api.types.is_numeric_dtype(df[col]):
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


def _merge_parallel_links(network: pypsa.Network) -> int:
    """Merge parallel transmission-style links into one per corridor, in place.

    Links merge when they share the same direction (``bus0 → bus1``), the same
    link ``carrier`` and the same ``p_nom_extendable`` flag — i.e. parallel DC
    interconnectors between two clustered buses. Only pure *transport* links
    qualify: both endpoint buses must share a bus carrier and the link must use
    no extra ports (``bus2``…). Conversion links (electrolysis, heat pumps,
    chargers) are never touched, and opposite-direction links are kept apart
    because ``efficiency`` applies to the bus0→bus1 flow.

    Algorithm (per merged corridor with members $i$, weights $w_i$):
        $$P^{nom} = \\sum_i P^{nom}_i, \\qquad
          \\eta = \\sum_i w_i\\,\\eta_i, \\quad
          w_i = P^{nom}_i / \\sum_j P^{nom}_j$$
        ASCII: p_nom = sum(p_nom_i); efficiency/costs/pu-limits =
        capacity-weighted mean (equal weights when total p_nom = 0).
        p_nom / p_nom_min / p_nom_max / p_set sum; every other numeric
        attribute (efficiency, marginal_cost, capital_cost, p_max_pu, length…)
        is capacity-weighted; text attributes keep the most common value.
        Time-varying attributes merge the same way, with a member's static
        value standing in where it has no series.

    Returns the number of link rows removed by merging.
    """
    links = network.links
    if links.empty:
        return 0

    bus_carrier = network.buses["carrier"]
    transport = links["bus0"].map(bus_carrier).eq(links["bus1"].map(bus_carrier))
    extra_ports = [
        c for c in links.columns if c.startswith("bus") and c not in ("bus0", "bus1")
    ]
    for col in extra_ports:
        transport &= links[col].fillna("").astype(str).str.strip().eq("")

    groups: dict[tuple[str, str, str, bool], list[str]] = {}
    for name in links.index[transport]:
        row = links.loc[name]
        key = (
            str(row["bus0"]),
            str(row["bus1"]),
            str(row.get("carrier", "")),
            bool(row.get("p_nom_extendable", False)),
        )
        groups.setdefault(key, []).append(str(name))

    removed = 0
    for (bus0, bus1, carrier, _ext), names in groups.items():
        if len(names) < 2:
            continue
        sub = network.links.loc[names]
        p_nom = sub["p_nom"].astype(float).clip(lower=0.0)
        w = (
            p_nom / p_nom.sum()
            if p_nom.sum() > 0
            else pd.Series(1.0 / len(sub), index=sub.index)
        )

        # NaN means "unset" for many link attributes (p_nom_set, p_set, ramp
        # limits…) — a merged value must stay NaN when every member is NaN,
        # never become 0.0 (a zero p_nom_set/ramp limit would freeze the link).
        merged: dict[str, Any] = {}
        for col in sub.columns:
            vals = sub[col]
            if col in ("bus0", "bus1"):
                merged[col] = vals.iloc[0]
            elif pd.api.types.is_bool_dtype(vals) or not pd.api.types.is_numeric_dtype(
                vals
            ):
                merged[col] = _majority(vals)
            elif vals.astype(float).isna().all():
                merged[col] = float("nan")
            elif col in _LINK_SUM_ATTRS:
                merged[col] = float(vals.astype(float).sum())
            else:
                # Weighted mean over the members that carry a value, weights
                # renormalised (equal split when they sum to zero).
                v = vals.astype(float)
                ww = w.where(v.notna(), 0.0)
                if ww.sum() <= 0:
                    ww = v.notna().astype(float)
                ww = ww / ww.sum()
                merged[col] = float((v.fillna(0.0) * ww).sum())

        # Time-varying inputs: merge like the statics, a member's static value
        # standing in where it carries no series. Output frames (p0, p1…) have
        # no static column and are skipped.
        dynamic: dict[str, pd.Series] = {}
        for attr, df in network.links_t.items():
            present = [n for n in names if n in df.columns]
            if not present or attr not in sub.columns:
                continue
            cols: dict[str, pd.Series] = {}
            for n in names:
                if n in df.columns:
                    cols[n] = df[n].astype(float)
                else:
                    static_value = sub.at[n, attr]
                    # A NaN static fallback means the member has the attribute
                    # unset — it contributes nothing to the blend.
                    if pd.isna(static_value):
                        continue
                    cols[n] = pd.Series(float(static_value), index=df.index)
            frame = pd.DataFrame(cols)
            if attr in _LINK_SUM_ATTRS:
                dynamic[attr] = frame.sum(axis=1)
            else:
                ws = w[list(cols)]
                ws = (
                    ws / ws.sum()
                    if ws.sum() > 0
                    else pd.Series(1.0 / len(cols), index=list(cols))
                )
                dynamic[attr] = (frame * ws).sum(axis=1)

        network.remove("Link", names)
        base = f"{bus0} - {bus1}" + (f" {carrier}" if carrier else "")
        new_name, i = base, 2
        while new_name in network.links.index:
            new_name, i = f"{base} ({i})", i + 1
        network.add("Link", new_name, **{**merged, **dynamic})
        removed += len(names) - 1
    return removed


def _preserved_config_sheets(
    model: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Non-PyPSA sheets a reduction must carry over untouched.

    ``network_to_model`` emits only ``snapshots``, ``network`` and schema-known
    component sheets, so every Ragnarok config sheet (``RAGNAROK_Pathway``,
    ``RAGNAROK_PathwayPeriods``, ``RAGNAROK_Sampling``, ``RAGNAROK_Rolling``,
    ``RAGNAROK_Scenarios``, ``RAGNAROK_CustomDSL``,
    ``RAGNAROK_CarbonSchedules``, …) would vanish from the reduced model — and
    the frontend applies that model over the session, so the loss is permanent.
    Dropping them takes a multi-period plan back to single period, discards
    representative-snapshot weighting and custom-DSL expansion constraints, and
    replaces the scenario catalogue with a synthetic base case.

``network`` and ``snapshots`` are handled by
    :func:`_restore_workbook_only_columns` instead — the serialiser always emits
    both, so a ``setdefault`` here could never take the source version.

    Other component sheets and their ``<component>-<attr>`` time-series are NOT
    preserved — the reduction owns those. A carried-over config sheet may still
    reference a component the reduction merged away (e.g. a scenario override on
    a bus that no longer exists); those references are resolved by name at run
    time and simply no longer match, which is strictly better than losing the
    whole configuration.
    """
    known = set(component_sheets())
    out: dict[str, list[dict[str, Any]]] = {}
    for sheet, rows in model.items():
        if not isinstance(rows, list) or not rows:
            continue
        if sheet in known:
            continue
        component, _, attribute = sheet.partition("-")
        if attribute and component in known:
            continue
        out[sheet] = rows
    return out


def _restore_workbook_only_columns(
    reduced: dict[str, list[dict[str, Any]]],
    source: dict[str, list[dict[str, Any]]],
) -> None:
    """Re-attach the columns of ``network`` / ``snapshots`` the network cannot hold.

    Both sheets are always re-emitted by the serialiser, so they cannot be carried
    by ``setdefault`` — they need merging:

    * ``network`` — the object round-trips only ``name``; the sheet also carries
      ``srid`` / ``crs`` / ``now``. Source columns are kept and the derived name
      wins (the reduction may have renamed the network).
    * ``snapshots`` — the pathway ``period`` column is only re-emitted when the
      network was built multi-period, so a transform run with the pathway off would
      drop it. A transform never changes the time axis, so the source sheet is
      preferred whenever it still covers every snapshot the reduction carries.
    """
    src_network = source.get("network")
    if isinstance(src_network, list) and src_network:
        merged = [dict(row) for row in src_network if isinstance(row, dict)]
        if merged:
            derived = ((reduced.get("network") or [{}])[0] or {}).get("name")
            if derived:
                merged[0]["name"] = derived
            reduced["network"] = merged

    src_snapshots = source.get("snapshots")
    if isinstance(src_snapshots, list) and src_snapshots:
        derived_axis = _snapshot_label_set(reduced.get("snapshots") or [])
        if derived_axis and derived_axis <= _snapshot_label_set(src_snapshots):
            reduced["snapshots"] = [dict(r) for r in src_snapshots if isinstance(r, dict)]


def _snapshot_label_set(rows: list[dict[str, Any]]) -> set[str]:
    """Normalised snapshot labels, so ``…T00:00:00`` and ``… 00:00:00`` compare equal."""
    out: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("snapshot", "name", "datetime", "timestep", "index"):
            value = row.get(key)
            if value in (None, ""):
                continue
            try:
                out.add(pd.Timestamp(value).isoformat())
            except (ValueError, TypeError):
                out.add(str(value).strip())
            break
    return out


def _restore_shapes(
    reduced: dict[str, list[dict[str, Any]]],
    source: dict[str, list[dict[str, Any]]],
    busmap: "pd.Series",
) -> None:
    """Put the workbook's ``shapes`` sheet back after clustering, in place.

    PyPSA's ``cluster_by_busmap`` drops the ``Shape`` component outright — the
    clustered network comes back with zero shape rows — so the user's region
    geometry, which nothing else in the model can reconstruct, disappeared on every
    reduction. ``_preserved_config_sheets`` cannot cover it either: ``shapes`` IS a
    schema component, so it is excluded there by design. Rows are copied back
    verbatim with a bus-referencing ``idx`` remapped through the busmap, so it names
    the cluster the bus merged into instead of a bus that no longer exists.
    """
    rows = source.get("shapes")
    if not isinstance(rows, list) or not rows:
        return
    if reduced.get("shapes"):
        return  # a future PyPSA that does cluster shapes wins over this fallback
    mapping = {str(k): str(v) for k, v in busmap.to_dict().items()}
    restored: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        new_row = dict(row)
        if str(new_row.get("component", "")).strip().lower() in ("bus", "buses"):
            idx = new_row.get("idx")
            if idx is not None and str(idx) in mapping:
                new_row["idx"] = mapping[str(idx)]
        restored.append(new_row)
    if restored:
        reduced["shapes"] = restored


def _transform_build_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """Run options for a build whose network is serialised straight back to a workbook.

    Two corrections, both because a transform's output becomes the user's model
    rather than a solve:

    * ``skipCapexAnnuitisation`` — otherwise the reduced workbook stores an
      annuitised ``capital_cost`` that the next run annuitises AGAIN (extendable
      CAPEX ≈ AF² of its real value, so capacity expansion builds almost for free).
    * the snapshot window, the ``snapshotWeight`` stride and representative
      ``samplingConfig`` are NEUTRALISED. ``build_network`` applies all three to
      ``network.snapshots``, and serialising that back would rewrite the user's
      model with a truncated, downsampled time axis. A transform rewrites the whole
      model, so it has to see the whole time axis.

    ``pathwayConfig`` is kept: it decides whether the network is built with an
    investment-period MultiIndex, and dropping it collapses per-period profiles
    into one shared profile.
    """
    out = {**(options or {}), "skipCapexAnnuitisation": True}
    for key in ("snapshotStart", "snapshotEnd", "snapshotCount"):
        out.pop(key, None)
    out["snapshotWeight"] = 1
    out["samplingConfig"] = {"enabled": False}
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
    additionally collapsed by carrier on each merged bus; ``"Link"`` merges
    parallel transmission-style links per corridor (capacity summed, loss
    capacity-weighted — see ``_merge_parallel_links``).

    Returns ``{model, busmap, method, before, after}`` where ``model`` is the
    reduced workbook model and ``busmap`` maps each original bus to its cluster.
    """
    scenario = dict(scenario or {})
    scenario.setdefault("discountRate", _DEFAULT_DISCOUNT_RATE)
    # See `_transform_build_options`: no CAPEX annuitisation (the reduced workbook
    # would be annuitised twice) and no run window / sampling (it would truncate
    # the user's time axis).
    network, _notes = build_network(model, scenario, _transform_build_options(options))

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

    agg = {
        c for c in (aggregate_components or []) if c in _ONEPORT_ATTRS or c == "Link"
    }
    oneport_agg = agg & set(_ONEPORT_ATTRS)
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
        if oneport_agg:
            gen_strat, oneport_strat = _component_strategies(
                network, oneport_agg, kind
            )
            if "Generator" in oneport_agg:
                strategies["aggregate_generators_weighted"] = True
                strategies["generator_strategies"] = gen_strat
            other = oneport_agg - {"Generator"}
            if other:
                strategies["aggregate_one_ports"] = other
                strategies["one_port_strategies"] = oneport_strat

        clustered = network.cluster.spatial.cluster_by_busmap(busmap, **strategies)
        clustered = getattr(clustered, "n", clustered)  # Clustering wrapper vs Network

        # Clustering only re-attaches links (dropping intra-cluster loops);
        # merging parallel corridors is our own post-step.
        if "Link" in agg:
            _merge_parallel_links(clustered)
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

    reduced = network_to_model(clustered)
    # Carry the Ragnarok config sheets (pathway, sampling, rolling, scenarios,
    # custom DSL, carbon schedules) across the network round-trip — the
    # serialiser only knows PyPSA components. `setdefault` so anything the
    # serialiser did produce still wins.
    for sheet, rows in _preserved_config_sheets(model).items():
        reduced.setdefault(sheet, rows)
    _restore_shapes(reduced, model, busmap)
    _restore_workbook_only_columns(reduced, model)

    return {
        "model": reduced,
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
