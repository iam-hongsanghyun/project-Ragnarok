"""Shared SOC-limited storage dispatch kernel and its four consumers.

Analytical: the kernel is checked against a hand-worked 4-snapshot case
(efficiency, power, energy and recharge-from-surplus limits). Behavioural: ELCC
of a battery must rise with its duration (0.25 h < 1 h < 8 h at equal power) —
the unlimited-energy treatment gave all three the same 75 %.
"""
from __future__ import annotations

import logging

import numpy as np
import pypsa
import pytest

from backend.pypsa.results.adequacy import (
    StorageFleet,
    build_adequacy,
    electricity_buses,
    extract_storage_fleet,
    storage_dispatch,
)
from backend.pypsa.results.elcc import build_elcc
from backend.pypsa.results.outage_mc import build_outage_mc

logging.disable(logging.CRITICAL)


def _fleet(power: float, energy: float, eta_c: float, eta_d: float, T: int, *, loss: float = 0.0,
           soc0: float = 0.0) -> StorageFleet:
    return StorageFleet(
        ("s",), ("battery",), np.full((1, T), power), np.array([power]), np.array([energy]),
        np.array([eta_c]), np.array([eta_d]), np.array([loss]), np.array([soc0]),
    )


def test_kernel_matches_hand_worked_case() -> None:
    # load 100; gen 130,60,60,100. P=30 MW, E=30 MWh, eta 0.9 each way, start empty.
    # t0 surplus 30: charge 30 MW -> e = 30*0.9 = 27 MWh.
    # t1 deficit 40: discharge min(40, 30, 27*0.9) = 24.3 MW, e -> 27 - 24.3/0.9 = 0.
    # t2 deficit 40: empty -> 0. t3 balanced -> 0.
    out = storage_dispatch(
        np.array([[130.0, 60.0, 60.0, 100.0]]), np.full(4, 100.0), np.ones(4),
        _fleet(30.0, 30.0, 0.9, 0.9, 4),
    )
    np.testing.assert_allclose(out[0], [0.0, 24.3, 0.0, 0.0], rtol=1e-12, atol=1e-12)


def test_kernel_uses_snapshot_weights() -> None:
    # Same case, but t1 represents 2 h: the stored 27 MWh covers only
    # 27*0.9/2 = 12.15 MW for two hours.
    out = storage_dispatch(
        np.array([130.0, 60.0, 60.0, 100.0]), np.full(4, 100.0), np.array([1.0, 2.0, 1.0, 1.0]),
        _fleet(30.0, 30.0, 0.9, 0.9, 4),
    )
    np.testing.assert_allclose(out[0], [0.0, 12.15, 0.0, 0.0], rtol=1e-12, atol=1e-12)


def test_kernel_recharges_only_from_surplus_and_applies_standing_loss() -> None:
    # No surplus ever: an empty store never fills, so it cannot discharge.
    out = storage_dispatch(np.array([60.0, 60.0]), np.full(2, 100.0), np.ones(2), _fleet(30, 30, 1, 1, 2))
    assert not out.any()
    # Full store, standing loss 10 %/h, balanced snapshot first: 20 -> 18 MWh before the deficit.
    out = storage_dispatch(
        np.array([100.0, 80.0]), np.full(2, 100.0), np.ones(2),
        _fleet(50.0, 20.0, 1.0, 1.0, 2, loss=0.1, soc0=20.0),
    )
    np.testing.assert_allclose(out[0], [0.0, 16.2], rtol=1e-12)  # 20*0.9 -> 18, then 0.9 again -> 16.2


def _system(max_hours: float) -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(range(24))
    n.add("Bus", "b")
    n.add("Carrier", ["gas", "solar", "battery", "shed"])
    load = 100 + 60 * np.exp(-((np.arange(24) - 19) ** 2) / 6)
    n.add("Load", "L", bus="b", p_set=load)
    n.add("Generator", "g", bus="b", carrier="gas", p_nom=130, marginal_cost=50)
    cf = np.clip(np.sin((np.arange(24) - 6) / 12 * np.pi), 0, None)
    n.add("Generator", "pv", bus="b", carrier="solar", p_nom=200, p_max_pu=cf, marginal_cost=0)
    n.add("Generator", "load_shedding_b", bus="b", carrier="shed", p_nom=1e4, marginal_cost=3000)
    n.add("StorageUnit", "bat", bus="b", carrier="battery", p_nom=40, max_hours=max_hours,
          efficiency_store=0.95, efficiency_dispatch=0.95, cyclic_state_of_charge=True)
    n.optimize(solver_name="highs", include_objective_constant=False)
    return n


def _elcc_pct(n: pypsa.Network, carrier: str) -> float:
    res = build_elcc(n, {"elccConfig": {"enabled": True, "nMembers": 100, "carriers": [carrier]}})
    assert res is not None
    return next(r["elccPct"] for r in res["byCarrier"] if r["carrier"] == carrier)


@pytest.fixture(scope="module")
def systems() -> dict[float, pypsa.Network]:
    return {h: _system(h) for h in (0.25, 1.0, 8.0)}


def test_elcc_rises_with_battery_duration(systems: dict[float, pypsa.Network]) -> None:
    pct = {h: _elcc_pct(n, "battery") for h, n in systems.items()}
    assert pct[0.25] < pct[1.0] < pct[8.0]
    assert pct[8.0] > 50.0  # an 8 h battery covers the 5 h evening deficit


def test_adequacy_and_outage_mc_count_storage_energy(systems: dict[float, pypsa.Network]) -> None:
    eens = {h: build_adequacy(n)["eens"] for h, n in systems.items()}
    assert eens[0.25] > eens[1.0] > eens[8.0]
    cfg = {"outageMcConfig": {"enabled": True, "nMembers": 50, "seed": 3}}
    lole = {h: build_outage_mc(n, cfg)["loleDistribution"]["mean"] for h, n in systems.items()}
    assert lole[0.25] >= lole[1.0] >= lole[8.0]
    assert lole[0.25] > lole[8.0]


def test_store_with_links_is_part_of_the_fleet() -> None:
    n = pypsa.Network()
    n.set_snapshots(range(6))
    n.add("Bus", "ac")
    n.add("Bus", "bat")
    n.add("Load", "L", bus="ac", p_set=[50, 50, 120, 120, 50, 50])
    n.add("Generator", "g", bus="ac", p_nom=100, marginal_cost=10)
    n.add("Generator", "peak", bus="ac", p_nom=100, marginal_cost=200)
    n.add("Store", "st", bus="bat", e_nom=60, e_cyclic=True, carrier="battery")
    n.add("Link", "chg", bus0="ac", bus1="bat", p_nom=25, efficiency=0.9)
    n.add("Link", "dis", bus0="bat", bus1="ac", p_nom=25, efficiency=0.8)
    n.optimize(solver_name="highs", include_objective_constant=False)
    assert electricity_buses(n) == {"ac"}  # the battery bus is plumbing, not electricity
    fleet = extract_storage_fleet(n)
    assert fleet.names == ("st",)
    assert fleet.energy_mwh[0] == pytest.approx(60.0)
    assert fleet.discharge_mw[0].max() == pytest.approx(25 * 0.8)  # grid-side delivery
    assert fleet.charge_mw[0] == pytest.approx(25.0)
    assert fleet.eta_charge[0] == pytest.approx(0.9)
    assert fleet.eta_discharge[0] == pytest.approx(0.8)
    # And the kernel serves a shortfall with it.
    out = storage_dispatch(np.full(6, 100.0), np.array([50, 50, 130, 130, 50, 50.0]), np.ones(6), fleet)
    assert out.max() == pytest.approx(20.0)
