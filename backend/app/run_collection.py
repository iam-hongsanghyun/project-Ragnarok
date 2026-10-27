"""Multi-run comparison through ``pypsa.NetworkCollection`` (P39).

A stored run keeps the model and every output frame but not a live network, so
each requested run is rebuilt with
:func:`backend.pypsa.results.statistics_query.network_from_outputs` and the
rebuilt networks are put in one :class:`pypsa.NetworkCollection`. A single
``collection.statistics.<metric>(groupby=...)`` call then evaluates the metric
for every run with PyPSA's own definitions (one row per ``(network, component,
carrier)``), instead of re-deriving each number per run by hand.

The runs must be compatible for a collection (PyPSA refuses to mix networks with
and without investment periods); when they are not the metrics are evaluated per
network and the response says so (``mode: "per-network"``); the same fallback applies to
a metric the collection cannot evaluate.
"""
from __future__ import annotations

import warnings
from typing import Any

import pandas as pd
import pypsa

from ..pypsa.results.statistics_query import network_from_outputs

#: Metrics offered in the comparison (a subset of ``n.statistics`` that is
#: meaningful side by side), with the unit each reports.
COMPARISON_METRICS: dict[str, str] = {
    "optimal_capacity": "MW",
    "installed_capacity": "MW",
    "supply": "MWh",
    "withdrawal": "MWh",
    "curtailment": "MWh",
    "capex": "currency/yr",
    "opex": "currency",
    "revenue": "currency",
    "capacity_factor": "-",
}
DEFAULT_METRICS: tuple[str, ...] = ("optimal_capacity", "supply", "capex", "opex")
_ROUND = 4


def _register_carriers(network: pypsa.Network) -> None:
    """Give every component a registered carrier (blank -> ``"-"``, PyPSA's own label).

    A collection groups by carrier across networks; a blank or unregistered
    carrier makes PyPSA drop the whole network from the result *silently*
    (observed: only the first run came back), so the rebuilt networks are made
    self-consistent first. The carrier text of unaffected components is unchanged.
    """
    known = set(network.carriers.index)
    for comp in network.components:
        static = comp.static
        if "carrier" not in static.columns or not len(static):
            continue
        static["carrier"] = static["carrier"].replace("", "-").fillna("-")
        for carrier in set(static["carrier"].astype(str)) - known:
            network.add("Carrier", carrier)
            known.add(carrier)


def _rebuild(bundle: dict[str, Any]) -> pypsa.Network:
    result = bundle.get("result") or {}
    network = network_from_outputs(
        bundle.get("model") or {}, bundle.get("scenario") or {}, bundle.get("options") or {},
        result.get("outputs") or {},
    )
    _register_carriers(network)
    return network


def _series_rows(series: pd.Series | pd.DataFrame, run_of_level: str) -> dict[str, list[dict[str, Any]]]:
    """Split a collection statistic into ``{run: [{component, carrier, value}]}``."""
    if isinstance(series, pd.DataFrame):  # multi-period: one column per period -> total
        series = series.sum(axis=1)
    out: dict[str, list[dict[str, Any]]] = {}
    for key, value in series.items():
        if pd.isna(value) or not isinstance(key, tuple):
            continue
        levels = dict(zip(series.index.names, key, strict=False))
        run = str(levels.pop(run_of_level))
        out.setdefault(run, []).append(
            {"component": str(levels.get("component", "")), "carrier": str(levels.get("carrier", "")),
             "value": round(float(value), _ROUND)}
        )
    return out


def collection_statistics(
    bundles: dict[str, dict[str, Any]],
    metrics: list[str] | None = None,
    groupby: str = "carrier",
) -> dict[str, Any]:
    """Native ``n.statistics`` metrics for several stored runs at once.

    Args:
        bundles: ``{run name: stored run bundle}`` (``run_store.get_run`` output).
        metrics: subset of :data:`COMPARISON_METRICS` (default :data:`DEFAULT_METRICS`).
        groupby: PyPSA grouper (``carrier``, ``bus_carrier``, ``bus`` ...).

    Returns:
        ``{"mode": "collection"|"per-network", "metrics": [...], "groupby": ...,
        "units": {metric: unit}, "runs": {run: {metric: [{component, carrier, value}]}}}``.

    Raises:
        ValueError: an unknown metric.
    """
    chosen = list(metrics or DEFAULT_METRICS)
    unknown = [m for m in chosen if m not in COMPARISON_METRICS]
    if unknown:
        raise ValueError(f"Unknown statistics metric(s) {unknown}. Options: {list(COMPARISON_METRICS)}.")
    networks = {name: _rebuild(b) for name, b in bundles.items()}
    per_run: dict[str, dict[str, list[dict[str, Any]]]] = {name: {} for name in networks}
    mode = "collection"
    try:
        collection = pypsa.NetworkCollection(networks)
    except ValueError:
        collection, mode = None, "per-network"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # upstream Pandas4Warning noise in grouping.py
        for metric in chosen:
            if collection is not None:
                try:
                    result = getattr(collection.statistics, metric)(groupby=groupby, drop_zero=False, round=_ROUND)
                except Exception:  # noqa: BLE001 - upstream raises on an all-empty metric; evaluate per network
                    result = None
                if result is not None:
                    for run, rows in _series_rows(result, collection.index.name or "network").items():
                        per_run[run][metric] = rows
                    for run in per_run:
                        per_run[run].setdefault(metric, [])
                    continue
                mode = "per-network"
            for name, net in networks.items():
                try:
                    single = getattr(net.statistics, metric)(groupby=groupby, drop_zero=False, round=_ROUND)
                except Exception:  # noqa: BLE001 - metric not defined for this run (e.g. no priced flows)
                    per_run[name][metric] = []
                    continue
                if isinstance(single, pd.DataFrame):
                    single = single.sum(axis=1)
                per_run[name][metric] = [
                    {"component": str(k[0]) if isinstance(k, tuple) else "", "carrier": str(k[-1]),
                     "value": round(float(v), _ROUND)}
                    for k, v in single.items() if not pd.isna(v)
                ]
    return {
        "mode": mode,
        "metrics": chosen,
        "groupby": groupby,
        "units": {m: COMPARISON_METRICS[m] for m in chosen},
        "runs": per_run,
    }
