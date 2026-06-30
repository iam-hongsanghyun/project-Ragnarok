"""N-1 contingency analysis (lpf_contingency) — branch loading under each outage.

A 3-bus meshed triangle (so any single line outage leaves the network
connected). With tight ratings every outage overloads the remaining path
(insecure); with generous ratings none do (secure).
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _triangle(s_nom: float) -> dict[str, list[dict[str, Any]]]:
    snap = "2030-01-01T00:00:00"
    return {
        "buses": [{"name": b, "v_nom": 380.0} for b in ("A", "B", "C")],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": snap}],
        "lines": [
            {"name": "AB", "bus0": "A", "bus1": "B", "x": 0.1, "r": 0.01, "s_nom": s_nom},
            {"name": "BC", "bus0": "B", "bus1": "C", "x": 0.1, "r": 0.01, "s_nom": s_nom},
            {"name": "AC", "bus0": "A", "bus1": "C", "x": 0.1, "r": 0.01, "s_nom": s_nom},
        ],
        "generators": [{"name": "G", "bus": "A", "carrier": "gas", "p_nom": 500.0, "marginal_cost": 10.0}],
        "loads": [{"name": "L", "bus": "C", "p_set": 200.0}],
        "loads-p_set": [{"snapshot": snap, "L": 200.0}],
    }


def test_contingency_flags_insecure_network() -> None:
    # s_nom 150: outaging any line forces 200 MW onto a 150 MVA path → overload.
    res = run_pypsa(_triangle(150.0), SCENARIO, {"contingencyConfig": {"enabled": True}})
    c = res["contingency"]
    assert c["error"] is None
    assert c["outagesTested"] == 3
    assert c["secure"] is False
    assert c["insecureCount"] == 3
    assert c["contingencies"][0]["worstLoadingPct"] > 100.0
    assert c["contingencies"][0]["worstBranch"] is not None
    assert res["runMeta"]["studyMode"] == "contingency"


def test_contingency_secure_network() -> None:
    # s_nom 400: the redirected 200 MW stays well within rating → N-1 secure.
    res = run_pypsa(_triangle(400.0), SCENARIO, {"contingencyConfig": {"enabled": True}})
    c = res["contingency"]
    assert c["error"] is None
    assert c["outagesTested"] == 3
    assert c["secure"] is True
    assert c["insecureCount"] == 0
    assert all(x["overloadCount"] == 0 for x in c["contingencies"])


def test_contingency_rejects_combination_with_other_modes() -> None:
    with pytest.raises(HTTPException):
        run_pypsa(
            _triangle(150.0),
            SCENARIO,
            {"contingencyConfig": {"enabled": True}, "powerFlowConfig": {"enabled": True}},
        )
