"""Parametrised ``n.statistics`` queries over a stored run (P31).

The solve payload carries one fixed ``n.statistics()`` table
(:mod:`.statistics`). This module answers the questions that table cannot: *which*
metric, grouped *how*, for *which* bus carrier, time-aggregated or not, at ports
or not - exactly the parameters of PyPSA's own
``n.statistics.<metric>(groupby=, bus_carrier=, aggregate_time=, at_port=, ...)``.

A stored run keeps the model and every output frame but not a live network, so
:func:`network_from_outputs` rebuilds the network from the model + run options and
injects *all* stored output frames (not just the handful the analytics need), after
which any statistic evaluates exactly as on the solved network.
"""
from __future__ import annotations

import re
import warnings
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from ..network import build_stored_network
from .from_outputs import _series_to_frame

#: Statistics metrics exposed (all are methods of ``n.statistics``).
STATISTIC_METRICS: tuple[str, ...] = (
    "energy_balance", "supply", "withdrawal", "curtailment", "capacity_factor",
    "optimal_capacity", "installed_capacity", "expanded_capacity",
    "capex", "opex", "installed_capex", "expanded_capex", "overnight_cost", "fom",
    "system_cost", "revenue", "market_value", "prices", "transmission",
)
_MAX_TIME_COLUMNS = 400


def network_from_outputs(
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any],
    outputs: dict[str, Any],
) -> pypsa.Network:
    """Rebuild the run's network and inject every stored output frame.

    Args:
        model, scenario, options: the run's inputs (as stored with the run).
        outputs: ``{"static": {list: {name: {attr: value}}}, "series": {"list-attr": rows}}``
            (the payload's ``outputs`` / ``get_run(...)["result"]["outputs"]``).

    Returns:
        A network whose ``*_t`` frames and ``*_opt`` columns equal the solved ones.
    """
    network, _ = build_stored_network(model, dict(scenario or {}), options or {})
    snaps = network.snapshots
    for list_name, by_name in ((outputs or {}).get("static") or {}).items():
        if list_name not in network.components.keys():
            continue
        frame = network.components[list_name].static
        for name, attrs in by_name.items():
            if name not in frame.index or not isinstance(attrs, dict):
                continue
            for attr, value in attrs.items():
                if attr in frame.columns:
                    try:
                        frame.loc[name, attr] = value
                    except (TypeError, ValueError):
                        continue
    for sheet, rows in ((outputs or {}).get("series") or {}).items():
        list_name, _, attr = sheet.partition("-")
        if not attr or list_name not in network.components.keys() or not rows:
            continue
        comp = network.components[list_name]
        if not len(comp.static):
            continue
        comp.dynamic[attr] = _series_to_frame(rows, snaps, list(comp.static.index))
    from .derive_outputs import mark_solved

    mark_solved(network)
    return network


def _clean(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if (f != f or f in (float("inf"), float("-inf"))) else round(f, 4)


def _downsample_columns(frame: pd.DataFrame, limit: int) -> pd.DataFrame:
    if frame.shape[1] <= limit:
        return frame
    stride = int(np.ceil(frame.shape[1] / limit))
    groups = np.arange(frame.shape[1]) // stride
    out = frame.T.groupby(groups).mean().T
    out.columns = [frame.columns[min(i * stride, frame.shape[1] - 1)] for i in range(out.shape[1])]
    return out


def run_statistic(
    network: pypsa.Network,
    metric: str,
    *,
    groupby: list[str] | str | None = None,
    bus_carrier: list[str] | str | None = None,
    aggregate_time: str | bool = "sum",
    at_port: bool = False,
    nice_names: bool = False,
    drop_zero: bool = True,
    components: list[str] | None = None,
    carrier: list[str] | str | None = None,
    round_digits: int | None = None,
) -> dict[str, Any]:
    """Evaluate one ``n.statistics`` metric with PyPSA's own parameters.

    Args:
        network: solved (or output-injected) network.
        metric: one of :data:`STATISTIC_METRICS`.
        groupby: grouper name(s) - ``carrier``, ``bus_carrier``, ``bus``, ``name``,
            ``location``, ``country``, ``unit`` ... (``None`` = PyPSA default
            ``["component", "carrier"]``).
        bus_carrier: restrict to buses of these carriers.
        aggregate_time: ``"sum"`` | ``"mean"`` or ``False`` (a time series; downsampled
            to at most 400 columns).
        at_port: evaluate multi-port components per port.
        nice_names: use carrier ``nice_name`` labels.
        drop_zero: drop all-zero rows.
        components: restrict to these component names (``["Generator", "Link"]``).
        carrier: restrict to these carriers.
        round_digits: PyPSA ``round`` argument.

    Returns:
        ``{metric, groupby, aggregateTime, levels, columns, rows: [{key, values}]}``
        where ``key`` maps each index level to its label and ``values`` maps column
        (metric name, period, or snapshot) to a number.

    Raises:
        ValueError: unknown metric or grouper.
    """
    if metric not in STATISTIC_METRICS:
        raise ValueError(f"Unknown statistic {metric!r}. Choose from: {', '.join(STATISTIC_METRICS)}.")
    fn = getattr(network.statistics, metric)
    kwargs: dict[str, Any] = {"nice_names": nice_names, "drop_zero": drop_zero}
    if groupby:
        kwargs["groupby"] = groupby if isinstance(groupby, str) else list(groupby)
    if bus_carrier:
        kwargs["bus_carrier"] = bus_carrier
    if components:
        kwargs["components"] = components
    if carrier:
        kwargs["carrier"] = carrier
    if round_digits is not None:
        kwargs["round"] = round_digits
    agg: str | bool = aggregate_time
    kwargs["aggregate_time"] = agg
    if at_port:
        kwargs["at_port"] = "all"  # PyPSA >= 1.1: ``True`` is deprecated
    dropped: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # P33: upstream Pandas4Warning noise in grouping.py
        # Metrics differ in which keyword arguments they accept (``prices`` has no
        # ``nice_names``, ``capex`` no ``aggregate_time`` ...): drop the ones a
        # metric rejects, one at a time, rather than hard-coding a table that
        # drifts with PyPSA.
        while True:
            try:
                result = fn(**kwargs)
                break
            except TypeError as exc:
                found = re.search(r"unexpected keyword argument '(\w+)'", str(exc))
                bad = found.group(1) if found else None
                if bad == "groupby_time":  # PyPSA's internal name for ``aggregate_time``
                    bad = "aggregate_time"
                if bad is None or bad not in kwargs:
                    raise
                dropped.append(bad)
                kwargs.pop(bad)
    if isinstance(result, pd.Series):
        frame = result.to_frame(metric)
    else:
        frame = result.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [" | ".join(str(p) for p in c if str(p) != "") for c in frame.columns]
    if agg is False or agg is None:
        frame = _downsample_columns(frame, _MAX_TIME_COLUMNS)
    levels = [str(x) for x in frame.index.names] if isinstance(frame.index, pd.MultiIndex) else [str(frame.index.name or "name")]
    rows = []
    for idx, row in frame.iterrows():
        parts = idx if isinstance(idx, tuple) else (idx,)
        rows.append({
            "key": {levels[i]: str(p) for i, p in enumerate(parts)},
            "values": {str(c): _clean(v) for c, v in row.items()},
        })
    return {
        "metric": metric,
        "groupby": groupby,
        "busCarrier": bus_carrier,
        "aggregateTime": agg if isinstance(agg, str) else bool(agg),
        "atPort": bool(at_port),
        "ignoredParameters": dropped,
        "levels": levels,
        "columns": [str(c) for c in frame.columns],
        "rows": rows,
    }
