"""The training course promises specific answers. This proves it still gets them.

Every module of "Power market modelling with Ragnarok" asks the learner to
reconcile an objective value by hand — 12,000 in module 1, then 7,500, 11,700 and
8,980 through module 2. Those numbers are printed in the course prose and in the
walkthrough callouts, so a change to the network builder that shifts an objective
by 1% silently turns the whole course into a liar.

The bundled checkpoints (``backend/data/examples/training_m*/project.db``) are the
end state of each module, so solving them through the app's own path — example db
→ session model → ``build_network`` → HiGHS — checks two things at once: the
checkpoint holds the model the course describes, and Ragnarok still answers what
the course says it answers.

Authored by ``scripts/author_training_checkpoint.py``, which documents the file
format.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from backend.app import sqlite_store
from backend.pypsa.network import build_network

EXAMPLES = Path(__file__).resolve().parent.parent / "data" / "examples"
SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.0}
OPTIONS = {"enableLoadShedding": False, "currencySymbol": "$"}


def _model_from_example(example_id: str, tmp_path: Path) -> dict:
    """Read a bundled example the way ``/api/examples`` load does: copy its
    project.db into a session directory, then read the full model back out."""
    session_id = f"test_{example_id}"
    dest = tmp_path / session_id
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXAMPLES / example_id / "project.db", dest / "project.db")

    original = sqlite_store.ss.SESSION_DIR
    sqlite_store.ss.SESSION_DIR = tmp_path
    try:
        model = sqlite_store.load_full_model(session_id)
    finally:
        sqlite_store.ss.SESSION_DIR = original
    assert model is not None, f"{example_id}: session model came back empty"
    return model


def _solved(example_id: str, tmp_path: Path, scenario: dict | None = None):
    model = _model_from_example(example_id, tmp_path)
    n, _notes = build_network(model, scenario or SCENARIO, OPTIONS)
    n.optimize(solver_name="highs")
    return n


# ── Module 1 — the smallest model that solves ────────────────────────────────

def test_module_1_checkpoint_solves_to_12000(tmp_path: Path) -> None:
    """240 MWh at 50/MWh from the single gas unit. The course derives this by hand."""
    n = _solved("training_m1", tmp_path)
    assert float(n.objective) == pytest.approx(12_000.0, rel=1e-6)
    assert float(n.buses_t.marginal_price["bus_1"].mean()) == pytest.approx(50.0, rel=1e-6)


# ── Module 2 — economic dispatch ─────────────────────────────────────────────

def test_module_2_checkpoint_solves_to_8980(tmp_path: Path) -> None:
    """The end state of module 2: four units, a demand profile and wind availability."""
    n = _solved("training_m2", tmp_path)
    assert float(n.objective) == pytest.approx(8_980.0, rel=1e-6)


def test_module_2_prices_are_zero_fifty_onetwenty(tmp_path: Path) -> None:
    """Three hours, three marginal units — wind, gas, then the oil peaker.

    This is the step-15 lesson: the price is the marginal unit's cost, and a free
    marginal unit means a zero price.
    """
    n = _solved("training_m2", tmp_path)
    prices = [float(v) for v in n.buses_t.marginal_price["bus_1"]]
    assert prices == pytest.approx([0.0, 50.0, 120.0], abs=1e-6)


def test_module_2_curtails_14_mwh_of_wind_in_the_first_hour(tmp_path: Path) -> None:
    """0.9 x 60 MW is available against 40 MW of demand, so 14 MWh goes untaken."""
    n = _solved("training_m2", tmp_path)
    available = n.generators.at["wind_1", "p_nom"] * n.generators_t.p_max_pu["wind_1"]
    curtailed = (available - n.generators_t.p["wind_1"]).round(6)
    assert float(curtailed.iloc[0]) == pytest.approx(14.0, abs=1e-6)
    assert float(curtailed.iloc[1:].sum()) == pytest.approx(0.0, abs=1e-6)


def test_module_2_demand_profile_overrides_the_static_p_set(tmp_path: Path) -> None:
    """The course tells the learner to leave the static 80 MW in place.

    If the static value won instead of the profile, every objective and price in
    steps 11 onwards would be wrong — so assert both that the static value is
    still there and that it is not the one being served.
    """
    model = _model_from_example("training_m2", tmp_path)
    assert model["loads"][0]["p_set"] == 80.0
    n = _solved("training_m2", tmp_path)
    served = [float(v) for v in n.loads_t.p["load_1"]]
    assert served == pytest.approx([40.0, 80.0, 170.0], abs=1e-6)


# ── The mid-module answers the course also asks the learner to reconcile ─────
# Module 2 has three solves in it, and only the last one has a checkpoint. The
# other two are derived from that checkpoint by removing what had not been added
# yet, so they cannot drift away from the data the learner is actually given.

def _without(model: dict, *, generators: tuple[str, ...], sheets: tuple[str, ...]) -> dict:
    trimmed = {k: v for k, v in model.items() if k not in sheets}
    trimmed["generators"] = [g for g in model["generators"] if g["name"] not in generators]
    return trimmed


def _solve_model(model: dict, scenario: dict | None = None):
    n, _notes = build_network(model, scenario or SCENARIO, OPTIONS)
    n.optimize(solver_name="highs")
    return n


def test_module_2_step_8_solves_to_7500(tmp_path: Path) -> None:
    """Coal added to module 1's gas unit, demand still flat at 80 MW.

    The step-8 hand-check: coal 50 at 20 plus gas 30 at 50 is 2,500 an hour, so
    7,500 over three — against module 1's 12,000 for the same demand.
    """
    model = _without(
        _model_from_example("training_m2", tmp_path),
        generators=("oil_1", "wind_1"),
        sheets=("loads-p_set", "generators-p_max_pu"),
    )
    n = _solve_model(model)
    assert float(n.objective) == pytest.approx(7_500.0, rel=1e-6)
    assert [float(v) for v in n.buses_t.marginal_price["bus_1"]] == pytest.approx([50.0] * 3, abs=1e-6)


def test_module_2_step_10_peaker_changes_nothing(tmp_path: Path) -> None:
    """Adding the oil peaker at flat 80 MW demand leaves cost and price untouched.

    The step-10 lesson: in a dispatch model, capacity you do not use is free.
    """
    model = _without(
        _model_from_example("training_m2", tmp_path),
        generators=("wind_1",),
        sheets=("loads-p_set", "generators-p_max_pu"),
    )
    n = _solve_model(model)
    assert float(n.objective) == pytest.approx(7_500.0, rel=1e-6)
    assert float(n.generators_t.p["oil_1"].sum()) == pytest.approx(0.0, abs=1e-6)


def test_module_2_step_12_solves_to_11700(tmp_path: Path) -> None:
    """The demand profile in, wind not yet: three hours, three marginal units."""
    model = _without(
        _model_from_example("training_m2", tmp_path),
        generators=("wind_1",),
        sheets=("generators-p_max_pu",),
    )
    n = _solve_model(model)
    assert float(n.objective) == pytest.approx(11_700.0, rel=1e-6)
    prices = [float(v) for v in n.buses_t.marginal_price["bus_1"]]
    assert prices == pytest.approx([20.0, 50.0, 120.0], abs=1e-6)


# ── Module 3 — networks and congestion ───────────────────────────────────────

def test_module_3_checkpoint_solves_to_9400(tmp_path: Path) -> None:
    """Two buses, one 60 MW line. The same fleet and demand as module 2, which
    answered 8,980 — the 420 difference is the network."""
    n = _solved("training_m3", tmp_path)
    assert float(n.objective) == pytest.approx(9_400.0, rel=1e-6)


def test_module_3_congested_hour_has_two_prices(tmp_path: Path) -> None:
    """The whole module: a binding line lets the two buses price differently.

    Hours 1 and 3 agree (the line is not binding); hour 2 splits 20 / 50 because
    the line is full and nothing more can cross.
    """
    n = _solved("training_m3", tmp_path)
    bus_1 = [float(v) for v in n.buses_t.marginal_price["bus_1"]]
    bus_2 = [float(v) for v in n.buses_t.marginal_price["bus_2"]]
    assert bus_1 == pytest.approx([0.0, 20.0, 120.0], abs=1e-6)
    assert bus_2 == pytest.approx([0.0, 50.0, 120.0], abs=1e-6)


def test_module_3_line_is_full_only_in_the_middle_hour(tmp_path: Path) -> None:
    """40 / 60 / 56 against a 60 MW rating — congested once, nearly-full once.

    The step-7 lesson is exactly this distinction: hour 3 at 56 MW is 93% loaded
    and NOT congested, which is why its prices agree.
    """
    n = _solved("training_m3", tmp_path)
    flow = [abs(float(v)) for v in n.lines_t.p0["line_1"]]
    assert flow == pytest.approx([40.0, 60.0, 56.0], abs=1e-6)


def test_module_3_congestion_rent_is_1800(tmp_path: Path) -> None:
    """Flow across the line times the price difference across it, summed."""
    n = _solved("training_m3", tmp_path)
    gap = n.buses_t.marginal_price["bus_2"] - n.buses_t.marginal_price["bus_1"]
    rent = float((gap * n.lines_t.p0["line_1"].abs()).sum())
    assert rent == pytest.approx(1_800.0, abs=1e-6)


def test_module_3_uprating_the_line_returns_module_2s_answer(tmp_path: Path) -> None:
    """The closing move of the module, and its whole point.

    A line big enough never to bind IS a single bus, so widening it recovers the
    copper-plate answer exactly — and the difference is what the constraint costs.
    """
    model = _model_from_example("training_m3", tmp_path)
    model["lines"] = [{**model["lines"][0], "s_nom": 100.0}]
    n = _solve_model(model)
    assert float(n.objective) == pytest.approx(8_980.0, rel=1e-6)

    congested = _solved("training_m3", tmp_path)
    assert float(congested.objective - n.objective) == pytest.approx(420.0, abs=1e-6)


# ── Module 4 — storage and time coupling ─────────────────────────────────────

def _with_storage(model: dict, **overrides) -> dict:
    return {**model, "storage_units": [{**model["storage_units"][0], **overrides}]}


def test_module_4_checkpoint_solves_to_7730(tmp_path: Path) -> None:
    """Module 3's congested network plus a 20 MW / 1 h battery at 90% each way."""
    n = _solved("training_m4", tmp_path)
    assert float(n.objective) == pytest.approx(7_730.0, rel=1e-6)


def test_module_4_battery_removes_the_peaker_entirely(tmp_path: Path) -> None:
    """The headline of the module: 20 MWh of storage displaces a 40 MW oil unit,
    and the peak price falls from 120 to 50 because it is no longer marginal."""
    n = _solved("training_m4", tmp_path)
    assert float(n.generators_t.p["oil_1"].sum()) == pytest.approx(0.0, abs=1e-6)
    prices = [float(v) for v in n.buses_t.marginal_price["bus_2"]]
    assert prices == pytest.approx([20.0, 50.0, 50.0], abs=1e-6)


def test_module_4_state_of_charge_closes_the_loop(tmp_path: Path) -> None:
    """Cyclic operation: what comes out went in, and the ends match.

    At 90% charging efficiency 20 MW for an hour puts 18 MWh in the store, which
    is the step-6 arithmetic the course asks the learner to check.
    """
    n = _solved("training_m4", tmp_path)
    soc = [float(v) for v in n.storage_units_t.state_of_charge["batt_1"]]
    assert soc[0] == pytest.approx(18.0, abs=1e-6)
    assert soc[-1] == pytest.approx(0.0, abs=1e-6)
    assert max(soc) <= 20.0 + 1e-6      # never above p_nom x max_hours
    assert min(soc) >= -1e-6            # and never negative


def test_module_4_step_4_lossless_battery_solves_to_7540(tmp_path: Path) -> None:
    """The hand-checkable first run: 120 + 1,720 + 5,700, with no losses."""
    model = _with_storage(
        _model_from_example("training_m4", tmp_path),
        efficiency_store=1.0, efficiency_dispatch=1.0,
    )
    n = _solve_model(model)
    assert float(n.objective) == pytest.approx(7_540.0, rel=1e-6)
    # Only the robust facts. With no losses, hours 2 and 3 both price at 50, so
    # WHEN the battery discharges between them is a degenerate choice — several
    # schedules cost exactly 7,540 and the solver may return any of them. It
    # fills in the cheap hour and ends empty in all of them; the middle value is
    # not determined, and the course says so rather than asserting one.
    soc = [float(v) for v in n.storage_units_t.state_of_charge["batt_1"]]
    assert soc[0] == pytest.approx(20.0, abs=1e-6)
    assert soc[-1] == pytest.approx(0.0, abs=1e-6)
    assert max(soc) <= 20.0 + 1e-6


def test_module_4_step_7_halving_the_energy_costs_more_than_the_losses(tmp_path: Path) -> None:
    """Energy and power are different limits, and duration was the valuable half.

    Halving max_hours costs 590; the round-trip losses cost 190. The course makes
    a point of that ordering because it is not most people's intuition.
    """
    model = _with_storage(_model_from_example("training_m4", tmp_path), max_hours=0.5)
    n = _solve_model(model)
    assert float(n.objective) == pytest.approx(8_320.0, rel=1e-6)
    # The peaker is back, which is why the peak price returns to 120.
    assert float(n.generators_t.p["oil_1"].sum()) > 0.0
    assert float(n.buses_t.marginal_price["bus_2"].iloc[-1]) == pytest.approx(120.0, abs=1e-6)


def test_module_4_step_8_placement_is_worth_more_than_the_battery(tmp_path: Path) -> None:
    """The same battery behind the constraint is worth about a third as much.

    7,730 at the demand end against 8,773.20 at the generation end — 1,043 of
    difference from one cell, which is the module's closing argument.
    """
    model = _with_storage(_model_from_example("training_m4", tmp_path), bus="bus_1")
    n = _solve_model(model)
    assert float(n.objective) == pytest.approx(8_773.2, rel=1e-6)
    at_demand = _solved("training_m4", tmp_path)
    assert float(n.objective - at_demand.objective) == pytest.approx(1_043.2, abs=1e-2)


# ── Module 5 — sector coupling and fuel supply ───────────────────────────────

def test_module_5_checkpoint_solves_to_7099(tmp_path: Path) -> None:
    """Gas on its own bus, a CCGT Link, a gas store, run-of-river and pumped hydro."""
    n = _solved("training_m5", tmp_path)
    assert float(n.objective) == pytest.approx(7_099.59, abs=0.01)


def test_module_5_gas_plant_is_a_link_not_a_generator(tmp_path: Path) -> None:
    """The rewire: gas_1 is gone, and a Link converts fuel into power at 50%.

    p_nom is measured on the fuel side, so 200 MW of gas is a 100 MW station —
    the step-4 trap the course warns about.
    """
    model = _model_from_example("training_m5", tmp_path)
    assert not any(g["name"] == "gas_1" for g in model["generators"])
    link = model["links"][0]
    assert (link["bus0"], link["bus1"]) == ("bus_gas", "bus_2")
    assert link["efficiency"] == 0.5 and link["p_nom"] == 200.0


def test_module_5_rewire_reproduces_module_4s_answer(tmp_path: Path) -> None:
    """The module's keystone: 25/MWh of gas through a 50% converter IS 50/MWh of
    electricity, so an uncapped, store-free rewire must return module 4's 7,730.

    A refactor that changes the answer changed the model — that is the whole
    point of step 5, so it is worth a test rather than a promise.
    """
    model = _model_from_example("training_m5", tmp_path)
    model = {k: v for k, v in model.items() if k != "stores"}
    model["generators"] = [
        {**g, "p_nom": 10_000.0} if g["name"] == "gas_supply" else g
        for g in model["generators"] if g["name"] != "ror_1"
    ]
    model["storage_units"] = [s for s in model["storage_units"] if s["name"] != "phs_1"]
    model["generators-p_max_pu"] = [
        {k: v for k, v in row.items() if k != "ror_1"} for row in model["generators-p_max_pu"]
    ]
    n = _solve_model(model)
    assert float(n.objective) == pytest.approx(7_730.0, rel=1e-6)


def test_module_5_capped_import_brings_the_peaker_back(tmp_path: Path) -> None:
    """Step 7: a fuel shortage is an adequacy problem a power-only model cannot see.

    Without the gas store, the 150 MW import binds in the peak hour, the CCGT can
    only make 75 MW, and oil covers the rest at 120.
    """
    model = _model_from_example("training_m5", tmp_path)
    model = {k: v for k, v in model.items() if k != "stores"}
    model["generators"] = [g for g in model["generators"] if g["name"] != "ror_1"]
    model["storage_units"] = [s for s in model["storage_units"] if s["name"] != "phs_1"]
    model["generators-p_max_pu"] = [
        {k: v for k, v in row.items() if k != "ror_1"} for row in model["generators-p_max_pu"]
    ]
    n = _solve_model(model)
    assert float(n.objective) == pytest.approx(9_221.11, abs=0.01)
    assert float(n.generators_t.p["oil_1"].sum()) > 0.0
    # Scarcity, not a price rise: the fuel still costs 25, but gas is worth more.
    gas_price = [float(v) for v in n.buses_t.marginal_price["bus_gas"]]
    assert gas_price[-1] == pytest.approx(60.0, abs=1e-6)
    assert gas_price[0] == pytest.approx(25.0, abs=1e-6)


def test_module_5_gas_store_neutralises_the_import_cap(tmp_path: Path) -> None:
    """Step 8: buy fuel in the quiet hour, burn it in the peak — 7,730 recovered."""
    model = _model_from_example("training_m5", tmp_path)
    model["generators"] = [g for g in model["generators"] if g["name"] != "ror_1"]
    model["storage_units"] = [s for s in model["storage_units"] if s["name"] != "phs_1"]
    model["generators-p_max_pu"] = [
        {k: v for k, v in row.items() if k != "ror_1"} for row in model["generators-p_max_pu"]
    ]
    n = _solve_model(model)
    assert float(n.objective) == pytest.approx(7_730.0, rel=1e-6)
    assert float(n.generators_t.p["oil_1"].sum()) == pytest.approx(0.0, abs=1e-6)


def test_module_5_pumped_hydro_behind_the_constraint_is_nearly_worthless(tmp_path: Path) -> None:
    """The module's sharpest result, and the reason it is worth a test.

    180 MWh of pumped hydro at bus_1 adds about 45. Module 4's 20 MWh battery at
    the demand end added 1,670 — nine times the energy, a fraction of the value,
    because pumped hydro is where the mountains are.
    """
    with_phs = _solved("training_m5", tmp_path)
    model = _model_from_example("training_m5", tmp_path)
    model["storage_units"] = [s for s in model["storage_units"] if s["name"] != "phs_1"]
    without = _solve_model(model)
    added = float(without.objective - with_phs.objective)
    assert added == pytest.approx(45.41, abs=0.5)
    assert added < 100.0, "180 MWh behind the constraint should be worth very little"


# ── Module 6 — time: resolution and horizon ──────────────────────────────────

def test_module_6_checkpoint_is_a_real_day(tmp_path: Path) -> None:
    """Module 5's components on a 24-hour axis with rebuilt profiles."""
    n = _solved("training_m6", tmp_path)
    assert len(n.snapshots) == 24
    assert float(n.objective) == pytest.approx(52_663.98, abs=0.01)


def test_module_6_profiles_cover_every_snapshot(tmp_path: Path) -> None:
    """The failure the module walks the learner into deliberately.

    A profile shorter than the axis does not error — the missing hours fall back
    to the static attribute and the model solves. The checkpoint must not have
    that defect, so assert both profiles are the full 24 rows.
    """
    model = _model_from_example("training_m6", tmp_path)
    assert len(model["snapshots"]) == 24
    assert len(model["loads-p_set"]) == 24
    assert len(model["generators-p_max_pu"]) == 24


def test_module_6_a_day_lets_pumped_hydro_earn(tmp_path: Path) -> None:
    """The module's whole argument, and a correction the course makes of itself.

    Module 5 measured phs_1 at 45.41 over three hours and called it nearly
    worthless. Over a full daily cycle the same 30 MW / 180 MWh scheme, in the
    same place, behind the same congested line, is worth about 1,026.
    """
    with_phs = _solved("training_m6", tmp_path)
    model = _model_from_example("training_m6", tmp_path)
    model["storage_units"] = [s for s in model["storage_units"] if s["name"] != "phs_1"]
    without = _solve_model(model)
    worth = float(without.objective - with_phs.objective)
    assert worth == pytest.approx(1_026.02, abs=1.0)
    assert worth > 20 * 45.41, "a day should be worth far more than the three-hour figure"


def test_module_6_coarsening_error_is_not_monotonic(tmp_path: Path) -> None:
    """Step 6's centrepiece: the error changes SIGN and jumps.

    2h is +0.96%, 4h is -3.24%, 6h is +24.94%. A learner told 'coarser is less
    accurate' would predict none of that, so the course states it and this pins
    the figures it states.
    """
    base = _solved("training_m6", tmp_path)
    ref = float(base.objective)

    def at(hours: int) -> float:
        # Coarsen an UNSOLVED network: PyPSA's copy(snapshots=...) is for
        # re-scoping a model, not for slicing results off a solved one.
        model = _model_from_example("training_m6", tmp_path)
        m, _notes = build_network(model, SCENARIO, OPTIONS)
        keep = m.snapshots[::hours]
        m = m.copy(snapshots=keep)
        m.snapshot_weightings.loc[:, :] = float(hours)
        m.optimize(solver_name="highs")
        return (float(m.objective) - ref) / ref * 100

    two, four, six = at(2), at(4), at(6)
    assert two == pytest.approx(0.96, abs=0.05)
    assert four == pytest.approx(-3.24, abs=0.05)
    assert six == pytest.approx(24.94, abs=0.05)
    # The sign flips, which is the part that makes coarsening dangerous.
    assert two > 0 > four and six > 0


# ── Module 7 — investment and capacity expansion, on a full year ─────────────
# A year is what makes the capital arithmetic honest: Ragnarok annuitises the
# workbook's OVERNIGHT cost and the results layer pro-rates the annual figure by
# modelled_hours/8760, so only at 8760 do the objective and the reported total
# agree. These solves take ~a minute each, so the module is covered by three
# tests rather than one per figure.
EXPANSION = {"carbonPrice": 0.0, "discountRate": 0.05}


def test_module_7_year_checkpoint_builds_three_of_four(tmp_path: Path) -> None:
    """Wind, solar, the line and the battery are all offered; three get built.

    Solar wins a place despite a capacity factor a third of wind's, because it
    sits at the demand end rather than behind the congested line. The battery is
    declined, which keeps the module's "the model says no" lesson intact.
    """
    n = _solved("training_m7", tmp_path, EXPANSION)
    assert len(n.snapshots) == 8760
    assert float(n.objective) == pytest.approx(18_115_684, rel=1e-4)
    assert float(n.generators.at["wind_1", "p_nom_opt"]) == pytest.approx(150.15, abs=0.5)
    assert float(n.generators.at["solar_1", "p_nom_opt"]) == pytest.approx(24.12, abs=0.5)
    assert float(n.lines.at["line_1", "s_nom_opt"]) == pytest.approx(141.04, abs=0.5)
    assert float(n.storage_units.at["batt_1", "p_nom_opt"]) == pytest.approx(20.0, abs=1e-6)


def test_module_7_capital_costs_are_overnight_and_unscaled(tmp_path: Path) -> None:
    """A full year is the only window where the overnight cost needs no fudge.

    Module 6 (time) exists partly for this: on a shorter horizon the optimiser
    needs capital pre-scaled and the display pro-rates it a second time. Here the
    sheet holds exactly what a cost database quotes.
    """
    model = _model_from_example("training_m7", tmp_path)
    wind = next(g for g in model["generators"] if g["name"] == "wind_1")
    solar = next(g for g in model["generators"] if g["name"] == "solar_1")
    assert wind["capital_cost"] == 1_200_000.0 and wind["lifetime"] == 25.0
    assert solar["capital_cost"] == 500_000.0 and solar["lifetime"] == 25.0
    assert model["lines"][0]["capital_cost"] == 600_000.0
    assert len(model["snapshots"]) == 8760


def test_module_7_starting_model_has_nothing_extendable(tmp_path: Path) -> None:
    """The prebuilt start is the year WITHOUT the investment attributes, so the
    learner adds them — which is the module."""
    model = _model_from_example("training_m7_year", tmp_path)
    assert len(model["snapshots"]) == 8760
    assert len(model["loads-p_set"]) == 8760
    assert len(model["generators-p_max_pu"]) == 8760
    for g in model["generators"]:
        assert not g.get("p_nom_extendable", False), g["name"]
    assert not model["lines"][0].get("s_nom_extendable", False)


# ── Module 8 — policy instruments ────────────────────────────────────────────
# These are full-year expansion solves and each takes about a minute, so the
# module is covered by two tests that assert several things each rather than one
# test per figure. `emissions` is recomputed here rather than read from results
# so the assertion does not depend on the reporting layer.

def _emissions(n) -> float:
    """Tonnes CO2: fuel burnt x the carrier factor, counting gas once."""
    total = 0.0
    for g in n.generators.index:
        carrier = n.generators.at[g, "carrier"]
        if carrier == "gas":
            continue          # the import; charged via the CCGT's fuel draw below
        factor = float(n.carriers.at[carrier, "co2_emissions"]) if carrier in n.carriers.index else 0.0
        if factor:
            total += float(n.generators_t.p[g].sum()) / float(n.generators.at[g, "efficiency"]) * factor
    return total + float(n.links_t.p0["ccgt_1"].sum()) * float(n.carriers.at["gas", "co2_emissions"])


def test_module_8_a_carbon_price_removes_coal_and_builds_storage(tmp_path: Path) -> None:
    """At 100/tCO2 emissions fall 98% and the battery is finally worth building.

    Module 7 offered the identical battery at the identical cost and the model
    declined it. Pricing coal out is what changes the value of flexibility, which
    is the module's second lesson.
    """
    model = _model_from_example("training_m7", tmp_path)
    n = _solve_model(model, {"carbonPrice": 100.0, "discountRate": 0.05})
    assert _emissions(n) == pytest.approx(4_376, rel=0.02)
    assert float(n.generators_t.p["coal_1"].sum()) == pytest.approx(0.0, abs=1.0)
    assert float(n.storage_units.at["batt_1", "p_nom_opt"]) == pytest.approx(82.3, abs=1.0)
    assert float(n.generators.at["solar_1", "p_nom_opt"]) == pytest.approx(133.2, abs=1.0)


def test_module_8_a_cap_and_a_price_are_duals(tmp_path: Path) -> None:
    """The module's centrepiece, and the reason it is worth a slow test.

    A 150,000 t cap has a shadow price of 3.46. Setting a carbon price to 3.46
    with no cap reproduces the capped system: the same capacities, the same coal
    output, the same emissions to three significant figures.
    """
    model = _model_from_example("training_m7", tmp_path)
    capped = _solve_model(
        {**model, "global_constraints": [{
            "name": "co2_cap", "type": "primary_energy",
            "carrier_attribute": "co2_emissions", "sense": "<=", "constant": 150_000.0}]},
        {"carbonPrice": 0.0, "discountRate": 0.05},
    )
    assert _emissions(capped) == pytest.approx(150_000, rel=1e-3)
    # A <= constraint carries a negative dual; the course teaches the magnitude.
    assert abs(float(capped.global_constraints.at["co2_cap", "mu"])) == pytest.approx(3.46, abs=0.05)

    priced = _solve_model(model, {"carbonPrice": 3.46, "discountRate": 0.05})
    assert _emissions(priced) == pytest.approx(_emissions(capped), rel=1e-3)
    for asset, frame in (("wind_1", "generators"), ("solar_1", "generators")):
        a = float(getattr(capped, frame).at[asset, "p_nom_opt"])
        b = float(getattr(priced, frame).at[asset, "p_nom_opt"])
        assert a == pytest.approx(b, rel=1e-3), asset


# ── Module 10 — meshed networks and power flow ───────────────────────────────
#
# Three buses in a ring, equal reactance everywhere. The module's arithmetic:
# the direct bus_1 → bus_3 path is one line, the way round is two, so the
# indirect path has twice the reactance and carries half as much. 90 MW divides
# 60 / 30. Every figure below is quoted in the module prose.

def _capped(model: dict, s_nom: float = 50.0) -> dict:
    """Module 10's step 5: the same ring with line_13 rated at 50 MW."""
    out = {k: [dict(r) for r in v] for k, v in model.items()}
    for row in out["lines"]:
        if row.get("name") == "line_13":
            row["s_nom"] = s_nom
    return out


def test_module_10_ring_solves_to_5400(tmp_path: Path) -> None:
    """90 MW of demand met entirely by 20/MWh coal: 90 × 20 × 3 hours."""
    n = _solved("training_m10", tmp_path)
    assert float(n.objective) == pytest.approx(5_400.0, rel=1e-6)


def test_module_10_flow_divides_two_thirds_one_third(tmp_path: Path) -> None:
    """The module's central hand-check, and the reason a loop is not a pipe.

    Nobody chose this split and no constraint produced it — it is Kirchhoff's
    voltage law, which the LP enforces on AC lines as a cycle constraint.
    """
    n = _solved("training_m10", tmp_path)
    flow = {name: [abs(float(v)) for v in n.lines_t.p0[name]] for name in
            ("line_12", "line_23", "line_13")}
    assert flow["line_13"] == pytest.approx([60.0] * 3, abs=1e-6)
    assert flow["line_12"] == pytest.approx([30.0] * 3, abs=1e-6)
    assert flow["line_23"] == pytest.approx([30.0] * 3, abs=1e-6)


def test_module_10_uncongested_ring_prices_one_price(tmp_path: Path) -> None:
    """No binding line, so every bus prices at the marginal unit: coal at 20."""
    n = _solved("training_m10", tmp_path)
    for bus in ("bus_1", "bus_2", "bus_3"):
        assert [float(v) for v in n.buses_t.marginal_price[bus]] == pytest.approx(
            [20.0] * 3, abs=1e-6
        ), bus


def test_module_10_capping_line_13_costs_2700(tmp_path: Path) -> None:
    """Cap the direct line at 50 MW and the answer moves 5,400 → 8,100.

    Nothing about cost or demand changed. The only way to unload a line in a
    meshed network is to change WHERE power is injected, so 30 MW of coal is
    replaced by 30 MW of gas at three times the price.
    """
    model = _capped(_model_from_example("training_m10", tmp_path))
    n = _solve_model(model)
    assert float(n.objective) == pytest.approx(8_100.0, rel=1e-6)
    assert float(n.generators_t.p["coal_1"].sum()) == pytest.approx(180.0, abs=1e-6)
    assert float(n.generators_t.p["gas_2"].sum()) == pytest.approx(90.0, abs=1e-6)


def test_module_10_capped_ring_loads_lines_50_40_10(tmp_path: Path) -> None:
    """60 MW of coal and 30 MW of gas superpose to exactly fill the capped line.

    Hand-check: coal's 60 MW splits 40 direct / 20 round; gas's 30 MW splits 20
    on line_23 / 10 counter-flowing through line_12 and on down line_13.
    """
    model = _capped(_model_from_example("training_m10", tmp_path))
    n = _solve_model(model)
    flow = {name: abs(float(n.lines_t.p0[name].iloc[0])) for name in
            ("line_12", "line_23", "line_13")}
    assert flow["line_13"] == pytest.approx(50.0, abs=1e-6)
    assert flow["line_23"] == pytest.approx(40.0, abs=1e-6)
    assert flow["line_12"] == pytest.approx(10.0, abs=1e-6)


def test_module_10_capped_ring_prices_20_50_80(tmp_path: Path) -> None:
    """The finding of the module: 80 at bus_3, above every generator in the model.

    Serving one more MW at bus_3 cannot simply run more coal — that would push
    the capped line further over. It takes 1 MW more gas and 1 MW less coal per
    ... the algebra gives dCost/dD = 80 exactly, and the solver agrees.
    """
    model = _capped(_model_from_example("training_m10", tmp_path))
    n = _solve_model(model)
    prices = {bus: float(n.buses_t.marginal_price[bus].iloc[0])
              for bus in ("bus_1", "bus_2", "bus_3")}
    assert prices["bus_1"] == pytest.approx(20.0, abs=1e-6)
    assert prices["bus_2"] == pytest.approx(50.0, abs=1e-6)
    assert prices["bus_3"] == pytest.approx(80.0, abs=1e-6)


def test_module_10_ac_power_flow_reports_losses_and_voltage_sag(tmp_path: Path) -> None:
    """The study mode the LP never runs: real impedance, so a real voltage drop.

    Values are quoted in the module's AC step — a sag to 0.9987 pu at the far
    bus and losses the optimisation reported as exactly zero.
    """
    from backend.pypsa.results import run_pypsa

    model = _model_from_example("training_m10", tmp_path)
    res = run_pypsa(model, SCENARIO, {"powerFlowConfig": {"enabled": True}})
    pf = res["powerFlow"]
    assert pf["converged"] is True
    assert pf["error"] is None
    assert pf["lossesMwh"] > 0.0
    volts = {v["bus"]: v["mean"] for v in pf["voltageProfile"]}
    assert volts["bus_1"] == pytest.approx(1.0, abs=1e-4)
    assert volts["bus_3"] < volts["bus_2"] < volts["bus_1"]
    # The card a learner actually reads must not round a real loss down to "0 MWh"
    # — the module's verify item says losses are greater than zero.
    losses = next(row for row in res["summary"] if row["label"] == "Losses")
    assert losses["value"] != "0 MWh"


def test_module_10_linear_power_flow_is_lossless(tmp_path: Path) -> None:
    """DC power flow agrees on the flows and reports no losses at all — which is
    what "linear" costs you, and why the module runs both."""
    from backend.pypsa.results import run_pypsa

    model = _model_from_example("training_m10", tmp_path)
    res = run_pypsa(model, SCENARIO, {"powerFlowConfig": {"enabled": True, "linear": True}})
    assert res["powerFlow"]["lossesMwh"] == 0.0
    loading = {row["label"]: row["value"] for row in res["lineLoading"]}
    assert loading["line_13"] == pytest.approx(30.0, abs=0.1)
    assert loading["line_12"] == pytest.approx(15.0, abs=0.1)


def test_module_10_n_minus_1_finds_two_insecure_outages(tmp_path: Path) -> None:
    """N-1 on the capped ring: losing either leg of the long path overloads the
    direct line to 180%, while losing the direct line is survivable at 45%."""
    from backend.pypsa.results import run_pypsa

    model = _capped(_model_from_example("training_m10", tmp_path))
    res = run_pypsa(model, SCENARIO, {"contingencyConfig": {"enabled": True}})
    cont = res["contingency"]
    assert cont["error"] is None
    assert cont["secure"] is False
    assert cont["outagesTested"] == 3
    assert cont["insecureCount"] == 2
    worst = {row["outage"]: row["worstLoadingPct"] for row in cont["contingencies"]}
    assert worst["line_12"] == pytest.approx(180.0, abs=0.1)
    assert worst["line_23"] == pytest.approx(180.0, abs=0.1)
    assert worst["line_13"] == pytest.approx(45.0, abs=0.1)


# ── Module 11 — commitment and operating constraints ─────────────────────────
#
# Six hours, demand 90/90/50/50/90/90, wind available only in the two dip hours.
# A committable coal unit with a 40 MW floor must either hold that floor through
# the dip (spilling free wind) or stop and pay to restart. Every figure the
# module quotes is one of the five runs below.

def _coal(model: dict) -> dict:
    return next(g for g in model["generators"] if g["name"] == "coal_1")


def _m11(tmp_path: Path, **patch) -> dict:
    """The module 11 checkpoint with coal_1 attributes overridden."""
    model = {k: [dict(r) for r in v] for k, v in
             _model_from_example("training_m11", tmp_path).items()}
    if patch:
        _coal(model).update(patch)
    return model


def _run(model: dict, options: dict | None = None) -> dict:
    from backend.pypsa.results import run_pypsa

    return run_pypsa(model, SCENARIO, {**OPTIONS, **(options or {})})


def _cost(res: dict, label: str) -> float:
    return next((c["value"] for c in res["costBreakdown"] if c["label"] == label), 0.0)


def test_module_11_committed_unit_holds_through_the_dip(tmp_path: Path) -> None:
    """As shipped: a 3,000 start-up beats 1,600 of minimum-stable coal, so it stays on.

    7,200 for the four busy hours plus 40 MW x 20 x 2 hours through the dip.
    """
    res = _run(_m11(tmp_path))
    assert _cost(res, "Fuel cost") == pytest.approx(8_800.0, rel=1e-6)
    assert _cost(res, "Start-up / shut-down cost") == pytest.approx(0.0)
    assert res["commitment"]["totals"]["starts"] == 0


def test_module_11_dip_holds_coal_at_its_floor_and_spills_wind(tmp_path: Path) -> None:
    """The picture the module asks the learner to predict: a 40 MW shelf, 70 MW spilt."""
    model = _m11(tmp_path)
    n = _solve_model(model)
    coal = [float(v) for v in n.generators_t.p["coal_1"]]
    assert coal == pytest.approx([90.0, 90.0, 40.0, 40.0, 90.0, 90.0], abs=1e-6)
    available = n.generators.at["wind_1", "p_nom"] * n.generators_t.p_max_pu["wind_1"]
    spilt = (available - n.generators_t.p["wind_1"]).round(6)
    assert [float(v) for v in spilt] == pytest.approx([0.0, 0.0, 70.0, 70.0, 0.0, 0.0], abs=1e-6)


def test_module_11_cheaper_start_flips_the_decision(tmp_path: Path) -> None:
    """One cell — 3000 to 1000 — and the unit stops instead. 7,200 + 1,000 = 8,200."""
    res = _run(_m11(tmp_path, start_up_cost=1000.0))
    assert _cost(res, "Fuel cost") == pytest.approx(7_200.0, rel=1e-6)
    assert _cost(res, "Start-up / shut-down cost") == pytest.approx(1_000.0, rel=1e-6)
    totals = res["commitment"]["totals"]
    assert totals["starts"] == 1
    assert totals["startUpCostTotal"] == pytest.approx(1_000.0, rel=1e-6)


def test_module_11_min_down_time_forbids_the_shutdown(tmp_path: Path) -> None:
    """Three hours off is longer than the dip, so the cheap shutdown is unavailable.

    Same 8,800 as the shipped run, reached for the opposite reason — economics
    said stop and the operating constraint said no.
    """
    res = _run(_m11(tmp_path, start_up_cost=1000.0, min_down_time=3))
    assert _cost(res, "Fuel cost") == pytest.approx(8_800.0, rel=1e-6)
    assert res["commitment"]["totals"]["starts"] == 0


def test_module_11_ramp_limit_costs_1000_in_the_hours_beside_the_dip(tmp_path: Path) -> None:
    """30 MW/h cannot make the 50 MW step, so the unit moves early and gas fills in.

    The module's point is WHERE the cost lands: gas runs 10 MW in two hours that
    have no scarcity of their own.
    """
    model = _m11(tmp_path, ramp_limit_up=0.3, ramp_limit_down=0.3)
    res = _run(model)
    assert _cost(res, "Fuel cost") == pytest.approx(9_800.0, rel=1e-6)
    n = _solve_model(model)
    coal = [float(v) for v in n.generators_t.p["coal_1"]]
    gas = [float(v) for v in n.generators_t.p["gas_1"]]
    assert coal == pytest.approx([90.0, 80.0, 50.0, 50.0, 80.0, 90.0], abs=1e-6)
    assert gas == pytest.approx([0.0, 10.0, 0.0, 0.0, 10.0, 0.0], abs=1e-6)
    # No step exceeds 30 MW — the constraint the module says is binding.
    assert max(abs(b - a) for a, b in zip(coal, coal[1:])) <= 30.0 + 1e-6


def test_module_11_force_lp_is_a_bound_and_the_only_run_that_prices(tmp_path: Path) -> None:
    """The relaxation: 7,200, below both committed answers, with usable duals.

    It is also the regression test for the p_min_pu trap — if Force LP left the
    0.4 floor behind, the "relaxation" would come back at 8,800, ABOVE the MILP
    it is supposed to bound.
    """
    res = _run(_m11(tmp_path), {"forceLp": True})
    assert _cost(res, "Fuel cost") == pytest.approx(7_200.0, rel=1e-6)
    assert res["commitment"] is None
    prices = [p["value"] for p in res["systemPriceSeries"]]
    assert prices == pytest.approx([20.0, 20.0, 0.0, 0.0, 20.0, 20.0], abs=1e-6)


def test_module_11_commitment_run_warns_that_its_prices_are_not_prices(tmp_path: Path) -> None:
    """A MILP has no duals, and the flat zero it reports is worse than no number."""
    res = _run(_m11(tmp_path))
    assert [p["value"] for p in res["systemPriceSeries"]] == pytest.approx([0.0] * 6, abs=1e-6)
    warning = [n for n in res["narrative"] if "NOT shadow prices" in n]
    assert warning, "a commitment run must say its prices are unusable"


def test_module_11_p_min_pu_without_commitment_is_flagged(tmp_path: Path) -> None:
    """The trap the module ends on: clearing the flag welds the unit on at 40 MW."""
    from backend.pypsa.model_check import check_model

    model = _m11(tmp_path)
    _coal(model).pop("committable")
    codes = {f["code"] for f in check_model(model)["findings"]}
    assert "min_pu_without_commitment" in codes


# ── The checkpoints the course references must exist and be loadable ─────────

def test_every_course_checkpoint_is_a_listable_example() -> None:
    """A checkpoint id the tutorial names but ``/api/examples`` cannot serve gives
    the learner a dead button, which is worse than no button."""
    for example_id in ("training_m1", "training_m2", "training_m3", "training_m4",
                       "training_m5", "training_m6", "training_m7_year", "training_m7",
                       "training_m10", "training_m11"):
        db = EXAMPLES / example_id / "project.db"
        assert db.exists(), f"{example_id}: no project.db"
        con = sqlite3.connect(db)
        try:
            row = con.execute("SELECT v FROM _kv WHERE k = 'example'").fetchone()
        finally:
            con.close()
        assert row is not None, f"{example_id}: no example metadata, so it lists as a bare id"
        meta = json.loads(row[0])
        assert meta.get("label"), f"{example_id}: no label"
        assert meta.get("description"), f"{example_id}: no description"
