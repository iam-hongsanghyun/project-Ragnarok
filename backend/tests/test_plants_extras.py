"""Plant extras: part-load efficiency, hot / warm / cold start costs, start-up time, and the (zero) H2 derate placeholder.

Hand calculations (CCGT, P = 58 MW_el, min load m = 0.4, eta_f = 0.58, eta_m = 0.52):
    F_f = 58/0.58 = 100 MW_th;  F_m = 0.4 x 58/0.52 = 44.6153846...;  b = (100 - 44.6153846)/(0.6 x 58) = 1.5915119...;  F0 = 100 - 58 b = 7.6923077...
Start tiers (P = 58 MW, hot 60, warm 120, cold 200 EUR/MW; warm after 2 h, cold after 4 h offline, hourly steps): a unit off N hours is charged
    c_hot P for N < 2, c_warm P for 2 <= N < 4, c_cold P for N >= 4   (the objective differs from the no-start-cost run by exactly that).
ASCII: F(P) = F0 + b*P; charged(N) = P * (60 if N<2 else 120 if N<4 else 200).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from fastapi import HTTPException
from numpy.testing import assert_allclose

from backend.app import fragment_merge
from backend.app import module_hooks as mh
from backend.app.plants import catalog, registry
from backend.app.plants import partload as pl
from backend.app.plants import startcosts as sc
from backend.app.plants import technologies as tech
from backend.pypsa.network import build_network
from backend.pypsa.network import time_units as tu

from ._plants_fixtures import SCENARIO, add_plant, grid, stamps

RTOL = 1e-9
P = tech.parameter_defaults()
GAS = 30.0
P_EL = 58.0


def _loads(model: dict[str, Any], load: list[float]) -> dict[str, Any]:
    out = dict(model)
    out["snapshots"] = [{"snapshot": s} for s in stamps(len(load))]
    out["loads-p_set"] = [{"snapshot": s, "demand": v} for s, v in zip(stamps(len(load)), load)]
    return out


def _plant(load: list[float], spec: dict[str, Any], kind: str = "ccgt") -> tuple[dict[str, Any], dict[str, Any]]:
    base = {"pNom": P_EL, "committable": True, "gasPrice": GAS, "params": {"ccgt.min_up_time": 1, "ccgt.min_down_time": 1, "ccgt.vom": 0}}
    return add_plant(_loads(grid(len(load)), load), kind, {**base, **spec})


def _solve(model: dict[str, Any], options: dict[str, Any] | None = None) -> tuple[Any, float, list[str]]:
    """Build the run network and solve it with the composed module hooks (the same path as ``run_pypsa``); returns (n, objective, notes)."""
    options = options or {}
    n, notes = build_network(model, SCENARIO, options)
    ctx = mh.RunContext(model=model, options=options, notes=notes, network=n)
    extra = mh.compose_constraints(ctx)
    status, cond = n.optimize(solver_name="highs", extra_functionality=extra, include_objective_constant=False, log_to_console=False,
                              linearized_unit_commitment=bool(options.get("forceLp")))
    assert status == "ok" and cond == "optimal", (status, cond)
    return n, float(n.objective), ctx.notes


# ── 1. part-load efficiency ─────────────────────────────────────────────────────────────────────────────────


def test_heat_rate_curve_reproduces_fuel_at_min_and_full_load() -> None:
    c = pl.heat_rate_curve(P_EL, 0.4, 0.58, 0.52)
    assert_allclose(c["fuelFullMw"], 100.0, rtol=RTOL)
    assert_allclose(c["fuelMinMw"], 0.4 * 58.0 / 0.52, rtol=RTOL)
    assert_allclose(c["incrementalHeatRate"], (100.0 - 0.4 * 58.0 / 0.52) / (0.6 * 58.0), rtol=RTOL)
    assert_allclose(c["noLoadFuelMw"], 100.0 - c["incrementalHeatRate"] * 58.0, rtol=RTOL)
    assert_allclose(pl.fuel_at(c, 0.4 * P_EL), 0.4 * P_EL / 0.52, rtol=RTOL)         # fuel at min load = P_min / eta_min
    assert_allclose(pl.fuel_at(c, P_EL), P_EL / 0.58, rtol=RTOL)                      # fuel at full load = P / eta_full
    assert_allclose(pl.fuel_at(c, 0.7 * P_EL), c["noLoadFuelMw"] + c["incrementalHeatRate"] * 0.7 * P_EL, rtol=RTOL)
    # a flat efficiency (eta_min = eta_full) has no no-load fuel: F(P) = P/eta
    flat = pl.heat_rate_curve(P_EL, 0.4, 0.58, 0.58)
    assert_allclose(flat["noLoadFuelMw"], 0.0, atol=1e-12)
    assert_allclose(flat["incrementalHeatRate"], 1 / 0.58, rtol=RTOL)


@pytest.mark.parametrize("eta_min, why", [(0.60, "above the full-load"), (0.2, "at or below")])
def test_heat_rate_curve_refuses_an_impossible_pair(eta_min: float, why: str) -> None:
    with pytest.raises(catalog.PlantError, match=why):
        pl.heat_rate_curve(P_EL, 0.4, 0.58, eta_min)


def test_link_curve_rows_are_visible_and_exact() -> None:
    _, built = _plant([58.0], {"minLoadEfficiency": 0.52})
    link = built["fragment"]["sheets"]["links"][0]
    rows = built["fragment"]["sheets"]["links-efficiency-pw"]
    c = pl.heat_rate_curve(P_EL, 0.4, 0.58, 0.52)
    assert [r["name"] for r in rows] == ["ccgt"] * 3
    assert_allclose([r["p_pu"] for r in rows], [0.0, c["fuelMinMw"] / c["fuelFullMw"], 1.0], rtol=RTOL, atol=1e-12)
    assert_allclose([r["efficiency"] for r in rows], [0.0, 0.52, 0.58], rtol=RTOL, atol=1e-12)
    assert_allclose(link["p_nom"], 100.0, rtol=RTOL)                                  # MW_th = F_full
    assert_allclose(link["p_min_pu"], c["fuelMinMw"] / 100.0, rtol=RTOL)             # fuel at min load per unit of p_nom
    # fuel and output at the two breakpoints, read from the written rows: p0 = p_pu x p_nom, p1 = efficiency x p0
    p0 = np.array([r["p_pu"] for r in rows]) * link["p_nom"]
    p1 = np.array([r["efficiency"] for r in rows]) * p0
    assert_allclose(p0[1:], [0.4 * P_EL / 0.52, P_EL / 0.58], rtol=RTOL)
    assert_allclose(p1[1:], [0.4 * P_EL, P_EL], rtol=RTOL)
    row = next(s for s in built["summary"] if s["sheet"] == "links")                  # the derived values are shown in the preview
    assert row["partLoad"]["route"] == "piecewise-link"
    assert_allclose(row["partLoad"]["noLoadFuelMw"], c["noLoadFuelMw"], rtol=1e-8)
    assert built["registry"]["partLoad"]["incrementalHeatRate"] == pytest.approx(c["incrementalHeatRate"], rel=1e-8)


def test_solved_link_burns_the_heat_rate_curve_at_min_and_full_load() -> None:
    c = pl.heat_rate_curve(P_EL, 0.4, 0.58, 0.52)
    for load, p_el in ((0.4 * P_EL, 0.4 * P_EL), (P_EL, P_EL), (0.7 * P_EL, 0.7 * P_EL)):
        model, _ = _plant([load], {"minLoadEfficiency": 0.52})
        n, obj, _ = _solve(model)
        fuel = float(n.links_t.p0["ccgt"].iloc[0])
        # HiGHS feasibility tolerance (1e-7 absolute on rows) limits a solved flow to rtol ~1e-7; the curve itself is checked at 1e-9 above
        assert_allclose(fuel, pl.fuel_at(c, p_el), rtol=1e-7)
        assert_allclose(-float(n.links_t.p1["ccgt"].iloc[0]), p_el, rtol=1e-7)
        assert_allclose(obj, GAS * pl.fuel_at(c, p_el), rtol=1e-7)                    # gas bought = fuel drawn (no-load fuel included)


def test_generator_route_stand_by_plus_incremental_cost_equals_the_curve() -> None:
    spec = {"h2Share": 0.0, "h2ShareUnit": "energy", "h2Price": 100.0, "minLoadEfficiency": 0.52}
    c = pl.heat_rate_curve(P_EL, 0.4, 0.58, 0.52)
    model, built = _plant([0.4 * P_EL], spec, "cofiring_simple")
    gen = model["generators"][0]
    assert_allclose(gen["stand_by_cost"], GAS * c["noLoadFuelMw"], rtol=RTOL)         # EUR/h while committed
    assert_allclose(gen["marginal_cost"], GAS * c["incrementalHeatRate"], rtol=RTOL)  # EUR/MWh_el (VOM 0 here)
    for load in (0.4 * P_EL, P_EL):
        m, _ = _plant([load], spec, "cofiring_simple")
        _, obj, _ = _solve(m)
        assert_allclose(obj, GAS * pl.fuel_at(c, load), rtol=RTOL)                    # fuel cost of the heat-rate line, no-load fuel included
    assert built["summary"][0]["partLoad"]["route"] == "stand-by-generator"


def test_part_load_is_off_by_default_and_needs_a_committable_fixed_unit() -> None:
    _, plain = _plant([58.0], {})
    assert "links-efficiency-pw" not in plain["fragment"]["sheets"] and sc.SHEET not in plain["fragment"]["sheets"]
    assert plain["fragment"]["sheets"]["links"][0]["p_min_pu"] == 0.4 and plain["fragment"]["sheets"]["links"][0]["p_nom"] == 100.0
    _, off = _plant([58.0], {"committable": False, "minLoadEfficiency": 0.52})
    assert "links-efficiency-pw" not in off["fragment"]["sheets"] and any("not applied" in w for w in off["warnings"])
    _, ext = _plant([58.0], {"extendable": True, "minLoadEfficiency": 0.52})
    assert "links-efficiency-pw" not in ext["fragment"]["sheets"]


def test_part_load_curve_follows_a_plant_edit_and_leaves_with_a_delete() -> None:
    model, _ = _plant([58.0], {"minLoadEfficiency": 0.52})
    change = catalog.edit_plant(model, "ccgt", {"minLoadEfficiency": 0.50})
    edited = registry.apply_change(model, change)
    rows = edited["links-efficiency-pw"]
    assert len(rows) == 3 and [r["efficiency"] for r in rows][1] == 0.5                  # replaced, not appended
    gone = registry.apply_change(edited, registry.delete_change(edited, "ccgt"))
    assert gone.get("links-efficiency-pw") == [] and not gone.get("links")


def test_pw_rows_keep_their_breakpoints_through_a_merge() -> None:
    """The name-dedupe must not rename the 2nd and 3rd breakpoint of one curve."""
    model, _ = _plant([58.0], {"minLoadEfficiency": 0.52})
    assert [r["name"] for r in model["links-efficiency-pw"]] == ["ccgt"] * 3
    again = fragment_merge.merge_fragment(model, {"sheets": {"links-efficiency-pw": [{"name": "ccgt", "breakpoint": 0, "p_pu": 0.0, "efficiency": 0.0},
                                                                              {"name": "ccgt", "breakpoint": 1, "p_pu": 1.0, "efficiency": 0.5}]}})
    assert [r["name"] for r in again["links-efficiency-pw"]] == ["ccgt"] * 2


# ── 2. hot / warm / cold start costs ────────────────────────────────────────────────────────────────────────

TIERS = {"startCostHot": 60.0, "startCostWarm": 120.0, "startWarmAfterHours": 2.0, "startCostCold": 200.0, "startColdAfterHours": 4.0}
NO_START = {"startCostHot": 0.0}


def _off_for(n_off: int) -> list[float]:
    return [58.0] + [0.0] * n_off + [58.0, 58.0]


@pytest.mark.parametrize("n_off, per_mw", [(1, 60.0), (2, 120.0), (3, 120.0), (4, 200.0), (6, 200.0)])
def test_charged_start_cost_is_the_tier_of_the_offline_duration(n_off: int, per_mw: float) -> None:
    load = _off_for(n_off)
    m_tiers, built = _plant(load, TIERS)
    m_zero, _ = _plant(load, NO_START)
    n, obj_tiers, notes = _solve(m_tiers)
    _, obj_zero, _ = _solve(m_zero)
    assert int(n.links_t.start_up["ccgt"].sum()) == 1
    assert_allclose(obj_tiers - obj_zero, per_mw * P_EL, rtol=1e-7)                      # one start, charged exactly its tier (native hot + increment)
    assert any("Start-cost tiers (plants module)" in x for x in notes)                    # declared in the run notes
    assert built["fragment"]["sheets"]["links"][0]["start_up_cost"] == 60.0 * P_EL        # native = HOT, so nothing is counted twice


def test_hot_only_run_without_the_hook_rows_is_the_native_cost() -> None:
    m, built = _plant(_off_for(6), {"startCostHot": 60.0})
    assert sc.SHEET not in built["fragment"]["sheets"]
    _, obj, notes = _solve(m)
    m0, _ = _plant(_off_for(6), NO_START)
    _, obj0, _ = _solve(m0)
    assert_allclose(obj - obj0, 60.0 * P_EL, rtol=1e-7)
    assert not any("Start-cost tiers" in x for x in notes)


def test_tier_thresholds_follow_the_run_step_through_the_time_units_module() -> None:
    """2 h = 4 half-hour snapshots: a unit off 3 half-hours (1.5 h) restarts hot, off 4 (2 h) restarts warm."""
    for n_off, per_mw in ((3, 60.0), (4, 120.0)):
        load = _off_for(n_off)
        out = []
        for spec in (TIERS, NO_START):
            m, _ = _plant(load, spec)
            m["snapshots"] = [{"snapshot": s, "objective": 0.5, "stores": 0.5, "generators": 0.5} for s in stamps(len(load))]
            out.append(_solve(m))
        assert_allclose(out[0][1] - out[1][1], per_mw * P_EL, rtol=1e-7)
        assert any("0.5 h step" in x or "snapshot(s) off" in x for x in out[0][2])


def test_pre_horizon_history_and_classification_helpers() -> None:
    assert list(sc.pre_horizon_status(3, 0, 5)) == [1, 1, 1, 0, 0]          # PyPSA: on for lag <= up_time_before
    assert list(sc.pre_horizon_status(0, 2, 5)) == [0, 0, 1, 1, 1]          # off for lag <= down_time_before, on beyond
    # statuses 1 0 0 1 | 0 0 0 0 1 : the first start follows 2 snapshots off, the second 4
    assert sc.classify_starts(np.array([1, 0, 0, 1, 0, 0, 0, 0, 1]), [2, 4], up_time_before=1) == [1, 2]
    assert sc.classify_starts(np.array([0, 0, 1]), [2, 4], up_time_before=0, down_time_before=3) == [2]   # 3 down before + 2 in the horizon = 5 off >= 4: cold


def test_down_time_before_makes_the_first_start_warm() -> None:
    m, _ = _plant([0.0, 0.0, 58.0, 58.0], TIERS)
    for r in m["RAGNAROK_TimeUnits"]:
        if r["attribute"] == "up_time_before":
            r["value"] = 0.0
    m["RAGNAROK_TimeUnits"] += [{"component": "links", "name": "ccgt", "attribute": "down_time_before", "value": 3.0, "unit": "hours"}]
    m0, _ = _plant([0.0, 0.0, 58.0, 58.0], NO_START)
    for r in m0["RAGNAROK_TimeUnits"]:
        if r["attribute"] == "up_time_before":
            r["value"] = 0.0
    m0["RAGNAROK_TimeUnits"] += [{"component": "links", "name": "ccgt", "attribute": "down_time_before", "value": 3.0, "unit": "hours"}]
    _, a, _ = _solve(m)
    _, b, _ = _solve(m0)
    # 3 h down before + 2 h in the horizon = 5 h offline at the start: cold (>= 4 h)
    assert_allclose(a - b, 200.0 * P_EL, rtol=1e-7)


def test_tiers_are_a_consistent_relaxation_under_force_lp() -> None:
    m, _ = _plant(_off_for(3), TIERS)
    _, obj, notes = _solve(m, {"forceLp": True})
    assert any("Force-LP" in x for x in notes)
    m0, _ = _plant(_off_for(3), NO_START)
    _, obj0, _ = _solve(m0, {"forceLp": True})
    assert 0.0 <= obj - obj0 <= 120.0 * P_EL + 1e-6                                     # never above the MIP charge


@pytest.mark.parametrize("bad", [
    {"startCostWarm": 120.0},                                         # no warm threshold
    {"startCostWarm": 50.0, "startWarmAfterHours": 2.0},              # below the hot cost (60)
    {"startCostWarm": 120.0, "startWarmAfterHours": 5.0, "startCostCold": 200.0, "startColdAfterHours": 4.0},   # thresholds not rising
])
def test_bad_tier_inputs_are_refused_at_build_time(bad: dict[str, float]) -> None:
    with pytest.raises(catalog.PlantError):
        _plant([58.0], {"startCostHot": 60.0, **bad})


def _ctx(model: dict[str, Any], **kw: Any) -> mh.RunContext:
    return mh.RunContext(model=model, options={}, notes=[], **kw)


def test_hook_refuses_modes_that_break_adjacency_and_a_bad_sheet() -> None:
    m, _ = _plant(_off_for(2), TIERS)
    from backend.app.plants import hooks
    for kw in ({"rolling": SimpleNamespace(enabled=True)}, {"stochastic": SimpleNamespace(enabled=True)}, {"sampling": SimpleNamespace(enabled=True)},
               {"pathway": SimpleNamespace(enabled=True)}):
        with pytest.raises(HTTPException) as e:
            hooks._prepare_start_costs(_ctx(m, **kw))
        assert e.value.status_code == 400 and "RAGNAROK_StartCosts" in e.value.detail
    bad = {**m, sc.SHEET: [{"component": "links", "name": "ccgt", "attribute": "warm_cost", "value": 1.0, "unit": "currency_per_start"}]}
    with pytest.raises(HTTPException):
        hooks._prepare_start_costs(_ctx(bad))                      # warm cost without its threshold
    assert hooks._prepare_start_costs(_ctx({"links": []})) is None  # no rows: the hook is silent


def test_start_cost_rows_leave_with_their_plant() -> None:
    m, _ = _plant(_off_for(2), TIERS)
    assert {r["attribute"] for r in m[sc.SHEET]} == {"hot_cost", "warm_cost", "warm_after", "cold_cost", "cold_after"}
    gone = registry.apply_change(m, registry.delete_change(m, "ccgt"))
    assert gone[sc.SHEET] == []


# ── 3. start-up time through PyPSA's native ramp_limit_start_up ─────────────────────────────────────────────


def test_start_up_time_is_a_time_units_row_converted_with_the_run_step() -> None:
    m, built = _plant([58.0, 58.0], {"startUpMinutes": 15.0, "shutDownMinutes": 30.0})
    link = built["fragment"]["sheets"]["links"][0]
    assert "ramp_limit_start_up" not in link and "ramp_limit_shut_down" not in link              # no per-snapshot number in the component row
    rows = {r["attribute"]: r for r in m["RAGNAROK_TimeUnits"]}
    assert rows["ramp_limit_start_up"]["unit"] == "per_minute"
    assert_allclose(rows["ramp_limit_start_up"]["value"], 0.4 / 15.0, rtol=RTOL)                  # reaches the minimum load (0.4) in 15 min
    assert_allclose(rows["ramp_limit_shut_down"]["value"], 0.4 / 30.0, rtol=RTOL)
    # PyPSA value = min(1, rate x w), never below p_min_pu (0.4); start rate 0.4/15 per min = 1.6/h, shut-down 0.4/30 per min = 0.8/h
    for step_h, start, shut in ((1.0, None, 0.8), (0.25, 0.4, 0.4)):
        mm = dict(m)
        mm["snapshots"] = [{"snapshot": s, "objective": step_h, "stores": step_h, "generators": step_h} for s in stamps(2)]
        n, _ = build_network(mm, SCENARIO, {})
        if start is None:
            assert np.isnan(n.links.at["ccgt", "ramp_limit_start_up"]) or n.links.at["ccgt", "ramp_limit_start_up"] == 1.0   # 1.6 >= 1: blank (no bound)
        else:
            assert_allclose(n.links.at["ccgt", "ramp_limit_start_up"], start, rtol=1e-9)
        assert_allclose(n.links.at["ccgt", "ramp_limit_shut_down"], shut, rtol=1e-9)


def test_start_up_time_bounds_the_start_snapshot_with_the_native_constraint() -> None:
    # 0.4 of p_nom in 40 min = 0.6 per hour: at a 1 h step the start snapshot may carry at most 0.6 x p_nom = 60 MW_th = 34.8 MW_el
    m, _ = _plant([0.0, 30.0, 58.0, 58.0], {"startUpMinutes": 40.0})
    n, _, _ = _solve(m)
    assert_allclose(n.links.at["ccgt", "ramp_limit_start_up"], 0.6, rtol=1e-9)
    assert float(n.links_t.p0["ccgt"].iloc[1]) <= 0.6 * float(n.links.at["ccgt", "p_nom"]) + 1e-6
    # a demand of 40 MW_el in the start snapshot (69 MW_th) is above that bound: PyPSA's own constraint makes it infeasible
    tight, _ = _plant([0.0, 40.0, 58.0, 58.0], {"startUpMinutes": 40.0})
    net, _ = build_network(tight, SCENARIO, {})
    _, cond = net.optimize(solver_name="highs", log_to_console=False, include_objective_constant=False)
    assert cond == "infeasible"


# ── 4. H2 co-firing derate: no citable source, so a documented zero ──────────────────────────────────────────


def test_h2_derate_is_a_documented_zero_assumption() -> None:
    cat = tech.catalogue()
    for key in ("h2_derate_efficiency_per_share", "h2_derate_capacity_per_share"):
        p = cat["fuels"][key]
        assert p["value"] == 0.0 and p["verified"] == "assumption" and "2026-10-29" in p["source"]["locator"]
    _, built = _plant([58.0], {"h2Share": 0.3, "h2ShareUnit": "vol", "h2Price": 100.0}, "cofiring_simple")
    assert built["registry"]["derate"]["applied"] is False


def test_defaults_do_not_change_an_existing_plant() -> None:
    """A CCGT / cofiring plant with none of the new keys carries exactly the legacy rows (no new sheet, no new column)."""
    _, ccgt = add_plant(grid(), "ccgt", {"pNom": 400, "committable": True})
    assert set(ccgt["fragment"]["sheets"]) == {"buses", "carriers", "generators", "links", "RAGNAROK_TimeUnits", "RAGNAROK_PLANTS", "RAGNAROK_Composites"}
    link = ccgt["fragment"]["sheets"]["links"][0]
    assert link["p_min_pu"] == 0.4 and link["start_up_cost"] == 24000.0 and link["efficiency"] == 0.58 and "stand_by_cost" not in link
    assert {r["attribute"] for r in ccgt["fragment"]["sheets"]["RAGNAROK_TimeUnits"]} == {"min_up_time", "min_down_time", "up_time_before", "ramp_limit_up", "ramp_limit_down"}
    _, cof = add_plant(grid(), "cofiring_simple", {"pNom": 100, "committable": True, "h2Share": 0.2, "h2ShareUnit": "energy"})
    gen = cof["fragment"]["sheets"]["generators"][0]
    assert "stand_by_cost" not in gen and "partLoad" not in cof["registry"] and "startCosts" not in cof["registry"]


def test_time_units_convert_is_the_single_conversion() -> None:
    counts, _ = sc.snapshot_thresholds([2.0, 4.0], 0.5, "u", "links")
    assert counts == [4, 8]
    counts, notes = sc.snapshot_thresholds([2.5], 1.0, "u", "links")
    assert counts == [3] and notes and tu.SHEET == "RAGNAROK_TimeUnits"


# ── results by plant ────────────────────────────────────────────────────────────────────────────────────────


def test_plant_results_report_the_start_tier_and_its_cost() -> None:
    from backend.app.plants import results as pr
    from backend.pypsa.results import run_pypsa

    from ._plants_fixtures import bundle

    for n_off, tier, per_mw in ((1, "hot", 60.0), (3, "warm", 120.0), (5, "cold", 200.0)):
        m, _ = _plant(_off_for(n_off), TIERS)
        res = run_pypsa(m, SCENARIO, {})
        out = pr.plant_results(bundle(m, res))["plants"][0]
        sc_out = out["startCosts"]
        assert sc_out["starts"] == {"hot": 0, "warm": 0, "cold": 0, tier: 1}
        assert_allclose(sc_out["startCost"], per_mw * P_EL, rtol=RTOL)
        assert_allclose(sc_out["nativeStartUpCost"], 60.0 * P_EL, rtol=RTOL)
        assert_allclose(sc_out["tierIncrement"], (per_mw - 60.0) * P_EL, atol=1e-9)
        assert_allclose(out["commitmentCost"], per_mw * P_EL, rtol=RTOL)
        assert "cofiring" not in out                                   # a plain turbine has no blend: the UI shows a dash, not "H2 0 %; avoided 0 t"
        assert out["emissions"]["avoidedT"] == 0.0


def test_plant_results_report_the_stand_by_cost_of_the_generator_route() -> None:
    from backend.app.plants import results as pr
    from backend.pypsa.results import run_pypsa

    from ._plants_fixtures import bundle

    spec = {"h2Share": 0.0, "h2ShareUnit": "energy", "minLoadEfficiency": 0.52}
    m, _ = _plant([40.0, 40.0, 40.0], spec, "cofiring_simple")
    res = run_pypsa(m, SCENARIO, {})
    out = pr.plant_results(bundle(m, res))["plants"][0]
    c = pl.heat_rate_curve(P_EL, 0.4, 0.58, 0.52)
    assert_allclose(out["standByCost"], 3 * GAS * c["noLoadFuelMw"], rtol=1e-9)             # 3 committed hours x currency/h
    assert_allclose(out["commitmentCost"], out["standByCost"], rtol=1e-12)
