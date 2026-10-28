"""P2X results: LCOH against a hand calculation, LCOA / LCOM / e-fuel identities, PPA mode, period slice."""
from __future__ import annotations

import pytest
from numpy.testing import assert_allclose

from backend.app.p2x import chains
from backend.app.p2x import results as pr
from backend.pypsa.results import run_pypsa
from pypsa.costs import annuity as annuity_factor

from ._p2x_fixtures import H2_SPEC, SCENARIO, night_gas_network, stamps, with_chain

R = 0.05


def _hand_case():
    """24 h, 10 MW fixed electrolyser (eff 0.7, 1000 EUR/kW, FOM 4 %, 20 a, no stack/water), 7 MW_LHV H2 load, gas at 40 EUR/MWh."""
    snaps = stamps("2030-01-01", 24)
    base = {"buses": [{"name": "grid", "carrier": "AC"}], "carriers": [{"name": "AC"}, {"name": "gas", "co2_emissions": 0.2}],
            "snapshots": [{"snapshot": s} for s in snaps],
            "generators": [{"name": "gas", "bus": "grid", "carrier": "gas", "p_nom": 300, "marginal_cost": 40}]}
    spec = {"chainId": "p2x", "products": ["H2"], "discountRate": R, "storage": {"type": "none"},
            "electrolyser": {"tech": "aec", "extendable": False, "pNom": 10, "applyAvailability": False},
            "offtake": {"H2": {"mode": "flat", "mw": 7}},
            "params": {"electrolyser_aec.specific_energy": 33.33 / 0.7, "electrolyser_aec.capex": 1000, "electrolyser_aec.fom": 4,
                       "electrolyser_aec.lifetime": 20, "electrolyser_aec.stack_capex": 0, "electrolyser_aec.water_use": 0}}
    model, _ = with_chain(base, spec)
    return model


def _bundle(model, result, options=None):
    return {"model": model, "result": result, "options": options or {}, "scenario": {"discountRate": R}}


def test_lcoh_matches_the_hand_calculation() -> None:
    model = _hand_case()
    res = run_pypsa(model, SCENARIO, {})
    out = pr.p2x_results(_bundle(model, res))
    # hand: E_el = 10 MW x 24 h = 240 MWh at 40 EUR/MWh; H2 = 7 MW x 24 h = 168 MWh_LHV = 168 000 / 33.33 kg
    af = annuity_factor(R, 20)
    capex = 10 * 1e6 * af * 24 / 8760
    fom = 10 * 1e6 * 0.04 * 24 / 8760
    elec = 240 * 40.0
    kg = 168 * 1000 / 33.33
    assert_allclose(out["lcoh"]["h2Kg"], kg, rtol=1e-9)
    pc = out["lcoh"]["perComponent"]
    assert_allclose(pc["Electricity (electrolyser)"], elec / kg, rtol=1e-9)
    assert_allclose(pc["Electrolyser capex"], capex / kg, rtol=1e-9)
    assert_allclose(pc["Electrolyser FOM"], fom / kg, rtol=1e-9)
    assert_allclose(out["lcoh"]["perKg"], (elec + capex + fom) / kg, rtol=1e-9)
    assert_allclose(out["lcoh"]["perKg"], 2.558140481, rtol=1e-8)
    # operation
    e = out["electrolyser"]
    assert_allclose(e["capacityFactor"], 1.0, rtol=1e-9)
    assert_allclose(e["fullLoadHours"], 24.0, rtol=1e-9)
    assert_allclose(e["fullLoadHoursPerYear"], 8760.0, rtol=1e-9)
    assert_allclose(e["h2Tonnes"], kg / 1000, rtol=1e-9)
    # the waterfall's last cumulative step is the LCOH
    assert_allclose(out["lcoh"]["waterfall"]["steps"][-1]["cumulative"], out["lcoh"]["perKg"], rtol=1e-12)


def test_lcoh_from_components_is_a_plain_sum_over_kilograms() -> None:
    out = pr.lcoh_from_components({"a": 100.0, "b": 50.0}, h2_mwh_lhv=33.33, h2_lhv_kwh_per_kg=33.33)   # 1000 kg
    assert_allclose(out["kg"], 1000.0, rtol=1e-12)
    assert_allclose(out["lcoh"], 0.15, rtol=1e-12)


def test_wear_and_water_enter_the_lcoh() -> None:
    base = night_gas_network(hours=24)
    spec = {**H2_SPEC, "storage": {"type": "none"}, "electrolyser": {"tech": "aec", "extendable": False, "pNom": 20, "applyAvailability": False}}
    model, built = with_chain(base, spec)
    res = run_pypsa(model, SCENARIO, {})
    out = pr.p2x_results(_bundle(model, res))
    reg = built["registry"]["electrolyser"]
    e_el = out["electrolyser"]["electricityMwh"]
    kg = out["lcoh"]["h2Kg"]
    assert_allclose(out["lcoh"]["perComponent"]["Stack replacement"], e_el * reg["stackWearEurPerMwhEl"] / kg, rtol=1e-9)
    assert_allclose(out["lcoh"]["perComponent"]["Water"], e_el * reg["waterM3PerMwhEl"] * reg["waterCostEurPerM3"] / kg, rtol=1e-9)
    assert 0 < out["lcoh"]["perComponent"]["Water"] < 0.05          # water is immaterial next to the total


def test_ppa_electricity_cost_uses_the_designated_generators() -> None:
    model, _ = with_chain(night_gas_network(hours=24), H2_SPEC)          # tank carries the wind hours over the night
    opts = {"rfnboConfig": {"enabled": True, "temporal": "hourly"}}
    res = run_pypsa(model, SCENARIO, opts)
    nodal = pr.p2x_results(_bundle(model, res, opts), electricity_cost="nodal")
    ppa = pr.p2x_results(_bundle(model, res, opts), electricity_cost="ppa")
    # hourly matching with a flat H2 load: the electrolyser runs only on wind (30 EUR/MWh marginal, no capex)
    assert_allclose(ppa["ppa"]["pricePerMwh"], 30.0, rtol=1e-9)
    e = ppa["electrolyser"]["electricityMwh"]
    assert_allclose(ppa["lcoh"]["costs"]["Electricity (electrolyser)"], 30.0 * e, rtol=1e-6)
    assert ppa["electricityCost"] == "ppa" and nodal["electricityCost"] == "nodal"
    assert ppa["rfnbo"]["compliance"]["hourly"]["compliantShareOfOperating"] == 1.0


def test_without_matching_the_shortfall_is_reported() -> None:
    model, _ = with_chain(night_gas_network(), H2_SPEC)
    res = run_pypsa(model, SCENARIO, {})
    out = pr.p2x_results(_bundle(model, res))
    c = out["rfnbo"]["compliance"]
    assert out["rfnbo"]["matchingEnabled"] is False
    assert c["hourly"]["unmatchedMwh"] > 100.0 and c["hourly"]["compliantShareOfOperating"] < 0.5
    assert c["hourly"]["unmatchedMwh"] >= c["monthly"]["unmatchedMwh"]          # monthly is looser
    assert out["rfnbo"]["checks"]["additionality"][0]["status"] == "pass"
    assert out["rfnbo"]["checks"]["geographic"][0]["status"] == "pass"


def test_derivative_products_cost_identities() -> None:
    base = night_gas_network(hours=24)
    spec = {"chainId": "x", "products": ["H2", "NH3", "MeOH", "eFuel"], "storage": {"type": "none"},
            "productStorage": {p: {"enabled": False} for p in chains.PRODUCTS},
            "offtake": {p: {"mode": "flat", "tonnesPerYear": 1000} for p in chains.ALL_PRODUCTS}}
    model, _ = with_chain(base, spec)
    res = run_pypsa(model, SCENARIO, {})
    out = pr.p2x_results(_bundle(model, res))
    lhv = {"NH3": 5.17, "MeOH": 5.54, "eFuel": 11.94}
    for p, e in out["products"].items():
        assert_allclose(e["producedTonnes"], 1000.0 * 24 / 8760, rtol=1e-6)               # the offtake over 24 h
        assert_allclose(e["totalCost"], sum(e["components"].values()), rtol=1e-12)
        assert_allclose(e["costPerTonne"] * e["producedTonnes"], e["totalCost"], rtol=1e-12)
        assert_allclose(e["costPerMwh"] * e["producedMwh"], e["totalCost"], rtol=1e-12)
        assert_allclose(e["costPerTonne"], e["costPerMwh"] * lhv[p], rtol=1e-12)
        assert_allclose(e["waterfall"]["steps"][-1]["cumulative"], e["costPerTonne"] if p != "eFuel" else e["costPerMwh"], rtol=1e-9)
    assert_allclose(out["products"]["eFuel"]["costPerLitre"], out["products"]["eFuel"]["costPerMwh"] * 0.8 * 11.94 / 1000, rtol=1e-12)
    # the hydrogen valued in the products is exactly what they took, at the LCOH component costs
    h2_in = sum(e["h2InMwh"] for e in out["products"].values())
    h2_cost_in_products = sum(v for e in out["products"].values() for k, v in e["components"].items() if k.startswith("H2: "))
    h2_kg_in = h2_in * 1000 / 33.33
    assert_allclose(h2_cost_in_products, out["lcoh"]["totalCost"] * h2_kg_in / out["lcoh"]["h2Kg"], rtol=1e-9)


def test_period_slice_and_missing_chain() -> None:
    model = _hand_case()
    res = run_pypsa(model, SCENARIO, {})
    series = {k: [{**r, "period": 2030 if i < 12 else 2040} for i, r in enumerate(rows)] for k, rows in res["outputs"]["series"].items()}
    res["outputs"] = {**res["outputs"], "series": series}
    full = pr.p2x_results(_bundle(model, res))
    half = pr.p2x_results(_bundle(model, res), period=2030)
    assert half["snapshots"] == 12 and half["period"] == 2030
    assert_allclose(half["windowYears"], full["windowYears"] / 2, rtol=1e-12)
    assert_allclose(half["lcoh"]["perKg"], full["lcoh"]["perKg"], rtol=1e-9)         # flat profile: same unit cost
    with pytest.raises(pr.P2XResultsError, match="no P2X chain"):
        pr.p2x_results(_bundle(night_gas_network(), res))
    with pytest.raises(pr.P2XResultsError, match="electricity_cost"):
        pr.p2x_results(_bundle(model, res), electricity_cost="spot")


def test_a_run_at_another_discount_rate_is_flagged() -> None:
    model = _hand_case()
    res = run_pypsa(model, {"discountRate": 0.08, "carbonPrice": 0.0}, {})
    out = pr.p2x_results({"model": model, "result": res, "options": {}, "scenario": {"discountRate": 0.08}})
    assert any("discount rate" in w for w in out["warnings"])
