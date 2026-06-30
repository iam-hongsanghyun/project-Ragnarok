"""Network clustering transform (modularity / k-means) — model reduction.

Reduces a workbook model to fewer buses and checks the reduced model is smaller,
carries a busmap, and rebuilds into a valid network. k-means must degrade
cleanly (scikit-learn is optional and not installed here).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from backend.app.routers.transforms import cluster_model
from backend.pypsa.network import build_network

SCENARIO = {"discountRate": 0.0}


def _path_model(n_buses: int = 4) -> dict[str, list[dict[str, Any]]]:
    """A linear chain of buses (A-B-C-…) with a generator at one end and a load
    at the other; each bus on a distinct x coordinate."""
    buses = [chr(ord("A") + i) for i in range(n_buses)]
    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    return {
        "buses": [
            {"name": b, "v_nom": 380.0, "x": float(i), "y": 0.0}
            for i, b in enumerate(buses)
        ],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "lines": [
            {
                "name": f"{buses[i]}{buses[i + 1]}",
                "bus0": buses[i],
                "bus1": buses[i + 1],
                "x": 0.1,
                "r": 0.01,
                "s_nom": 500.0,
            }
            for i in range(n_buses - 1)
        ],
        "generators": [
            {
                "name": "G",
                "bus": buses[0],
                "carrier": "gas",
                "p_nom": 900.0,
                "marginal_cost": 10.0,
            }
        ],
        "loads": [{"name": "L", "bus": buses[-1], "p_set": 300.0}],
        "loads-p_set": [{"snapshot": s, "L": 300.0} for s in snaps],
    }


def test_modularity_clustering_reduces_buses() -> None:
    res = cluster_model(
        _path_model(4), n_clusters=2, method="modularity", scenario=SCENARIO
    )
    assert res["before"]["buses"] == 4
    assert res["after"]["buses"] == 2
    assert len(res["model"]["buses"]) == 2
    # busmap covers every original bus and lands on exactly 2 clusters
    assert len(res["busmap"]) == 4
    assert len(set(res["busmap"].values())) == 2
    # generation + load survive the aggregation
    assert res["model"].get("generators")
    assert res["model"].get("loads")
    # the reduced model rebuilds into a valid 2-bus network
    net, _ = build_network(res["model"], SCENARIO, {})
    assert len(net.buses) == 2


def test_clustering_rejects_bad_target() -> None:
    with pytest.raises(HTTPException):
        cluster_model(_path_model(4), n_clusters=4, scenario=SCENARIO)  # == bus count
    with pytest.raises(HTTPException):
        cluster_model(_path_model(4), n_clusters=0, scenario=SCENARIO)


def test_kmeans_degrades_cleanly_without_sklearn() -> None:
    # scikit-learn isn't installed → k-means must surface a 400, never a 500.
    with pytest.raises(HTTPException):
        cluster_model(_path_model(4), n_clusters=2, method="kmeans", scenario=SCENARIO)
