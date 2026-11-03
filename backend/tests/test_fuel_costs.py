"""Fuel-costs module: fuel price series -> time-varying marginal cost at run time, checked against hand calculations.

The system: one electric bus ``b`` (load 100 MW), coal Generator ``coal`` (eta 0.4, VOM 3, 70 MW) and a CCGT Link
(gas bus -> b, eta 0.55, VOM 2, 70 MW_el). Fuel prices (currency/MWh_th) over four hours:

    hour          0     1     2     3
    coal         20    20    40    40      -> 20/0.4 + 3 = 53, 53, 103, 103
    gas          50    30    50    30      -> 50/0.55 + 2 = 92.909, 56.545, 92.909, 56.545

The dearer unit is marginal (the cheaper one is at its 70 MW limit), so the SMP is
[92.909, 56.545, 103, 103] and the marginal unit switches between hours.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from backend.app import carbon_pricing as cp
from backend.app import fuel_costs as fc
from backend.app import module_hooks as mh
from backend.app.fuel_costs import hooks as fc_hooks
from backend.pypsa.network import build_network

COAL_P = [20.0, 20.0, 40.0, 40.0]
GAS_P = [50.0, 30.0, 50.0, 30.0]
STAMPS = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]
ETA_COAL, VOM_COAL, ETA_GAS, VOM_GAS = 0.4, 3.0, 0.55, 2.0
SMP = [GAS_P[0] / ETA_GAS + VOM_GAS, GAS_P[1] / ETA_GAS + VOM_GAS, COAL_P[2] / ETA_COAL + VOM_COAL, COAL_P[3] / ETA_COAL + VOM_COAL]


def _model(*, supplier: bool = True, sheets: bool = True, link_cap_cost: float = 0.0, coal_cap_cost: float = 0.0) -> dict[str, Any]:
    gens: list[dict[str, Any]] = [
        {"name": "coal", "bus": "b", "carrier": "coal", "p_nom": 70, "efficiency": ETA_COAL, "marginal_cost": 999.0,
         "capital_cost": coal_cap_cost},
    ]
    if supplier:   # a fuel-supply Generator on the gas bus (carrier gas): the fuel is priced THERE
        gens.append({"name": "gas_supply", "bus": "gas", "carrier": "gas", "p_nom": 1000, "marginal_cost": 777.0})
    else:          # a free source (carrier not priced): the fuel is priced on the Link
        gens.append({"name": "free_gas", "bus": "gas", "carrier": "free", "p_nom": 1000, "marginal_cost": 0.0})
    m: dict[str, Any] = {
        "buses": [{"name": "b"}, {"name": "gas", "carrier": "gas"}],
        "carriers": [{"name": "coal", "co2_emissions": 0.34}, {"name": "gas", "co2_emissions": 0.2}, {"name": "free"}, {"name": "CCGT"}],
        "snapshots": [{"snapshot": s} for s in STAMPS],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "generators": gens,
        "links": [{"name": "ccgt", "bus0": "gas", "bus1": "b", "carrier": "CCGT", "p_nom": 70 / ETA_GAS, "efficiency": ETA_GAS,
                   "marginal_cost": 555.0, "capital_cost": link_cap_cost}],
    }
    if sheets:
        m[fc.SHEET_PRICES] = [{"snapshot": s, "coal": c, "gas": g} for s, c, g in zip(STAMPS, COAL_P, GAS_P)]
        m[fc.SHEET_VOM] = [
            {"component": "Generator", "name": "coal", "vom": VOM_COAL},
            {"component": "Link", "carrier": "CCGT", "vom": VOM_GAS},
        ]
    return m


def _solve(model: dict[str, Any], carbon: float = 0.0, options: dict[str, Any] | None = None):
    n, notes = build_network(model, {"carbonPrice": carbon, "discountRate": 0.0}, options or {})
    n.optimize(solver_name="highs", extra_functionality=cp.extra_functionality, include_objective_constant=False)
    return n, notes


# ── 1. analytical SMP ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("supplier", [True, False], ids=["priced supplier", "no supplier (fuel on the Link)"])
def test_smp_is_fuel_over_efficiency_plus_vom_of_the_marginal_unit(supplier: bool) -> None:
    n, notes = _solve(_model(supplier=supplier))
    np.testing.assert_allclose(n.buses_t.marginal_price["b"].to_numpy(), SMP, rtol=1e-9)
    # the marginal unit really switches: gas is marginal in hours 0-1, coal in hours 2-3
    assert n.generators_t.p["coal"].round(6).tolist() == [70.0, 70.0, 30.0, 30.0]
    assert any("Fuel costs" in line for line in notes)


def test_link_convention_and_what_is_written() -> None:
    n, _ = _solve(_model(supplier=True))
    # supplier prices the fuel per MWh_th; the Link carries VOM x eta per MWh of p0
    np.testing.assert_allclose(n.generators_t.marginal_cost["gas_supply"].to_numpy(), GAS_P, rtol=1e-12)
    np.testing.assert_allclose(n.links_t.marginal_cost["ccgt"].to_numpy(), [VOM_GAS * ETA_GAS] * 4, rtol=1e-12)
    np.testing.assert_allclose(n.generators_t.marginal_cost["coal"].to_numpy(), [c / ETA_COAL + VOM_COAL for c in COAL_P], rtol=1e-12)
    n2, _ = _solve(_model(supplier=False))
    np.testing.assert_allclose(n2.links_t.marginal_cost["ccgt"].to_numpy(), [g + VOM_GAS * ETA_GAS for g in GAS_P], rtol=1e-12)
    assert "free_gas" not in n2.generators_t.marginal_cost.columns
    # the workbook's marginal_cost columns are untouched (the series live in *_t)
    assert float(n.generators.at["coal", "marginal_cost"]) == 999.0


def test_flat_carrier_price_is_a_constant_series_and_a_sheet_column_wins() -> None:
    m = _model(sheets=False)
    m["carriers"][0]["fuel_cost_thermal"] = 20.0          # coal flat
    m["carriers"][1]["fuel_cost_thermal"] = 30.0          # gas flat
    m[fc.SHEET_VOM] = [{"component": "Generator", "name": "coal", "vom": VOM_COAL}, {"component": "Link", "name": "ccgt", "vom": VOM_GAS}]
    n, _ = _solve(m)
    np.testing.assert_allclose(n.generators_t.marginal_cost["coal"].to_numpy(), [20 / ETA_COAL + VOM_COAL] * 4)
    # a sheet column for gas takes over from its flat value; coal keeps the flat one
    m[fc.SHEET_PRICES] = [{"snapshot": s, "gas": g} for s, g in zip(STAMPS, GAS_P)]
    n, _ = _solve(m)
    np.testing.assert_allclose(n.generators_t.marginal_cost["gas_supply"].to_numpy(), GAS_P)
    np.testing.assert_allclose(n.generators_t.marginal_cost["coal"].to_numpy(), [20 / ETA_COAL + VOM_COAL] * 4)


def test_blank_price_keeps_the_workbook_cost_and_is_reported() -> None:
    m = _model()
    m[fc.SHEET_PRICES][1]["coal"] = None
    n, notes = _solve(m)
    mc = n.generators_t.marginal_cost["coal"].to_numpy()
    assert mc[1] == 999.0 and mc[0] == pytest.approx(20 / ETA_COAL + VOM_COAL)
    assert any("coal" in line and "1 of 4" in line for line in notes)


def test_name_vom_row_beats_carrier_row_and_missing_vom_is_zero_and_reported() -> None:
    m = _model()
    m[fc.SHEET_VOM] = [{"component": "Generator", "carrier": "coal", "vom": 10.0}, {"component": "Generator", "name": "coal", "vom": 3.0}]
    n, notes = _solve(m)
    np.testing.assert_allclose(n.generators_t.marginal_cost["coal"].to_numpy(), [c / ETA_COAL + 3.0 for c in COAL_P])
    # the Link has no VOM row and a static marginal_cost of 555 per MWh_th: kept as its VOM (fuel is on the supplier)
    np.testing.assert_allclose(n.links_t.marginal_cost["ccgt"].to_numpy(), 555.0)
    assert not any("no RAGNAROK_VariableOM row" in line and "ccgt" in line for line in notes)
    # with no static value either, the VOM is 0 and the Link is listed in the notes
    m["links"][0]["marginal_cost"] = 0.0
    n, notes = _solve(m)
    np.testing.assert_allclose(n.links_t.marginal_cost["ccgt"].to_numpy(), 0.0)
    assert any("no RAGNAROK_VariableOM row" in line and "ccgt" in line for line in notes)


def test_a_catalogue_ccgt_keeps_its_built_in_vom_when_its_gas_is_priced() -> None:
    """The plants catalogue writes the supplier's mc = price and the Link's mc = vom x eta, and no VOM row.

    Pricing the gas carrier must not drop that VOM: per MWh_el the CCGT costs gas/eta + vom, so the SMP in the
    gas-marginal hours is 50/0.55 + 2 and 30/0.55 + 2 exactly as with a VOM row.
    """
    m = _model()
    m["links"][0]["marginal_cost"] = VOM_GAS * ETA_GAS
    m[fc.SHEET_VOM] = [{"component": "Generator", "name": "coal", "vom": VOM_COAL}]
    n, _ = _solve(m)
    np.testing.assert_allclose(n.links_t.marginal_cost["ccgt"].to_numpy(), VOM_GAS * ETA_GAS, rtol=1e-12)
    np.testing.assert_allclose(n.buses_t.marginal_price["b"].to_numpy(), SMP, rtol=1e-9)
    spec = next(u for u in fc.resolve_units(m) if u.name == "ccgt")
    assert spec.vom_source == "workbook" and spec.vom == pytest.approx(VOM_GAS)


def test_vom_row_names_a_renewable_generator() -> None:
    m = _model()
    m["generators"].append({"name": "wind", "bus": "b", "carrier": "wind", "p_nom": 10, "marginal_cost": 5.0})
    m[fc.SHEET_VOM].append({"component": "Generator", "name": "wind", "vom": 1.5})
    n, _ = _solve(m)
    np.testing.assert_allclose(n.generators_t.marginal_cost["wind"].to_numpy(), 1.5)


def test_part_load_and_piecewise_units_are_skipped_with_a_note() -> None:
    m = _model()
    m["generators"][0]["stand_by_cost"] = 12.0
    n, notes = _solve(m)
    assert "coal" not in n.generators_t.marginal_cost.columns
    assert any("coal" in line and "part-load" in line for line in notes)
    m = _model()
    m["generators-marginal_cost-pw"] = [{"name": "coal", "p_pu": 0.0, "marginal_cost": 1.0}, {"name": "coal", "p_pu": 1.0, "marginal_cost": 2.0}]
    with mh.isolated(empty=False):
        plan = fc.build_plan(build_network(_model(), {"discountRate": 0.0}, {"fuelCosts": {"enabled": False}})[0], m)
    assert plan.get("Generator", "coal").status == "skipped"


# ── 2. carbon is not counted twice ─────────────────────────────────────────────────

def test_carbon_is_in_the_objective_once_and_not_in_marginal_cost() -> None:
    price = 50.0
    n, _ = _solve(_model(), carbon=price)
    coal_p, ccgt_out = n.generators_t.p["coal"], -n.links_t.p1["ccgt"]
    gas_in, supply = n.links_t.p0["ccgt"], n.generators_t.p["gas_supply"]
    np.testing.assert_allclose(supply.to_numpy(), gas_in.to_numpy(), atol=1e-6)
    fuel_vom = (coal_p * [c / ETA_COAL + VOM_COAL for c in COAL_P]).sum() + (ccgt_out * [g / ETA_GAS + VOM_GAS for g in GAS_P]).sum()
    carbon = price * (0.34 / ETA_COAL * coal_p.sum() + 0.2 * gas_in.sum())        # gas emits at the supplier (efficiency 1), once
    assert float(n.objective) == pytest.approx(fuel_vom + carbon, rel=1e-9)
    # marginal_cost carries no carbon
    np.testing.assert_allclose(n.generators_t.marginal_cost["coal"].to_numpy(), [c / ETA_COAL + VOM_COAL for c in COAL_P], rtol=1e-12)
    # SMP = fuel/eta + VOM + price x e / eta of the marginal unit. With the price the merit order moves (hour 1: coal 53 + 42.5 =
    # 95.5 now costs more than gas 56.545 + 18.18 = 74.73), and the dearer of the two (each limited to 70 MW) is marginal.
    coal_cost = [c / ETA_COAL + VOM_COAL + price * 0.34 / ETA_COAL for c in COAL_P]
    gas_cost = [g / ETA_GAS + VOM_GAS + price * 0.2 / ETA_GAS for g in GAS_P]
    np.testing.assert_allclose(n.buses_t.marginal_price["b"].to_numpy(), np.maximum(coal_cost, gas_cost), rtol=1e-9)
    assert [bool(c > g) for c, g in zip(coal_cost, gas_cost)] == [False, True, True, True]    # the marginal unit switched in hour 1


# ── 3. refusals and the no-op ───────────────────────────────────────────────────────

def test_missing_efficiency_on_a_priced_unit_is_a_400_in_the_guard_and_the_build() -> None:
    m = _model()
    del m["generators"][0]["efficiency"]
    ctx = mh.RunContext(model=m, options={})
    with pytest.raises(HTTPException) as exc:
        mh.run_guards(ctx)
    assert exc.value.status_code == 400 and "coal" in str(exc.value.detail) and "efficiency" in str(exc.value.detail)
    with pytest.raises(HTTPException) as exc2:
        build_network(m, {"carbonPrice": 0.0, "discountRate": 0.0}, {})
    assert exc2.value.status_code == 400
    m["generators"][0]["efficiency"] = 0
    with pytest.raises(HTTPException):
        mh.run_guards(mh.RunContext(model=m, options={}))
    # the switch turns the module (and so the refusal) off
    mh.run_guards(mh.RunContext(model=m, options={"fuelCosts": {"enabled": False}}))


def test_a_supplier_without_efficiency_is_fine_and_a_link_without_efficiency_is_not() -> None:
    mh.run_guards(mh.RunContext(model=_model(), options={}))            # gas_supply states no efficiency: 1
    m = _model()
    del m["links"][0]["efficiency"]
    with pytest.raises(HTTPException) as exc:
        mh.run_guards(mh.RunContext(model=m, options={}))
    assert "ccgt" in str(exc.value.detail)


def test_malformed_inputs_are_a_400() -> None:
    m = _model()
    m[fc.SHEET_PRICES][0]["coal"] = "abc"
    with pytest.raises(HTTPException) as exc:
        build_network(m, {"carbonPrice": 0.0, "discountRate": 0.0}, {})
    assert exc.value.status_code == 400 and "not a finite number" in str(exc.value.detail)
    m = _model()
    m[fc.SHEET_VOM][0]["vom"] = -1
    with pytest.raises(HTTPException):
        build_network(m, {"carbonPrice": 0.0, "discountRate": 0.0}, {})


def test_no_inputs_is_a_no_op_identical_to_a_host_without_the_module() -> None:
    m = _model(sheets=False)
    assert not fc.has_inputs(m)
    n, notes = _solve(m)
    assert not any("Fuel costs" in line for line in notes)
    assert n.generators_t.marginal_cost.empty and n.links_t.marginal_cost.empty
    with mh.isolated(empty=True):
        n0, _ = build_network(_model(sheets=False), {"carbonPrice": 0.0, "discountRate": 0.0}, {})
        n0.optimize(solver_name="highs", include_objective_constant=False)
    assert float(n.objective) == float(n0.objective)                     # byte-identical, not approximately
    assert n.generators_t.p.equals(n0.generators_t.p) and n.links_t.p0.equals(n0.links_t.p0)


def test_switch_off_leaves_a_model_with_inputs_as_written() -> None:
    n, _ = _solve(_model(), options={"fuelCosts": {"enabled": False}})
    assert n.generators_t.marginal_cost.empty
    assert float(n.generators.at["coal", "marginal_cost"]) == 999.0


# ── 5. LCOE ex post ────────────────────────────────────────────────────────────────

def test_lcoe_against_a_hand_calculation() -> None:
    n, _ = _solve(_model(link_cap_cost=55.0, coal_cap_cost=100.0))
    plan = n._ragnarok_fuel_plan
    out = fc.results(n, plan, "$")
    rows = {(u["component"], u["name"]): u for u in out["units"]}
    # coal: 70 + 70 + 30 + 30 = 200 MWh; fuel 7000 + 6000, VOM 600, capex 70 MW x 100 = 7000
    coal = rows[("Generator", "coal")]
    assert coal["generationMwh"] == pytest.approx(200.0)
    assert coal["lcoe"]["value"] == pytest.approx((7000 + 7000 + 6000 + 600) / 200, rel=1e-9)
    assert coal["lcoe"]["capex"] == pytest.approx(7000 / 200) and coal["lcoe"]["fuel"] == pytest.approx(13000 / 200)
    # CCGT: out 30 + 30 + 70 + 70 = 200 MWh_el; fuel (50x30 + 30x30 + 50x70 + 30x70) / 0.55, VOM 2 x 200, capex 70/0.55 MW_th x 55
    ccgt = rows[("Link", "ccgt")]
    assert ccgt["generationMwh"] == pytest.approx(200.0)
    assert ccgt["lcoe"]["value"] == pytest.approx((7000 + (1500 + 900 + 3500 + 2100) / ETA_GAS + 400) / 200, rel=1e-8)  # payload rounds to 1e-6
    # the supplier is priced per MWh_th and carries no LCOE of its own
    assert rows[("Generator", "gas_supply")]["lcoe"] is None and rows[("Generator", "gas_supply")]["basis"] == "MWh_th"
    # the breakdown: coal time mean fuel = mean(50, 50, 100, 100), dispatch-weighted = (70*50*2 + 30*100*2) / 200
    assert coal["timeMean"]["fuel"] == pytest.approx(75.0)
    assert coal["dispatchWeighted"]["fuel"] == pytest.approx(65.0)
    assert coal["timeMean"]["total"] == pytest.approx(75.0 + VOM_COAL)
    # no zero-generation unit gets an LCOE
    assert out["smp"]["source"] == "buses_t.marginal_price"


def test_lcoe_carbon_part_is_the_carbon_pricing_modules_own_cost() -> None:
    n, _ = _solve(_model(coal_cap_cost=100.0), carbon=50.0)
    out = fc.results(n, n._ragnarok_fuel_plan, "$")
    coal = next(u for u in out["units"] if u["name"] == "coal")
    gen = float(n.generators_t.p["coal"].sum())
    assert coal["lcoe"]["carbon"] == pytest.approx(cp.carbon_cost_by_generator(n)["coal"] / gen, rel=1e-9)
    ccgt = next(u for u in out["units"] if u["name"] == "ccgt")
    # a Link's carbon is the upstream supplier's: price x 0.2 / eta per MWh_el
    assert ccgt["timeMean"]["carbon"] == pytest.approx(50.0 * 0.2 / ETA_GAS)


def test_zero_generation_unit_has_a_null_lcoe() -> None:
    m = _model()
    m["loads"][0]["p_set"] = 10.0
    for row in m[fc.SHEET_PRICES]:
        row["gas"] = 1000.0                 # gas is dear in every hour: the CCGT never runs
    n, _ = _solve(m)
    out = fc.results(n, n._ragnarok_fuel_plan, "$")
    rows = {u["name"]: u for u in out["units"]}
    assert rows["ccgt"]["generationMwh"] == 0.0 and rows["ccgt"]["lcoe"] is None
    assert rows["coal"]["lcoe"] is not None


# ── preview (no solve) and the run path ───────────────────────────────────────────

def test_preview_shows_the_series_and_the_breakdown_without_solving() -> None:
    from backend.pypsa.network import build_components

    model = _model()
    net, _ = build_components(model, {})
    cp.set_plan(net, cp.parse_carbon_price_config(50.0, None))
    plan = fc.build_plan(net, model)
    prev = fc.preview(net, plan)
    rows = {u["name"]: u for u in prev["units"]}
    assert prev["active"] and prev["carbonPriceActive"]
    assert rows["coal"]["marginalCost"]["newMean"] == pytest.approx(np.mean([c / ETA_COAL + VOM_COAL for c in COAL_P]))
    assert rows["coal"]["marginalCost"]["oldMean"] == pytest.approx(999.0)
    assert rows["coal"]["timeMean"]["carbon"] == pytest.approx(50 * 0.34 / ETA_COAL)
    assert rows["coal"]["timeMean"]["total"] == pytest.approx(rows["coal"]["timeMean"]["fuel"] + VOM_COAL + 50 * 0.34 / ETA_COAL)
    assert rows["ccgt"]["marginalCost"]["newMean"] == pytest.approx(VOM_GAS * ETA_GAS)
    assert n_has_no_solution(net)


def n_has_no_solution(net: Any) -> bool:
    return net.generators_t.p.empty


def test_run_pypsa_carries_the_fuel_costs_payload() -> None:
    from backend.pypsa.results import run_pypsa

    res = run_pypsa(_model(), {"carbonPrice": 0.0, "discountRate": 0.0}, {})
    block = res["fuelCosts"] if isinstance(res, dict) else res.fuelCosts
    assert block is not None and {u["name"] for u in block["units"]} >= {"coal", "ccgt", "gas_supply"}
    assert any("Fuel costs" in line for line in res["narrative"])
    # no inputs: the key is present and None
    res0 = run_pypsa(_model(sheets=False), {"carbonPrice": 0.0, "discountRate": 0.0}, {})
    assert res0["fuelCosts"] is None


def test_hooks_are_registered_under_the_module() -> None:
    reg = mh.registered()
    assert any(h["id"] == "fuel-costs" and h["module"] == "fuel-costs" for h in reg["build_step"])
    assert any(h["id"] == "fuel-costs-guard" for h in reg["guard"])
    assert "fuelCosts" in mh.declared_payload_keys()
    assert fc_hooks.MODULE == "fuel-costs"


# ── the endpoint, the stored sheet and Forge alignment ────────────────────────────

def test_preview_endpoint_reads_the_session_sheets_including_the_stored_series_sheet() -> None:
    from fastapi.testclient import TestClient

    from backend.app import model_store, timeseries
    from backend.app.main import app

    assert timeseries.is_series_sheet_name(fc.SHEET_PRICES) and not timeseries.is_series_sheet_name(fc.SHEET_VOM)
    c = TestClient(app)
    sid = "test-fuel-costs-preview"
    model_store.save_model(sid, _model())
    try:
        body = c.post("/api/fuel-costs/preview", json={"sessionId": sid, "carbonPrice": 50.0}).json()
        rows = {u["name"]: u for u in body["units"]}
        assert body["active"] and body["carbonPriceActive"] and body["smp"]["source"] == "buses_t.marginal_price"
        assert rows["coal"]["marginalCost"]["newMean"] == pytest.approx(78.0)          # mean(53, 53, 103, 103)
        assert rows["coal"]["timeMean"]["carbon"] == pytest.approx(50 * 0.34 / ETA_COAL)
        assert rows["gas_supply"]["marginalCost"]["newMean"] == pytest.approx(np.mean(GAS_P))
        assert body["inputs"]["priceSheet"] == fc.SHEET_PRICES
        # a priced unit without efficiency is a 400 from the preview too
        bad = _model()
        del bad["generators"][0]["efficiency"]
        model_store.save_model(sid, bad)
        r = c.post("/api/fuel-costs/preview", json={"sessionId": sid})
        assert r.status_code == 400 and "coal" in r.json()["detail"]
        # a model with no input: inactive, nothing priced
        model_store.save_model(sid, _model(sheets=False))
        none = c.post("/api/fuel-costs/preview", json={"sessionId": sid}).json()
        assert none["active"] is False and none["units"] == []
    finally:
        model_store.clear(sid)


def test_forge_realign_keeps_the_price_sheet_on_the_new_axis() -> None:
    idx = pd.DatetimeIndex(pd.to_datetime(STAMPS))
    rows = _model()[fc.SHEET_PRICES]
    kept = fc.inputs.realign(rows, STAMPS[1:3], idx[1:3], mode="filter")
    assert [r["snapshot"] for r in kept] == STAMPS[1:3] and kept[0]["coal"] == COAL_P[1]
    blocks = fc.inputs.realign(rows, [STAMPS[0], STAMPS[2]], idx[[0, 2]], mode="blocks")
    assert [r["snapshot"] for r in blocks] == [STAMPS[0], STAMPS[2]]
    assert blocks[0]["gas"] == pytest.approx(np.mean(GAS_P[:2])) and blocks[1]["coal"] == pytest.approx(np.mean(COAL_P[2:]))
    rows[1]["coal"] = None                                    # a blank hour is skipped in the mean; a fully blank block stays blank
    rows[0]["coal"] = None
    assert fc.inputs.realign(rows, [STAMPS[0], STAMPS[2]], idx[[0, 2]], mode="blocks")[0]["coal"] is None


def test_price_series_align_on_a_pathway_snapshot_index() -> None:
    snaps = pd.MultiIndex.from_product([[2030, 2040], pd.DatetimeIndex(pd.to_datetime(STAMPS))], names=["period", "timestep"])
    ps = fc.price_set(_model(), snaps)
    assert list(ps.frame.index) == list(snaps)
    np.testing.assert_allclose(ps.frame["coal"].to_numpy(), COAL_P * 2)


def test_merit_order_and_rolling_penalty_read_the_written_series_not_the_workbook_column() -> None:
    from backend.pypsa.results.market import build_merit_order
    from backend.pypsa.rolling import auto_terminal_penalty

    n, _ = _solve(_model())
    order = {r["name"]: r["marginal_cost"] for r in build_merit_order(n)}
    assert order["coal"] == pytest.approx(78.0)              # mean(53, 53, 103, 103), not the workbook's 999
    assert order["gas_supply"] == pytest.approx(np.mean(GAS_P))
    from backend.pypsa.rolling import AUTO_PENALTY_FACTOR

    assert auto_terminal_penalty(n) == pytest.approx(AUTO_PENALTY_FACTOR * 103.0)    # the dearest cost charged (coal in hours 2-3)


# ── stochastic runs ────────────────────────────────────────────────────────────────

W_LOW, W_HIGH = 0.6, 0.4


def _ov(sheet: str, attribute: str, scope: str, value: float, op: str = "multiply", scope_type: str = "name") -> dict[str, Any]:
    return {"sheet": sheet, "attribute": attribute, "scopeType": scope_type, "scopeValue": scope, "operation": op, "value": value}


def _stoch(low: list[dict[str, Any]] | None = None, high: list[dict[str, Any]] | None = None, extra: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    scenarios = [{"name": "low", "weight": W_LOW, "overrides": low if low is not None else [_ov("carriers", "fuel_price", "gas", 0.5)]},
                 {"name": "high", "weight": W_HIGH, "overrides": high if high is not None else [_ov("carriers", "fuel_price", "gas", 2.0)]}]
    return {"stochasticConfig": {"enabled": True, "scenarios": scenarios + (extra or [])}}


def _price(n: Any, scenario: str, weight: float) -> np.ndarray:
    """Per-scenario price: PyPSA's stochastic duals are probability-weighted."""
    return n.buses_t.marginal_price[(scenario, "b")].to_numpy() / weight


def _costs(gas_mult: float, coal_eta: float = ETA_COAL) -> tuple[np.ndarray, np.ndarray]:
    coal = np.array([c / coal_eta + VOM_COAL for c in COAL_P])
    gas = np.array([gas_mult * g / ETA_GAS + VOM_GAS for g in GAS_P])
    return coal, gas


def test_stochastic_smp_per_scenario_is_that_scenarios_fuel_over_efficiency_plus_vom() -> None:
    n, notes = _solve(_model(), options=_stoch())
    for name, w, mult in (("low", W_LOW, 0.5), ("high", W_HIGH, 2.0)):
        coal, gas = _costs(mult)
        np.testing.assert_allclose(_price(n, name, w), np.maximum(coal, gas), rtol=1e-9)
    # the marginal unit differs between the scenarios in hour 0: coal (53 > 47.5) in "low", gas (183.8 > 53) in "high"
    assert _costs(0.5)[0][0] > _costs(0.5)[1][0] and _costs(2.0)[1][0] > _costs(2.0)[0][0]
    # VOM is NOT scaled: the Link keeps VOM x eta, the supplier carries mult x fuel, coal is untouched
    mc_l, mc_g, mc_c = n.links_t.marginal_cost, n.generators_t.marginal_cost, n.generators_t.marginal_cost
    for name, mult in (("low", 0.5), ("high", 2.0)):
        np.testing.assert_allclose(mc_l[(name, "ccgt")].to_numpy(), VOM_GAS * ETA_GAS, rtol=1e-12)
        np.testing.assert_allclose(mc_g[(name, "gas_supply")].to_numpy(), [mult * g for g in GAS_P], rtol=1e-12)
        np.testing.assert_allclose(mc_c[(name, "coal")].to_numpy(), _costs(1.0)[0], rtol=1e-12)
    assert float(n.generators.at[("low", "coal"), "marginal_cost"]) == 999.0       # the static column is untouched
    assert any("[scenario low]" in x for x in notes) and any("[scenario high]" in x for x in notes)


def test_price_scenarios_sheet_gives_the_same_series_as_the_override_row_and_supports_price_and_snapshot() -> None:
    m = _model()
    m[fc.SHEET_PRICE_SCENARIOS] = [
        {"scenario": "low", "carrier": "gas", "multiplier": 0.5},
        {"scenario": "high", "carrier": "gas", "multiplier": 2.0},
    ]
    n, _ = _solve(m, options=_stoch(low=[], high=[]))
    for name, mult in (("low", 0.5), ("high", 2.0)):
        np.testing.assert_allclose(n.generators_t.marginal_cost[(name, "gas_supply")].to_numpy(), [mult * g for g in GAS_P], rtol=1e-12)
    # an absolute price on one snapshot only, then a multiplier on top (rows apply in order)
    m[fc.SHEET_PRICE_SCENARIOS] = [{"scenario": "high", "carrier": "gas", "snapshot": STAMPS[2], "price": 100.0},
                                   {"scenario": "high", "carrier": "gas", "multiplier": 2.0}]
    n, _ = _solve(m, options=_stoch(low=[], high=[]))
    np.testing.assert_allclose(n.generators_t.marginal_cost[("high", "gas_supply")].to_numpy(), [100.0, 60.0, 200.0, 60.0], rtol=1e-12)
    np.testing.assert_allclose(n.generators_t.marginal_cost[("low", "gas_supply")].to_numpy(), GAS_P, rtol=1e-12)   # base for the other scenario
    bad = _model()
    bad[fc.SHEET_PRICE_SCENARIOS] = [{"scenario": "low", "carrier": "gas"}]
    with pytest.raises(HTTPException) as exc:
        build_network(bad, {"carbonPrice": 0.0, "discountRate": 0.0}, _stoch())
    assert exc.value.status_code == 400 and "price or a multiplier" in str(exc.value.detail)


def test_an_efficiency_override_is_honoured_by_that_scenarios_marginal_cost() -> None:
    n, _ = _solve(_model(), options=_stoch(low=[_ov("generators", "efficiency", "coal", 0.5, op="set")], high=[]))
    np.testing.assert_allclose(n.generators_t.marginal_cost[("low", "coal")].to_numpy(), _costs(1.0, coal_eta=0.5)[0], rtol=1e-12)
    np.testing.assert_allclose(n.generators_t.marginal_cost[("high", "coal")].to_numpy(), _costs(1.0)[0], rtol=1e-12)
    coal, gas = _costs(1.0, coal_eta=0.5)
    np.testing.assert_allclose(_price(n, "low", W_LOW), np.maximum(coal, gas), rtol=1e-9)
    # an efficiency override that makes a priced unit unusable is a 400 naming the scenario
    with pytest.raises(HTTPException) as exc:
        build_network(_model(), {"carbonPrice": 0.0, "discountRate": 0.0}, _stoch(low=[_ov("generators", "efficiency", "coal", 0.0, op="set")]))
    assert exc.value.status_code == 400 and "scenario 'low'" in str(exc.value.detail)


def test_a_marginal_cost_override_of_a_priced_unit_is_refused_but_an_unpriced_one_is_not() -> None:
    for ov in (_ov("generators", "marginal_cost", "coal", 2.0), _ov("generators", "marginal_cost", "gas", 2.0, scope_type="carrier"),
               _ov("links", "marginal_cost", "ccgt", 2.0), _ov("generators", "marginal_cost", "", 1.1, scope_type="all")):
        opts = _stoch(low=[ov])
        with pytest.raises(HTTPException) as exc:
            mh.run_guards(mh.RunContext(model=_model(), options={}, stochastic=type("S", (), {"enabled": True, "scenarios": _cfg(opts).scenarios})()))
        assert exc.value.status_code == 400 and "scenario 'low'" in str(exc.value.detail) and "marginal_cost" in str(exc.value.detail)
        with pytest.raises(HTTPException):
            build_network(_model(), {"carbonPrice": 0.0, "discountRate": 0.0}, opts)
    m = _model()
    m["generators"].append({"name": "wind", "bus": "b", "carrier": "wind", "p_nom": 10, "marginal_cost": 5.0})
    n, _ = build_network(m, {"carbonPrice": 0.0, "discountRate": 0.0}, _stoch(low=[_ov("generators", "marginal_cost", "wind", 3.0)]))
    assert float(n.generators.at[("low", "wind"), "marginal_cost"]) == 15.0


def _cfg(options: dict[str, Any]) -> Any:
    from backend.app.stochastic.scenarios import parse_stochastic_config

    return parse_stochastic_config(options["stochasticConfig"])


def test_stochastic_results_per_scenario_expected_values_and_representative() -> None:
    from backend.pypsa.results import run_pypsa

    m = _model(link_cap_cost=55.0, coal_cap_cost=100.0)
    res = run_pypsa(m, {"carbonPrice": 50.0, "discountRate": 0.0}, _stoch())
    fcs = res["fuelCosts"]
    assert fcs["representativeScenario"] == "low" and [s["name"] for s in fcs["scenarios"]] == ["low", "high"]
    by = {s["name"]: {u["name"]: u for u in s["units"]} for s in fcs["scenarios"]}
    # the plain rows are the representative (highest-weight) scenario's
    assert {u["name"]: u["lcoe"] for u in fcs["units"]} == {k: v["lcoe"] for k, v in by["low"].items()}
    exp = {u["name"]: u for u in fcs["expected"]["units"]}
    for unit in ("coal", "ccgt"):
        parts = [(W_LOW, by["low"][unit]), (W_HIGH, by["high"][unit])]
        for key in ("value", "fuel", "carbon"):
            want = sum(w * (u["lcoe"][key] or 0.0) for w, u in parts)
            assert exp[unit]["lcoe"][key] == pytest.approx(want, abs=1e-5)
        assert exp[unit]["timeMean"]["total"] == pytest.approx(sum(w * u["timeMean"]["total"] for w, u in parts), abs=1e-5)
    # hand check of one scenario: "high" coal fuel term = dispatch-weighted mean of coal fuel / eta (price does not depend on scenario)
    coal_high = by["high"]["coal"]
    assert coal_high["timeMean"]["carbon"] == pytest.approx(50 * 0.34 / ETA_COAL)
    # the gas Link's carbon is its supplier's: price x 0.2 / eta, per scenario
    assert by["high"]["ccgt"]["timeMean"]["carbon"] == pytest.approx(50 * 0.2 / ETA_GAS)
    # the scenario fuel of the CCGT follows ITS gas price: time mean of mult x gas / eta
    assert by["low"]["ccgt"]["timeMean"]["fuel"] == pytest.approx(0.5 * np.mean(GAS_P) / ETA_GAS)
    assert by["high"]["ccgt"]["timeMean"]["fuel"] == pytest.approx(2.0 * np.mean(GAS_P) / ETA_GAS)


def test_stochastic_lcoe_carbon_part_matches_the_carbon_pricing_modules_per_scenario_cost() -> None:
    n, _ = _solve(_model(coal_cap_cost=100.0), carbon=50.0, options=_stoch())
    out = fc.stochastic_results(n, n._ragnarok_fuel_plans, {"low": W_LOW, "high": W_HIGH}, "low")
    carbon = cp.carbon_cost_by_generator(n, per_scenario=True)
    for sc in out["scenarios"]:
        coal = next(u for u in sc["units"] if u["name"] == "coal")
        gen = float(n.generators_t.p[(sc["name"], "coal")].sum())
        assert coal["lcoe"]["carbon"] == pytest.approx(carbon[(sc["name"], "coal")] / gen, rel=1e-9)


def test_deterministic_path_does_not_touch_the_stochastic_machinery() -> None:
    n, _ = _solve(_model())
    assert not hasattr(n, "_ragnarok_fuel_plans") and hasattr(n, "_ragnarok_fuel_plan")
    m = _model()
    m[fc.SHEET_PRICE_SCENARIOS] = [{"scenario": "high", "carrier": "gas", "multiplier": 2.0}]
    n2, notes = _solve(m)
    np.testing.assert_allclose(n2.generators_t.marginal_cost["gas_supply"].to_numpy(), GAS_P)   # scenario rows ignored
    assert any("stochastic scenarios only" in x for x in notes)


def test_preview_endpoint_shows_per_scenario_mean_marginal_cost_when_stochastic() -> None:
    from fastapi.testclient import TestClient

    from backend.app import model_store
    from backend.app.main import app

    c = TestClient(app)
    sid = "test-fuel-costs-preview-stoch"
    model_store.save_model(sid, _model())
    try:
        body = c.post("/api/fuel-costs/preview", json={"sessionId": sid, **_stoch()}).json()
        sc = {s["name"]: {u["name"]: u for u in s["units"]} for s in body["scenarios"]}
        assert sc["low"]["gas_supply"]["marginalCost"]["newMean"] == pytest.approx(0.5 * np.mean(GAS_P))
        assert sc["high"]["gas_supply"]["marginalCost"]["newMean"] == pytest.approx(2.0 * np.mean(GAS_P))
        assert sc["high"]["ccgt"]["marginalCost"]["newMean"] == pytest.approx(VOM_GAS * ETA_GAS)
        bad = c.post("/api/fuel-costs/preview", json={"sessionId": sid, **_stoch(low=[_ov("generators", "marginal_cost", "coal", 2.0)])})
        assert bad.status_code == 400
        plain = c.post("/api/fuel-costs/preview", json={"sessionId": sid}).json()
        assert "scenarios" not in plain or plain["scenarios"] is None
    finally:
        model_store.clear(sid)
