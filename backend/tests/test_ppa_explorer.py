"""DW4 — PPA opportunity explorer: rank contract shapes by capture price.

Prices split 10 / 100 across two hours (cheap gas is capacity-capped in the peak
hour). A solar owner only produces in the cheap hour, so its as-produced capture
is 10; a flat 24/7 block captures the mean 55; a peak block captures the 100.
The explorer must rank them peak > flat > generation.
"""
from __future__ import annotations

from typing import Any

from backend.pypsa.network import build_network
from backend.pypsa.results.ppa_explorer import build_ppa_explorer

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
OPTIONS = {"snapshotStart": 0, "snapshotCount": 2, "snapshotWeight": 1.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "solar"}, {"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b"}],
        "loads-p_set": [{"snapshot": snaps[0], "L": 50.0}, {"snapshot": snaps[1], "L": 150.0}],
        "generators": [
            {"name": "cheap", "bus": "b", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0},
            {"name": "peak", "bus": "b", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 100.0},
            {"name": "solar1", "bus": "b", "carrier": "solar", "p_nom": 20.0, "marginal_cost": 0.0, "owner": "Acme"},
        ],
        "generators-p_max_pu": [
            {"snapshot": snaps[0], "solar1": 1.0},
            {"snapshot": snaps[1], "solar1": 0.0},
        ],
    }


def test_explorer_ranks_shapes_by_capture_price() -> None:
    n, _ = build_network(_model(), SCENARIO, OPTIONS)
    n.optimize(solver_name="highs")
    out = build_ppa_explorer(
        n, _model(), owner="Acme", owner_column="owner", flat_mw=10.0, strike_price=50.0, currency="$",
    )
    assert out is not None
    labels = [s["shape"] for s in out["shapes"]]
    captures = [s["avgSpotPrice"] for s in out["shapes"]]
    # Ranked by capture price, descending: peak > flat > generation.
    assert labels[0].startswith("Peak")
    assert labels[-1].startswith("Generation")
    assert captures == sorted(captures, reverse=True)

    by = {s["shape"]: s for s in out["shapes"]}
    assert by["Generation (as-produced)"]["avgSpotPrice"] == 10.0   # solar only runs in the cheap hour
    assert by["Flat block (24/7)"]["avgSpotPrice"] == 55.0          # mean of 10 and 100
    assert by["Peak block (top 25% hours)"]["avgSpotPrice"] == 100.0


def test_explorer_none_when_unsolved() -> None:
    n, _ = build_network(_model(), SCENARIO, OPTIONS)
    assert build_ppa_explorer(
        n, _model(), owner="Acme", owner_column="owner", flat_mw=10.0, strike_price=50.0, currency="$",
    ) is None
