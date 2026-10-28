"""CCGT / OCGT plants: technology file values, unit-commitment wiring, the extendable + committable warning, a solved UC case."""
from __future__ import annotations

import math

import pytest
from numpy.testing import assert_allclose

from backend.app.plants import catalog
from backend.app.plants import results as pr
from backend.app.plants import technologies as tech
from backend.pypsa.network import build_network
from backend.pypsa.results import run_pypsa

from ._plants_fixtures import SCENARIO, add_plant, bundle, grid, series

P = tech.parameter_defaults()


def test_ccgt_row_from_the_data_file() -> None:
    model, built = add_plant(grid(), "ccgt", {"pNom": 400})
    link = next(r for r in model["links"] if r["name"] == "ccgt")
    eta = P["ccgt"]["efficiency"]
    assert link["bus0"] == "ccgt_bus_gas" and link["bus1"] == "grid" and link["efficiency"] == pytest.approx(eta)
    assert_allclose(link["p_nom"], 400 / eta, rtol=1e-7)                                          # p_nom is MW_th at bus0
    assert_allclose(link["marginal_cost"], P["ccgt"]["vom"] * eta, rtol=1e-6)                      # EUR per MWh_th
    # PyPSA's own split: overnight cost per MW_th and FOM per MW_th per year; no folded / annualised capital_cost, no discount_rate
    assert_allclose(link["overnight_cost"], P["ccgt"]["capex"] * 1000 * eta, rtol=1e-7)
    assert_allclose(link["fom_cost"], link["overnight_cost"] * P["ccgt"]["fom"] / 100, rtol=1e-6)
    assert link["lifetime"] == 25 and "capital_cost" not in link and link["discount_rate"] == 0.05
    assert "committable" not in link and "p_min_pu" not in link          # not committable: no always-on floor, no start-up fields
    gas_c = next(c for c in model["carriers"] if c["name"] == "gas")
    assert gas_c["co2_emissions"] == pytest.approx(0.198)
    sup = next(g for g in model["generators"] if g["name"] == "ccgt_gas_supply")
    assert sup["marginal_cost"] == pytest.approx(P["fuels"]["gas_price"])
    assert all(r.get("plant") == "ccgt" for rows in built["fragment"]["sheets"].values() for r in rows)


def test_committable_wires_minimum_load_start_up_cost_and_min_times() -> None:
    _, built = add_plant(grid(), "ccgt", {"pNom": 400, "committable": True})
    link = built["fragment"]["sheets"]["links"][0]
    assert link["committable"] is True
    assert link["p_min_pu"] == pytest.approx(0.40)                                                  # DEA sheet 05
    assert_allclose(link["start_up_cost"], P["ccgt"]["start_up_cost"] * 400, rtol=1e-9)             # EUR per start = EUR/MW x MW_el
    assert (link["min_up_time"], link["min_down_time"]) == (4, 4)                                    # 4 h at 1 h snapshots
    assert "ramp_limit_up" not in link                                                               # 15 %/min = 900 %/h: not binding
    # OCGT: 20 % minimum load, DEA start-up cost 43 EUR2015 x 1.3358
    _, o = add_plant(grid(), "ocgt", {"pNom": 100, "committable": True})
    ol = o["fragment"]["sheets"]["links"][0]
    assert ol["p_min_pu"] == pytest.approx(0.20) and ol["start_up_cost"] == pytest.approx(43 * 1108.7166 / 830 * 100, rel=1e-6)
    # a coarser time step turns the ramp into a limit and the hours into fewer snapshots
    coarse = grid()
    coarse["snapshots"] = [{"snapshot": f"2030-01-01T{h:02d}:00:00"} for h in range(0, 24, 3)]
    _, c = add_plant(coarse, "ccgt", {"pNom": 400, "committable": True, "params": {"ccgt.ramp_rate": 0.2}})
    cl = c["fragment"]["sheets"]["links"][0]
    assert cl["min_up_time"] == math.ceil(4 / 3) and cl["ramp_limit_up"] == pytest.approx(0.2 * 60 * 3 / 100)


def test_committable_and_extendable_is_refused_with_a_warning() -> None:
    _, built = add_plant(grid(), "ccgt", {"extendable": True, "committable": True})
    link = built["fragment"]["sheets"]["links"][0]
    assert "committable" not in link and link["p_nom_extendable"] is True
    assert any("mutually exclusive" in w for w in built["warnings"])


def test_second_plant_reuses_the_gas_bus_and_supplier() -> None:
    model, a = add_plant(grid(), "ccgt", {"pNom": 100})
    model, b = add_plant(model, "ocgt", {"pNom": 50})
    assert [x["name"] for x in model["buses"]].count("ccgt_bus_gas") == 1
    assert "buses" not in b["fragment"]["sheets"] and "generators" not in b["fragment"]["sheets"]
    assert b["registry"]["gasBus"] == "ccgt_bus_gas"


def test_the_extendable_plant_is_charged_its_annuitised_capex_in_the_solve() -> None:
    model, built = add_plant(grid(hours=24), "ccgt", {"extendable": True})
    net, _ = build_network(model, SCENARIO, {})
    a = 0.05 / (1 - 1.05 ** -25)
    overnight = P["ccgt"]["capex"] * 1000 * P["ccgt"]["efficiency"]
    # PyPSA's effective cost (what the LP is charged): overnight x annuity(run rate, lifetime) x window years; FOM is not in it
    assert_allclose(float(net.components["links"].capital_cost["ccgt"]), overnight * a * 24 / 8760, rtol=1e-9)
    res = run_pypsa(model, SCENARIO, {})
    out = pr.plant_results(bundle(model, res))["plants"][0]
    assert_allclose(out["capacityMwEl"], 100.0, rtol=1e-6)                                         # sized to the 100 MW load
    # fixed charge = capacity x PyPSA's effective capital cost (read back, window-scaled) + fom_cost x capacity x window years
    cap_th = 100.0 / P["ccgt"]["efficiency"]
    years = 24 / 8760
    assert_allclose(out["fixedCost"], cap_th * (overnight * a * years + overnight * P["ccgt"]["fom"] / 100 * years), rtol=1e-6)


def test_unit_commitment_case_starts_once_and_respects_the_minimum_load() -> None:
    """Demand 0 / 300 MW / 0: the CCGT (400 MW, 40 % minimum load) starts once and never runs below 160 MW_el."""
    base = grid(hours=24)
    base["loads"] = [{"name": "demand", "bus": "grid"}]
    base["loads-p_set"] = [{"snapshot": r["snapshot"], "demand": 300.0 if 6 <= i < 18 else 0.0} for i, r in enumerate(base["snapshots"])]
    base["generators"] = [{"name": "sink", "bus": "grid", "carrier": "AC", "p_nom": 1000, "p_min_pu": -1, "p_max_pu": 0, "marginal_cost": 0}]
    model, built = add_plant(base, "ccgt", {"pNom": 400, "committable": True})
    res = run_pypsa(model, SCENARIO, {})
    el = [-v for v in series(res, "links-p1", "ccgt")]
    on = [v for v in el if v > 1e-6]
    assert len(on) >= 12 and min(on) >= 0.40 * 400 - 1e-6
    out = pr.plant_results(bundle(model, res))["plants"][0]
    assert out["starts"] == 1 and "committable" in out["startsBasis"]
    commit = res["commitment"]["generators"][0]
    assert commit["name"] == "ccgt" and commit["starts"] == 1 and commit["startUpCost"] == pytest.approx(60 * 400)
    assert_allclose(out["generationMwh"], 300.0 * 12, rtol=1e-6)


def test_bess_extendable_cost_restates_the_inverter_at_the_storage_lifetime() -> None:
    model, built = add_plant(grid(), "bess", {"extendable": True})
    su = model["storage_units"][0]
    from backend.pypsa.utils.annuity import annuity_factor

    B = P["bess"]
    a_i, a_s = annuity_factor(0.05, B["inverter_lifetime"]), annuity_factor(0.05, B["storage_lifetime"])
    # one lifetime per row (the storage's): the inverter's overnight cost is restated at that lifetime, K_inv a(r, 10) / a(r, 25)
    assert_allclose(su["overnight_cost"], B["inverter_capex"] * 1000 * a_i / a_s + B["storage_capex"] * 1000 * B["max_hours"], rtol=1e-9)
    assert_allclose(su["fom_cost"], B["inverter_capex"] * 1000 * B["inverter_fom"] / 100, rtol=1e-9)
    assert su["lifetime"] == 25 and "capital_cost" not in su
    assert su["max_hours"] == 4.0 and su["efficiency_store"] == pytest.approx(0.96) and su["cyclic_state_of_charge"] is True


def test_unknown_parameter_override_and_bad_inputs_are_refused() -> None:
    with pytest.raises(catalog.PlantError, match="Unknown plant parameter"):
        catalog.build_plant("ccgt", {"params": {"ccgt.nope": 1}}, grid())
    with pytest.raises(catalog.PlantError, match="not found"):
        catalog.build_plant("ccgt", {"bus": "nowhere"}, grid())
    with pytest.raises(catalog.PlantError, match="pNom"):
        catalog.build_plant("ccgt", {"pNom": 0}, grid())
    with pytest.raises(catalog.PlantError, match="efficiency"):
        catalog.build_plant("ccgt", {"efficiency": 1.4}, grid())
