"""Aggregate generators that share ``(bus, carrier)`` into a single component.

Designed to run after :func:`~lib.region.aggregate_by_region` so the
bus structure is the final aggregation granularity.

Rules
-----
The ``aggregation_by_carrier`` sheet supplies static-attribute rules
(``attribute, rule``); the ``aggregation_by_carrier_t`` sheet supplies
time-series rules (same shape).  Recognised rule values:

==============  ==================================================
Rule            Behaviour
==============  ==================================================
``sum``         Sum across members.
``mean``        Unweighted arithmetic mean.
``weighted_avg``Weighted by ``p_nom``.  Falls back to ``mean`` when
                ``p_nom`` is missing or all zero.
``min``         Minimum.
``max``         Maximum.
``carrier``     The group's carrier name.
``bus``         The group's bus.
``p_nom``       Use the value from the member with the largest
                ``p_nom`` (the "lead" unit).
``ignore``      Drop the attribute from the merged component.
*other*         Treated as a literal value and copied verbatim.
==============  ==================================================

The ``others`` row provides the default rule for attributes that have no
explicit row.  ``p_nom`` is always summed (safety override) so total
capacity is preserved regardless of what the rule sheet says.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pypsa

if TYPE_CHECKING:
    from lib.settings import Dashboard


def _rule_lookup(rules_df: pd.DataFrame | None) -> tuple[dict[str, str], str]:
    """Return ``(attribute → rule, default_rule)`` from a rules DataFrame."""
    if rules_df is None or rules_df.empty:
        return {}, "ignore"
    table: dict[str, str] = {
        str(a).strip(): str(r).strip()
        for a, r in zip(rules_df["attribute"], rules_df["rule"])
    }
    default = table.pop("others", "ignore")
    return table, default


def _apply_static_rule(
    group: pd.DataFrame,
    col: str,
    rule: str,
    bus: str,
    carrier: str,
    lead: str,
) -> object:
    """Reduce ``group[col]`` to a single value via *rule*."""
    if rule == "ignore":
        return None
    if rule == "carrier":
        return carrier
    if rule == "bus":
        return bus
    if rule == "p_nom":
        return group.at[lead, col]

    series = pd.to_numeric(group[col], errors="coerce") if group[col].dtype != object else group[col]

    if rule == "sum":
        return series.sum()
    if rule == "mean":
        return series.mean()
    if rule == "min":
        return series.min()
    if rule == "max":
        return series.max()
    if rule == "weighted_avg":
        weights = pd.to_numeric(group.get("p_nom"), errors="coerce").fillna(0.0)
        wsum = weights.sum()
        if wsum > 0 and pd.api.types.is_numeric_dtype(series):
            return float((series * weights).sum() / wsum)
        return series.mean()

    # Literal value: numeric strings become floats, others pass through.
    try:
        return float(rule)
    except (TypeError, ValueError):
        return rule


def _reduce_ts(df: pd.DataFrame, rule: str) -> pd.Series:
    """Reduce a per-snapshot DataFrame of member time series to one column."""
    if rule == "sum":
        return df.sum(axis=1)
    if rule == "max":
        return df.max(axis=1)
    if rule == "min":
        return df.min(axis=1)
    # mean / weighted_avg / ignore / anything else → mean (best general default
    # for per-unit profiles such as p_max_pu).
    return df.mean(axis=1)


def aggregate_by_carrier(network: pypsa.Network, dashboard: "Dashboard") -> None:
    """Merge generators sharing ``(bus, carrier)`` into one component.

    Pipeline contract:

    * Skips silently when ``settings.aggregate_by_carrier`` is ``False``.
    * Reads rules from ``dashboard.carrier_rules`` (static) and
      ``dashboard.carrier_rules_t`` (time-series).  ``None`` means no rules
      → only ``p_nom`` (sum), ``carrier``, and ``bus`` are kept.
    * Modifies *network* in place.

    Algorithm:
        groups = generators.groupby(['bus', 'carrier'])
        for each group with len(group) >= 2:
            new_name = f"{carrier}_{bus}"
            for each static attribute col:
                rule = static_rules.get(col, default_static)
                new[col] = _apply_static_rule(group, col, rule, …)
            for each time-series attribute attr:
                rule = ts_rules.get(attr, default_ts)
                generators_t[attr][new_name] = _reduce_ts(member_columns, rule)
            remove members; add new_name

    Args:
        network:   PyPSA Network to modify in place.
        dashboard: Parsed :class:`~lib.settings.Dashboard`.  Reads
            ``settings.aggregate_by_carrier``, ``dashboard.carrier_rules``,
            ``dashboard.carrier_rules_t``.
    """
    s = dashboard.settings
    if not s.aggregate_by_carrier:
        return

    gen = network.generators
    if gen.empty:
        print("  Carrier aggregation: no generators — skipping")
        return
    if "carrier" not in gen.columns or "bus" not in gen.columns:
        print("  Carrier aggregation: 'carrier' or 'bus' column missing — skipping")
        return

    static_rules, default_static = _rule_lookup(dashboard.carrier_rules)
    ts_rules, default_ts = _rule_lookup(dashboard.carrier_rules_t)

    n_before = len(gen)
    attr_cols = [c for c in gen.columns if c not in ("bus", "carrier")]

    groups = gen.groupby(["bus", "carrier"], dropna=False).groups
    to_remove: list[str] = []
    to_add: list[tuple[str, dict[str, object]]] = []
    group_members: dict[str, list[str]] = {}

    for (bus, carrier), members in groups.items():
        members = list(members)
        if pd.isna(carrier) or pd.isna(bus):
            continue
        if len(members) < 2:
            continue                         # nothing to merge

        sub = gen.loc[members]
        # "Lead" unit: largest p_nom (handles rule=='p_nom' and ties).
        p_nom = pd.to_numeric(sub.get("p_nom"), errors="coerce").fillna(0.0)
        lead = p_nom.idxmax() if not p_nom.empty else members[0]

        merged: dict[str, object] = {"bus": str(bus), "carrier": str(carrier)}
        for col in attr_cols:
            rule = static_rules.get(col, default_static)
            try:
                value = _apply_static_rule(sub, col, rule, str(bus), str(carrier), lead)
            except Exception:
                value = sub.at[lead, col]
            if value is None:
                continue                     # rule == "ignore"
            merged[col] = value

        # p_nom is always summed — safety override.
        merged["p_nom"] = float(p_nom.sum())

        merged_name = f"{carrier}_{bus}"
        to_remove.extend(members)
        to_add.append((merged_name, merged))
        group_members[merged_name] = members

    if not to_add:
        print("  Carrier aggregation: no (bus, carrier) group has ≥2 members")
        return

    # 1. Aggregate time series BEFORE we remove the originals.
    new_ts: dict[str, dict[str, pd.Series]] = {}    # attr → {new_name → Series}
    for attr in dir(network.generators_t):
        if attr.startswith("_"):
            continue
        ts_df = getattr(network.generators_t, attr, None)
        if ts_df is None or not hasattr(ts_df, "columns") or ts_df.empty:
            continue
        rule = ts_rules.get(attr, default_ts)
        if rule == "ignore":
            continue
        per_attr: dict[str, pd.Series] = {}
        for new_name, members in group_members.items():
            cols = [m for m in members if m in ts_df.columns]
            if not cols:
                continue
            per_attr[new_name] = _reduce_ts(ts_df[cols], rule)
        if per_attr:
            new_ts[attr] = per_attr

    # 2. Drop the original members.
    network.remove("Generator", to_remove)

    # 3. Add the merged generators.
    pypsa_attrs = set(network.component_attrs["Generator"].index)
    for name, merged in to_add:
        std = {k: v for k, v in merged.items() if k in pypsa_attrs and pd.notna(v)}
        network.add("Generator", name, **std)
        # Custom (non-standard) columns: write directly on the DataFrame.
        for k, v in merged.items():
            if k not in pypsa_attrs and pd.notna(v):
                network.generators.at[name, k] = v

    # 4. Attach the aggregated time series.
    for attr, cols in new_ts.items():
        target: pd.DataFrame = getattr(network.generators_t, attr)
        for new_name, series in cols.items():
            target[new_name] = series

    print(
        f"  Carrier aggregation: {n_before} generators → "
        f"{len(network.generators)} (merged {len(to_remove)} into {len(to_add)} groups)"
    )
