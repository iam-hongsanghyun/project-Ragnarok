"""Whole-network operations on PyPSA 1.4's native APIs (P35, P38, P39).

Pure functions: each takes the workbook model (as ``build_network`` does), and
transforms return a *reduced workbook model* via ``network_to_model`` so the
session can swap it in, exactly like spatial clustering does.

* :func:`temporal_cluster`  - ``n.cluster.temporal.resample / downsample / segment``
* :func:`slice_model`       - ``n.slice_network(buses=, snapshots=)``
* :func:`merge_models`      - ``n.merge(other)``
* :func:`network_analysis`  - PTDF / BODF / cycle matrix / adjacency / incidence / sub-networks
"""
from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np
import pandas as pd
import pypsa
from fastapi import HTTPException

from .network import build_network
from .network.serialize import network_to_model

TEMPORAL_METHODS = ("resample", "downsample", "segment")
ANALYSIS_PARTS = ("subnetworks", "ptdf", "bodf", "cycles", "adjacency", "incidence")
_MAX_MATRIX_BRANCHES = 250


def has_tsam() -> bool:
    """``segment`` (TSAM-like) needs the optional ``tsam`` package."""
    return importlib.util.find_spec("tsam") is not None


def _build(model: dict[str, list[dict[str, Any]]], scenario: dict[str, Any] | None, options: dict[str, Any] | None) -> pypsa.Network:
    """Build the network the way structural transforms do (whole time axis, no annuitisation)."""
    from ..app.routers.transforms import _transform_build_options

    network, _ = build_network(dict(model), dict(scenario or {}), _transform_build_options(options))
    return network


def _to_model(network: pypsa.Network, source: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Serialise back to a workbook and carry the Ragnarok config sheets across."""
    from ..app.routers.transforms import _preserved_config_sheets

    reduced = network_to_model(network)
    for sheet, rows in _preserved_config_sheets(source).items():
        reduced.setdefault(sheet, rows)
    return reduced


def _counts(network: pypsa.Network) -> dict[str, Any]:
    weights = network.snapshot_weightings["objective"]
    return {
        "snapshots": int(len(network.snapshots)),
        "buses": int(len(network.buses)),
        "weightedHours": float(weights.sum()),
    }


def temporal_cluster(
    model: dict[str, list[dict[str, Any]]],
    *,
    method: str,
    scenario: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    offset: str | None = None,
    drop_leap_day: bool = False,
    stride: int | None = None,
    num_segments: int | None = None,
    solver: str = "highs",
    aggregation_rules: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Reduce the time axis with PyPSA's native temporal clustering.

    Snapshot weightings are carried through (a 3-hour resample weights each kept
    snapshot 3.0), which is what makes the reduced model's annual energy and cost
    equal the original's - something hand-rolled striding gets wrong.

    Args:
        method: ``resample`` (``offset`` like ``"3h"``, ``"1D"``), ``downsample``
            (keep every ``stride``-th snapshot, weight x stride) or ``segment``
            (``num_segments`` TSAM-style segments; needs the ``tsam`` package).
        aggregation_rules: per-attribute resample rules (``{"p_max_pu": "mean"}``).

    Returns:
        ``{model, method, before, after}``.

    Raises:
        HTTPException: 400 on bad parameters / missing ``tsam``.
    """
    method = method.lower()
    if method not in TEMPORAL_METHODS:
        raise HTTPException(status_code=400, detail=f"method must be one of {TEMPORAL_METHODS}.")
    network = _build(model, scenario, options)
    before = _counts(network)
    try:
        if method == "resample":
            if not offset:
                raise HTTPException(status_code=400, detail="resample needs offset, e.g. '3h' or '1D'.")
            kwargs: dict[str, Any] = {"drop_leap_day": drop_leap_day}
            if aggregation_rules:
                kwargs["aggregation_rules"] = aggregation_rules
            reduced = network.cluster.temporal.resample(offset, **kwargs)
        elif method == "downsample":
            if not stride or int(stride) < 2:
                raise HTTPException(status_code=400, detail="downsample needs stride >= 2.")
            reduced = network.cluster.temporal.downsample(int(stride))
        else:
            if not num_segments or int(num_segments) < 1:
                raise HTTPException(status_code=400, detail="segment needs num_segments >= 1.")
            if not has_tsam():
                raise HTTPException(
                    status_code=400,
                    detail="segment needs the optional 'tsam' package (pip install tsam); use resample/downsample instead.",
                )
            kwargs = {"solver": solver}
            if aggregation_rules:
                kwargs["aggregation_rules"] = aggregation_rules
            reduced = network.cluster.temporal.segment(int(num_segments), **kwargs)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - surface as 400
        raise HTTPException(status_code=400, detail=f"Temporal clustering failed: {exc}") from exc
    reduced = getattr(reduced, "n", reduced)
    return {
        "model": _to_model(reduced, model),
        "method": method,
        "before": before,
        "after": _counts(reduced),
    }


def slice_model(
    model: dict[str, list[dict[str, Any]]],
    *,
    scenario: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    start: int | str | None = None,
    end: int | str | None = None,
    buses: list[str] | None = None,
) -> dict[str, Any]:
    """Cut a time window and/or a set of buses out of the model (``n.slice_network``).

    ``start`` / ``end`` are snapshot positions (int, end exclusive) or labels
    (inclusive, as pandas label slicing); ``buses`` keeps those buses and every
    component fully attached to them.
    """
    network = _build(model, scenario, options)
    before = _counts(network)
    snaps = network.snapshots
    sns: slice | None = None
    if start is not None or end is not None:
        if isinstance(start, int) or isinstance(end, int) or (start is None and end is None):
            sns = slice(start if isinstance(start, int) else None, end if isinstance(end, int) else None)
        else:
            lo = snaps.get_loc(pd.Timestamp(start)) if start is not None else 0
            hi = snaps.get_loc(pd.Timestamp(end)) + 1 if end is not None else len(snaps)
            sns = slice(lo, hi)
    try:
        sliced = network.slice_network(buses=buses or None, snapshots=sns)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"slice failed: {exc}") from exc
    if not len(sliced.snapshots):
        raise HTTPException(status_code=400, detail="The requested window contains no snapshots.")
    return {"model": _to_model(sliced, model), "before": before, "after": _counts(sliced)}


def merge_models(
    model: dict[str, list[dict[str, Any]]],
    other: dict[str, list[dict[str, Any]]],
    *,
    scenario: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    components_to_skip: list[str] | None = None,
    with_time: bool = True,
) -> dict[str, Any]:
    """Merge ``other`` into ``model`` (``n.merge``): union of components, names must be unique.

    Raises:
        HTTPException: 400 when component names collide or the merge fails.
    """
    base = _build(model, scenario, options)
    extra = _build(other, scenario, options)
    before = _counts(base)
    try:
        merged = base.merge(extra, components_to_skip=components_to_skip, inplace=False, with_time=with_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"merge failed: {exc}") from exc
    return {
        "model": _to_model(merged, model),
        "before": before,
        "after": _counts(merged),
        "merged": _counts(extra),
    }


def _matrix(frame: pd.DataFrame, digits: int = 6) -> dict[str, Any]:
    return {
        "rows": [str(r) for r in frame.index],
        "columns": [str(c) for c in frame.columns],
        "data": np.round(frame.to_numpy(dtype=float), digits).tolist(),
    }


def network_analysis(
    model: dict[str, list[dict[str, Any]]],
    *,
    scenario: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    include: list[str] | None = None,
    cycle_basis_method: str = "bfs-refined",
    max_branches: int = _MAX_MATRIX_BRANCHES,
) -> dict[str, Any]:
    """Grid-analysis outputs of the network topology (no solve).

    ``subnetworks`` lists each synchronous sub-network with its slack bus
    (``determine_network_topology``); ``ptdf`` / ``bodf`` are the per-sub-network
    power-transfer and branch-outage distribution factors
    (``sub_network.calculate_PTDF/BODF``); ``cycles`` the cycle matrix
    (``n.cycle_matrix``); ``adjacency`` / ``incidence`` the bus-bus and bus-branch
    graphs. Matrices larger than ``max_branches`` per side are omitted with a
    reason rather than returned whole.
    """
    parts = [p for p in (include or ANALYSIS_PARTS) if p in ANALYSIS_PARTS] or list(ANALYSIS_PARTS)
    network = _build(model, scenario, options)
    network.determine_network_topology(cycle_basis_method=cycle_basis_method)
    out: dict[str, Any] = {"parts": parts, "cycleBasisMethod": cycle_basis_method}
    subs = list(network.c.sub_networks.static.obj)

    if "subnetworks" in parts or "ptdf" in parts or "bodf" in parts:
        listing: list[dict[str, Any]] = []
        for sub in subs:
            branches = sub.branches_i()
            entry: dict[str, Any] = {
                "name": str(sub.name),
                "carrier": str(network.c.sub_networks.static.at[sub.name, "carrier"]),
                "buses": [str(b) for b in sub.buses_i()],
                "branches": [f"{c}:{n}" for c, n in branches],
                "slackBus": str(getattr(sub, "slack_bus", "")),
                "slackGenerator": str(getattr(sub, "slack_generator", "")),
            }
            for what, calc in (("ptdf", "calculate_PTDF"), ("bodf", "calculate_BODF")):
                if what not in parts:
                    continue
                if len(branches) > max_branches or len(entry["buses"]) > max_branches:
                    entry[what] = {"omitted": f"more than {max_branches} branches/buses; raise maxBranches or analyse a cluster"}
                    continue
                try:
                    getattr(sub, calc)()
                    arr = getattr(sub, what.upper())
                    cols = entry["buses"] if what == "ptdf" else entry["branches"]
                    entry[what] = {
                        "rows": entry["branches"],
                        "columns": cols,
                        "data": np.round(np.asarray(arr, dtype=float), 6).tolist(),
                    }
                except Exception as exc:  # noqa: BLE001 - e.g. a sub-network without branches
                    entry[what] = {"error": str(exc)}
            listing.append(entry)
        out["subNetworks"] = listing
    if "cycles" in parts:
        try:
            cm = network.cycle_matrix(cycle_basis_method=cycle_basis_method)
            out["cycleMatrix"] = _matrix(cm) if max(cm.shape) <= max_branches else {"omitted": f"{cm.shape[0]}x{cm.shape[1]} exceeds maxBranches"}
        except Exception as exc:  # noqa: BLE001
            out["cycleMatrix"] = {"error": str(exc)}
    if "adjacency" in parts:
        adj = network.adjacency_matrix(return_dataframe=True)
        out["adjacency"] = _matrix(adj, 4) if len(adj) <= max_branches else {"omitted": f"{len(adj)} buses exceeds maxBranches"}
    if "incidence" in parts:
        inc = network.incidence_matrix()
        buses = list(network.buses.index)
        out["incidence"] = (
            {"shape": list(inc.shape), "rows": [str(b) for b in buses], "data": inc.toarray().astype(int).tolist()}
            if max(inc.shape) <= max_branches else {"shape": list(inc.shape), "omitted": "exceeds maxBranches"}
        )
    return out
