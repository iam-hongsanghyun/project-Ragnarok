"""Forge clustering extras: what PyPSA's spatial clustering leaves to the caller.

PyPSA owns the busmaps and ``cluster_by_busmap`` / ``aggregate_one_ports``. This module adds, before the model is
handed back to the workbook as visible rows: a busmap read from a bus **column** (a user-chosen grouping),
conflict-aware aggregation strategies for attributes PyPSA's defaults do not cover, and the merge of the parallel
links that clustering leaves between the same two buses. ``routers/transforms.py`` calls these.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa
from fastapi import HTTPException
from pypsa.clustering.spatial import (
    DEFAULT_ONE_PORT_STRATEGIES as _DEFAULT_ONE_PORT_STRATEGIES,
)

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

