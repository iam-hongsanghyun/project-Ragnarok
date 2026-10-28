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
