"""M2 — shiftable-load demand response.

A load peaks at 150 MW in hour 1 but only 50 MW in hour 0. Cheap generation is
capped at 100 MW, so without demand response the 150 MW peak forces the expensive
100 $/MWh unit to run. With a shiftable load the demand flattens to 100/100 —
the cheap unit covers everything, the expensive unit stays off — and total energy
is unchanged (demand is moved, not dropped).
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network.demand_response import build_demand_response

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
OPTIONS = {"snapshotStart": 0, "snapshotCount": 2, "snapshotWeight": 1.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "cheap"}, {"name": "peaker"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b"}],
        "loads-p_set": [
            {"snapshot": snaps[0], "L": 50.0},
            {"snapshot": snaps[1], "L": 150.0},
        ],
        "generators": [
            {"name": "G_cheap", "bus": "b", "carrier": "cheap", "p_nom": 100.0, "marginal_cost": 10.0},
            {"name": "G_peak", "bus": "b", "carrier": "peaker", "p_nom": 100.0, "marginal_cost": 100.0},
        ],
    }


def _dr_options(**dr: Any) -> dict[str, Any]:
    return {**OPTIONS, "demandResponseConfig": {"enabled": True, "shiftFraction": 0.5, "maxShiftHours": 2.0, **dr}}


def test_without_dr_peaker_runs() -> None:
    n, _ = build_network(_model(), SCENARIO, OPTIONS)
    n.optimize(solver_name="highs")
    assert float(n.generators_t.p["G_peak"].sum()) == pytest.approx(50.0, abs=1e-3)  # covers the 150 peak
    assert float(n.generators_t.p["G_cheap"].sum()) == pytest.approx(150.0, abs=1e-3)


def test_dr_flattens_load_and_avoids_peaker() -> None:
    n, _ = build_network(_model(), SCENARIO, _dr_options())
    # DR components were created and the load moved to its DR bus.
    assert "dr_L" in n.buses.index
    assert "drlink_L" in n.links.index
    assert "drstore_L" in n.stores.index
    assert n.loads.at["L", "bus"] == "dr_L"

    n.optimize(solver_name="highs")
    # Cheap unit serves everything; the peaker stays off.
    assert float(n.generators_t.p["G_peak"].sum()) == pytest.approx(0.0, abs=1e-3)
    assert float(n.generators_t.p["G_cheap"].sum()) == pytest.approx(200.0, abs=1e-3)
    # Grid draw flattened to ~100/100.
    draw = n.links_t.p0["drlink_L"]
    assert float(draw.iloc[0]) == pytest.approx(100.0, abs=1e-2)
    assert float(draw.iloc[1]) == pytest.approx(100.0, abs=1e-2)
    # Energy conserved: total demand still 200 MWh.
    assert float(n.loads_t.p_set["L"].sum()) == pytest.approx(200.0, abs=1e-6)


def test_build_demand_response_reports_shift() -> None:
    n, _ = build_network(_model(), SCENARIO, _dr_options())
    n.optimize(solver_name="highs")
    out = build_demand_response(n)
    assert out is not None
    assert out["totalShiftedMWh"] == pytest.approx(50.0, abs=1e-2)  # 50 MW moved from h1 to h0
    row = next(r for r in out["loads"] if r["name"] == "L")
    assert row["peakBeforeMW"] == pytest.approx(150.0, abs=1e-2)
    assert row["peakAfterMW"] == pytest.approx(100.0, abs=1e-2)
    assert row["peakReductionPct"] == pytest.approx(33.3, abs=0.5)


def test_dr_load_subset_only_shifts_selected() -> None:
    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    model = _model()
    model["loads"].append({"name": "L2", "bus": "b"})
    model["loads-p_set"] = [
        {"snapshot": snaps[0], "L": 50.0, "L2": 30.0},
        {"snapshot": snaps[1], "L": 150.0, "L2": 30.0},
    ]
    n, _ = build_network(model, SCENARIO, _dr_options(loads=["L"]))
    # Only the selected load is rewired.
    assert "dr_L" in n.buses.index and n.loads.at["L", "bus"] == "dr_L"
    assert "dr_L2" not in n.buses.index and n.loads.at["L2", "bus"] == "b"


def test_no_dr_config_returns_none() -> None:
    n, _ = build_network(_model(), SCENARIO, OPTIONS)
    n.optimize(solver_name="highs")
    assert build_demand_response(n) is None
