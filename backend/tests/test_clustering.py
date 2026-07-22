"""Network clustering transform (modularity / k-means) — model reduction.

Reduces a workbook model to fewer buses and checks the reduced model is smaller,
carries a busmap, and rebuilds into a valid network. k-means must degrade
cleanly (scikit-learn is optional and not installed here).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import HTTPException

from backend.app.routers.transforms import cluster_model
from backend.pypsa.network import build_network
from backend.pypsa.network.serialize import network_to_model

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


def _islands_model() -> dict[str, list[dict[str, Any]]]:
    """Two disconnected islands (A-B and C-D, no line between) — the shape where
    a single-node reduction must still reach one bus."""
    m = _path_model(4)
    # Drop the B-C line so {A,B} and {C,D} are separate connected components.
    m["lines"] = [ln for ln in m["lines"] if ln["name"] != "BC"]
    return m


def test_single_node_collapses_everything_onto_one_bus() -> None:
    res = cluster_model(_islands_model(), n_clusters=1, method="single", scenario=SCENARIO)
    assert res["method"] == "single"
    assert res["before"]["buses"] == 4
    assert res["after"]["buses"] == 1
    assert res["after"]["lines"] == 0  # every line becomes intra-cluster and drops
    # every original bus maps to the one surviving bus
    assert len(set(res["busmap"].values())) == 1
    net, _ = build_network(res["model"], SCENARIO, {})
    assert len(net.buses) == 1


def test_single_node_ignores_cluster_count_bounds() -> None:
    # n_clusters is irrelevant for "single" — an out-of-range value must not raise.
    res = cluster_model(_path_model(4), n_clusters=999, method="single", scenario=SCENARIO)
    assert res["after"]["buses"] == 1


def _two_load_model() -> dict[str, list[dict[str, Any]]]:
    """Path model with a second load, so merging loads is observable (2 → 1)."""
    m = _path_model(4)
    snaps = [r["snapshot"] for r in m["snapshots"]]
    m["loads"] = [
        {"name": "L1", "bus": "B", "p_set": 300.0},
        {"name": "L2", "bus": "D", "p_set": 200.0},
    ]
    m["loads-p_set"] = [{"snapshot": s, "L1": 300.0, "L2": 200.0} for s in snaps]
    return m


def test_single_node_merges_loads_into_one() -> None:
    # The "merge loads into a single load" option: aggregating the Load one-port
    # on the single bus collapses both loads to one row (demand summed: 500 MW).
    res = cluster_model(
        _two_load_model(),
        n_clusters=1,
        method="single",
        aggregate_components=["Load"],
        scenario=SCENARIO,
    )
    assert res["after"]["buses"] == 1
    assert res["after"]["loads"] == 1
    net, _ = build_network(res["model"], SCENARIO, {})
    assert len(net.loads) == 1
    # Total demand is preserved through the merge (300 + 200 = 500 MW).
    total = float(net.loads_t.p_set.sum(axis=1).iloc[0]) or float(net.loads.p_set.iloc[0])
    assert total == pytest.approx(500.0)


def test_single_node_without_aggregation_keeps_loads_split() -> None:
    # Default (no aggregate_components): loads are only reassigned to the one bus.
    res = cluster_model(_two_load_model(), n_clusters=1, method="single", scenario=SCENARIO)
    assert res["after"]["buses"] == 1
    assert res["after"]["loads"] == 2


def test_serialized_model_is_json_safe_with_subnetworks() -> None:
    """Regression: sub_networks carry a live SubNetwork object; the serialized
    model must drop it (and any non-scalar) so the HTTP response serialises."""
    net, _ = build_network(_path_model(4), SCENARIO, {})
    net.determine_network_topology()  # populates sub_networks (with an `obj` col)
    assert len(net.sub_networks) > 0
    model = network_to_model(net)
    assert "sub_networks" not in model
    json.dumps(model)  # must not raise (this is what FastAPI does for the response)


def test_clustered_result_is_json_serializable() -> None:
    net, _ = build_network(_path_model(4), SCENARIO, {})
    net.determine_network_topology()
    res = cluster_model(
        _path_model(4), n_clusters=2, method="modularity", scenario=SCENARIO
    )
    json.dumps(res)  # the whole transform response must serialise


def test_clustering_rejects_bad_target() -> None:
    with pytest.raises(HTTPException):
        cluster_model(_path_model(4), n_clusters=4, scenario=SCENARIO)  # == bus count
    with pytest.raises(HTTPException):
        cluster_model(_path_model(4), n_clusters=0, scenario=SCENARIO)


def test_kmeans_clustering_reduces_buses() -> None:
    # scikit-learn is a dependency, so spatial k-means runs (buses have distinct x).
    res = cluster_model(
        _path_model(4), n_clusters=2, method="kmeans", scenario=SCENARIO
    )
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
    res = cluster_model(
        _mixed_attr_model(), n_clusters=2, method="kmeans", scenario=SCENARIO
    )
    assert res["after"]["buses"] == 2
    assert set(res["resolvedConflicts"]) >= {"carrier", "unit"}
    # the merged model still rebuilds into a valid network
    net, _ = build_network(res["model"], SCENARIO, {})
    assert len(net.buses) == 2


def test_clustering_strict_mode_reports_conflicting_attributes() -> None:
    with pytest.raises(HTTPException) as ei:
        cluster_model(
            _mixed_attr_model(),
            n_clusters=2,
            method="kmeans",
            resolve_conflicts=False,
            scenario=SCENARIO,
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
        "lines": [
            {
                "name": "AB",
                "bus0": "A",
                "bus1": "B",
                "x": 0.1,
                "r": 0.01,
                "s_nom": 500.0,
            }
        ],
        "generators": [
            {
                "name": "G",
                "bus": "A",
                "carrier": "gas",
                "p_nom": 900.0,
                "marginal_cost": 10.0,
            }
        ],
        "loads": [{"name": "L", "bus": "B", "p_set": 300.0}],
        "loads-p_set": [{"snapshot": s, "L": 300.0} for s in snaps],
    }


@pytest.mark.parametrize(
    "strategy,expected",
    [("mean", 1.1), ("max", 1.2), ("min", 1.0), ("zero", 0.0), ("default", 1.0)],
)
def test_clustering_numeric_conflict_strategy(strategy: str, expected: float) -> None:
    res = cluster_model(
        _vmag_model(),
        n_clusters=1,
        method="modularity",
        conflict_strategy=strategy,
        scenario=SCENARIO,
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


# ── Aggregate buses by a workbook column (e.g. province) ────────────────────
def _region_model() -> dict[str, list[dict[str, Any]]]:
    """Path model whose 4 buses carry a ``region`` column: A/B=north, C/D=south."""
    m = _path_model(4)
    region = {"A": "north", "B": "north", "C": "south", "D": "south"}
    for row in m["buses"]:
        row["region"] = region[row["name"]]
    return m


def test_group_by_column_merges_buses_sharing_a_value() -> None:
    res = cluster_model(
        _region_model(), n_clusters=99, group_by_column="region", scenario=SCENARIO
    )
    assert res["method"] == "column:region"
    assert res["groupByColumn"] == "region"
    assert res["before"]["buses"] == 4
    assert res["after"]["buses"] == 2
    # busmap groups exactly by the region value
    assert res["busmap"] == {"A": "north", "B": "north", "C": "south", "D": "south"}
    net, _ = build_network(res["model"], SCENARIO, {})
    assert len(net.buses) == 2


def test_group_by_column_keeps_blank_valued_buses_separate() -> None:
    m = _region_model()
    # Blank out one bus's region → it must stay on its own, not merge with the other blank.
    m["buses"][2]["region"] = ""  # C
    res = cluster_model(m, n_clusters=99, group_by_column="region", scenario=SCENARIO)
    # north {A,B} merges; C (blank) alone; D (south) alone → 3 buses
    assert res["after"]["buses"] == 3
    assert res["busmap"]["C"] == "C"


def test_group_by_missing_column_raises() -> None:
    with pytest.raises(HTTPException):
        cluster_model(
            _path_model(4), n_clusters=99, group_by_column="nope", scenario=SCENARIO
        )


def test_group_by_column_merging_nothing_raises() -> None:
    # Every bus a distinct region → nothing to merge.
    m = _path_model(4)
    for i, row in enumerate(m["buses"]):
        row["region"] = f"r{i}"
    with pytest.raises(HTTPException):
        cluster_model(m, n_clusters=99, group_by_column="region", scenario=SCENARIO)


# ── Aggregate one-port components by carrier per merged bus ─────────────────
def _two_gas_model() -> dict[str, list[dict[str, Any]]]:
    """4-bus path with two gas generators (on A and B, which cluster together)
    plus two batteries, so carrier-aggregation is observable."""
    m = _region_model()
    m["carriers"] = [{"name": "gas"}, {"name": "battery"}]
    m["generators"] = [
        {
            "name": "g1",
            "bus": "A",
            "carrier": "gas",
            "p_nom": 100.0,
            "marginal_cost": 10.0,
        },
        {
            "name": "g2",
            "bus": "B",
            "carrier": "gas",
            "p_nom": 200.0,
            "marginal_cost": 12.0,
        },
    ]
    m["storage_units"] = [
        {"name": "s1", "bus": "A", "carrier": "battery", "p_nom": 10.0},
        {"name": "s2", "bus": "B", "carrier": "battery", "p_nom": 20.0},
    ]
    return m


def test_component_aggregation_collapses_generators_by_carrier() -> None:
    res = cluster_model(
        _two_gas_model(),
        n_clusters=99,
        group_by_column="region",
        aggregate_components=["Generator", "StorageUnit"],
        scenario=SCENARIO,
    )
    assert res["aggregatedComponents"] == ["Generator", "StorageUnit"]
    # A+B both 'north': two gas gens → one; two batteries → one
    assert res["after"]["generators"] == 1
    assert res["after"]["storageUnits"] == 1
    gens = res["model"]["generators"]
    assert float(gens[0]["p_nom"]) == pytest.approx(300.0)  # p_nom summed
    net, _ = build_network(res["model"], SCENARIO, {})
    assert len(net.generators) == 1


def test_component_aggregation_off_by_default_leaves_components_split() -> None:
    # Same busmap, no aggregate_components → generators only reassigned, not merged.
    res = cluster_model(
        _two_gas_model(),
        n_clusters=99,
        group_by_column="region",
        scenario=SCENARIO,
    )
    assert res["after"]["generators"] == 2
    assert res["after"]["storageUnits"] == 2
    assert res["aggregatedComponents"] == []


# ── Aggregate parallel transmission links (DC corridors) ────────────────────
def _dc_links_model() -> dict[str, list[dict[str, Any]]]:
    """Region model (north {A,B} / south {C,D}) with two parallel DC links
    A→C and B→D that become the same north→south corridor after clustering.
    dc1 additionally carries a p_max_pu series so dynamic merging is
    observable (dc2 falls back to its static 1.0)."""
    m = _region_model()
    snaps = [r["snapshot"] for r in m["snapshots"]]
    m["carriers"] = [{"name": "gas"}, {"name": "DC"}]
    m["links"] = [
        {
            "name": "dc1",
            "bus0": "A",
            "bus1": "C",
            "carrier": "DC",
            "p_nom": 100.0,
            "efficiency": 0.95,
            "marginal_cost": 2.0,
        },
        {
            "name": "dc2",
            "bus0": "B",
            "bus1": "D",
            "carrier": "DC",
            "p_nom": 300.0,
            "efficiency": 0.90,
            "marginal_cost": 4.0,
        },
    ]
    m["links-p_max_pu"] = [
        {"snapshot": snaps[0], "dc1": 0.8},
        {"snapshot": snaps[1], "dc1": 0.6},
    ]
    return m


def test_link_aggregation_merges_parallel_dc_links() -> None:
    res = cluster_model(
        _dc_links_model(),
        n_clusters=99,
        group_by_column="region",
        aggregate_components=["Link"],
        scenario=SCENARIO,
    )
    assert res["aggregatedComponents"] == ["Link"]
    assert res["before"]["links"] == 2
    assert res["after"]["links"] == 1
    net, _ = build_network(res["model"], SCENARIO, {})
    link = net.links.iloc[0]
    # Capacity sums; loss (efficiency) and marginal cost are capacity-weighted:
    # η = 0.25·0.95 + 0.75·0.90 = 0.9125, mc = 0.25·2 + 0.75·4 = 3.5.
    assert float(link["p_nom"]) == pytest.approx(400.0)
    assert float(link["efficiency"]) == pytest.approx(0.9125)
    assert float(link["marginal_cost"]) == pytest.approx(3.5)
    # Dynamic p_max_pu: dc1's series blends with dc2's static 1.0 →
    # 0.25·0.8 + 0.75·1 = 0.95 and 0.25·0.6 + 0.75·1 = 0.90.
    pmax = net.links_t.p_max_pu[net.links.index[0]]
    assert float(pmax.iloc[0]) == pytest.approx(0.95)
    assert float(pmax.iloc[1]) == pytest.approx(0.90)
    json.dumps(res)


def test_link_aggregation_off_keeps_links_split() -> None:
    res = cluster_model(
        _dc_links_model(),
        n_clusters=99,
        group_by_column="region",
        scenario=SCENARIO,
    )
    assert res["after"]["links"] == 2


def test_link_aggregation_keeps_opposite_directions_apart() -> None:
    # Reverse dc2 (D→B): efficiency applies to bus0→bus1 flow, so a
    # south→north link must not merge with the north→south one.
    m = _dc_links_model()
    m["links"][1]["bus0"], m["links"][1]["bus1"] = "D", "B"
    res = cluster_model(
        m,
        n_clusters=99,
        group_by_column="region",
        aggregate_components=["Link"],
        scenario=SCENARIO,
    )
    assert res["after"]["links"] == 2


def test_link_aggregation_leaves_conversion_links_alone() -> None:
    # Two parallel electrolysis links to a hydrogen bus connect buses of
    # DIFFERENT carriers → not transport, never merged. The DC pair still is.
    m = _dc_links_model()
    m["carriers"] += [{"name": "hydrogen"}, {"name": "electrolysis"}]
    m["buses"].append(
        {"name": "E", "v_nom": 380.0, "x": 4.0, "y": 0.0, "carrier": "hydrogen"}
    )
    m["links"] += [
        {"name": "el1", "bus0": "A", "bus1": "E", "carrier": "electrolysis", "p_nom": 50.0, "efficiency": 0.7},
        {"name": "el2", "bus0": "B", "bus1": "E", "carrier": "electrolysis", "p_nom": 60.0, "efficiency": 0.7},
    ]
    res = cluster_model(
        m,
        n_clusters=99,
        group_by_column="region",
        aggregate_components=["Link"],
        scenario=SCENARIO,
    )
    # DC pair merges to 1; both electrolysis links survive untouched.
    assert res["after"]["links"] == 3
    names = {row["name"] for row in res["model"]["links"]}
    assert {"el1", "el2"} <= names


def test_component_aggregation_all_oneports_json_serialisable() -> None:
    res = cluster_model(
        _two_gas_model(),
        n_clusters=99,
        group_by_column="region",
        aggregate_components=[
            "Generator",
            "StorageUnit",
            "Store",
            "Load",
            "ShuntImpedance",
        ],
        scenario=SCENARIO,
    )
    json.dumps(res)
    net, _ = build_network(res["model"], SCENARIO, {})
    assert len(net.buses) == 2
