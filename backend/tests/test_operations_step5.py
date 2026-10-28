"""Core cleanup step 5 (operations): load shedding by PyPSA, Force-LP, and the visible workbook steps.

Pins: ``n.optimize.add_load_shedding`` is the only shedding builder (names ``"<bus> load shedding"``, carrier
``LoadShedding``); it is sized by the system peak of static AND time-series loads (audit finding 18); every result path
tells shedding by carrier (legacy ``load_shedding_<bus>`` names of stored runs still read); the values do not change.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network.load_shedding import system_peak_load
from backend.pypsa.results import run_pypsa
from backend.pypsa.utils.shedding import is_shedding, shed_carrier, shedding_mask, shedding_names

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _model(n: int = 4, load: float = 500.0, two_buses: bool = False) -> dict[str, Any]:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(n)]
    m: dict[str, Any] = {
        "buses": [{"name": "b"}] + ([{"name": "c"}] if two_buses else []),
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": load}],
        "generators": [{"name": "G", "bus": "b", "carrier": "gas", "p_nom": 300.0, "marginal_cost": 10.0}],
    }
    return m


def test_shedding_is_pypsas_add_load_shedding_one_generator_per_bus() -> None:
    n, notes = build_network(_model(two_buses=True), SCENARIO, {"enableLoadShedding": True, "loadSheddingCost": 777.0})
    assert sorted(shedding_names(n.generators)) == ["b load shedding", "c load shedding"]
    g = n.generators.loc["b load shedding"]
    assert g["carrier"] == shed_carrier() and g["marginal_cost"] == pytest.approx(777.0) and g["sign"] == 1.0
    assert shed_carrier() in n.carriers.index
    assert any(x.startswith("Load shedding (PyPSA add_load_shedding)") for x in notes)


def test_p_nom_is_the_system_peak_of_static_and_time_series_loads() -> None:
    """Finding 18: a bus with a static load AND a time-series load. The old size was max(ts peak, static sum) = 80 here."""
    m = _model(3, load=50.0)
    m["loads"].append({"name": "L2", "bus": "b", "p_set": 0.0})
    m["loads-p_set"] = [{"snapshot": s["snapshot"], "L2": v} for s, v in zip(m["snapshots"], [10.0, 30.0, 20.0])]
    n, _ = build_network(m, SCENARIO, {"enableLoadShedding": True})
    assert system_peak_load(n) == pytest.approx(80.0)  # 50 (static L) + 30 (peak of L2), not max(30, 50)
    assert n.generators.at["b load shedding", "p_nom"] == pytest.approx(80.0)
    # a series that replaces a static value counts once
    m2 = _model(3, load=50.0)
    m2["loads-p_set"] = [{"snapshot": s["snapshot"], "L": v} for s, v in zip(m2["snapshots"], [10.0, 90.0, 20.0])]
    n2, _ = build_network(m2, SCENARIO, {"enableLoadShedding": True})
    assert n2.generators.at["b load shedding", "p_nom"] == pytest.approx(90.0)


def test_values_are_unchanged_and_shedding_is_not_supply() -> None:
    res = run_pypsa(_model(2, load=500.0), SCENARIO, {"enableLoadShedding": True, "loadSheddingCost": 1234.0})
    assert not any(is_shedding(ge["name"], ge.get("carrier")) for ge in res["generatorEnergy"])
    assert {ge["name"] for ge in res["generatorEnergy"]} == {"G"}
    assert any("Load shedding totalled 400.00 MWh" in n for n in res["narrative"])  # (500 - 300) MW x 2 h
    shed = next(r for r in res["costBreakdown"] if r["label"] == "Load shedding")
    assert shed["value"] == 400 * 1234
    # an energy-balance total counts neither the shedding carrier as generation nor double counts it
    assert sum(ge["value"] for ge in res["generatorEnergy"]) == pytest.approx(600.0)


def test_legacy_names_still_read_as_shedding() -> None:
    assert is_shedding("load_shedding_b") and is_shedding("load_shedding_elastic_b_1") and is_shedding("x load shedding")
    assert is_shedding("anything", shed_carrier()) and not is_shedding("gas_plant", "gas")
    frame = pd.DataFrame({"carrier": ["gas", "gas", shed_carrier()]}, index=["G", "load_shedding_old", "new"])
    assert shedding_names(frame) == ["load_shedding_old", "new"]
    assert shedding_mask(frame).tolist() == [False, True, True]


def test_a_stored_run_with_the_old_names_rebuilds_and_analytics_exclude_them() -> None:
    """A run stored before build version 4 has ``load_shedding_<bus>`` outputs; the compat reader keeps them out of supply."""
    from backend.pypsa.results.emissions import build_emissions_breakdown  # noqa: F401  (import must keep working)
    from backend.pypsa.utils.shedding import is_shedding as reader

    stored = {"load_shedding_b": [0.0, 12.0], "G": [300.0, 300.0]}
    supply = [k for k in stored if not reader(k)]
    assert supply == ["G"]


def test_force_lp_run_is_an_lp_with_prices_and_no_commitment_view() -> None:
    m = _model(4, load=100.0)
    m["generators"][0].update(committable=True, p_min_pu=0.5, p_nom=200.0, start_up_cost=500.0, marginal_cost=10.0)
    m["generators"].append({"name": "peak", "bus": "b", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 50.0})
    res = run_pypsa(m, SCENARIO, {"forceLp": True})
    assert res["commitment"] is None
    assert any("LP-relaxed (linearized) unit commitment" in n for n in res["narrative"])
    assert res["runMeta"]["averageSystemPrice"] == pytest.approx(10.0)  # a real shadow price: LP
    mip = run_pypsa(m, SCENARIO, {})
    assert mip["commitment"] is not None


def test_relaxing_maintenance_is_the_visible_workbook_step() -> None:
    from backend.pypsa.network.force_lp import relax_maintenance

    m = _model(4, load=100.0)
    m["generators"][0].update(maintainable=True, maintenance_duration=1, maintenance_events=1)
    out, changed = relax_maintenance(m)
    assert changed == [{"sheet": "generators", "name": "G"}] and out["generators"][0]["maintainable"] is False
