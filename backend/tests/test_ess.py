"""ESS business-case builder (DW3) — battery size sweep vs arbitrage revenue.

A spiky price (cheap and dear hours alternate) gives a battery real arbitrage
value. The sweep should return a size curve with NPV/IRR/payback and pick the
NPV-maximising size.
"""
from __future__ import annotations

from typing import Any

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.07, "carbonPrice": 0.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    # Alternating cheap/dear hours → a wide price spread for arbitrage.
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(8)]
    load = [60, 200, 60, 200, 60, 200, 60, 200]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "base"}, {"name": "peak"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "base1", "bus": "b", "carrier": "base", "p_nom": 120, "marginal_cost": 20},
            {"name": "peak1", "bus": "b", "carrier": "peak", "p_nom": 200, "marginal_cost": 150},
        ],
    }


def test_ess_business_case_size_sweep() -> None:
    res = run_pypsa(
        _model(), SCENARIO,
        {"essConfig": {"enabled": True, "maxHours": 4, "capitalCostPerMW": 30000,
                       "minSizeMW": 10, "maxSizeMW": 60, "steps": 4, "roundTripEfficiency": 0.9}},
    )
    ess = res["essBusinessCase"]
    assert ess is not None
    assert ess["bus"] == "b"
    assert len(ess["sizes"]) == 4
    for s in ess["sizes"]:
        assert s["sizeMW"] > 0
        assert s["arbitrageRevenue"] >= 0  # a battery never loses money arbitraging
        assert "npv" in s and "paybackYears" in s
    # Best size is the NPV-maximiser reported in the curve.
    assert ess["bestNpv"] == max(s["npv"] for s in ess["sizes"])
    assert any(s["sizeMW"] == ess["bestSizeMW"] for s in ess["sizes"])


def test_ess_business_case_absent_when_disabled() -> None:
    assert run_pypsa(_model(), SCENARIO, {})["essBusinessCase"] is None
