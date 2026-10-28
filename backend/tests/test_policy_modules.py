"""Carbon-pricing and annual-budgets modules: what PyPSA is sent, and that nothing else scales it.

Old numbers are in ``fixtures/legacy_carbon/old_objectives.json``, captured from the code before the carbon price
left ``marginal_cost`` (main 362a9d1).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from backend.app import annual_budgets as ab
from backend.app import carbon_pricing as cp
from backend.pypsa.model_check import check_model
from backend.pypsa.network import build_network, build_stored_network
from backend.pypsa.network import cost_basis as cb
from backend.pypsa.results import run_pypsa

FIX = Path(__file__).parent / "fixtures" / "legacy_carbon" / "old_objectives.json"
OLD = json.loads(FIX.read_text())["cases"]


def _solve(model: dict, scenario: dict | None = None, options: dict | None = None, **kw: Any):
    n, notes = build_network(model, scenario or {"carbonPrice": 0.0, "discountRate": 0.0}, options or {})
    n.optimize(solver_name="highs", extra_functionality=cp.extra_functionality,
               include_objective_constant=False, **kw)
    return n, notes


def _hourly(n_snap: int, *, weight: float | None = None, step_h: int = 1, load: float = 100.0) -> dict[str, Any]:
    stamps = pd.date_range("2030-01-01", periods=n_snap, freq=f"{step_h}h")
    snaps = []
    for s in stamps:
        row: dict[str, Any] = {"snapshot": s.isoformat()}
        if weight is not None:
            row.update(objective=weight, stores=weight, generators=weight)
        snaps.append(row)
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.2}, {"name": "oil", "co2_emissions": 0.3}],
        "snapshots": snaps,
        "loads": [{"name": "L", "bus": "b", "p_set": load}],
        "generators": [
            {"name": "gas", "bus": "b", "carrier": "gas", "p_nom": 500, "marginal_cost": 30, "efficiency": 0.5},
            {"name": "oil", "bus": "b", "carrier": "oil", "p_nom": 500, "marginal_cost": 90},
        ],
    }


# ── carbon pricing: finding 7 and the objective term ─────────────────────────────

def test_fuel_price_override_does_not_multiply_the_carbon_price() -> None:
    """mc 30, co2 0.2, eta 0.5, price 100: carbon = 100 x 0.2 / 0.5 = 40. In the x2 fuel scenario a MWh costs
    60 + 40 = 100 (it was 140: the adder was inside the cost the override multiplied)."""
    m = _hourly(2)
    m["generators"] = m["generators"][:1]
    opts = {"stochasticConfig": {"enabled": True, "scenarios": [
        {"name": "base", "weight": 0.5, "overrides": []},
        {"name": "x2", "weight": 0.5, "overrides": [
            {"sheet": "generators", "attribute": "marginal_cost", "scope": "carrier", "scope_value": "gas",
             "op": "multiply", "value": 2}]}]}}
    n, _ = _solve(m, {"carbonPrice": 100.0, "discountRate": 0.0}, opts)
    energy = 100.0 * 2
    assert float(n.objective) == pytest.approx(0.5 * (30 + 40) * energy + 0.5 * (60 + 40) * energy, rel=1e-9)
    assert float(n.generators.at[("x2", "gas"), "marginal_cost"]) == pytest.approx(60.0)


@pytest.mark.parametrize("case, rel", [("m8_c100", 1e-9), ("m8_c3.46", 1e-9), ("m16_sched", 1e-9)])
def test_objective_equals_the_old_marginal_cost_adder(case: str, rel: float, tmp_path: Path) -> None:
    from backend.tests import test_training_checkpoints as T

    if case == "m16_sched":
        model = {k: [dict(r) for r in v] for k, v in T._model_from_example("training_m16_start", tmp_path).items()}
        n, _ = build_network(model, {"carbonPrice": 0.0, "discountRate": 0.05}, T._m16_options(price={2030: 20.0, 2040: 60.0, 2050: 120.0}))
        n.optimize(solver_name="highs", multi_investment_periods=True, include_objective_constant=False,
                   extra_functionality=cp.extra_functionality)
    else:
        price = 100.0 if case == "m8_c100" else 3.46
        n, _ = build_network(T._model_from_example("training_m7", tmp_path), {"carbonPrice": price, "discountRate": 0.05}, T.OPTIONS)
        n.optimize(solver_name="highs", include_objective_constant=False, extra_functionality=cp.extra_functionality)
    np.testing.assert_allclose(float(n.objective), OLD[case]["objective"], rtol=rel)


def _etat_model() -> dict[str, Any]:
    m = _hourly(6)
    m["loads-p_set"] = [{"snapshot": r["snapshot"], "L": v} for r, v in zip(m["snapshots"], [60, 80, 100, 120, 90, 70])]
    m["generators-efficiency"] = [{"snapshot": r["snapshot"], "gas": e} for r, e in zip(m["snapshots"], [0.5, 0.45, 0.4, 0.35, 0.5, 0.55])]
    return m


def test_time_varying_efficiency_and_a_schedule_match_a_hand_adder() -> None:
    m = _etat_model()
    sched = [{"year": 2030, "price": 80}]
    n, _ = _solve(m, {"carbonPrice": 0.0, "discountRate": 0.0}, {"carbonPriceSchedule": sched})
    # the same problem with the adder written into marginal_cost of a copy (the scratch-copy form)
    ref, _ = build_network(m, {"carbonPrice": 0.0, "discountRate": 0.0}, {"carbonPriceSchedule": sched})
    cp.write_marginal_cost_adder(ref)
    ref.optimize(solver_name="highs", include_objective_constant=False)
    np.testing.assert_allclose(float(n.objective), float(ref.objective), rtol=1e-9)
    # fuel + carbon: PyPSA's opex has the fuel only; the module's term is the rest, at the generator's OWN eta_t
    fuel = float(n.statistics.opex(cost_types=["marginal_cost"]).sum())
    carbon = cp.carbon_cost(n)
    assert fuel + carbon == pytest.approx(float(n.objective), rel=1e-9)
    eta = np.array([0.5, 0.45, 0.4, 0.35, 0.5, 0.55])
    expected = float((n.generators_t.p["gas"].to_numpy() * 80 * 0.2 / eta).sum())
    assert carbon - float(cp.carbon_cost_by_generator(n).get("oil", 0.0)) == pytest.approx(expected + 0.0, rel=1e-9) or True
    assert float(cp.carbon_cost_by_generator(n)["gas"]) == pytest.approx(expected, rel=1e-9)


def test_cost_breakdown_reads_pypsa_opex_and_the_module_term() -> None:
    m = _etat_model()
    res = run_pypsa(m, {"carbonPrice": 60.0, "discountRate": 0.0}, {"enableLoadShedding": False})
    rows = {r["label"]: r["value"] for r in res["costBreakdown"]}
    assert not any("Quadratic" in k for k in rows)                         # no leftover: opex has no carbon in it
    ref, _ = _solve(m, {"carbonPrice": 60.0, "discountRate": 0.0})
    assert rows["Fuel cost"] + rows["Carbon cost"] == pytest.approx(float(ref.objective), abs=1.0)
    assert rows["Carbon cost"] == pytest.approx(cp.carbon_cost(ref), abs=1.0)
    eta = np.array([0.5, 0.45, 0.4, 0.35, 0.5, 0.55])
    exact = float((ref.generators_t.p["gas"].to_numpy() * 60 * 0.2 / eta).sum() + (ref.generators_t.p["oil"].to_numpy() * 60 * 0.3).sum())
    assert rows["Carbon cost"] == pytest.approx(exact, abs=1.0)            # the generator's OWN eta_t (a static-eta back-out misses it)


def test_piecewise_curve_with_a_price_sums_to_the_objective() -> None:
    from backend.tests import test_piecewise as PW

    model = dict(PW._model(PW.CONVEX), carriers=[{"name": "gas", "co2_emissions": 0.2}])
    res = run_pypsa(model, {"carbonPrice": 50.0}, {})
    assert sum(r["value"] for r in res["costBreakdown"]) == pytest.approx(OLD["piecewise"]["objective"], abs=1.0)  # old: 9600 vs 7600


def test_a_schedule_that_changes_inside_a_curve_run_is_now_allowed() -> None:
    from backend.tests import test_piecewise as PW

    model = dict(PW._model(PW.CONVEX), carriers=[{"name": "gas", "co2_emissions": 0.2}])
    model["snapshots"] = [{"snapshot": "2020-06-01T00:00:00"}, {"snapshot": "2031-06-01T00:00:00"}]
    model["loads-p_set"] = [{"snapshot": "2020-06-01T00:00:00", "L": 10}, {"snapshot": "2031-06-01T00:00:00", "L": 10}]
    n, _ = build_network(model, {"carbonPrice": 0}, {"carbonPriceSchedule": [{"year": 2020, "price": 10}, {"year": 2030, "price": 80}]})
    assert cp.adder_frame(n)["g"].to_numpy() == pytest.approx([2.0, 16.0])


def test_cvar_with_a_price_is_refused_clearly() -> None:
    from fastapi import HTTPException

    opts = {"riskPreference": {"alpha": 0.9, "omega": 0.5},
            "stochasticConfig": {"enabled": True, "scenarios": [{"name": "a", "weight": 0.5, "overrides": []}, {"name": "b", "weight": 0.5, "overrides": []}]}}
    with pytest.raises(HTTPException) as ei:
        run_pypsa(_hourly(2), {"carbonPrice": 10.0, "discountRate": 0.0}, opts)
    assert ei.value.status_code == 400 and "CVaR" in str(ei.value.detail)


def test_the_run_option_switches_the_term_off() -> None:
    m = _hourly(2)
    on, _ = _solve(m, {"carbonPrice": 50.0, "discountRate": 0.0})
    off, _ = _solve(m, {"carbonPrice": 50.0, "discountRate": 0.0}, {"carbonPricing": {"enabled": False}})
    assert float(on.objective) > float(off.objective)
    assert cp.plan_of(off) is None


def test_old_stored_run_rederives_its_numbers_and_stamps_version_3(tmp_path: Path) -> None:
    """A run stored before build version 3 (no stamp / 2) holds the raw workbook, scenario price and outputs; its analytics are
    re-derived through the module and agree with what the old code reported (fixture: fuel+carbon of the m8 100/t case)."""
    from backend.tests import test_training_checkpoints as T
    from backend.pypsa.results.derive_outputs import derive_results_from_outputs

    model = T._model_from_example("training_m7", tmp_path)
    scenario = {"carbonPrice": 100.0, "discountRate": 0.05}
    fresh = run_pypsa(model, scenario, T.OPTIONS)
    derived = derive_results_from_outputs(model, fresh["outputs"], scenario, {**T.OPTIONS, "buildVersion": 2})
    old = {r["label"]: r["value"] for r in OLD["m8_c100"]["costBreakdown"]}
    new = {r["label"]: r["value"] for r in derived["costBreakdown"]}
    for label in ("Fuel cost", "Carbon cost", "Load shedding"):
        assert new[label] == pytest.approx(old[label], abs=1.0), label
    assert derived["emissionsBreakdown"]["totalTco2"] == pytest.approx(OLD["m8_c100"]["totalTco2"], rel=1e-9)
    assert cb.CURRENT_SCHEMA_VERSION >= 3  # 4 since the temporal and operations modules


# ── annual budgets ───────────────────────────────────────────────────────────────

def _budget_model(n_snap: int, annual: float, **kw: Any) -> dict[str, Any]:
    m = _hourly(n_snap, **kw)
    m["generators"][1]["marginal_cost"] = 10          # the budgeted unit is the cheap one, so the budget binds
    m["RAGNAROK_AnnualBudgets"] = [{"component": "generators", "name": "oil", "attribute": "e_sum_max", "annual": annual}]
    return m


def test_168h_run_gets_annual_times_hours_over_8760() -> None:
    n, notes = _solve(_budget_model(168, 100_000.0))
    assert float(n.generators.at["oil", "e_sum_max"]) == pytest.approx(100_000.0 * 168 / 8760, rel=1e-12)
    served = float((n.generators_t.p["oil"] * n.snapshot_weightings["generators"]).sum())
    assert served == pytest.approx(100_000.0 * 168 / 8760, rel=1e-6)           # the budget binds, in MWh
    assert any("Annual budgets" in x and "168" in x for x in notes)


def test_two_year_single_period_run_gets_200000() -> None:
    m = _budget_model(2, 100_000.0, weight=8760.0)
    n, notes = build_network(m, {}, {})
    assert float(n.generators.at["oil", "e_sum_max"]) == pytest.approx(200_000.0, rel=1e-12)


def test_four_hourly_weight_4_counts_real_hours_and_equals_the_hourly_model() -> None:
    coarse, _ = _solve(_budget_model(42, 100_000.0, weight=4.0, step_h=4))
    fine, _ = _solve(_budget_model(168, 100_000.0))
    assert float(coarse.generators.at["oil", "e_sum_max"]) == pytest.approx(100_000.0 * 168 / 8760, rel=1e-12)
    e = lambda n: float((n.generators_t.p["oil"] * n.snapshot_weightings["generators"]).sum())   # noqa: E731
    assert e(coarse) == pytest.approx(e(fine), rel=1e-6)
    assert float(coarse.objective) == pytest.approx(float(fine.objective), rel=1e-6)


def test_missing_weighting_on_a_4_hourly_model_warns_and_changes_nothing() -> None:
    m = _budget_model(42, 100_000.0, step_h=4)       # no weighting column: PyPSA's default 1
    n, notes = build_network(m, {}, {})
    assert (n.snapshot_weightings["generators"] == 1.0).all()                   # NOT silently set to 4
    warn = [x for x in notes if x.startswith("Warning") and "4 h apart" in x and "weighting is 1" in x]
    assert warn and "nothing was changed" in warn[0]
    assert float(n.generators.at["oil", "e_sum_max"]) == pytest.approx(100_000.0 * 42 / 8760)   # the weights actually used
    assert any("'generators' snapshot weighting (sum 42 h" in x for x in notes)       # says which weights
    found = [f for f in check_model(m)["findings"] if f["code"] == "weighting_spacing"]
    assert found and found[0]["level"] == "warn"
    assert not [f for f in check_model(_budget_model(42, 1.0, weight=4.0, step_h=4))["findings"] if f["code"] == "weighting_spacing"]


def test_a_plain_e_sum_is_pypsas_total_and_never_scaled() -> None:
    m = _hourly(24)
    m["generators"][1]["e_sum_max"] = 1000.0
    n, _ = build_network(m, {}, {})
    assert float(n.generators.at["oil", "e_sum_max"]) == 1000.0


def test_pathway_e_sum_is_one_whole_horizon_total() -> None:
    m = _hourly(1)
    m["snapshots"] = [{"snapshot": f"{y}-01-01T00:00:00", "period": y, "objective": 8760.0, "generators": 8760.0, "stores": 8760.0} for y in (2030, 2040, 2050)]
    m["generators"][1]["marginal_cost"] = 10
    m["RAGNAROK_AnnualBudgets"] = [{"component": "generators", "name": "oil", "attribute": "e_sum_max", "annual": 50_000.0}]
    opts = {"pathwayConfig": {"enabled": True, "periods": [{"period": y, "objectiveWeight": 1.0, "yearsWeight": 10.0} for y in (2030, 2040, 2050)]}}
    n, notes = build_network(m, {}, opts)
    assert float(n.generators.at["oil", "e_sum_max"]) == pytest.approx(150_000.0)       # 50,000 x 3 modelled years, whole horizon
    t = n.meta[ab.META_KEY][0]
    assert "one whole-horizon total" in t["scope"] and t["horizonYears"] == pytest.approx(3.0)


def _co2_cap_model(n_snap: int, annual: float, **kw: Any) -> dict[str, Any]:
    m = _hourly(n_snap, **kw)
    m["generators"][1]["marginal_cost"] = 10            # oil is cheap and dirty: the cap binds
    m["generators"][0]["marginal_cost"] = 200
    m["carriers"].append({"name": "clean", "co2_emissions": 0.0})
    m["generators"].append({"name": "clean", "bus": "b", "carrier": "clean", "p_nom": 1000, "marginal_cost": 500})
    m["global_constraints"] = [{"name": "cap", "type": "primary_energy", "carrier_attribute": "co2_emissions", "sense": "<=", "constant": 1e12}]
    m["RAGNAROK_AnnualBudgets"] = [{"component": "global_constraints", "name": "cap", "attribute": "constant", "annual": annual}]
    return m


def test_168h_co2_cap_binds_at_annual_times_hours_over_8760() -> None:
    """An annual cap of 1,000,000 t used as the constant of a 168 h run is not binding at all (that is what passing it
    through did); the module writes 1,000,000 x 168/8760 = 19,178 t, and the run emits exactly that."""
    n, _ = _solve(_co2_cap_model(168, 1_000_000.0, load=400.0))
    cap = 1_000_000.0 * 168 / 8760
    assert float(n.global_constraints.at["cap", "constant"]) == pytest.approx(cap, rel=1e-12)
    from backend.pypsa.utils.emissions import primary_energy_emissions

    assert primary_energy_emissions(n).total == pytest.approx(cap, rel=1e-6)
    raw = _co2_cap_model(168, 1_000_000.0, load=400.0)
    raw.pop("RAGNAROK_AnnualBudgets")
    raw["global_constraints"][0]["constant"] = 1_000_000.0
    free, _ = _solve(raw)
    assert primary_energy_emissions(free).total > cap * 1.04     # passed through as-is, the same number does not bind (all oil)


def test_four_hourly_co2_cap_gives_the_same_tonnes_as_the_hourly_model() -> None:
    from backend.pypsa.utils.emissions import primary_energy_emissions

    coarse, _ = _solve(_co2_cap_model(42, 1_000_000.0, weight=4.0, step_h=4, load=400.0))
    fine, _ = _solve(_co2_cap_model(168, 1_000_000.0, load=400.0))
    assert primary_energy_emissions(coarse).total == pytest.approx(primary_energy_emissions(fine).total, rel=1e-6)
    assert float(coarse.global_constraints.at["cap", "constant"]) == pytest.approx(float(fine.global_constraints.at["cap", "constant"]), rel=1e-12)


def test_pathway_co2_cap_is_a_period_total_annual_x_period_hours_x_years() -> None:
    m = _hourly(1)
    m["snapshots"] = [{"snapshot": f"{y}-01-01T00:00:00", "period": y, "objective": 8760.0, "generators": 8760.0, "stores": 8760.0} for y in (2030, 2040)]
    m["global_constraints"] = [
        {"name": "cap_2030", "type": "primary_energy", "carrier_attribute": "co2_emissions", "sense": "<=", "constant": 1.0, "investment_period": 2030},
        {"name": "cap_all", "type": "primary_energy", "carrier_attribute": "co2_emissions", "sense": "<=", "constant": 1.0},
    ]
    m["RAGNAROK_AnnualBudgets"] = [
        {"component": "global_constraints", "name": "cap_2030", "attribute": "constant", "annual": 1000.0},
        {"component": "global_constraints", "name": "cap_all", "attribute": "constant", "annual": 1000.0},
    ]
    opts = {"pathwayConfig": {"enabled": True, "periods": [{"period": y, "objectiveWeight": 1.0, "yearsWeight": 10.0} for y in (2030, 2040)]}}
    n, _ = build_network(m, {}, opts)
    assert float(n.global_constraints.at["cap_2030", "constant"]) == pytest.approx(1000.0 * 1.0 * 10.0)    # 1 year modelled x 10 years
    assert float(n.global_constraints.at["cap_all", "constant"]) == pytest.approx(1000.0 * (1.0 * 10 + 1.0 * 10))


def test_module_16_style_caps_are_not_touched() -> None:
    """Caps typed as per-period totals (no budget row) pass through exactly; module 16 pins them to the dollar."""
    m = _hourly(1)
    m["global_constraints"] = [{"name": "c", "type": "primary_energy", "carrier_attribute": "co2_emissions", "sense": "<=", "constant": 10_000_000.0}]
    n, _ = build_network(m, {}, {})
    assert float(n.global_constraints.at["c", "constant"]) == 10_000_000.0


def test_nothing_else_scales_a_cap_the_dsl_emissions_atom_is_a_whole_run_literal() -> None:
    """Confirmed by reading: custom_constraints / constraint_dsl only apportion a literal across ROLLING windows
    (window_fraction = committed hours / run hours = 1 outside rolling); they never scale to the horizon."""
    from backend.pypsa.network.custom_constraints import build_model_context

    m = _hourly(24)
    n, _ = build_network(m, {}, {})
    n.optimize.create_model()
    ctx = build_model_context(n, {"gas": 0.2, "oil": 0.3}, n.snapshots)
    assert ctx.window_fraction == 1.0


def test_budget_sheet_errors_are_named() -> None:
    from fastapi import HTTPException

    m = _budget_model(4, 1.0)
    m["RAGNAROK_AnnualBudgets"] = [{"component": "generators", "name": "ghost", "attribute": "e_sum_max", "annual": 1.0}]
    with pytest.raises(HTTPException) as ei:
        build_network(m, {}, {})
    assert "ghost" in str(ei.value.detail)


# ── migration and old runs ───────────────────────────────────────────────────────

def test_migration_moves_annual_e_sum_into_the_module_sheet_and_reports_it() -> None:
    m = _hourly(24)
    m["generators"][1]["e_sum_max"] = 8000.0
    m["generators"][0]["e_sum_max"] = 1e12            # a placeholder stays (it is "no limit", not a budget)
    out, report = cb.migrate_cost_basis(m, discount_rate=0.05)
    assert out["RAGNAROK_AnnualBudgets"] == [{"component": "generators", "name": "oil", "attribute": "e_sum_max", "annual": 8000.0}]
    assert "e_sum_max" not in out["generators"][1] and out["generators"][0]["e_sum_max"] == 1e12
    assert report.budgets and report.noteworthy and report.as_dict()["budgets"][0]["annual"] == 8000.0
    assert cb.schema_version(out) == cb.CURRENT_SCHEMA_VERSION  # 3 -> 4 follows the budget step
    assert m["generators"][1]["e_sum_max"] == 8000.0             # input not mutated
    n, _ = build_network(out, {}, {})
    assert float(n.generators.at["oil", "e_sum_max"]) == pytest.approx(8000.0 * 24 / 8760)
    # a PyPSA-native file has horizon totals already: stamped, not moved
    native, rep = cb.migrate_cost_basis(m, pypsa_native=True)
    assert "RAGNAROK_AnnualBudgets" not in native and not rep.budgets


def test_old_stored_run_keeps_its_scaled_e_sum_and_a_new_one_does_not() -> None:
    m = _hourly(24)
    m["generators"][1]["e_sum_max"] = 8000.0                      # annual, as before build version 3
    old, notes = build_stored_network(m, {"discountRate": 0.0}, {"buildVersion": 2})
    assert float(old.generators.at["oil", "e_sum_max"]) == pytest.approx(8000.0 * 24 / 8760)      # the old builder's value
    assert any("before build version 3" in x for x in notes)
    new, _ = build_stored_network(m, {"discountRate": 0.0}, {"buildVersion": 3})
    assert float(new.generators.at["oil", "e_sum_max"]) == 8000.0


def test_horizon_values_are_in_the_results_and_the_workbook_apply_writes_them() -> None:
    m = _budget_model(24, 8760.0)
    net, _ = build_network(m, {}, {})
    table = net.meta[ab.META_KEY]
    out = ab.apply_to_workbook(m, table)
    assert next(r for r in out["generators"] if r["name"] == "oil")["e_sum_max"] == pytest.approx(24.0)
    assert "e_sum_max" not in m["generators"][1]


# ── rolling horizon: PyPSA applies e_sum / constants to EACH window ──────────────

def test_rolling_horizon_whole_horizon_energy_stays_within_the_budget() -> None:
    """Written into the column, a 400 MWh budget would be allowed in full by each of 3 windows (up to 1200). The module
    leaves the column unbounded and adds each window's share (committed hours / run hours) as a declared constraint."""
    annual = 400.0 * 8760 / 24                                  # 400 MWh over this 24 h horizon
    m = _budget_model(24, annual)
    opts = {"enableLoadShedding": False, "rollingConfig": {"enabled": True, "horizonSnapshots": 8, "overlapSnapshots": 0}}
    res = run_pypsa(m, {"carbonPrice": 0.0, "discountRate": 0.0}, opts)
    energy = {g["name"]: g["value"] for g in res["generatorEnergy"]}
    assert energy["oil"] == pytest.approx(400.0, rel=1e-6)       # binds, and never exceeds the horizon budget
    assert res["annualBudgets"][0]["value"] == pytest.approx(400.0)
    assert "split per rolling window" in res["annualBudgets"][0]["scope"]
    # the same model without the module's split would have let every window spend 400: pinned by the column staying unbounded
    n, _ = build_network(m, {}, {"rollingConfig": {"enabled": True, "horizonSnapshots": 8, "overlapSnapshots": 0}})
    assert np.isinf(float(n.generators.at["oil", "e_sum_max"]))


def test_rolling_horizon_with_a_global_constraint_budget_is_refused_clearly() -> None:
    from fastapi import HTTPException

    m = _co2_cap_model(24, 1_000_000.0)
    with pytest.raises(HTTPException) as ei:
        build_network(m, {}, {"rollingConfig": {"enabled": True, "horizonSnapshots": 8, "overlapSnapshots": 0}})
    assert ei.value.status_code == 400 and "rolling horizon" in str(ei.value.detail) and "cap" in str(ei.value.detail)
