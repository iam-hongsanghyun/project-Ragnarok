"""Merge Gas Turbine (GT) and Steam Turbine (ST) components of Combined Cycle
(CC) plants into a single CC generator.

Each CC group is defined by a shared ``cc_group`` column value in the
generator sheet.  Merge rules (which attributes are summed, weighted-averaged,
or taken from the GT component) are read from the ``CC_group`` sheet in
``dashboard.xlsx``.

Typical rule table in the ``CC_group`` dashboard sheet
(columns: ``attribute``, ``rule``):

    attribute        | rule
    -----------------+--------------
    p_nom            | sum
    marginal_cost    | weighted_avg
    capital_cost     | weighted_avg
    build_year       | min
    close_year       | max
    others           | GT

Available rules
---------------
sum          Sum the numeric values across all members.
weighted_avg Weighted average using each member's ``p_nom`` as the weight.
GT           Take the value from the GT component (or the member with the
             largest ``p_nom`` when no GT can be identified).
min          Take the minimum numeric value.
max          Take the maximum numeric value.
mean         Un-weighted arithmetic mean.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import pypsa

if TYPE_CHECKING:
    from lib.settings import Dashboard


# ---------------------------------------------------------------------------
# Reading merge rules from dashboard
# ---------------------------------------------------------------------------

def read_cc_rules(dashboard_path: str | Path) -> pd.DataFrame | None:
    """Read CC merge rules from the ``CC_group`` sheet in *dashboard_path*.

    Args:
        dashboard_path: Path to ``dashboard.xlsx`` (or equivalent workbook).

    Returns:
        DataFrame with columns ``attribute`` and ``rule``, or ``None`` if the
        ``CC_group`` sheet is absent (CC merging is then disabled).
    """
    dashboard_path = Path(dashboard_path)
    for engine in ("calamine", "openpyxl"):
        try:
            xl = pd.ExcelFile(dashboard_path, engine=engine)
            break
        except ImportError:
            continue
    else:
        raise ImportError("Install python-calamine or openpyxl to read dashboard.xlsx")

    if "CC_group" not in xl.sheet_names:
        return None

    df = xl.parse("CC_group")
    if df.empty:
        return None

    df.columns = df.columns.str.strip()
    if "attribute" not in df.columns or "rule" not in df.columns:
        raise ValueError(
            "CC_group sheet must have 'attribute' and 'rule' columns. "
            f"Found: {list(df.columns)}"
        )

    return df[["attribute", "rule"]].dropna(subset=["attribute", "rule"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_gt(group: pd.DataFrame) -> str:
    """Return the index label (generator name) of the GT in *group*.

    Prefers the row whose ``type`` column is ``"GT"`` (case-insensitive).
    Falls back to the member with the largest ``p_nom``.

    Args:
        group: Slice of ``network.generators`` for one cc_group.

    Returns:
        Generator name (index label) of the identified GT component.
    """
    if "type" in group.columns:
        gt_mask = group["type"].astype(str).str.strip().str.upper() == "GT"
        if gt_mask.any():
            return group.index[gt_mask][0]
    return str(group["p_nom"].idxmax())


def _apply_rule(
    group: pd.DataFrame,
    col: str,
    rule: str,
    gt_name: str,
) -> object:
    """Apply one merge *rule* to column *col* of *group*.

    Args:
        group:   Slice of generators DataFrame for one cc_group.
        col:     Column name to merge.
        rule:    One of ``sum``, ``weighted_avg``, ``GT``, ``min``, ``max``,
                 ``mean``.
        gt_name: Index label of the GT (or reference) generator.

    Returns:
        Scalar merged value.
    """
    rule = str(rule).strip().lower()

    if rule == "sum":
        return pd.to_numeric(group[col], errors="coerce").fillna(0).sum()

    if rule == "weighted_avg":
        vals = pd.to_numeric(group[col], errors="coerce")
        weights = pd.to_numeric(group["p_nom"], errors="coerce").fillna(0)
        total_w = weights.sum()
        if total_w == 0 or vals.isna().all():
            return group.at[gt_name, col]
        return float((vals.fillna(0) * weights).sum() / total_w)

    if rule in ("gt",):
        return group.at[gt_name, col]

    if rule == "min":
        v = pd.to_numeric(group[col], errors="coerce")
        return v.min() if not v.isna().all() else group.at[gt_name, col]

    if rule == "max":
        v = pd.to_numeric(group[col], errors="coerce")
        return v.max() if not v.isna().all() else group.at[gt_name, col]

    if rule == "mean":
        v = pd.to_numeric(group[col], errors="coerce")
        return v.mean() if not v.isna().all() else group.at[gt_name, col]

    # Literal numeric value typed in the GUI (e.g. "10000"): use as-is.
    try:
        return float(rule)
    except (TypeError, ValueError):
        pass

    # Unknown rule — follow GT
    return group.at[gt_name, col]


def _merge_timeseries(
    network: pypsa.Network,
    group_members: dict[str, list[str]],
    gen_snapshot: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Compute merged time-series for each CC group.

    For ``p_max_pu``: weighted average by static ``p_nom`` of the member generators.
    For all other time-series attributes: take values from the GT component.

    Args:
        network:       PyPSA Network object.
        group_members: Mapping ``{merged_name: [original_gen_names...]}``.
        gen_snapshot:  Snapshot of ``network.generators`` (before removal) with
                       ``p_nom`` column available.

    Returns:
        Mapping ``{ts_attr: wide DataFrame}`` with merged values for the new
        CC generators, ready to assign back to ``network.generators_t``.
    """
    result: dict[str, pd.DataFrame] = {}
    gen_t = network.generators_t

    for attr, ts_df in gen_t.items():
        if ts_df.empty:
            continue

        merged_cols: dict[str, pd.Series] = {}
        for merged_name, members in group_members.items():
            present = [m for m in members if m in ts_df.columns]
            if not present:
                continue

            if attr == "p_max_pu":
                # Weighted average by p_nom
                weights = gen_snapshot.loc[present, "p_nom"].astype(float)
                total_w = weights.sum()
                if total_w == 0:
                    merged_cols[merged_name] = ts_df[present[0]]
                else:
                    merged_cols[merged_name] = (
                        ts_df[present].multiply(weights, axis=1).sum(axis=1) / total_w
                    )
            else:
                # Follow GT: take the first present member's series
                merged_cols[merged_name] = ts_df[present[0]]

        if merged_cols:
            result[attr] = pd.DataFrame(merged_cols, index=ts_df.index)

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def merge_cc_generators(
    network: pypsa.Network,
    dashboard: "Dashboard",
) -> None:
    """Merge GT + ST components of each ``cc_group`` into one CC generator.

    Gating (handled inside this function so the runner stays branch-free):

    * ``settings.cc_rule = False``    → print "disabled" and return.
    * ``dashboard.cc_rules is None``   → print "no CC_group sheet" and return.

    Otherwise modifies *network* **in place**:

    1. Groups ``network.generators`` by the ``cc_group`` column.
    2. For each group with two or more members, applies the per-attribute
       merge rules from ``dashboard.cc_rules``.
    3. Removes the original member generators (including their time-series rows).
    4. Adds one merged generator per group, named after the ``cc_group`` value.

    ``p_nom`` is always summed (overrides any rule for safety).
    The merged generator's ``carrier`` follows the GT component.

    Args:
        network:   PyPSA Network to modify in place.
        dashboard: Parsed :class:`~lib.settings.Dashboard`; reads
                   ``dashboard.settings.cc_rule`` and ``dashboard.cc_rules``.
    """
    if not dashboard.settings.cc_rule:
        print("  CC merge: disabled via cc_rule = False in dashboard")
        return
    if dashboard.cc_rules is None:
        print("  CC merge: no CC_group sheet in dashboard — skipping")
        return

    cc_rules = dashboard.cc_rules
    gen = network.generators

    if "cc_group" not in gen.columns:
        print("  CC merge: 'cc_group' column absent from generators — skipping")
        return

    # Normalise: blank strings / whitespace → NaN
    cc_col: pd.Series = (
        gen["cc_group"]
        .astype(str)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    )
    has_group = cc_col.notna()

    if not has_group.any():
        print("  CC merge: no generators have a cc_group value — skipping")
        return

    # Build rules lookup: attribute → rule string
    rules: dict[str, str] = dict(
        zip(
            cc_rules["attribute"].astype(str).str.strip(),
            cc_rules["rule"].astype(str).str.strip(),
        )
    )
    default_rule: str = rules.get("others", "GT")

    # Columns available (the index is the generator name, not a column)
    attr_cols = [c for c in gen.columns if c != "cc_group"]

    all_to_remove: list[str] = []
    to_add: list[tuple[str, dict]] = []       # (merged_name, attrs_dict)
    group_members: dict[str, list[str]] = {}  # for time-series merging

    for grp_val, grp_idx in gen[has_group].groupby(cc_col[has_group]).groups.items():
        grp_idx = list(grp_idx)
        if len(grp_idx) < 2:
            continue  # single-member group — nothing to merge

        group = gen.loc[grp_idx]
        gt_name = _find_gt(group)

        merged_attrs: dict = {}
        for col in attr_cols:
            rule = rules.get(col, default_rule)
            try:
                merged_attrs[col] = _apply_rule(group, col, rule, gt_name)
            except Exception:
                merged_attrs[col] = group.at[gt_name, col]

        # p_nom is always the sum (safety override)
        merged_attrs["p_nom"] = float(
            pd.to_numeric(group["p_nom"], errors="coerce").fillna(0).sum()
        )

        merged_name = str(grp_val)
        all_to_remove.extend(grp_idx)
        to_add.append((merged_name, merged_attrs))
        group_members[merged_name] = grp_idx

        print(
            f"  CC merge: '{merged_name}'  {len(grp_idx)} components → 1"
            f"  [Σp_nom {group['p_nom'].sum():.1f} MW,"
            f"  GT: {gt_name},"
            f"  marginal_cost {merged_attrs.get('marginal_cost', 'n/a')}]"
        )

    if not to_add:
        print("  CC merge: no cc_group has 2+ members — skipping")
        return

    # Merge time-series before removing originals
    merged_ts = _merge_timeseries(network, group_members, gen)

    # Remove original generators (and their time-series rows automatically)
    network.remove("Generator", all_to_remove)

    # Add merged CC generators
    for merged_name, attrs in to_add:
        network.add("Generator", merged_name, **attrs)

    # Re-attach merged time-series
    for attr, merged_df in merged_ts.items():
        existing: pd.DataFrame = getattr(network.generators_t, attr)
        if existing.empty:
            setattr(network.generators_t, attr, merged_df)
        else:
            combined = existing.copy()
            for col in merged_df.columns:
                combined[col] = merged_df[col]
            setattr(network.generators_t, attr, combined)

    print(
        f"  CC merge: {len(all_to_remove)} generator components"
        f" → {len(to_add)} CC units"
    )
