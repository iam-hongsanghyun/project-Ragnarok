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


def test_kmeans_clustering_reduces_buses() -> None:
    # scikit-learn is a dependency, so spatial k-means runs (buses have distinct x).
    res = cluster_model(_path_model(4), n_clusters=2, method="kmeans", scenario=SCENARIO)
    assert res["method"] == "kmeans"
    assert res["before"]["buses"] == 4
    assert res["after"]["buses"] == 2
    assert len(set(res["busmap"].values())) == 2


def _mixed_attr_model() -> dict[str, list[dict[str, Any]]]:
    """Path model where buses disagree on carrier + unit so a k-means cluster
    ({A,B} and {C,D} by x) mixes them: A/C=AC, B/D=DC; units kV vs a 'kv' typo."""
    m = _path_model(4)
    m["carriers"] = [{"name": "gas"}, {"name": "AC"}, {"name": "DC"}]
    carrier = {"A": "AC", "B": "DC", "C": "AC", "D": "DC"}
    unit = {"A": "kV", "B": "kv", "C": "kV", "D": "kV"}
    for row in m["buses"]:
        row["carrier"] = carrier[row["name"]]
        row["unit"] = unit[row["name"]]
    return m


def test_clustering_resolves_attribute_conflicts_by_default() -> None:
    # Default resolve_conflicts=True → merge AC+DC (and kV/kv) by most-common value.
    res = cluster_model(_mixed_attr_model(), n_clusters=2, method="kmeans", scenario=SCENARIO)
    assert res["after"]["buses"] == 2
    assert set(res["resolvedConflicts"]) >= {"carrier", "unit"}
    # the merged model still rebuilds into a valid network
    net, _ = build_network(res["model"], SCENARIO, {})
    assert len(net.buses) == 2


def test_clustering_strict_mode_reports_conflicting_attributes() -> None:
    with pytest.raises(HTTPException) as ei:
        cluster_model(
            _mixed_attr_model(), n_clusters=2, method="kmeans",
            resolve_conflicts=False, scenario=SCENARIO,
        )
    detail = str(ei.value.detail).lower()
    assert "carrier" in detail or "unit" in detail
    assert "merge conflicting attributes" in detail


def _vmag_model() -> dict[str, list[dict[str, Any]]]:
    """Two buses with differing v_mag_pu_set (a numeric attr PyPSA has no default
    aggregation for) that cluster into one."""
    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    return {
        "buses": [
            {"name": "A", "v_nom": 380.0, "x": 0.0, "y": 0.0, "v_mag_pu_set": 1.0},
            {"name": "B", "v_nom": 380.0, "x": 1.0, "y": 0.0, "v_mag_pu_set": 1.2},
        ],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "lines": [{"name": "AB", "bus0": "A", "bus1": "B", "x": 0.1, "r": 0.01, "s_nom": 500.0}],
        "generators": [{"name": "G", "bus": "A", "carrier": "gas", "p_nom": 900.0, "marginal_cost": 10.0}],
        "loads": [{"name": "L", "bus": "B", "p_set": 300.0}],
        "loads-p_set": [{"snapshot": s, "L": 300.0} for s in snaps],
    }


@pytest.mark.parametrize(
    "strategy,expected",
    [("mean", 1.1), ("max", 1.2), ("min", 1.0), ("zero", 0.0), ("default", 1.0)],
)
def test_clustering_numeric_conflict_strategy(strategy: str, expected: float) -> None:
    res = cluster_model(
        _vmag_model(), n_clusters=1, method="modularity",
        conflict_strategy=strategy, scenario=SCENARIO,
    )
    assert "v_mag_pu_set" in res["resolvedConflicts"]
    net, _ = build_network(res["model"], SCENARIO, {})
    assert float(net.buses["v_mag_pu_set"].iloc[0]) == pytest.approx(expected)


def test_kmeans_requires_distinct_coordinates() -> None:
    # All buses on the same coordinate → k-means has no spatial signal → 400.
    model = _path_model(4)
    for row in model["buses"]:
        row["x"] = 0.0
        row["y"] = 0.0
    with pytest.raises(HTTPException):
        cluster_model(model, n_clusters=2, method="kmeans", scenario=SCENARIO)
