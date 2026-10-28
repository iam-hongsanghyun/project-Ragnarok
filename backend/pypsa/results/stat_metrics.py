"""Per-asset ``n.statistics`` readers shared by the result builders (P28).

PyPSA's statistics are the single definition of revenue, supply/withdrawal,
capacity factor, market value and the CAPEX family. This module reads them per
asset (``groupby=False``), keeps the per-investment-period columns a multi-period
solve produces, and combines the periods in one place so every consumer applies
the same rule:

* PyPSA masks inactive assets itself in the period-resolved statistics (an asset
  outside its build/lifetime window is NaN in that period), so no extra mask is
  needed here; NaN is read as 0.
* Money statistics (``revenue``) are per period *without* the investment-period
  ``objective`` weighting; ``capex`` already carries it. :func:`combine_periods`
  applies the weighting where a money total over the horizon is wanted.
* Energy statistics (``supply``/``withdrawal``) are physical: summed over periods,
  never weighted.
"""
from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence

import pandas as pd
import pypsa

_ROUND = 12


def name_dynamic_axes(network: pypsa.Network) -> None:
    """Give every per-component time-series frame PyPSA's axis names (``name`` columns).

    PyPSA's own solve names the column axis ``name``, and ``n.statistics.revenue``
    relies on it (``static["bus"][df.columns]`` then ``.droplevel("name")``). A
    frame written by hand or from stored outputs has an *unnamed* column axis.
    pandas 3.1 keeps the Series' own index name when selecting with an unnamed
    ``Index``; pandas 3.0.5 takes the key's (``None``), so ``droplevel("name")``
    raises ``KeyError`` — which PyPSA swallows into an empty result
    (``pass_empty_series_if_keyerror``), so revenue silently reads as nothing.
    Naming the axis makes both versions identical. Idempotent; renames labels only.

    Args:
        network: network whose ``*_t`` frames may carry unnamed axes.
    """
    for component in network.components.values():
        for frame in component.dynamic.values():
            if isinstance(frame, pd.DataFrame) and frame.columns.name is None:
                frame.columns.name = "name"


def asset_statistic(
    network: pypsa.Network,
    name: str,
    components: Sequence[str],
    **kwargs: object,
) -> pd.DataFrame:
    """``n.statistics.<name>`` per asset: index ``(component, name)``, columns = periods.

    A single-period run has one column labelled ``0``. Returns an empty frame when
    the statistic is unavailable (no solution, empty component set) so a reporting
    helper never sinks a run.

    Args:
        network: solved (or output-injected) network.
        name: statistics method, e.g. ``"revenue"``.
        components: component class names (``"Generator"``, ``"StorageUnit"``, ...).
        **kwargs: forwarded to the statistic (``at_port``, ``direction`` ...).
    """
    method = getattr(network.statistics, name)
    name_dynamic_axes(network)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = method(components=list(components), groupby=False, drop_zero=False, round=_ROUND, **kwargs)
    except Exception:  # noqa: BLE001 — a reporting extra must not sink the run
        return pd.DataFrame()
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    if isinstance(raw, pd.Series):
        raw = raw.to_frame(0)
    return raw


def combine_periods(
    frame: pd.DataFrame,
    weights: Mapping[int, float] | None = None,
) -> pd.Series:
    """Collapse the period columns of :func:`asset_statistic` to one value per asset.

    Args:
        frame: result of :func:`asset_statistic`.
        weights: investment-period -> weight (``None`` = plain sum). NaN (asset
            inactive that period) counts as 0.

    Returns:
        Series indexed ``(component, name)``; empty when ``frame`` is empty.
    """
    if frame.empty:
        return pd.Series(dtype=float)
    filled = frame.fillna(0.0)
    if weights is None or (len(filled.columns) == 1 and filled.columns[0] == 0):
        return filled.sum(axis=1)
    w = pd.Series({c: float(weights.get(int(c), 1.0)) for c in filled.columns})
    return filled.mul(w, axis=1).sum(axis=1)


def asset_value(series: pd.Series, component: str, name: str, default: float = 0.0) -> float:
    """One asset's value from a ``(component, name)`` Series, ``default`` when absent."""
    try:
        return float(series.loc[(component, name)])
    except KeyError:
        return default


def period_hours_mean(
    frame: pd.DataFrame,
    hours: Mapping[int, float],
) -> tuple[pd.Series, pd.Series]:
    """Hours-weighted mean of an intensive statistic over the periods an asset is active.

    For a per-unit statistic such as ``capacity_factor`` (mean |p| / capacity in each
    period; NaN while the asset is inactive) the horizon value is
    $\\sum_p h_p\\,x_p / \\sum_p h_p\\,a_p$ with $a_p = 1$ when the asset exists in
    period $p$. Returned as ``(numerator, denominator)`` so a group (carrier) can be
    formed as $\\sum_i P_i\\,num_i / \\sum_i P_i\\,den_i$ — PyPSA's capacity-weighted
    group value.

    Args:
        frame: result of :func:`asset_statistic`.
        hours: period -> modelled hours (``{0: H}`` for a single-period run).
    """
    if frame.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    h = pd.Series({c: float(hours.get(int(c), 0.0)) for c in frame.columns})
    num = frame.fillna(0.0).mul(h, axis=1).sum(axis=1)
    den = frame.notna().mul(h, axis=1).sum(axis=1)
    return num, den


# ── fixed cost (CAPEX + fom) as PyPSA charges it ──────────────────────────────

#: PyPSA component class <-> its components list name.
COMPONENT_LISTS = {
    "Generator": "generators", "StorageUnit": "storage_units", "Store": "stores",
    "Link": "links", "Process": "processes", "Line": "lines", "Transformer": "transformers",
}

_FIXED_COLUMNS = ["capex_horizon", "fom_horizon", "capex_sunk", "capex_expanded", "annual"]


def nyears_by_period(network: pypsa.Network) -> dict[int, float]:
    """PyPSA's ``n.nyears`` per investment period (``{0: nyears}`` for a single-period run)."""
    ny = network.nyears
    if hasattr(ny, "items"):
        return {int(k): float(v) for k, v in ny.items()}
    return {0: float(ny)}


def fixed_cost_table(
    network: pypsa.Network,
    components: Sequence[str] = tuple(COMPONENT_LISTS),
) -> pd.DataFrame:
    """Per-asset fixed cost read from ``n.statistics`` - nothing is converted here.

    Index ``(component, name)``; columns, all currency:

    * ``capex_horizon`` / ``fom_horizon`` - ``n.statistics.capex`` / ``.fom`` over the modelled
      horizon, as the objective charges them (a pathway run: summed over periods with the
      investment-period ``objective`` weight PyPSA applies);
    * ``capex_sunk`` / ``capex_expanded`` - the ``installed_capex`` / ``expanded_capex`` parts of
      ``capex_horizon`` (already-built ``p_nom`` vs. new build);
    * ``annual`` - ``(capex + fom) / n.nyears`` PER YEAR, the one conversion made here, for display
      (a pathway run: one active period, weight divided out).

    Empty when the statistics are unavailable (an unsolved network).

    Args:
        network: solved (or output-injected) network.
        components: component class names to read.
    """
    comps = list(components)
    frames = {k: asset_statistic(network, k, comps) for k in ("capex", "fom", "installed_capex", "expanded_capex")}
    if frames["capex"].empty and frames["fom"].empty:
        return pd.DataFrame(columns=_FIXED_COLUMNS)
    from .pathway_periods import is_pathway, period_objective_weights

    pathway = is_pathway(network)
    weights = period_objective_weights(network) if pathway else {}
    ny = nyears_by_period(network)
    index = frames["capex"].index.union(frames["fom"].index)
    out = pd.DataFrame(0.0, index=index, columns=_FIXED_COLUMNS)
    for key, col in (("capex", "capex_horizon"), ("fom", "fom_horizon"),
                     ("installed_capex", "capex_sunk"), ("expanded_capex", "capex_expanded")):
        total = combine_periods(frames[key])
        common = total.index.intersection(index)
        out.loc[common, col] = total.loc[common]
    for key in ("capex", "fom"):
        for idx, row in frames[key].iterrows():
            vals = row.dropna()
            if vals.empty:
                continue
            col = int(vals.index[0])
            value = float(vals.iloc[0])
            if pathway:
                value = value / (weights.get(col, 1.0) or 1.0)
            out.at[idx, "annual"] += value / (ny.get(col, 1.0) or 1.0)
    return out


def fixed_cost_of(table: pd.DataFrame, component: str, name: str) -> dict[str, float]:
    """One asset's row of :func:`fixed_cost_table` (all zero when absent)."""
    if table.empty or (component, name) not in table.index:
        return dict.fromkeys(_FIXED_COLUMNS, 0.0)
    return {k: float(v) for k, v in table.loc[(component, name)].items()}


def overnight_capex_table(
    network: pypsa.Network,
    components: Sequence[str] = tuple(COMPONENT_LISTS),
) -> pd.Series:
    """``n.statistics.overnight_cost`` per asset (currency, not periodised), index ``(component, name)``.

    PyPSA returns ``overnight_cost x capacity`` where the row has an ``overnight_cost`` and
    back-calculates it from ``capital_cost`` where it can (needs ``discount_rate`` and ``lifetime``).
    Empty when PyPSA cannot resolve it for the network.
    """
    frame = asset_statistic(network, "overnight_cost", list(components))
    if frame.empty:
        return pd.Series(dtype=float)
    return frame.bfill(axis=1).iloc[:, 0].astype(float)
