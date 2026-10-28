"""P28/P29 — metrics moved onto ``n.statistics`` agree with the hand-rolled originals.

The reference implementation of the per-carrier energy balance (the pre-1.4
hand-rolled one, link ports walked by hand) lives in this file so the move is
pinned against it: identical on Generator/Load/Link/Store models, and PyPSA-correct
(Process included) where the original was blind.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import pandas as pd
import pypsa
import pytest

from backend.pypsa.results.energy_balance import _bus_carriers, build_energy_balance
from backend.pypsa.utils.series import weighted_sum

logging.getLogger("linopy").setLevel(logging.ERROR)
logging.getLogger("pypsa").setLevel(logging.ERROR)


def _legacy_energy_balance(network: pypsa.Network) -> dict[str, dict[str, dict[str, float]]]:
    """Reference: ``{carrier: {"sources"|"sinks": {label: MWh}}}`` the hand-rolled way."""
    bus_carrier = _bus_carriers(network)
    w = network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)
    out: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: {"sources": defaultdict(float), "sinks": defaultdict(float)})
    gp = network.generators_t.p
    for g in network.generators.index:
        if str(g).startswith("load_shedding_") or g not in gp.columns:
            continue
        c = bus_carrier.get(str(network.generators.at[g, "bus"]), "AC")
        out[c]["sources"][str(network.generators.at[g, "carrier"]) or "generation"] += weighted_sum(gp[g].clip(lower=0.0), w)
    lp = network.loads_t.p_set
    for load in network.loads.index:
        if load in lp.columns:
            c = bus_carrier.get(str(network.loads.at[load, "bus"]), "AC")
            out[c]["sinks"]["Demand"] += weighted_sum(lp[load].clip(lower=0.0), w)
    for lk in network.links.index:
        links = network.links
        c0 = bus_carrier.get(str(links.at[lk, "bus0"]), "AC")
        c1 = bus_carrier.get(str(links.at[lk, "bus1"]), "AC")
        lcarr = str(links.at[lk, "carrier"]) or ""
        out[c0]["sinks"][lcarr or f"→ {c1}"] += weighted_sum(network.links_t.p0[lk].clip(lower=0.0), w)
        out[c1]["sources"][lcarr or f"{c0} →"] += weighted_sum((-network.links_t.p1[lk]).clip(lower=0.0), w)
    for comp, frame in (("storage_units", "storage_units_t"), ("stores", "stores_t")):
        for unit in getattr(network, comp).index:
            pf = getattr(network, frame).p
            c = bus_carrier.get(str(getattr(network, comp).at[unit, "bus"]), "AC")
            dl = "Storage discharge" if comp == "storage_units" else "Store discharge"
            cl = "Storage charge" if comp == "storage_units" else "Store charge"
            out[c]["sources"][dl] += weighted_sum(pf[unit].clip(lower=0.0), w)
            out[c]["sinks"][cl] += weighted_sum(pf[unit].clip(upper=0.0).abs(), w)
    return out


def _sector_network(weight: float = 1.0, with_process: bool = False) -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=4, freq="h"))
    n.snapshot_weightings.loc[:, :] = weight
    n.add("Carrier", ["gas", "electricity", "heat", "CCGT", "chp", "battery"])
    n.add("Bus", "gas", carrier="gas")
    n.add("Bus", "elec", carrier="electricity")
    n.add("Bus", "heat", carrier="heat")
    n.add("Generator", "well", bus="gas", carrier="gas", p_nom=2000, marginal_cost=5)
    n.add("Generator", "wind", bus="elec", carrier="electricity", p_nom=60, marginal_cost=0,
          p_max_pu=[0.2, 1.0, 0.5, 0.9])
    n.add("Load", "L", bus="elec", p_set=[100.0, 80.0, 120.0, 90.0])
    n.add("Link", "CCGT", bus0="gas", bus1="elec", carrier="CCGT", efficiency=0.5, p_nom=500)
    n.add("Store", "bat", bus="elec", e_nom=100, e_cyclic=True, carrier="battery")
    if with_process:
        n.add("Load", "H", bus="heat", p_set=15.0)
        n.add("Process", "chp", bus0="gas", bus1="elec", bus2="heat", rate0=-1.0, rate1=0.4, rate2=0.3,
              p_nom=300, carrier="chp", p_min_pu=0.0)
        n.add("Generator", "heat_dump", bus="heat", p_nom=100, p_min_pu=-1.0, p_max_pu=0.0, carrier="heat")  # absorbs surplus heat only
    status, cond = n.optimize(solver_name="highs", log_to_console=False)
    assert (status, cond) == ("ok", "optimal")
    return n


def _as_maps(balance: dict[str, Any]) -> dict[str, dict[str, dict[str, float]]]:
    return {
        c["carrier"]: {
            "sources": {s["label"]: s["energyMWh"] for s in c["sources"]},
            "sinks": {s["label"]: s["energyMWh"] for s in c["sinks"]},
        }
        for c in balance["carriers"]
    }


@pytest.mark.parametrize("weight", [1.0, 3.0])
def test_energy_balance_matches_hand_rolled_reference(weight: float) -> None:
    """Statistics-based balance == the old hand-rolled one (Generator/Load/Link/Store), incl. weights != 1."""
    n = _sector_network(weight)
    got = _as_maps(build_energy_balance(n))
    ref = _legacy_energy_balance(n)
    for carrier, sides in ref.items():
        for side in ("sources", "sinks"):
            expected = {k: round(v, 1) for k, v in sides[side].items() if v > 1e-9}
            actual = got.get(carrier, {}).get(side, {})
            assert set(actual) == set(expected), (carrier, side, actual, expected)
            for label, value in expected.items():
                assert actual[label] == pytest.approx(value, abs=0.11), (carrier, side, label)


def test_energy_balance_accounts_process_ports_analytically() -> None:
    """A CHP *Process* (rate0=-1, rate1=0.4, rate2=0.3) shows up as sink on gas and source on elec + heat."""
    n = _sector_network(with_process=True)
    p = n.c.processes.dynamic.p["chp"]
    chp_mwh = float(p.sum())
    assert chp_mwh > 1.0, "the cheap-gas CHP must run for this test to mean anything"
    got = _as_maps(build_energy_balance(n))
    assert got["gas"]["sinks"]["chp"] == pytest.approx(chp_mwh, abs=0.11)
    assert got["electricity"]["sources"]["chp"] == pytest.approx(0.4 * chp_mwh, abs=0.11)
    assert got["heat"]["sources"]["chp"] == pytest.approx(0.3 * chp_mwh, abs=0.11)


def _two_bus_solar_network() -> pypsa.Network:
    """Congested two-bus system with curtailed solar and snapshot weights of 2 h."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=6, freq="h"))
    n.snapshot_weightings.loc[:, :] = 2.0
    n.add("Carrier", ["gas", "solar"])
    n.add("Bus", "a")
    n.add("Bus", "b")
    n.add("Line", "ab", bus0="a", bus1="b", x=0.1, s_nom=40)
    n.add("Generator", "sol", bus="a", carrier="solar", p_nom=100, marginal_cost=0,
          p_max_pu=[0, 0.3, 0.9, 1.0, 0.8, 0.2])
    n.add("Generator", "gas", bus="b", carrier="gas", p_nom=200, marginal_cost=50)
    n.add("Load", "la", bus="a", p_set=[10, 20, 30, 20, 10, 5])
    n.add("Load", "lb", bus="b", p_set=[80, 60, 70, 90, 50, 40])
    assert n.optimize(solver_name="highs", log_to_console=False, include_objective_constant=False) == ("ok", "optimal")
    return n


def test_curtailment_series_total_matches_statistics_for_renewables() -> None:
    """Hand-rolled curtailment (time-varying p_max_pu units only) == n.statistics.curtailment for solar.

    Deliberately not moved onto statistics: PyPSA also books part-loaded thermal units
    (static p_max_pu) as 'curtailment', which is not what the chart means.
    """
    from backend.pypsa.results.dispatch import build_curtailment_series

    n = _two_bus_solar_network()
    series = build_curtailment_series(n, n.generators_t.p)
    hand_mwh = sum(sum(r["values"].values()) for r in series) * 2.0
    native = n.statistics.curtailment(groupby="carrier")
    solar = float(native.xs("solar", level="carrier").iloc[0])
    assert hand_mwh > 1.0
    assert hand_mwh == pytest.approx(solar, rel=1e-9)


def test_generator_revenue_matches_statistics_revenue() -> None:
    """build_generator_economics revenue == n.statistics.revenue per Generator (single period)."""
    from backend.pypsa.results.market import build_generator_economics

    n = _two_bus_solar_network()
    eco = {g["name"]: g["revenue"] for g in build_generator_economics(n)["generators"]}
    native = n.statistics.revenue(groupby="name")
    for name, revenue in eco.items():
        assert revenue == pytest.approx(float(native.loc[("Generator", name)]), abs=1.0)


def test_process_flows_through_run_payload_analytics() -> None:
    """P29: a Process shows in the carrier mix, expansion table and energy balance of run_pypsa."""
    from backend.pypsa.results import run_pypsa

    snaps = [f"2030-01-01T0{h}:00:00" for h in range(4)]
    model = {
        "buses": [{"name": "gas", "carrier": "gas"}, {"name": "elec", "carrier": "electricity"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.2}, {"name": "electricity"}, {"name": "CCGTp"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "elec", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": 100} for s in snaps],
        "generators": [{"name": "well", "bus": "gas", "carrier": "gas", "p_nom": 1000, "marginal_cost": 5}],
        "processes": [{"name": "proc", "bus0": "gas", "bus1": "elec", "rate0": -1.0, "rate1": 0.5,
                       "carrier": "CCGTp", "p_nom_extendable": True, "capital_cost": 1000}],
    }
    res = run_pypsa(model, {"discountRate": 0.0}, {})
    mix = {m["label"]: m["value"] for m in res["carrierMix"]}
    assert mix["CCGTp"] == pytest.approx(400.0, abs=1e-3)
    row = next(e for e in res["expansionResults"] if e["name"] == "proc")
    assert row["component"] == "Process" and row["p_nom_opt_mw"] == pytest.approx(200.0, abs=0.11)
    # An extendable Process is annuitised like a Link (it was charged its overnight cost before): rate 0 over the 20 a fallback lifetime
    # is 1/20 of the overnight 1000 per MW, on the annual basis.
    assert row["capex_annual"] == pytest.approx(200.0 * 1000 / 20.0, rel=1e-6)
    bal = {c["carrier"]: c for c in res["energyBalance"]["carriers"]}
    assert bal["gas"]["sinks"][0]["energyMWh"] == pytest.approx(800.0, abs=0.11)
