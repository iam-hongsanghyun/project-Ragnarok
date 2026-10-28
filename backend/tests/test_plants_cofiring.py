"""Gas + H2 co-firing: vol / energy conversion, the blend-share constraint (hourly and period), simple-mode factors, avoided CO2.

Algorithm (hand checks):
    s = x L_H / (x L_H + (1-x) L_G);  simple mc = ((1-s) c_g + s c_h)/eta + VOM;  carrier co2 = (1-s) e_g;
    hourly cap: h_t <= s_max (h_t + g_t) for every t; period cap: sum w h <= s_max sum w (h + g);
    avoided = e_g * sum w h  (same fuel energy burnt as 100 % gas).
ASCII: see the formulas in backend/pypsa/network/cofiring.py and backend/app/plants/thermal.py.
"""
from __future__ import annotations

import numpy as np
import pytest
from fastapi import HTTPException
from numpy.testing import assert_allclose

from backend.app.plants import results as pr
from backend.app.plants import technologies as tech
from backend.pypsa.network import cofiring as cf
from backend.pypsa.results import run_pypsa

from ._plants_fixtures import SCENARIO, add_plant, bundle, grid, series, with_h2_window

RTOL = 1e-9
ATOL = 1e-7
K = tech.constants()
LH, LG = K["h2_lhv_mj_per_nm3"], K["ch4_lhv_mj_per_nm3"]
S_MAX = cf.vol_to_energy_share(0.3, LH, LG)


def test_30_vol_percent_is_about_11_4_percent_of_the_energy() -> None:
    s = cf.vol_to_energy_share(0.30, LH, LG)
    assert_allclose(s, 0.30 * 10.78 / (0.30 * 10.78 + 0.70 * 35.8), rtol=1e-12)       # hand calculation
    assert 0.1135 < s < 0.1150 and round(s * 100, 1) == 11.4
    assert_allclose(cf.vol_to_energy_share(0.30, 10.8, 35.8), 3.24 / (3.24 + 25.06), rtol=1e-12)   # the brief's rounded constants
    assert_allclose(cf.energy_to_vol_share(s, LH, LG), 0.30, rtol=1e-12)               # inverse
    for x in (0.0, 0.05, 0.5, 1.0):
        assert_allclose(cf.energy_to_vol_share(cf.vol_to_energy_share(x, LH, LG), LH, LG), x, rtol=1e-12, atol=1e-15)
    assert cf.vol_to_energy_share(0.0, LH, LG) == 0.0 and cf.vol_to_energy_share(1.0, LH, LG) == 1.0
    with pytest.raises(ValueError):
        cf.vol_to_energy_share(1.2, LH, LG)


def test_constants_carry_a_source_and_a_verified_flag() -> None:
    cat = tech.catalogue()
    for key in ("h2_lhv_mj_per_nm3", "ch4_lhv_mj_per_nm3"):
        assert cat["constants"][key]["source"] and cat["constants"][key]["verified"] in ("file", "derived", "literature", "assumption")
    for tname in ("ccgt", "ocgt"):
        for name, p in cat["technologies"][tname]["parameters"].items():
            assert p["source"]["document"] and p["verified"] in ("file", "derived", "literature", "assumption"), (tname, name)
    assert cat["technologies"]["ccgt"]["parameters"]["efficiency"]["verified"] == "file"
    assert cat["technologies"]["ccgt"]["parameters"]["min_up_time"]["verified"] == "assumption"


def test_simple_mode_cost_and_emission_factors_against_a_hand_calculation() -> None:
    model, built = add_plant(grid(), "cofiring_simple", {"turbine": "ccgt", "pNom": 150, "h2Share": 0.30, "h2ShareUnit": "vol",
                                                           "gasPrice": 30.0, "h2Price": 100.0})
    P = tech.parameter_defaults()
    eta, vom, ef = P["ccgt"]["efficiency"], P["ccgt"]["vom"], P["fuels"]["gas_co2"]
    s = 0.30 * LH / (0.30 * LH + 0.70 * LG)
    gen = model["generators"][0]
    assert_allclose(gen["marginal_cost"], ((1 - s) * 30.0 + s * 100.0) / eta + vom, rtol=1e-7)       # EUR/MWh_el
    carrier = next(c for c in model["carriers"] if c["name"] == "cofiring_simple blend")
    assert_allclose(carrier["co2_emissions"], (1 - s) * ef, rtol=1e-7)                               # tCO2/MWh_th
    assert gen["carrier"] == "cofiring_simple blend" and gen["efficiency"] == pytest.approx(eta)
    # hand numbers: s = 0.11431; mc = ((0.88569 x 30 + 0.11431 x 100)/0.58) + 5.6104
    assert_allclose(gen["marginal_cost"], (26.5707 + 11.431) / 0.58 + 5.6104, rtol=1e-4)
    # in a solve the app reports tCO2 = E_el * co2 / eta
    res = run_pypsa(model, SCENARIO, {})
    e_el = 100.0 * 24
    byg = {r["name"]: r for r in res["emissionsBreakdown"]["byGenerator"]}
    assert_allclose(byg["cofiring_simple"]["emissions_tco2"], e_el / eta * (1 - s) * ef, rtol=1e-6, atol=0.006)   # payload rounds to 0.01 t
    out = pr.plant_results(bundle(model, res))["plants"][0]
    assert_allclose(out["emissions"]["actualT"], byg["cofiring_simple"]["emissions_tco2"], rtol=1e-6, atol=0.006)
    assert_allclose(out["emissions"]["avoidedT"], s * e_el / eta * ef, rtol=1e-9)                    # avoided = e_g * H2 energy
    assert_allclose(out["fuel"]["h2EnergyShare"], s, rtol=1e-9)
    assert_allclose(out["fuel"]["h2VolShare"], 0.30, rtol=1e-9)


def _network_case(spec: dict, hours: int = 24, h2_hours: int = 12):
    base = with_h2_window(grid(hours), available_hours=h2_hours, price=10.0)
    return add_plant(base, "cofiring_network", {"turbine": "ccgt", "pNom": 150, "h2Bus": "h2", "gasPrice": 30.0, **spec})


def _flows(res: dict, built: dict):
    f = built["registry"]["feeders"]
    return np.array(series(res, "links-p0", f["h2"])), np.array(series(res, "links-p0", f["gas"]))


def test_unconstrained_the_cheaper_h2_takes_the_whole_fuel() -> None:
    model, built = _network_case({})
    res = run_pypsa(model, SCENARIO, {})
    h, g = _flows(res, built)
    assert_allclose(h[:12], 100.0 / 0.58, rtol=1e-6)               # 100 MW_el / eta, all H2 while it is available (10 < 30 EUR/MWh)
    assert_allclose(g[:12], 0.0, atol=1e-6)
    assert_allclose(g[12:], 100.0 / 0.58, rtol=1e-6)


def test_hourly_cap_binds_exactly_in_every_snapshot() -> None:
    model, built = _network_case({"blendMax": 0.30, "blendUnit": "vol", "blendScope": "hourly"})
    res = run_pypsa(model, SCENARIO, {})                            # no cofiringConfig: the plant's stored limits apply
    h, g = _flows(res, built)
    fuel = h + g
    assert_allclose(fuel, 100.0 / 0.58, rtol=1e-6)                  # the load is served every hour
    share = np.divide(h, fuel, out=np.zeros_like(h), where=fuel > 0)
    assert_allclose(share[:12], S_MAX, rtol=1e-6, atol=1e-9)        # H2 available: the cap is binding exactly, hour by hour
    assert_allclose(share[12:], 0.0, atol=1e-9)                     # no H2 later
    assert (share <= S_MAX + 1e-9).all()
    out = pr.plant_results(bundle(model, res))["plants"][0]
    assert_allclose(out["cofiring"]["maxHourlyEnergyShare"], S_MAX, rtol=1e-6)
    assert_allclose(out["cofiring"]["maxHourlyVolShare"], 0.30, rtol=1e-6)


def test_period_cap_is_looser_than_the_hourly_cap_and_binds_on_the_total() -> None:
    h_model, h_built = _network_case({"blendMax": 0.30, "blendUnit": "vol", "blendScope": "hourly"})
    p_model, p_built = _network_case({"blendMax": 0.30, "blendUnit": "vol", "blendScope": "period"})
    h_res, p_res = run_pypsa(h_model, SCENARIO, {}), run_pypsa(p_model, SCENARIO, {})
    hh, hg = _flows(h_res, h_built)
    ph, pg = _flows(p_res, p_built)
    assert ph.sum() > hh.sum() * 1.5                                # the same limit on a weighted total lets H2 pile into its 12 hours
    assert_allclose(ph.sum() / (ph + pg).sum(), S_MAX, rtol=1e-6)   # and the total share binds exactly
    assert ((ph / (ph + pg)) > S_MAX + 1e-3).any()                  # so single hours exceed the hourly cap
    obj_h = sum(r["value"] for r in h_res["costBreakdown"])
    obj_p = sum(r["value"] for r in p_res["costBreakdown"])
    assert obj_p < obj_h                                            # looser constraint, cheaper system


def test_explicit_run_option_overrides_and_min_share_is_enforced() -> None:
    model, built = _network_case({"blendMax": 0.30, "blendUnit": "vol"})
    off = run_pypsa(model, SCENARIO, {"cofiringConfig": {"enabled": False}})
    h, g = _flows(off, built)
    assert_allclose(h[:12], 100.0 / 0.58, rtol=1e-6)                # explicit {enabled: false} beats the stored limit
    # a MINIMUM in the hours with no H2 available is infeasible; limit the min to the plant and the cheap-H2 hours: use energy basis 5 %
    base = grid()
    base = with_h2_window(base, available_hours=24, price=500.0)    # H2 dearer than gas: the minimum is what forces it in
    m2, b2 = add_plant(base, "cofiring_network", {"turbine": "ccgt", "pNom": 150, "h2Bus": "h2", "gasPrice": 30.0})
    res = run_pypsa(m2, SCENARIO, {"cofiringConfig": {"minShare": 0.05, "unit": "energy", "scope": "hourly"}})
    h2, g2 = _flows(res, b2)
    assert_allclose(h2 / (h2 + g2), 0.05, rtol=1e-6)                # dearer H2 is used exactly at the floor, every hour


def test_option_errors_are_400_before_the_solve() -> None:
    model, _ = _network_case({})
    with pytest.raises(HTTPException) as e:
        run_pypsa(model, SCENARIO, {"cofiringConfig": {"enabled": True}})          # no min / max
    assert e.value.status_code == 400 and "minShare" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run_pypsa(grid(), SCENARIO, {"cofiringConfig": {"maxShare": 0.1}})        # no fuel-network plant
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        run_pypsa(model, SCENARIO, {"cofiringConfig": {"minShare": 0.5, "maxShare": 0.2}})
    assert e.value.status_code == 400


def test_emissions_avoided_identity_and_agreement_with_the_app_total() -> None:
    model, built = _network_case({"blendMax": 0.30, "blendUnit": "vol", "blendScope": "period"})
    res = run_pypsa(model, SCENARIO, {})
    plant = pr.plant_results(bundle(model, res))["plants"][0]
    h, g = _flows(res, built)
    ef = tech.parameter_defaults()["fuels"]["gas_co2"]
    e = plant["emissions"]
    assert_allclose(e["gasOnlyBaselineT"] - e["actualT"], e["avoidedT"], rtol=1e-12)                     # identity
    assert_allclose(e["avoidedT"], ef * h.sum(), rtol=1e-9)                                              # = e_g x H2 energy (w = 1 h)
    assert_allclose(e["gasOnlyBaselineT"], ef * (h.sum() + g.sum()), rtol=1e-9)
    byg = {r["name"]: r for r in res["emissionsBreakdown"]["byGenerator"]}
    assert_allclose(e["actualT"], byg[f"{built['plantId']}_gas_supply"]["emissions_tco2"], rtol=1e-6, atol=0.006)   # the app books the gas supplier
    assert plant["capacityFactor"] > 0.6 and plant["generationMwh"] == pytest.approx(2400.0, rel=1e-6)
    assert_allclose(plant["fuel"]["h2EnergyShare"], S_MAX, rtol=1e-6)


def test_derate_is_off_by_default_and_flagged_as_an_assumption_when_on() -> None:
    _, b0 = _network_case({"blendMax": 0.3, "blendUnit": "vol"})
    assert b0["registry"]["derate"]["applied"] is False
    assert not any("derate" in w.lower() for w in b0["warnings"])
    model, on = _network_case({"blendMax": 0.3, "blendUnit": "vol", "params": {"fuels.h2_derate_efficiency_per_share": 0.1}})
    d = on["registry"]["derate"]
    assert d["applied"] is True and "assumption" in d["basis"]
    eta = tech.parameter_defaults()["ccgt"]["efficiency"]
    assert_allclose(on["registry"]["efficiency"], eta - 0.1 * S_MAX, rtol=1e-9)
    assert any("assumption" in w for w in on["warnings"])


def test_a_shared_gas_supplier_is_not_booked_on_the_plant_that_owns_the_row() -> None:
    """Plant `a` (idle CCGT) created the gas bus and supplier; plant `b` (co-firing) burns the gas. Fuel is valued at the bus price per plant."""
    base = with_h2_window(grid(), price=10.0)
    model, a = add_plant(base, "ccgt", {"plantId": "a", "pNom": 20, "gasPrice": 30.0, "efficiency": 0.3})
    model, b = add_plant(model, "cofiring_network", {"plantId": "b", "pNom": 150, "h2Bus": "h2", "blendMax": 0.3, "blendUnit": "vol"})
    assert b["registry"]["gasBus"] == "a_bus_gas"                                    # b reuses a's gas bus and supplier
    res = run_pypsa(model, SCENARIO, {})
    plants = {p["plantId"]: p for p in pr.plant_results(bundle(model, res))["plants"]}
    h, g = _flows(res, b)
    assert_allclose(plants["a"]["fuelCost"], 0.0, atol=1e-6)                           # a burns nothing
    assert any(c["sharedSupply"] for c in plants["a"]["components"])
    price_gas = 30.0                                                                     # a's gasPrice sets the supplier
    assert_allclose(plants["b"]["fuelCost"], g.sum() * price_gas + h.sum() * 10.0, rtol=1e-6)
    total_fuel = sum(p["fuelCost"] for p in plants.values())
    assert_allclose(total_fuel, g.sum() * price_gas + h.sum() * 10.0, rtol=1e-6)       # = what the suppliers were paid


def test_fuel_is_valued_at_the_supplier_cost_when_a_committable_unit_makes_the_run_a_milp() -> None:
    """A committable plant makes the solve a MILP: no duals, every nodal price reads 0. The fuel cost must not collapse to 0."""
    base = with_h2_window(grid(), price=10.0)
    model, a = add_plant(base, "ccgt", {"plantId": "u", "pNom": 200, "committable": True, "gasPrice": 30.0, "efficiency": 0.3})
    model, b = add_plant(model, "cofiring_network", {"plantId": "b", "pNom": 150, "h2Bus": "h2", "blendMax": 0.3, "blendUnit": "vol"})
    res = run_pypsa(model, SCENARIO, {})
    prices = np.array([[v for k, v in r.items() if k != "snapshot"] for r in res["outputs"]["series"]["buses-marginal_price"]])
    assert np.abs(prices).max() == 0.0                                                  # no duals
    plant = {p["plantId"]: p for p in pr.plant_results(bundle(model, res))["plants"]}["b"]
    h, g = _flows(res, b)
    assert_allclose(plant["fuelCost"], g.sum() * 30.0 + h.sum() * 10.0, rtol=1e-6)
    assert "supplier" in plant["fuelCostBasis"]
