"""PyPSA statistics passthrough — the canonical per-carrier metrics table."""
from __future__ import annotations

from typing import Any

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T0{h}:00:00" for h in range(3)]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": "wind"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 120}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, [120, 180, 90])],
        "generators": [
            {"name": "g_gas", "bus": "b", "carrier": "gas", "p_nom": 200, "marginal_cost": 50},
            {"name": "g_wind", "bus": "b", "carrier": "wind", "p_nom": 150, "marginal_cost": 0},
        ],
        "generators-p_max_pu": [{"snapshot": s, "g_wind": v} for s, v in zip(snaps, [0.5, 0.8, 0.3])],
    }


def test_statistics_passthrough_table() -> None:
    res = run_pypsa(_model(), SCENARIO, {})
    st = res["statistics"]
    # PyPSA's canonical metric columns are present.
    assert st["columns"]
    for col in ("Optimal Capacity", "Capacity Factor", "Curtailment", "Revenue", "Market Value"):
        assert col in st["columns"]
    # Both generator carriers show up as rows.
    gen_carriers = {r["carrier"] for r in st["rows"] if r["component"] == "Generator"}
    assert {"gas", "wind"} <= gen_carriers
    # Wind has a sane capacity factor in [0, 1].
    wind = next(r for r in st["rows"] if r["carrier"] == "wind")
    cf = wind["values"]["Capacity Factor"]
    assert cf is not None and 0.0 <= cf <= 1.0
