"""P2X chain templates: structure, mass/energy conversion factors, offtake, fragment merge, and a solved chain."""
from __future__ import annotations

import pytest
from numpy.testing import assert_allclose

from backend.app import fragment_merge
from backend.app.p2x import chains
from backend.app.p2x import technologies as tech
from backend.pypsa.network import rfnbo as rf
from backend.pypsa.results import run_pypsa

from ._p2x_fixtures import H2_SPEC, SCENARIO, night_gas_network, series, with_chain

ALL = {"chainId": "x", "products": ["H2", "NH3", "MeOH", "eFuel"],
       "storage": {"type": "tank", "compressor": True},
       "offtake": {p: {"mode": "flat", "tonnesPerYear": 1000} for p in chains.ALL_PRODUCTS}}


def _by_name(rows):
    return {r["name"]: r for r in rows}


def test_electrolyser_link_efficiency_and_costs_from_the_data_file() -> None:
    built = chains.build_chain({**H2_SPEC, "storage": {"type": "none"}}, night_gas_network())
    ely = _by_name(built["fragment"]["sheets"]["links"])["p2x_electrolyser"]
    P = tech.parameter_defaults()["electrolyser_aec"]
    assert ely["bus0"] == "grid" and ely["efficiency"] == pytest.approx(33.33 / P["specific_energy"], abs=1e-7)
    # PyPSA's own split: overnight cost (EUR/MW_el), FOM (EUR/MW_el/yr), lifetime and the chain's discount rate; no folded capital_cost
    assert_allclose(ely["overnight_cost"], P["capex"] * 1000, rtol=1e-9)
    assert_allclose(ely["fom_cost"], P["capex"] * 1000 * P["fom"] / 100, rtol=1e-9)
    assert ely["lifetime"] == P["lifetime"] and ely["discount_rate"] == 0.05 and "capital_cost" not in ely
    wear = P["stack_capex"] * 1000 / P["stack_lifetime_hours"]
    water = P["water_use"] / 1000 * tech.parameter_defaults()["water"]["supply_cost"]
    assert_allclose(ely["marginal_cost"], wear + water, rtol=1e-6)
    assert "p_max_pu" not in ely or ely["p_max_pu"] == 1.0   # applyAvailability False in H2_SPEC


def test_synthesis_processes_conserve_the_technology_file_ratios() -> None:
    """Process ports: rate0 = -1 on the H2 input, rate1 = 1/h (product), rate2 = -e/h (electricity), rate3 = -m/h (N2 / CO2)."""
    built = chains.build_chain(ALL, night_gas_network())
    procs = _by_name(built["fragment"]["sheets"]["processes"])
    links = _by_name(built["fragment"]["sheets"]["links"])
    assert set(links) == {"x_electrolyser", "x_compressor", "x_h2_discharge"}      # the electrolyser stays a Link
    P = tech.parameter_defaults()
    hb = procs["x_synth_NH3"]            # bus0 = H2 (MWh_H2), bus1 = NH3, bus2 = AC, bus3 = N2
    assert (hb["bus1"].endswith("NH3"), hb["bus2"], hb["bus3"].endswith("n2"), hb["rate0"]) == (True, "grid", True, -1.0)
    h = P["haber_bosch"]["h2_input"]
    assert_allclose(hb["rate1"], 1 / h, rtol=1e-7)
    assert_allclose(hb["rate2"], -P["haber_bosch"]["el_input"] / h, rtol=1e-7)
    assert_allclose(hb["rate3"], -P["haber_bosch"]["n2_input"] / h, rtol=1e-7)
    # t N2 per t NH3 = 0.1597 t/MWh x 5.17 MWh/t = 0.826 (stoichiometry 0.822)
    assert 0.80 < P["haber_bosch"]["n2_input"] * 5.17 < 0.85
    me = procs["x_synth_MeOH"]
    assert_allclose(me["rate3"], -P["methanolisation"]["co2_input"] / P["methanolisation"]["h2_input"], rtol=1e-7)
    # t CO2 per t MeOH ~ 1.37 (CO2 + 3 H2 -> CH3OH + H2O is 1.37)
    assert 1.3 < P["methanolisation"]["co2_input"] * 5.54 < 1.45
    ft = procs["x_synth_eFuel"]
    assert_allclose(ft["rate1"], 1 / P["fischer_tropsch"]["h2_input"], rtol=1e-7) and ft["rate1"] < 1.0
    # every product-leg ratio in (0, 1]
    assert all(0 < procs[k]["rate1"] <= 1.0 for k in ("x_synth_NH3", "x_synth_MeOH", "x_synth_eFuel"))
    assert all(0 < links[k]["efficiency"] <= 1.0 for k in ("x_electrolyser", "x_compressor"))
    # the Link form (componentType "link") carries the same ratios as efficiency / efficiency2 / efficiency3
    as_links = _by_name(chains.build_chain({**ALL, "componentType": "link"}, night_gas_network())["fragment"]["sheets"]["links"])
    assert_allclose(as_links["x_synth_NH3"]["efficiency"], hb["rate1"], rtol=1e-12)
    assert_allclose(as_links["x_synth_NH3"]["efficiency2"], hb["rate2"], rtol=1e-12)
    assert_allclose(as_links["x_synth_NH3"]["efficiency3"], hb["rate3"], rtol=1e-12)


def test_dac_energy_per_tonne_and_asu() -> None:
    built = chains.build_chain(ALL, night_gas_network())
    procs = _by_name(built["fragment"]["sheets"]["processes"])
    d = tech.parameter_defaults()
    el_per_t = d["co2_dac"]["el_input"] + d["co2_dac"]["compression_el"] + d["co2_dac"]["heat_input"] / d["co2_dac"]["heat_cop"]
    assert_allclose(procs["x_co2_supply"]["rate1"], 1 / el_per_t, rtol=1e-7)          # t_CO2 per MWh_el
    assert_allclose(procs["x_asu"]["rate1"], 1 / d["asu"]["specific_energy_el"], rtol=1e-7)   # 4 t_N2 per MWh_el
    point = chains.build_chain({**ALL, "co2": {"source": "point"}}, night_gas_network())
    pl = _by_name(point["fragment"]["sheets"]["processes"])["x_co2_supply"]
    assert pl["carrier"] == "point-source capture" and pl["marginal_cost"] > 0     # DEA cement-kiln VOM


def test_compressor_penalty_and_storage_bus() -> None:
    built = chains.build_chain(ALL, night_gas_network())
    sheets = built["fragment"]["sheets"]
    comp = _by_name(sheets["links"])["x_compressor"]
    assert comp["efficiency"] == 1.0 and comp["efficiency2"] == -0.05 and comp["bus2"] == "grid"
    store = _by_name(sheets["stores"])["x_h2_store"]
    assert store["bus"] == comp["bus1"] and store["e_cyclic"] is True and store["e_nom_extendable"] is True
    no_comp = chains.build_chain({**ALL, "storage": {"type": "cavern"}}, night_gas_network())
    assert "x_compressor" not in _by_name(no_comp["fragment"]["sheets"]["links"])
    cav = _by_name(no_comp["fragment"]["sheets"]["stores"])["x_h2_store"]
    assert cav["lifetime"] == 100 and cav["bus"] == no_comp["registry"]["buses"]["h2"]


def test_offtake_flat_tonnes_and_uploaded_profile() -> None:
    base = night_gas_network(hours=4)
    spec = {"chainId": "y", "products": ["H2", "NH3"], "offtake": {"H2": {"mode": "flat", "tonnesPerYear": 876.0},
            "NH3": {"mode": "profile", "mw": 10.0, "profile": [1, 1, 3, 3]}}}
    built = chains.build_chain(spec, base)
    loads = _by_name(built["fragment"]["sheets"]["loads"])
    assert_allclose(loads["y_load_H2"]["p_set"], 876.0 * 33.33 / 8760, rtol=1e-9)          # t/yr -> MW_LHV
    prof = built["fragment"]["sheets"]["loads-p_set"]
    assert [r["y_load_NH3"] for r in prof] == [5.0, 5.0, 15.0, 15.0]                       # shape normalised to mean 1, x 10 MW
    merged = fragment_merge.merge_fragment({**base, "loads-p_set": [{"snapshot": s["snapshot"], "demand": 20} for s in base["snapshots"]]},
                                           built["fragment"])
    assert len(merged["loads-p_set"]) == 4 and merged["loads-p_set"][2]["demand"] == 20 and merged["loads-p_set"][2]["y_load_NH3"] == 15.0
    with pytest.raises(ValueError, match="snapshots"):
        chains.build_chain({**spec, "offtake": {"NH3": {"mode": "profile", "mw": 1, "profile": [1, 2]}}}, base)


def test_registry_row_and_designated_generators() -> None:
    model, _ = with_chain(night_gas_network(), H2_SPEC)
    regs = rf.registry_chains(model)
    assert regs[0]["chainId"] == "p2x" and regs[0]["designatedGenerators"] == ["wind"]
    assert regs[0]["components"]["electrolyser"] == {"sheet": "links", "name": "p2x_electrolyser"}
    with pytest.raises(ValueError, match="already exists"):
        chains.build_chain(H2_SPEC, model)
    with pytest.raises(ValueError, match="Designated generator"):
        chains.build_chain({**H2_SPEC, "chainId": "z", "designatedGenerators": ["nope"]}, night_gas_network())
    with pytest.raises(ValueError, match="Unknown product"):
        chains.build_chain({"products": ["H3"]}, night_gas_network())


def test_min_load_needs_a_fixed_size() -> None:
    fixed = chains.build_chain({**H2_SPEC, "electrolyser": {**H2_SPEC["electrolyser"], "enforceMinLoad": True}}, night_gas_network())
    ely = _by_name(fixed["fragment"]["sheets"]["links"])["p2x_electrolyser"]
    assert ely["committable"] is True and "p_nom_extendable" not in ely and ely["p_min_pu"] == pytest.approx(0.15)
    ext = chains.build_chain({**H2_SPEC, "electrolyser": {"extendable": True, "enforceMinLoad": True}}, night_gas_network())
    ely2 = _by_name(ext["fragment"]["sheets"]["links"])["p2x_electrolyser"]
    assert "committable" not in ely2 and ely2["p_nom_extendable"] is True
    assert any("mutually exclusive" in w for w in ext["warnings"])


def test_a_full_chain_solves_and_balances_every_bus() -> None:
    """H2 -> NH3 / MeOH / e-fuel: each product load is met and H2 production equals H2 consumed (no stores sized)."""
    base = night_gas_network(hours=24)
    base["generators"][1]["marginal_cost"] = 20.0
    spec = {**ALL, "storage": {"type": "none"}, "productStorage": {p: {"enabled": False} for p in chains.PRODUCTS}}
    model, built = with_chain(base, spec)
    res = run_pypsa(model, SCENARIO, {})
    reg = built["registry"]
    n_h = 24
    tpy = {"H2": 33.33, "NH3": 5.17, "MeOH": 5.54, "eFuel": 11.94}
    for prod, lhv in tpy.items():
        mw = 1000.0 * lhv / 8760.0
        # the load sits on the product bus and is served: link output equals it
        out = (-sum(series(res, "links-p1", reg["components"]["electrolyser"]["name"])) if prod == "H2"
               else -sum(series(res, "processes-p1", reg["components"][f"synth_{prod}"]["name"])))
        if prod == "H2":
            h2_total_out, h2_direct = out, mw * n_h
        else:
            assert_allclose(out, mw * n_h, rtol=1e-6)
    h2_to_synth = sum(sum(series(res, "processes-p0", reg["components"][f"synth_{p}"]["name"])) for p in chains.PRODUCTS)
    assert_allclose(h2_total_out, h2_direct + h2_to_synth, rtol=1e-6)
