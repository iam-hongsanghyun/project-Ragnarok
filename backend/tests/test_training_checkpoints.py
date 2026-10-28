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

import functools
import itertools
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from backend.app import sqlite_store
from backend.app import carbon_pricing
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
    n.optimize(solver_name="highs", extra_functionality=carbon_pricing.extra_functionality)
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
    # the carbon-pricing module's objective term (a no-op when the scenario's carbonPrice is 0)
    n.optimize(solver_name="highs", extra_functionality=carbon_pricing.extra_functionality)
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


def _m6_coarsened(tmp_path: Path, method: str, hours: int) -> float:
    """Module 6 at ``hours`` through the VISIBLE temporal transform (what Run -> Resolution calls), solved from the written workbook."""
    from backend.pypsa.network_ops import temporal_cluster

    model = _model_from_example("training_m6", tmp_path)
    kw = {"offset": f"{hours}h"} if method == "resample" else {"stride": hours}
    reduced = temporal_cluster(model, method=method, **kw)["model"]
    n, _notes = build_network(reduced, SCENARIO, OPTIONS)
    n.optimize(solver_name="highs")
    return float(n.objective)


def test_module_6_coarsening_by_block_means_understates_cost_and_grows_with_the_step(tmp_path: Path) -> None:
    """Step 6 (re-pinned in core cleanup step 4): the Resolution buttons are the Forge temporal RESAMPLE.

    Before, the buttons were a run-time stride that point-sampled every k-th row; the course's figures (+0.96 %,
    -3.24 %, +24.94 %, -39.30 %) were the error of that sampling, which is why they changed sign and jumped. A resample
    takes block MEANS, so the load and the wind keep their daily totals and the only thing lost is the peak: the
    objective is always below the hourly 52,663.98 and the error grows with the step. The old figures are pinned below
    as `downsample`, PyPSA's point sampling, because that contrast is now the lesson.
    """
    ref = float(_solved("training_m6", tmp_path).objective)
    got = {h: _m6_coarsened(tmp_path, "resample", h) for h in (2, 4, 6, 12)}
    assert got[2] == pytest.approx(52_489.67, abs=0.01)
    assert got[4] == pytest.approx(51_630.22, abs=0.01)
    assert got[6] == pytest.approx(52_489.67, abs=0.01)
    assert got[12] == pytest.approx(49_190.00, abs=0.01)
    errors = {h: (v - ref) / ref * 100 for h, v in got.items()}
    assert errors[2] == pytest.approx(-0.33, abs=0.01) and errors[4] == pytest.approx(-1.96, abs=0.01)
    assert errors[6] == pytest.approx(-0.33, abs=0.01) and errors[12] == pytest.approx(-6.60, abs=0.01)
    assert all(e < 0 for e in errors.values())          # block means never see the peak: always an understatement
    assert errors[12] < errors[4] < errors[2] < 0       # and the coarsest step is the worst


def test_module_6_point_sampling_is_the_dangerous_way_to_coarsen(tmp_path: Path) -> None:
    """The old stride, now explicit as the Forge `downsample` method: the error changes SIGN and jumps.

    2h is +0.96%, 4h is -3.24%, 6h is +24.94%, 12h is -39.30% (unchanged by step 4: it is PyPSA's own point sampling,
    weight = stride). A learner told 'coarser is less accurate' would predict none of that.
    """
    ref = float(_solved("training_m6", tmp_path).objective)
    two, four, six, twelve = (
        (_m6_coarsened(tmp_path, "downsample", h) - ref) / ref * 100 for h in (2, 4, 6, 12)
    )
    assert two == pytest.approx(0.96, abs=0.05)
    assert four == pytest.approx(-3.24, abs=0.05)
    assert six == pytest.approx(24.94, abs=0.05)
    assert twelve == pytest.approx(-39.30, abs=0.05)
    assert two > 0 > four and six > 0


# ── Module 7 — investment and capacity expansion, on a full year ─────────────
# A year is what makes the capital arithmetic honest: the workbook holds PyPSA's
# `overnight_cost`, which PyPSA annuitises as overnight x annuity(r, L) x n.nyears, so
# on a full year (nyears = 1) the objective's capital term is the annuity itself. These
# solves take ~a minute each, so the module is covered by three tests rather than one
# per figure.
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
    """The sheet holds exactly what a cost database quotes, in PyPSA's own column.

    `overnight_cost` is the upfront price; PyPSA annuitises it (annuity(discount_rate, lifetime) x
    n.nyears), so the workbook needs no pre-scaling and `capital_cost` stays 0. Module 6 (time) exists
    partly for this: on a shorter horizon PyPSA's nyears does the scaling, not the learner.
    """
    model = _model_from_example("training_m7", tmp_path)
    wind = next(g for g in model["generators"] if g["name"] == "wind_1")
    solar = next(g for g in model["generators"] if g["name"] == "solar_1")
    assert wind["overnight_cost"] == 1_200_000.0 and wind["lifetime"] == 25.0 and wind["capital_cost"] == 0
    assert solar["overnight_cost"] == 500_000.0 and solar["lifetime"] == 25.0 and solar["capital_cost"] == 0
    assert model["lines"][0]["overnight_cost"] == 600_000.0 and model["lines"][0]["capital_cost"] == 0
    assert wind["discount_rate"] == 0.05
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
    assert max(abs(b - a) for a, b in itertools.pairwise(coal)) <= 30.0 + 1e-6


def test_module_11_force_lp_is_a_bound_and_the_only_run_that_prices(tmp_path: Path) -> None:
    """The relaxation: 8,640, below the committed 8,800, with usable duals.

    Re-pinned in core cleanup step 5 (D12): Force LP is PyPSA's own ``linearized_unit_commitment`` and clears
    nothing, so the minimum load while running (p_min_pu 0.4), the start-up cost and the times stay in the
    relaxation as continuous constraints. It used to clear ``committable`` and ``p_min_pu`` and solve a plain
    dispatch LP: 7,200 and prices 20/20/0/0/20/20, a looser bound that threw the unit's operating limits away.
    The p_min_pu trap it was written to avoid (a floor left behind turning the bound into 8,800+) cannot occur
    now: the floor is still a floor only while the unit is committed.
    """
    res = _run(_m11(tmp_path), {"forceLp": True})
    assert _cost(res, "Fuel cost") == pytest.approx(8_640.0, rel=1e-6)
    assert 7_200.0 < _cost(res, "Fuel cost") < 8_800.0   # between plain dispatch and the committed answer
    assert res["commitment"] is None
    prices = [p["value"] for p in res["systemPriceSeries"]]
    assert prices == pytest.approx([20.0, 20.0, 0.0, 0.0, 36.0, 20.0], abs=1e-6)
    assert any("linearized" in n and "unit commitment" in n for n in res["narrative"])


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


# ── Module 12 — adequacy and uncertainty ─────────────────────────────────────
#
# The same two checkpoints module 7 uses, put through the reliability studies at
# the panels' own defaults. The module's arc is the comparison: the system
# module 7 started from against the one its least-cost expansion built.

_M12_MC = {
    "enabled": True, "nMembers": 200, "seed": 42,
    "forcedOutageRate": 0.05, "mttrHours": 48.0,
}


def _reliability(example_id: str, tmp_path: Path, options: dict) -> dict:
    from backend.pypsa.results import run_pypsa

    model = _model_from_example(example_id, tmp_path)
    return run_pypsa(model, {"carbonPrice": 0.0, "discountRate": 0.05},
                     {**OPTIONS, **options})


def test_module_12_brownfield_year_misses_the_reliability_standard(tmp_path: Path) -> None:
    """The system module 7 started from, sampled for forced outages.

    Nothing in its deterministic run suggested a problem — it sheds no load at
    all. Against the 2.4 h/yr "one day in ten years" yardstick its mean LOLE is
    twenty-seven times over.

    Re-baselined 2026-10-27 (was P50 8.0 / P95 58.25 / mean 17.78): adequacy now
    dispatches storage with its state-of-charge limits (RE2) instead of counting
    the 20 MW battery and the pumped hydro as firm for as long as the shortfall
    lasts, so the same fleet is far less adequate. The lesson only got stronger.
    """
    res = _reliability("training_m7_year", tmp_path, {"outageMcConfig": _M12_MC})
    lole = res["outageMc"]["loleDistribution"]
    eue = res["outageMc"]["eueDistribution"]
    assert lole["p50"] == pytest.approx(46.5, abs=1.0)
    assert lole["p95"] == pytest.approx(160.55, rel=0.02)
    assert lole["mean"] == pytest.approx(64.06, rel=0.02)
    assert eue["p50"] == pytest.approx(1_045.7, rel=0.02)
    assert eue["p95"] == pytest.approx(5_608.3, rel=0.02)
    assert lole["mean"] > 2.4 * 5, "the module's point is that this misses the standard badly"


def test_module_12_expansion_improves_adequacy_it_never_asked_about(tmp_path: Path) -> None:
    """Module 7 optimised cost. Reliability was not in the objective or a constraint.

    The mean LOLE still falls about thirteen-fold — and the system still misses
    the standard, on the mean (about twice it) and far more at P95. That is the
    caveat the module refuses to drop: least-cost expansion improved adequacy by
    accident, it did not deliver it.

    Re-baselined 2026-10-27 (was P50 0.0 / P95 3.0 / mean 0.61, i.e. "meets the
    standard on the mean"): with storage dispatched under its state-of-charge
    limits (RE2) the expanded system's mean LOLE is 4.73 h/yr, above 2.4.
    """
    res = _reliability("training_m7", tmp_path, {"outageMcConfig": _M12_MC})
    lole = res["outageMc"]["loleDistribution"]
    assert lole["p50"] == pytest.approx(1.0, abs=0.5)
    assert lole["p95"] == pytest.approx(19.1, rel=0.03)
    assert lole["mean"] == pytest.approx(4.73, rel=0.03)
    assert res["outageMc"]["eueDistribution"]["p50"] == pytest.approx(4.69, rel=0.05)
    assert res["outageMc"]["eueDistribution"]["p95"] == pytest.approx(366.5, rel=0.03)
    brownfield_mean = 64.06  # pinned in test_module_12_brownfield_year_misses_the_reliability_standard
    assert brownfield_mean / lole["mean"] > 10, "the expansion improved the mean LOLE more than tenfold"
    assert 2.4 < lole["mean"] < 2.4 * 3, "but the mean is still about twice the standard"
    assert lole["p95"] > 2.4 * 5, "and one year in twenty is many times over it"


def test_module_12_capacity_credit_ranks_by_when_the_system_is_short(tmp_path: Path) -> None:
    """Wind about 50% of nameplate, solar about 20% — because the tight hours are
    winter evenings. The module makes the point that this is a property of the
    pairing rather than of the technology.

    The 20 MW battery is credited 11% — it was 98% when storage counted as firm at
    its power rating for the whole shortfall (RE2): its state of charge now limits it.
    """
    res = _reliability("training_m7", tmp_path,
                       {"elccConfig": {**_M12_MC, "carriers": []}})
    by_carrier = {c["carrier"]: c for c in res["elcc"]["byCarrier"]}
    assert by_carrier["wind"]["elccPct"] == pytest.approx(50.2, rel=0.03)
    assert by_carrier["solar"]["elccPct"] == pytest.approx(20.4, rel=0.05)
    assert by_carrier["wind"]["elccPct"] > by_carrier["solar"]["elccPct"] * 2
    assert by_carrier["AC"]["elccPct"] == pytest.approx(11.03, rel=0.05)  # battery (carrier "AC")
    assert by_carrier["AC"]["elccPct"] < 25.0, "an energy-limited battery is not firm capacity"


def test_module_12_elcc_baseline_matches_the_monte_carlo_mean(tmp_path: Path) -> None:
    """Step 7 asks the learner to check this, so it had better hold.

    The two studies must measure the same system for their numbers to be
    comparable — they did not until storage got one shared definition.
    """
    mc = _reliability("training_m7", tmp_path, {"outageMcConfig": _M12_MC})
    elcc = _reliability("training_m7", tmp_path, {"elccConfig": {**_M12_MC, "carriers": []}})
    assert elcc["elcc"]["baselineLoleHrs"] == pytest.approx(
        mc["outageMc"]["loleDistribution"]["mean"], rel=1e-3
    )


def test_module_12_convergence_reports_that_it_did_not_converge(tmp_path: Path) -> None:
    """A rare-event estimate at a 2% tolerance does not settle in 1,000 members.

    The module teaches the trace rather than the headline: the estimate is
    stable from 50 members and the standard error is still ~3% at 1,000.

    Re-authored 2026-10-27: at the old 5% tolerance the study now converges (400
    members) because the brownfield year's shortfalls are no longer rare once
    storage is energy-limited (EUE 1,554 MWh/yr, was 192), so the sampling
    setting is tightened to 2% to keep the lesson true.
    """
    res = _reliability("training_m7_year", tmp_path, {"convergenceConfig": {
        "enabled": True, "targetMetric": "eue", "tolerance": 0.02,
        "batchSize": 50, "maxMembers": 1000, "seed": 42,
        "forcedOutageRate": 0.05, "mttrHours": 48.0, "maintenanceEnabled": False,
    }})
    cv = res["convergenceSampling"]
    assert cv["converged"] is False
    assert cv["achievedMembers"] == 1000
    assert cv["estimate"] == pytest.approx(1_554.30, rel=0.02)
    assert cv["ciLow"] == pytest.approx(1_457.16, rel=0.02)
    assert cv["ciHigh"] == pytest.approx(1_651.44, rel=0.02)
    # The estimate settles long before the error does — the step's whole point.
    trace = cv["trace"]
    assert trace[0]["se"] > 2 * trace[-1]["se"]


# ── Module 13 — where the demand comes from ──────────────────────────────────
#
# The module projects module 7's year to 2040 two ways that agree on annual
# energy and disagree on shape, then asks the optimiser to build for each. The
# transforms are the ones behind Forge's Temporal tools, called directly here so
# the figures are pinned without a session.

_M13_SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.05}


def _demand_stats(model: dict) -> tuple[float, float]:
    """(peak MW, annual energy GWh) of the model's demand series."""
    hourly = [sum(v for k, v in row.items() if k != "snapshot")
              for row in model["loads-p_set"]]
    return max(hourly), sum(hourly) / 1000.0


def _projected(example_id: str, tmp_path: Path, kind: str) -> dict:
    """Run one of Forge's Temporal transforms over a checkpoint, via the router.

    The transforms live in the session router and operate on a stored session,
    which is exactly how Forge reaches them — so drive them the same way rather
    than reimplementing the maths the assertions are meant to check.
    """
    from backend.app import model_store, session_store
    from backend.app.routers import session as session_router

    session_id = f"m13_{kind}"
    original = session_store.SESSION_DIR
    original_sqlite = sqlite_store.ss.SESSION_DIR
    session_store.SESSION_DIR = tmp_path
    sqlite_store.ss.SESSION_DIR = tmp_path
    try:
        model_store.save_model(session_id, _model_from_example(example_id, tmp_path))
        if kind == "cagr":
            session_router.forecast_snapshots(session_router.SnapshotForecast(
                fromYear=2030, toYear=2040, growthPct=2.0, method="cagr",
                sessionId=session_id))
        else:
            session_router.driver_forecast_snapshots(session_router.DriverForecast(
                fromYear=2030, toYear=2040, popGrowthPct=0.0, gdpGrowthPct=0.0,
                gdpElasticity=0.5, heatAddedGWh=120.0, evAddedGWh=106.0,
                sessionId=session_id))
        out = model_store.load_full_model(session_id)
    finally:
        session_store.SESSION_DIR = original
        sqlite_store.ss.SESSION_DIR = original_sqlite
    assert out is not None
    return out


def test_module_13_base_year_is_the_profile_the_module_measures(tmp_path: Path) -> None:
    """Step 1's two numbers. Everything later is a comparison against these."""
    peak, energy = _demand_stats(_model_from_example("training_m7_year", tmp_path))
    assert peak == pytest.approx(174.7, abs=0.1)
    assert energy == pytest.approx(1_030.5, abs=0.1)


def test_module_13_cagr_grows_every_hour_by_the_same_factor(tmp_path: Path) -> None:
    """2% for ten years is 1.219, applied uniformly — so the shape is untouched.

    Asserted as a ratio per hour, because "the shape does not change" is the
    module's claim and the totals alone would not catch a reshaping that
    happened to preserve them.
    """
    before = [sum(v for k, v in r.items() if k != "snapshot")
              for r in _model_from_example("training_m7_year", tmp_path)["loads-p_set"]]
    after = [sum(v for k, v in r.items() if k != "snapshot")
             for r in _projected("training_m7_year", tmp_path, "cagr")["loads-p_set"]]
    assert len(after) == len(before)
    ratios = [b / a for a, b in zip(before, after, strict=True) if a > 0]
    assert max(ratios) == pytest.approx(min(ratios), rel=1e-6), "growth must be uniform"
    assert ratios[0] == pytest.approx(1.219, rel=1e-3)
    assert max(after) == pytest.approx(212.9, abs=0.2)
    assert sum(after) / 1000.0 == pytest.approx(1_256.2, abs=0.5)


def test_module_13_electrification_lifts_the_peak_at_the_same_energy(tmp_path: Path) -> None:
    """The module's finding: identical annual energy, 3.5% more peak.

    Heat and EV load is added on its own winter/evening signature rather than in
    proportion to what is already there, so it piles onto the busiest hours.
    """
    peak, energy = _demand_stats(_projected("training_m7_year", tmp_path, "driver"))
    assert energy == pytest.approx(1_256.5, abs=0.5)
    assert peak == pytest.approx(220.4, abs=0.3)
    assert peak > 212.9, "the whole point: same energy, higher peak"


def test_module_13_brownfield_fleet_cannot_serve_the_projection(tmp_path: Path) -> None:
    """Step 4: a demand projection can invalidate a model outright."""
    from fastapi import HTTPException

    from backend.pypsa.results import run_pypsa

    model = _projected("training_m7_year", tmp_path, "cagr")
    with pytest.raises(HTTPException) as excinfo:
        run_pypsa(model, _M13_SCENARIO, OPTIONS)
    assert "infeasible" in str(excinfo.value.detail).lower()


def test_module_13_shape_changes_what_gets_built(tmp_path: Path) -> None:
    """Steps 6 and 9 together, and the reason the module exists.

    Same fleet, same capital costs, same annual energy — and thirty megawatts of
    solar moves out of the plan because the new load lands in winter evenings.
    """
    from backend.pypsa.results import run_pypsa

    def built(model: dict) -> dict:
        res = run_pypsa(model, _M13_SCENARIO, OPTIONS)
        return {r["name"]: r["p_nom_opt_mw"] for r in res["expansionResults"]}

    cagr = built(_projected("training_m7", tmp_path, "cagr"))
    driven = built(_projected("training_m7", tmp_path, "driver"))
    assert cagr["wind_1"] == pytest.approx(202.8, abs=1.0)
    assert cagr["solar_1"] == pytest.approx(50.0, abs=1.0)
    assert driven["wind_1"] == pytest.approx(208.3, abs=1.0)
    assert driven["solar_1"] == pytest.approx(20.2, abs=1.0)
    assert cagr["solar_1"] - driven["solar_1"] > 25.0, "the module claims ~30 MW of solar moves"


# ── Module 14 — the other side of the market ─────────────────────────────────
#
# Module 7's expanded year, with ownership assigned, read from the participant's
# books instead of the planner's. Nordwind owns what the expansion BUILT (so it
# carries a capital charge); Altkraft owns the incumbent thermal (sunk).

_M14_SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.05}
_M14_OWNERS = {"wind_1": "Nordwind", "solar_1": "Nordwind",
               "coal_1": "Altkraft", "oil_1": "Altkraft"}


def _owned(tmp_path: Path) -> dict:
    model = {k: [dict(r) for r in v] for k, v
             in _model_from_example("training_m7", tmp_path).items()}
    for gen in model["generators"]:
        if gen["name"] in _M14_OWNERS:
            gen["owner"] = _M14_OWNERS[gen["name"]]
    return model


def _participant(tmp_path: Path, options: dict) -> dict:
    from backend.pypsa.results import run_pypsa

    return run_pypsa(_owned(tmp_path), _M14_SCENARIO, {**OPTIONS, **options})


def _merchant(tmp_path: Path, owner: str) -> dict:
    res = _participant(tmp_path, {"merchantConfig": {
        "enabled": True, "owner": owner, "priceSource": "lmp"}})
    return res["merchant"]


def test_module_14_capture_price_differs_by_technology(tmp_path: Path) -> None:
    """Wind below the system average, solar and coal above it.

    Cannibalisation: there is 150 MW of wind in a system peaking at 175, so it
    depresses the price in exactly the hours it sells.
    """
    nordwind = _merchant(tmp_path, "Nordwind")
    altkraft = _merchant(tmp_path, "Altkraft")
    mean_price = nordwind["priceStats"]["mean"]
    assert mean_price == pytest.approx(23.92, abs=0.05)
    by_name = {a["name"]: a for a in nordwind["assets"]}
    assert by_name["wind_1"]["capturePrice"] == pytest.approx(21.18, abs=0.05)
    assert by_name["solar_1"]["capturePrice"] == pytest.approx(24.59, abs=0.05)
    coal = next(a for a in altkraft["assets"] if a["name"] == "coal_1")
    assert coal["capturePrice"] == pytest.approx(28.25, abs=0.05)
    assert by_name["wind_1"]["capturePrice"] < mean_price < coal["capturePrice"]


def test_module_14_built_assets_earn_exactly_their_capital_cost(tmp_path: Path) -> None:
    """The long-run equilibrium, and the "missing money" argument in one number.

    At a capacity-expansion optimum the marginal prices pay an asset the
    optimiser chose to build exactly what it cost — no more.
    """
    assets = {a["name"]: a for a in _merchant(tmp_path, "Nordwind")["assets"]}
    for name in ("wind_1", "solar_1"):
        asset = assets[name]
        assert asset["capex"] > 0.0
        assert asset["revenue"] == pytest.approx(asset["capex"], rel=1e-4)
        assert asset["profit"] == pytest.approx(0.0, abs=1.0)


def test_module_14_sunk_capital_makes_the_incumbent_profitable(tmp_path: Path) -> None:
    """Same market, other books: no capital charge, so coal clears 902,548.

    Its merchant volume is also below the system dispatch — a price-taker sells
    only when the price beats its own cost, and the hours it drops contributed
    nothing, which is why the profit is unchanged by dropping them.
    """
    altkraft = _merchant(tmp_path, "Altkraft")
    coal = next(a for a in altkraft["assets"] if a["name"] == "coal_1")
    assert coal["capex"] == pytest.approx(0.0)
    assert coal["profit"] == pytest.approx(902_548.0, rel=0.01)
    assert coal["energyMWh"] == pytest.approx(109_400.0, rel=0.01)
    assert coal["energyMWh"] < 316_353.0, "below what the system dispatched"


def test_module_14_the_peaker_earns_nothing(tmp_path: Path) -> None:
    """Module 12 counted this unit toward adequacy. The energy market pays it nothing."""
    altkraft = _merchant(tmp_path, "Altkraft")
    oil = next(a for a in altkraft["assets"] if a["name"] == "oil_1")
    assert oil["energyMWh"] == pytest.approx(0.0, abs=1e-6)
    assert oil["revenue"] == pytest.approx(0.0, abs=1e-6)
    assert oil["capturePrice"] is None


def test_module_14_ppa_is_zero_sum_and_settles_on_capture(tmp_path: Path) -> None:
    """A hedge moves money between two parties and changes nothing physical.

    And it settles on the SELLER's capture price (21.36), not the system average
    (23.92) — the point the module makes about pricing a wind PPA.
    """
    res = _participant(tmp_path, {"ppaConfig": {
        "enabled": True, "owner": "Nordwind",
        "volumeType": "generation", "strikePrice": 25.0}})
    ppa = res["ppa"]
    assert ppa["energyMWh"] == pytest.approx(638_440.0, rel=0.01)
    assert ppa["avgSpotPrice"] == pytest.approx(21.36, abs=0.05)
    assert ppa["sellerNet"] == pytest.approx(2_320_908.0, rel=0.01)
    assert ppa["buyerNet"] == pytest.approx(-ppa["sellerNet"], rel=1e-6)
    assert ppa["sellerNet"] == pytest.approx(
        ppa["energyMWh"] * (ppa["strikePrice"] - ppa["avgSpotPrice"]), rel=1e-2)


def test_module_14_a_pivotal_unit_raises_the_price_without_losing_volume(tmp_path: Path) -> None:
    """Market power: coal offers 50% above cost, sells exactly as much, and the
    whole system pays 26% more."""
    res = _participant(tmp_path, {"bidStrategyConfig": {
        "enabled": True, "owner": "Altkraft", "markupType": "percent", "markup": 0.5}})
    bid = res["bidStrategy"]
    assert bid["baseline"]["profit"] == pytest.approx(902_548.0, rel=0.01)
    assert bid["strategic"]["profit"] == pytest.approx(4_269_487.0, rel=0.01)
    assert bid["baseline"]["energyMWh"] == pytest.approx(bid["strategic"]["energyMWh"], rel=1e-6)
    assert bid["systemAvgPrice"]["baseline"] == pytest.approx(24.28, abs=0.05)
    assert bid["systemAvgPrice"]["strategic"] == pytest.approx(30.71, abs=0.05)


# ── Module 15 — market design ────────────────────────────────────────────────
#
# The market-simulation study mode: explicit clearing rules instead of an LP.
# It runs on the BROWNFIELD year, and that is load-bearing — the study never
# solves, so it clears the capacity in the workbook. On an expansion model that
# is the pre-expansion fleet, which the module teaches as a trap in step 8.

_M15_SIM = {
    "enabled": True, "voll": 3000.0, "chargeQuantile": 0.25,
    "dischargeQuantile": 0.75, "clearingModel": "singleSided",
}


def _sim(tmp_path: Path, pricing: str, *, gas_p_nom: float | None = None) -> dict:
    from backend.pypsa.results import run_pypsa

    model = {k: [dict(r) for r in v] for k, v
             in _model_from_example("training_m7_year", tmp_path).items()}
    if gas_p_nom is not None:
        for gen in model["generators"]:
            if gen["name"] == "gas_supply":
                gen["p_nom"] = gas_p_nom
    res = run_pypsa(model, {"carbonPrice": 0.0, "discountRate": 0.05},
                    {**OPTIONS, "marketSimConfig": {**_M15_SIM, "pricing": pricing}})
    return res["marketSimulation"]


def test_module_15_uniform_pricing_baseline(tmp_path: Path) -> None:
    """The design every earlier module assumed, priced explicitly for once."""
    sim = _sim(tmp_path, "uniform")
    summary = sim["summary"]
    assert summary["avgPrice"] == pytest.approx(24.50, abs=0.02)
    assert summary["totalCost"] == pytest.approx(25_394_711.0, rel=0.001)
    assert summary["unservedMWh"] == pytest.approx(0.0, abs=1e-6)
    units = {u["name"]: u for u in sim["units"]}
    assert units["coal_1"]["profit"] == pytest.approx(1_972_000.0, rel=0.001)
    assert units["wind_1"]["revenue"] == pytest.approx(5_905_943.0, rel=0.001)
    # The marginal unit is paid its own cost, by construction.
    assert units["gas_supply"]["profit"] == pytest.approx(0.0, abs=1.0)


def test_module_15_gas_sets_the_price_nine_hours_in_ten(tmp_path: Path) -> None:
    """The most useful single summary of a market: who is marginal, and how often."""
    units = {u["name"]: u for u in _sim(tmp_path, "uniform")["units"]}
    assert units["gas_supply"]["priceSettingHours"] == 7888
    assert units["coal_1"]["priceSettingHours"] == 872
    assert units["wind_1"]["priceSettingHours"] == 0
    assert sum(u["priceSettingHours"] for u in units.values()) == 8760


def test_module_15_pay_as_bid_same_dispatch_much_smaller_bill(tmp_path: Path) -> None:
    """The settlement rule moves the money and not one megawatt-hour.

    And the truthful zero-cost bidders are paid nothing — the reason nobody bids
    truthfully under pay-as-bid, which is why the 38% saving is imaginary.
    """
    uniform = _sim(tmp_path, "uniform")
    pab = _sim(tmp_path, "payAsBid")
    u_units = {u["name"]: u for u in uniform["units"]}
    p_units = {u["name"]: u for u in pab["units"]}
    for name in ("coal_1", "gas_supply", "wind_1", "ror_1"):
        assert p_units[name]["energyMWh"] == pytest.approx(u_units[name]["energyMWh"], rel=1e-9)
    assert pab["summary"]["totalCost"] == pytest.approx(15_622_897.0, rel=0.001)
    assert pab["summary"]["totalCost"] < uniform["summary"]["totalCost"] * 0.65
    for name in ("wind_1", "ror_1"):
        assert p_units[name]["revenue"] == pytest.approx(0.0, abs=1e-6)
    for name in ("coal_1", "gas_supply", "wind_1", "ror_1"):
        assert p_units[name]["profit"] == pytest.approx(0.0, abs=1.0)


def test_module_15_rule_based_storage_finds_no_spread(tmp_path: Path) -> None:
    """A threshold rule needs price variance, and the base market has almost none."""
    for unit in _sim(tmp_path, "uniform")["storage"]:
        assert unit["energyDischargedMWh"] == pytest.approx(0.0, abs=1e-6)
        assert unit["energyChargedMWh"] == pytest.approx(0.0, abs=1e-6)


def test_module_15_scarcity_pays_the_peaker_that_earned_nothing(tmp_path: Path) -> None:
    """0.27% of the year unserved, the bill up 8.5 times — and module 14's idle
    peaker clears 54 million. This is how an energy-only market pays capacity.

    The storage that found no spread in the base market trades here, because the
    variance it needed finally exists.

    Re-baselined 2026-10-27 (was 2,779.5 MWh / 470 h / 209.94 / 214,758,788 / oil
    2,374 h): the simulation's storage rule now respects the units' energy limits
    (RE3), which moves the scarcity hours by a handful and the bill by 0.15%.
    """
    scarce = _sim(tmp_path, "uniform", gas_p_nom=40.0)
    summary = scarce["summary"]
    assert summary["unservedMWh"] == pytest.approx(2_782.2, rel=0.01)
    assert summary["unservedHours"] == 471
    assert summary["peakPrice"] == pytest.approx(3_000.0, rel=1e-6)
    assert summary["avgPrice"] == pytest.approx(210.32, rel=0.01)
    assert summary["totalCost"] == pytest.approx(215_094_657.0, rel=0.001)
    oil = next(u for u in scarce["units"] if u["name"] == "oil_1")
    assert oil["energyMWh"] == pytest.approx(63_316.7, rel=0.01)
    assert oil["profit"] == pytest.approx(54_259_200.0, rel=0.01)
    assert oil["priceSettingHours"] == 2379
    assert any(s["energyDischargedMWh"] > 0 for s in scarce["storage"]), "storage wakes up"


def test_module_15_the_study_clears_workbook_capacity(tmp_path: Path) -> None:
    """Step 8's trap, asserted so it cannot quietly stop being true.

    The study never solves, so it reads p_nom. On the expanded checkpoint that
    is the PRE-expansion wind farm — the same 241,212 MWh as the brownfield
    year, not the 603,645 that fleet really generates.
    """
    from backend.pypsa.results import run_pypsa

    expanded = run_pypsa(
        _model_from_example("training_m7", tmp_path),
        {"carbonPrice": 0.0, "discountRate": 0.05},
        {**OPTIONS, "marketSimConfig": {**_M15_SIM, "pricing": "uniform"}},
    )["marketSimulation"]
    brownfield = _sim(tmp_path, "uniform")
    wind_expanded = next(u for u in expanded["units"] if u["name"] == "wind_1")
    wind_brownfield = next(u for u in brownfield["units"] if u["name"] == "wind_1")
    assert wind_expanded["energyMWh"] == pytest.approx(wind_brownfield["energyMWh"], rel=1e-6)
    assert wind_expanded["energyMWh"] < 300_000.0, "not the expanded fleet's 603,645 MWh"


# ── Module 16 — the multi-year pathway ───────────────────────────────────────
#
# `training_m16_start` is three investment periods (2030 / 2040 / 2050), each ONE
# representative day standing for a year: snapshot weights 365 on `objective` and
# `generators`, 1 on `stores`. Every number the module states comes from solving it
# through the app's own path with the Settings -> Multi-year planning table the
# module has the learner type (objective weights = discounted years, years = 10).

_M16_SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.05}
_M16_PERIODS = (2030, 2040, 2050)
_M16_WEIGHTS = {2030: 8.1078, 2040: 4.9775, 2050: 3.0558}


def _m16_options(weights: dict[int, float] | None = None, years: float = 10.0,
                 price: dict[int, float] | None = None) -> dict:
    options: dict = {
        **OPTIONS,
        "pathwayConfig": {
            "enabled": True, "planningMode": "pathway",
            "snapshotMappingMode": "explicit_period_column",
            "periods": [
                {"period": p, "objectiveWeight": (weights or _M16_WEIGHTS)[p], "yearsWeight": years}
                for p in _M16_PERIODS
            ],
        },
    }
    if price:
        options["carbonPriceSchedule"] = [{"year": y, "price": v} for y, v in price.items()]
    return options


def _m16_model(tmp_path: Path, example: str = "training_m16_start", *,
               caps: dict[int, float] | None = None, coal_old_lifetime: float | None = None) -> dict:
    model = {k: [dict(r) for r in v] for k, v in _model_from_example(example, tmp_path).items()}
    if caps is not None:
        model["global_constraints"] = [
            {"name": f"co2_cap_{p}", "type": "primary_energy", "carrier_attribute": "co2_emissions",
             "sense": "<=", "constant": c, "investment_period": p}
            for p, c in caps.items()
        ]
    if coal_old_lifetime is not None:
        for gen in model["generators"]:
            if gen["name"] == "coal_old":
                gen["lifetime"] = coal_old_lifetime
    return model


def _m16_solve(model: dict, options: dict):
    n, _notes = build_network(model, _M16_SCENARIO, options)
    n.optimize(solver_name="highs", multi_investment_periods=True, include_objective_constant=False,
               extra_functionality=carbon_pricing.extra_functionality)
    return n


def _m16_annual_emissions(n) -> dict[int, float]:
    """tCO2 a year per period: sum_t w_t * p_t / eta * co2 (the `years` weight is NOT applied)."""
    out: dict[int, float] = {}
    level = n.snapshots.get_level_values("period")
    for p in _M16_PERIODS:
        snaps = n.snapshots[level == p]
        weight = n.snapshot_weightings["generators"].loc[snaps]
        total = 0.0
        for g in n.generators.index:
            factor = float(n.carriers.at[n.generators.at[g, "carrier"], "co2_emissions"])
            total += (
                float((n.generators_t.p.loc[snaps, g] * weight).sum())
                / float(n.generators.at[g, "efficiency"]) * factor
            )
        out[p] = total
    return out


def _m16_builds(n) -> dict[str, float]:
    """Optimal capacity (MW) of every vintage the optimiser actually built."""
    out = {k: float(v) for k, v in n.generators.p_nom_opt.items() if k[-4:].isdigit() and v > 0.01}
    out.update({k: float(v) for k, v in n.storage_units.p_nom_opt.items() if v > 0.01})
    return out


def test_module_16_objective_weights_are_discounted_years() -> None:
    """Step 2's typed numbers: w_p = sum_{k<10} 1.05^-(p - 2030 + k)."""
    from backend.scripts.make_examples import pathway_objective_weights

    weights = pathway_objective_weights()
    for period, typed in _M16_WEIGHTS.items():
        assert weights[period] == pytest.approx(typed, abs=5e-5)
    # Each decade is worth 1.05^-10 = 0.6139 of the one before: the discount factor, not 'a third each'.
    assert weights[2040] / weights[2030] == pytest.approx(1.05 ** -10, rel=1e-9)
    assert weights[2050] / weights[2040] == pytest.approx(1.05 ** -10, rel=1e-9)


def test_module_16_checkpoint_carries_the_settings_the_module_types(tmp_path: Path) -> None:
    """`training_m16` restores the pathway table and the three caps, so 'start from the finished model' works."""
    model = _model_from_example("training_m16", tmp_path)
    periods = {int(r["period"]): r for r in model["RAGNAROK_PathwayPeriods"]}
    assert {p: r["objectiveWeight"] for p, r in periods.items()} == _M16_WEIGHTS
    assert all(r["yearsWeight"] == 10 for r in periods.values())
    assert model["RAGNAROK_Pathway"][0]["enabled"] is True
    caps = {int(r["investment_period"]): float(r["constant"]) for r in model["global_constraints"]}
    assert caps == {2030: 10_000_000.0, 2040: 4_000_000.0, 2050: 300_000.0}
    # The start model has neither.
    start = _model_from_example("training_m16_start", tmp_path)
    assert "global_constraints" not in start and "RAGNAROK_PathwayPeriods" not in start
    assert all("period" in row for row in start["snapshots"]), "the snapshots sheet carries the period column"


def test_module_16_assets_become_active_and_retire_by_build_year_and_lifetime(tmp_path: Path) -> None:
    """Step 3: active iff build_year <= period < build_year + lifetime."""
    from backend.pypsa.results.pathway_periods import active_assets

    n = _m16_solve(_m16_model(tmp_path), _m16_options())
    active = {p: active_assets(n, "generators", p) for p in _M16_PERIODS}
    assert [bool(active[p]["coal_old"]) for p in _M16_PERIODS] == [True, False, False]   # 1985 + 50 = 2035
    assert [bool(active[p]["coal_new"]) for p in _M16_PERIODS] == [True, True, False]    # 2000 + 45 = 2045
    assert [bool(active[p]["gas_ccgt"]) for p in _M16_PERIODS] == [True, True, True]     # 2010 + 45 = 2055
    assert [bool(active[p]["wind_2040"]) for p in _M16_PERIODS] == [False, True, True]
    assert [bool(active[p]["solar_2050"]) for p in _M16_PERIODS] == [False, False, True]


def test_module_16_baseline_pathway_without_policy(tmp_path: Path) -> None:
    """Step 4: nothing is built in 2030 — waiting is cheaper while the vintages get cheaper."""
    n = _m16_solve(_m16_model(tmp_path), _m16_options())
    assert float(n.objective) == pytest.approx(589_565_227.7, rel=1e-6)
    builds = _m16_builds(n)
    assert set(builds) == {"wind_2040", "solar_2040", "wind_2050", "solar_2050", "batt_2040", "batt_2050"}
    assert builds["wind_2040"] == pytest.approx(183.39, abs=0.05)
    assert builds["solar_2040"] == pytest.approx(7.60, abs=0.05)
    assert builds["wind_2050"] == pytest.approx(200.0, abs=0.05)      # the p_nom_max
    assert builds["solar_2050"] == pytest.approx(250.0, abs=0.05)     # the p_nom_max
    assert builds["batt_2040"] == pytest.approx(39.57, abs=0.05)
    assert builds["batt_2050"] == pytest.approx(100.0, abs=0.05)
    annual = _m16_annual_emissions(n)
    assert annual[2030] == pytest.approx(1_189_325.0, rel=1e-4)
    assert annual[2040] == pytest.approx(967_293.0, rel=1e-4)
    assert annual[2050] == pytest.approx(59_145.0, rel=1e-3)


def test_module_16_period_views_mask_inactive_assets_and_weight_money(tmp_path: Path) -> None:
    """Steps 5-6: the period selector. Energy is summed, money is x the period's objective weight."""
    from backend.app import results_derived as rd
    from backend.pypsa.results import run_pypsa
    from backend.pypsa.results.derive_outputs import derive_results_from_outputs

    model = _m16_model(tmp_path)
    options = _m16_options()
    whole = run_pypsa(model, _M16_SCENARIO, options)
    views = {p: derive_results_from_outputs(model, whole["outputs"], _M16_SCENARIO, options, period=p)
             for p in _M16_PERIODS}

    def kpis(result: dict) -> dict:
        return rd.compute_kpis(result, model["carriers"], set(), "$", list)

    # Whole-horizon KPI strip: emissions are x years (22,158 kt = 10 x the sum of the annual figures).
    assert kpis(whole)["emissions"] == "22,158 ktCO2e"
    assert kpis(views[2030])["emissions"] == "11,893 ktCO2e"
    assert kpis(views[2040])["emissions"] == "9,673 ktCO2e"
    assert kpis(views[2050])["emissions"] == "591 ktCO2e"
    # Inactive assets are masked: 2040 has coal_new + gas_ccgt + wind_2040 + solar_2040 = 491 MW, not 641.
    capacity = {p: next(s["value"] for s in views[p]["summary"] if s["label"] == "Generator capacity")
                for p in _M16_PERIODS}
    assert capacity == {2030: "450 MW", 2040: "491 MW", 2050: "791 MW"}
    summaries = {s["period"]: s for s in whole["pathway"]["summaries"]}
    assert summaries[2040]["installedCapacityMw"] == pytest.approx(490.99, abs=0.05)
    assert summaries[2040]["installedCapacityMw"] != pytest.approx(490.99 + 150.0, abs=1.0)

    # Money: fuel cost in a period view = annual fuel x the period's objective weight; the periods add up to the run.
    def part(result: dict, label: str) -> float:
        return float(next(c["value"] for c in result["costBreakdown"] if c["label"].startswith(label)))

    for label in ("Fuel cost", "Capital cost"):
        assert sum(part(views[p], label) for p in _M16_PERIODS) == pytest.approx(part(whole, label), rel=1e-6)
    assert part(whole, "Fuel cost") == pytest.approx(365_027_989.0, rel=1e-6)
    assert part(whole, "Capital cost") == pytest.approx(224_537_234.0, rel=1e-6)
    assert part(views[2030], "Fuel cost") == pytest.approx(226_889_583.0, rel=1e-6)
    assert part(views[2030], "Capital cost") == pytest.approx(0.0, abs=1.0)
    # Average prices are NOT weighted (they are per-MWh): coal marginal in 2030, gas in 2050.
    assert summaries[2030]["averagePrice"] == pytest.approx(20.0, abs=1e-6)
    assert summaries[2050]["averagePrice"] == pytest.approx(38.67, abs=0.02)
    assert [summaries[p]["objectiveWeight"] for p in _M16_PERIODS] == [8.1078, 4.9775, 3.0558]


def test_module_16_capital_is_an_annuity_charged_in_every_active_period(tmp_path: Path) -> None:
    """Step 7: overnight 1.3M -> 92,238/yr; wind_2040 is active 2040 AND 2050, so it is paid twice."""
    from backend.pypsa.results import run_pypsa
    from pypsa.costs import annuity

    af25, af15 = annuity(0.05, 25.0), annuity(0.05, 15.0)
    assert af25 == pytest.approx(0.0709525, abs=1e-7)
    assert af15 == pytest.approx(0.0963423, abs=1e-7)
    res = run_pypsa(_m16_model(tmp_path), _M16_SCENARIO, _m16_options())
    rows = {r["name"]: r for r in res["expansionResults"]}
    assert rows["wind_2040"]["capital_cost"] == pytest.approx(1_300_000.0 * af25, rel=1e-6)
    assert rows["batt_2040"]["capital_cost"] == pytest.approx(350_000.0 * af15, rel=1e-6)
    assert rows["wind_2040"]["active_periods"] == [2040, 2050]
    assert rows["wind_2050"]["active_periods"] == [2050]
    annual = rows["wind_2040"]["capital_cost"] * rows["wind_2040"]["p_nom_opt_mw"]
    assert rows["wind_2040"]["capex_by_period"]["2040"] == pytest.approx(annual, rel=1e-4)
    assert rows["wind_2040"]["capex_by_period"]["2050"] == pytest.approx(annual, rel=1e-4)
    assert rows["wind_2040"]["capex_by_period"]["2030"] == 0
    assert rows["wind_2040"]["capex_weighted"] == pytest.approx(annual * (4.9775 + 3.0558), rel=1e-4)


def test_module_16_retirement_date_moves_the_baseline_but_not_the_capped_plan(tmp_path: Path) -> None:
    """Step 6: extending coal_old to 60 years keeps it through 2040 (retires 2045)."""
    options = _m16_options()
    base = _m16_solve(_m16_model(tmp_path, coal_old_lifetime=60.0), options)
    assert float(base.objective) == pytest.approx(581_972_357.1, rel=1e-6)
    annual = _m16_annual_emissions(base)
    assert annual[2040] == pytest.approx(1_337_165.0, rel=1e-4)     # was 967,293
    assert annual[2050] == pytest.approx(256_170.0, rel=1e-3)       # was 59,145
    # Under the cap trajectory the retirement date is irrelevant: the same plan, to the dollar.
    capped = _m16_solve(_m16_model(tmp_path, "training_m16", coal_old_lifetime=60.0), options)
    assert float(capped.objective) == pytest.approx(626_611_133.6, rel=1e-6)


def test_module_16_carbon_price_schedule_is_read_by_period_label(tmp_path: Path) -> None:
    """Step 7b: a year -> price table; in pathway mode the 'year' is the period label."""
    from backend.pypsa.results import run_pypsa

    price = {2030: 20.0, 2040: 60.0, 2050: 120.0}
    options = _m16_options(price=price)
    n = _m16_solve(_m16_model(tmp_path), options)
    annual = _m16_annual_emissions(n)
    assert annual[2030] == pytest.approx(570_936.0, rel=1e-3)
    assert annual[2040] == pytest.approx(123_492.0, rel=1e-3)
    assert annual[2050] == pytest.approx(0.0, abs=1.0)
    assert float(n.objective) == pytest.approx(872_790_016.5, rel=1e-6)
    res = run_pypsa(_m16_model(tmp_path), _M16_SCENARIO, options)
    carbon = next(c["value"] for c in res["costBreakdown"] if c["label"] == "Carbon cost")
    assert float(carbon) == pytest.approx(129_461_548.0, rel=1e-4)
    # The objective now includes the carbon payments, so it is NOT comparable with the cap run's.
    assert float(n.objective) > 626_611_133.6


def test_module_16_cap_trajectory_binds_every_period(tmp_path: Path) -> None:
    """Step 8: caps typed as tonnes PER PERIOD = annual tonnes x years."""
    from backend.pypsa.results import run_pypsa

    n = _m16_solve(_m16_model(tmp_path, "training_m16"), _m16_options())
    assert float(n.objective) == pytest.approx(626_611_133.6, rel=1e-6)
    annual = _m16_annual_emissions(n)
    for period, cap in {2030: 10_000_000.0, 2040: 4_000_000.0, 2050: 300_000.0}.items():
        assert annual[period] * 10.0 == pytest.approx(cap, rel=1e-4)     # binds exactly, x the years weight
    builds = _m16_builds(n)
    assert builds["solar_2030"] == pytest.approx(89.27, abs=0.05)         # the first thing the 2030 cap buys
    assert builds["wind_2040"] == pytest.approx(200.0, abs=0.05)
    assert builds["solar_2040"] == pytest.approx(154.59, abs=0.05)
    assert builds["batt_2040"] == pytest.approx(89.05, abs=0.05)
    # The Settings table pre-fills sense "==": here every cap binds, so an equality lands on the same plan.
    equal_model = _m16_model(tmp_path, "training_m16")
    for row in equal_model["global_constraints"]:
        row["sense"] = "=="
    assert float(_m16_solve(equal_model, _m16_options()).objective) == pytest.approx(float(n.objective), rel=1e-9)
    # Ragnarok reports ONE shadow price: the binding constraint with the largest |dual| - the 2030 cap.
    res = run_pypsa(_m16_model(tmp_path, "training_m16"), _M16_SCENARIO, _m16_options())
    shadow = res["co2Shadow"]
    assert shadow["constraint_name"] == "co2_cap_2030" and shadow["status"] == "binding"
    assert shadow["shadow_price"] == pytest.approx(12.0533, rel=2e-3)
    assert shadow["cap_value"] == pytest.approx(10_000.0, abs=0.1)        # kt of period tonnes
    mu = {name: abs(float(v)) for name, v in n.global_constraints["mu"].items()}
    assert mu["co2_cap_2030"] == pytest.approx(12.0533, rel=2e-3)
    assert mu["co2_cap_2040"] == pytest.approx(8.3878, rel=5e-3)
    assert mu["co2_cap_2050"] == pytest.approx(0.6943, rel=2e-2)


def test_module_16_a_cap_dual_is_in_discounted_dollars_per_period_tonne(tmp_path: Path) -> None:
    """The unit the module teaches: relax the 2030 cap by 1,000 t and the objective falls by mu x 1,000;
    in 2030 money per annual tonne the price is mu x years / objective weight = 14.87."""
    base = _m16_solve(_m16_model(tmp_path, "training_m16"), _m16_options())
    mu = abs(float(base.global_constraints.at["co2_cap_2030", "mu"]))
    relaxed = _m16_solve(
        _m16_model(tmp_path, "training_m16", caps={2030: 10_001_000.0, 2040: 4_000_000.0, 2050: 300_000.0}),
        _m16_options(),
    )
    assert float(base.objective) - float(relaxed.objective) == pytest.approx(mu * 1_000.0, rel=1e-3)
    assert mu * 10.0 / 8.1078 == pytest.approx(14.866, abs=0.01)


def test_module_16_years_weight_scales_the_cap_in_both_directions(tmp_path: Path) -> None:
    """Step 9: the cap is on sum_t w_t x years x e_t, so the constant and the years weight are one decision."""
    correct = _m16_solve(_m16_model(tmp_path, "training_m16"), _m16_options())
    # (a) years weight left at 1 with the per-period caps: the caps are ten times too loose - and slack.
    slack = _m16_solve(_m16_model(tmp_path, "training_m16"), _m16_options(years=1.0))
    assert float(slack.objective) == pytest.approx(589_565_227.7, rel=1e-6)    # the no-policy baseline
    assert _m16_annual_emissions(slack)[2030] == pytest.approx(1_189_325.0, rel=1e-4)
    # (b) annual tonnes typed with years = 10: ten times too tight.
    annual_caps = {2030: 1_000_000.0, 2040: 400_000.0, 2050: 30_000.0}
    tight = _m16_solve(_m16_model(tmp_path, "training_m16", caps=annual_caps), _m16_options())
    assert float(tight.objective) == pytest.approx(907_496_653.8, rel=1e-6)
    assert float(tight.objective) / float(correct.objective) == pytest.approx(1.448, abs=0.002)
    em = _m16_annual_emissions(tight)
    assert em[2030] == pytest.approx(100_000.0, rel=1e-3)
    assert em[2040] == pytest.approx(40_000.0, rel=1e-3)
    assert em[2050] == pytest.approx(3_000.0, rel=1e-2)
    # (c) the same annual tonnes with years = 1 is the intended plan again.
    fixed = _m16_solve(_m16_model(tmp_path, "training_m16", caps=annual_caps), _m16_options(years=1.0))
    assert float(fixed.objective) == pytest.approx(float(correct.objective), rel=1e-9)


def test_module_16_only_ratios_of_objective_weights_matter(tmp_path: Path) -> None:
    """Step 10: weights 1/1/1 and 10/10/10 give one plan (objective x10); discounting gives a different one."""
    model = _m16_model(tmp_path, "training_m16")
    one = _m16_solve(model, _m16_options(weights={2030: 1.0, 2040: 1.0, 2050: 1.0}))
    ten = _m16_solve(model, _m16_options(weights={2030: 10.0, 2040: 10.0, 2050: 10.0}))
    discounted = _m16_solve(model, _m16_options())
    assert float(one.objective) == pytest.approx(128_682_062.9, rel=1e-6)
    assert float(ten.objective) == pytest.approx(10.0 * float(one.objective), rel=1e-9)
    assert _m16_builds(one) == pytest.approx(_m16_builds(ten), abs=1e-3)
    assert _m16_builds(one)["solar_2030"] == pytest.approx(85.94, abs=0.05)
    assert _m16_builds(discounted)["solar_2030"] == pytest.approx(89.27, abs=0.05)
    # Without discounting the 2050 cap is not even binding any more.
    assert _m16_annual_emissions(one)[2050] * 10.0 < 300_000.0 * 0.5
    assert float(discounted.objective) / float(one.objective) > 4.5


def test_module_16_kpi_strip_strings_the_lessons_quote(tmp_path: Path) -> None:
    """What the KPI strip prints for each run the module has the learner make (whole run and per period)."""
    from backend.app import results_derived as rd
    from backend.pypsa.results import run_pypsa
    from backend.pypsa.results.derive_outputs import derive_results_from_outputs

    def strip(model: dict, options: dict) -> dict:
        res = run_pypsa(model, _M16_SCENARIO, options)
        out = {"whole": rd.compute_kpis(res, model["carriers"], set(), "$", list)}
        for p in _M16_PERIODS:
            view = derive_results_from_outputs(model, res["outputs"], _M16_SCENARIO, options, period=p)
            out[p] = rd.compute_kpis(view, model["carriers"], set(), "$", list)
        return out

    base = strip(_m16_model(tmp_path), _m16_options())
    assert base["whole"]["totalCost"] == "$589,565,227"
    assert [base[p]["emissions"] for p in _M16_PERIODS] == ["11,893 ktCO2e", "9,673 ktCO2e", "591 ktCO2e"]
    assert base[2040]["totalCost"] == "$205,870,256"
    life = strip(_m16_model(tmp_path, coal_old_lifetime=60.0), _m16_options())
    assert life["whole"]["totalCost"] == "$581,972,357"
    assert [life[p]["emissions"] for p in _M16_PERIODS] == ["11,893 ktCO2e", "13,372 ktCO2e", "2,562 ktCO2e"]
    price = strip(_m16_model(tmp_path), _m16_options(price={2030: 20.0, 2040: 60.0, 2050: 120.0}))
    assert price["whole"]["totalCost"] == "$872,790,016"
    assert [price[p]["emissions"] for p in _M16_PERIODS] == ["5,709 ktCO2e", "1,235 ktCO2e", "0 ktCO2e"]
    cap = strip(_m16_model(tmp_path, "training_m16"), _m16_options())
    assert cap["whole"]["totalCost"] == "$626,611,134"
    assert [cap[p]["emissions"] for p in _M16_PERIODS] == ["10,000 ktCO2e", "4,000 ktCO2e", "300 ktCO2e"]
    loose = strip(_m16_model(tmp_path, "training_m16"), _m16_options(years=1.0))
    assert loose["whole"]["totalCost"] == "$589,565,227"
    assert [loose[p]["emissions"] for p in _M16_PERIODS] == ["1,189 ktCO2e", "967 ktCO2e", "59 ktCO2e"]
    tight = strip(_m16_model(tmp_path, "training_m16", caps={2030: 1e6, 2040: 4e5, 2050: 3e4}), _m16_options())
    assert tight["whole"]["totalCost"] == "$907,496,654"
    assert [tight[p]["emissions"] for p in _M16_PERIODS] == ["1,000 ktCO2e", "400 ktCO2e", "30 ktCO2e"]


def test_module_16_foresight_a_2050_cap_changes_what_is_built_in_2040(tmp_path: Path) -> None:
    """Step 11: one joint problem. Ragnarok has no myopic mode; a late cap pulls investment forward."""
    base = _m16_solve(_m16_model(tmp_path), _m16_options())
    late = _m16_solve(_m16_model(tmp_path, caps={2050: 300_000.0}), _m16_options())
    assert _m16_builds(base)["batt_2040"] == pytest.approx(39.57, abs=0.05)
    assert _m16_builds(late)["batt_2040"] == pytest.approx(97.7, abs=0.1)
    assert _m16_builds(base)["solar_2040"] == pytest.approx(7.60, abs=0.05)
    assert _m16_builds(late)["solar_2040"] == pytest.approx(63.85, abs=0.1)
    # 2040 itself is unconstrained, yet its emissions differ from the no-policy run.
    assert _m16_annual_emissions(base)[2040] == pytest.approx(967_293.0, rel=1e-4)
    assert _m16_annual_emissions(late)[2040] == pytest.approx(1_004_338.0, rel=1e-4)


# ── Module 17 — batteries in depth ───────────────────────────────────────────
#
# `training_m17_start` is a solar-heavy single bus over three days (the middle one
# overcast): 700 MW of solar, a 300 MW CCGT at 80 and a 200 MW peaker at 140
# against a 400 MW evening peak. `training_m17` adds a 100 MW / 4 h battery at
# 0.95 each way. Every figure the module states is solved here through the app's
# own build path; module 4's 3-hour battery is not repeated.

_M17_SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.05}


def _m17_model(tmp_path: Path, example: str = "training_m17", **battery: object) -> dict:
    model = {k: [dict(r) for r in v] for k, v in _model_from_example(example, tmp_path).items()}
    for row in model.get("storage_units", []):
        row.update(battery)
    return model


def _m17_solve(model: dict, options: dict | None = None):
    n, _notes = build_network(model, _M17_SCENARIO, {**OPTIONS, **(options or {})})
    n.optimize(solver_name="highs", include_objective_constant=False)
    return n


def _m17_objective(tmp_path: Path, example: str = "training_m17", options: dict | None = None,
                   **battery: object) -> float:
    return float(_m17_solve(_m17_model(tmp_path, example, **battery), options).objective)


def _m17_flows(n) -> tuple[float, float]:
    """(MWh discharged, MWh drawn from the grid) over the run."""
    su = n.storage_units_t
    return float(su.p_dispatch["batt"].sum()), float(su.p_store["batt"].sum())


def test_module_17_start_system_has_a_midday_surplus_and_three_prices(tmp_path: Path) -> None:
    """Step 1: with no battery, prices are 0 / 80 / 140 and 40% of the solar is thrown away."""
    n = _m17_solve(_m17_model(tmp_path, "training_m17_start"))
    assert float(n.objective) == pytest.approx(997_894.4, rel=1e-6)
    price = n.buses_t.marginal_price["grid"]
    assert int((price.abs() < 1e-6).sum()) == 23           # solar surplus: free energy
    assert int(((price - 80.0).abs() < 1e-6).sum()) == 37  # CCGT marginal
    assert int(((price - 140.0).abs() < 1e-6).sum()) == 12 # peaker marginal
    available = n.generators.at["solar", "p_nom"] * n.generators_t.p_max_pu["solar"]
    curtailed = float((available - n.generators_t.p["solar"]).sum())
    assert float(available.sum()) == pytest.approx(11_245.4, abs=0.1)
    assert curtailed == pytest.approx(4_463.4, abs=0.1)
    assert float(n.generators_t.p["gas_peaker"].sum()) == pytest.approx(831.4, abs=0.1)
    assert float(n.generators_t.p["gas_ccgt"].sum()) == pytest.approx(11_018.8, abs=0.1)


def test_module_17_battery_removes_the_peaker_and_cannibalises_its_own_spread(tmp_path: Path) -> None:
    """Step 2: 100 MW / 4 h. The system saves 125,176; the battery's OWN revenue at the new prices is 60,800."""
    n = _m17_solve(_m17_model(tmp_path))
    assert float(n.objective) == pytest.approx(872_717.9, rel=1e-6)
    assert 997_894.4 - float(n.objective) == pytest.approx(125_176.5, abs=0.5)
    discharged, drawn = _m17_flows(n)
    assert discharged == pytest.approx(941.19, abs=0.02)
    assert drawn == pytest.approx(1_042.87, abs=0.02)
    assert discharged / drawn == pytest.approx(0.95 * 0.95, rel=1e-9)     # round trip is the product
    assert discharged / 400.0 == pytest.approx(2.35, abs=0.005)            # equivalent full cycles in the window
    price = n.buses_t.marginal_price["grid"]
    assert float(price.max()) == pytest.approx(80.0, abs=1e-6)             # the 140 hours are gone
    assert int(((price - 140.0).abs() < 1e-6).sum()) == 0
    assert float(price.mean()) == pytest.approx(59.458, abs=0.001)          # was 64.444
    revenue = float(((n.storage_units_t.p_dispatch["batt"] - n.storage_units_t.p_store["batt"]) * price).sum())
    assert revenue == pytest.approx(60_800.0, abs=0.5)
    # The state of charge fills on the sunny days and only part-way on the overcast one.
    soc = n.storage_units_t.state_of_charge["batt"]
    by_day = [float(soc.iloc[24 * d: 24 * d + 24].max()) for d in range(3)]
    assert by_day == pytest.approx([400.0, 291.7, 400.0], abs=0.1)
    assert [int(soc.iloc[24 * d: 24 * d + 24].to_numpy().argmax()) for d in (0, 2)] == [16, 16]
    # Curtailment fell by exactly what the battery drew.
    available = n.generators.at["solar", "p_nom"] * n.generators_t.p_max_pu["solar"]
    assert float((available - n.generators_t.p["solar"]).sum()) == pytest.approx(4_463.4 - drawn, abs=0.2)


def test_module_17_value_of_each_extra_hour_of_duration_falls_and_then_stops(tmp_path: Path) -> None:
    """Step 3: max_hours 1 / 2 / 4 / 8 at 100 MW; more than 8 h is worth nothing here."""
    objective = {h: _m17_objective(tmp_path, max_hours=h) for h in (1, 2, 4, 8, 16)}
    assert objective[1] == pytest.approx(957_994.4, rel=1e-6)
    assert objective[2] == pytest.approx(918_875.7, rel=1e-6)
    assert objective[4] == pytest.approx(872_717.9, rel=1e-6)
    assert objective[8] == pytest.approx(818_988.5, rel=1e-6)
    assert objective[16] == pytest.approx(objective[8], rel=1e-9)
    base = 997_894.4
    per_hour = [(base - objective[1]) / 1, (objective[1] - objective[2]) / 1,
                (objective[2] - objective[4]) / 2, (objective[4] - objective[8]) / 4]
    assert per_hour == pytest.approx([39_900.0, 39_118.7, 23_079.0, 13_432.3], abs=1.0)
    assert per_hour == sorted(per_hour, reverse=True)


def test_module_17_energy_binds_before_power_and_then_power_binds(tmp_path: Path) -> None:
    """Step 3: 400 MWh as 400 MW x 1 h, 200 x 2 h or 100 x 4 h is one answer; 50 x 8 h is power-limited."""
    same = [_m17_objective(tmp_path, p_nom=p, max_hours=h) for p, h in ((400, 1), (200, 2), (100, 4))]
    assert same == pytest.approx([872_717.9] * 3, rel=1e-6)
    assert _m17_objective(tmp_path, p_nom=50, max_hours=8) == pytest.approx(890_040.0, rel=1e-6)


def test_module_17_efficiency_applies_to_each_leg_and_splitting_wrongly_double_counts(tmp_path: Path) -> None:
    """Step 4: 0.95 x 0.95 = 0.9025 round trip. Typing the round trip into BOTH legs gives 0.8145."""
    lossless = _m17_objective(tmp_path, efficiency_store=1.0, efficiency_dispatch=1.0)
    split = _m17_objective(tmp_path)
    double = _m17_objective(tmp_path, efficiency_store=0.9025, efficiency_dispatch=0.9025)
    assert lossless == pytest.approx(867_952.0, rel=1e-6)
    assert split == pytest.approx(872_717.9, rel=1e-6)
    assert double == pytest.approx(877_712.6, rel=1e-6)
    assert double - split == pytest.approx(4_994.7, abs=0.5)
    n = _m17_solve(_m17_model(tmp_path, efficiency_store=0.9025, efficiency_dispatch=0.9025))
    discharged, drawn = _m17_flows(n)
    assert discharged / drawn == pytest.approx(0.9025 ** 2, rel=1e-9)       # 0.8145
    # What the learner meant by "90% round trip": sqrt(0.9) = 0.9487 on each leg.
    assert 0.9 ** 0.5 == pytest.approx(0.94868, abs=1e-5)


def test_module_17_standing_loss_is_a_fraction_of_the_stock_lost_every_hour(tmp_path: Path) -> None:
    """Step 5: 1% an hour is 21.4% a day, and it makes holding energy expensive."""
    objective = {sl: _m17_objective(tmp_path, standing_loss=sl) for sl in (0.0, 0.002, 0.01, 0.02)}
    assert objective[0.0] == pytest.approx(872_717.9, rel=1e-6)
    assert objective[0.002] == pytest.approx(873_718.0, rel=1e-6)
    assert objective[0.01] == pytest.approx(876_703.9, rel=1e-6)
    assert objective[0.02] == pytest.approx(879_928.8, rel=1e-6)
    assert 1 - 0.99 ** 24 == pytest.approx(0.2143, abs=1e-4)
    n = _m17_solve(_m17_model(tmp_path, standing_loss=0.01))
    soc, su = n.storage_units_t.state_of_charge["batt"], n.storage_units_t
    idle = [i for i in range(1, len(soc))
            if abs(su.p_dispatch["batt"].iloc[i]) < 1e-9 and abs(su.p_store["batt"].iloc[i]) < 1e-9
            and soc.iloc[i - 1] > 1.0]
    assert idle, "the schedule has an idle hour holding energy"
    for i in idle:
        assert soc.iloc[i] == pytest.approx(0.99 * soc.iloc[i - 1], rel=1e-9)


def test_module_17_state_of_charge_boundaries_are_free_energy_or_a_forbidden_carry(tmp_path: Path) -> None:
    """Step 6: initial energy is paid for by nobody; a short cyclic window forbids carrying energy over."""
    cyclic = _m17_objective(tmp_path)
    empty_start = _m17_objective(tmp_path, cyclic_state_of_charge=False, state_of_charge_initial=0.0)
    half_start = _m17_objective(tmp_path, cyclic_state_of_charge=False, state_of_charge_initial=200.0)
    full_start = _m17_objective(tmp_path, cyclic_state_of_charge=False, state_of_charge_initial=400.0)
    assert empty_start == pytest.approx(cyclic, rel=1e-9)
    assert half_start == pytest.approx(857_517.9, rel=1e-6)
    assert cyclic - half_start == pytest.approx(200.0 * 0.95 * 80.0, abs=0.5)     # 190 MWh out x 80
    assert cyclic - full_start == pytest.approx(400.0 * 0.95 * 80.0, abs=0.5)
    # One day at a time: the three windows, each closed on itself.
    days, base_days = [], []
    for start in (0, 24, 48):
        window = {"snapshotStart": start, "snapshotCount": 24}
        days.append(_m17_objective(tmp_path, options=window))
        base_days.append(_m17_objective(tmp_path, "training_m17_start", options=window))
    assert days == pytest.approx([271_976.0, 326_985.5, 274_585.6], rel=1e-6)
    assert base_days == pytest.approx([319_003.2, 357_278.4, 321_612.8], rel=1e-6)
    assert sum(days) - cyclic == pytest.approx(829.2, abs=0.5)    # closing the loop daily costs this much
    saving = [b - d for b, d in zip(base_days, days)]
    assert saving == pytest.approx([47_027.2, 30_292.9, 47_027.2], abs=1.0)
    assert saving[0] / ((997_894.4 - cyclic) / 3.0) == pytest.approx(1.127, abs=0.002)   # one sunny day flatters


def test_module_17_rolling_horizon_terminal_soc_only_governs_the_last_window(tmp_path: Path) -> None:
    """Step 7: a soft target of the horizon-start energy on the final window (an explicit option, default OFF since core cleanup step 5)."""
    from backend.pypsa.results import run_pypsa
    from backend.pypsa.rolling import auto_terminal_penalty

    def roll(terminal: bool, soc0: float) -> tuple[float, list[float]]:
        res = run_pypsa(
            _m17_model(tmp_path, cyclic_state_of_charge=False, state_of_charge_initial=soc0),
            _M17_SCENARIO,
            {**OPTIONS, "rollingConfig": {"enabled": True, "horizonSnapshots": 24, "overlapSnapshots": 0,
                                          "terminalSoc": terminal}},
        )
        cost = sum(float(c["value"]) for c in res["costBreakdown"])
        soc = [float(r["batt"]) for r in res["outputs"]["series"]["storage_units-state_of_charge"]]
        return cost, soc

    on_cost, on_soc = roll(True, 200.0)
    off_cost, off_soc = roll(False, 200.0)
    assert on_soc[-1] == pytest.approx(200.0, abs=0.01)
    assert off_soc[-1] == pytest.approx(0.0, abs=0.01)
    assert on_cost == pytest.approx(875_602.0, rel=1e-4)
    assert off_cost == pytest.approx(858_347.0, rel=1e-4)
    # The first two windows drain the energy regardless: they cannot see the end.
    assert on_soc[23] == pytest.approx(0.0, abs=0.01) and on_soc[47] == pytest.approx(0.0, abs=0.01)
    # No initial energy, no target: both options agree, and cost 829 more than the joint three-day solve.
    zero_on, _ = roll(True, 0.0)
    zero_off, _ = roll(False, 0.0)
    assert zero_on == pytest.approx(zero_off, rel=1e-9)
    assert zero_on == pytest.approx(873_547.0, rel=1e-4)
    # The automatic penalty: twice the dearest marginal cost, so refilling always beats paying the shortfall.
    n = _m17_solve(_m17_model(tmp_path))
    assert auto_terminal_penalty(n) == pytest.approx(280.0, abs=1e-9)


def test_module_17_three_answers_to_what_is_a_battery_worth(tmp_path: Path) -> None:
    """Step 8: the price-taker ESS sweep (base prices), the battery's revenue at the prices it makes, and
    the system saving are three different numbers for the same 100 MW / 4 h."""
    from backend.pypsa.results import run_pypsa

    # The Settings defaults except capital cost, size range and step count: bus auto, 4 h, round trip 90%.
    cfg = {"enabled": True, "bus": "", "maxHours": 4, "capitalCostPerMW": 60_000.0, "minSizeMW": 50.0,
           "maxSizeMW": 200.0, "steps": 4, "roundTripEfficiency": 0.9}
    res = run_pypsa(_m17_model(tmp_path, "training_m17_start"), _M17_SCENARIO, {**OPTIONS, "essConfig": cfg})
    case = res["essBusinessCase"]
    assert case["bus"] == "grid"
    assert case["windowHours"] == pytest.approx(72.0) and case["annualisationFactor"] == pytest.approx(121.6667, abs=1e-4)
    assert case["notes"] == ["No lifetime given: 15 years assumed."]
    sizes = {s["sizeMW"]: s for s in case["sizes"]}
    assert sorted(sizes) == [50.0, 100.0, 150.0, 200.0]
    row = sizes[100.0]
    assert row["arbitrageRevenue"] == pytest.approx(159_378.79, rel=1e-5)            # window revenue
    assert row["annualArbitrageRevenue"] == pytest.approx(19_391_086.61, rel=1e-5)
    assert row["annualisedCapex"] == pytest.approx(6_000_000.0, rel=1e-9)
    assert row["energyCapacityMWh"] == pytest.approx(400.0)
    assert row["throughputMWh"] == pytest.approx(1_138.4, abs=0.1)
    assert row["equivalentFullCycles"] == pytest.approx(2.85, abs=0.005)
    assert row["annualEquivalentFullCycles"] == pytest.approx(346.3, abs=0.1)
    assert row["avgChargePrice"] == pytest.approx(0.0, abs=1e-6)
    assert row["avgDischargePrice"] == pytest.approx(140.0, abs=1e-6)
    assert row["priceSpread"] == pytest.approx(140.0, abs=1e-6)
    assert row["npv"] == pytest.approx(138_994_899.79, rel=1e-4)
    assert row["irr"] == pytest.approx(0.30566, abs=1e-4) and row["paybackYears"] == pytest.approx(3.21, abs=0.01)
    assert case["bestSizeMW"] == 200.0                                                # NPV rises with size, to the top
    # A price taker has no price effect, so revenue is linear in size - the flaw the module names.
    assert sizes[200.0]["arbitrageRevenue"] == pytest.approx(2.0 * row["arbitrageRevenue"], rel=1e-6)
    assert sizes[50.0]["arbitrageRevenue"] == pytest.approx(0.5 * row["arbitrageRevenue"], rel=1e-6)
    # The same battery inside the optimisation: it removes the 140 hours it was assumed to sell into.
    n = _m17_solve(_m17_model(tmp_path))
    price = n.buses_t.marginal_price["grid"]
    own = float(((n.storage_units_t.p_dispatch["batt"] - n.storage_units_t.p_store["batt"]) * price).sum())
    system = 997_894.4 - float(n.objective)
    assert (round(own, 1), round(system, 1)) == pytest.approx((60_800.0, 125_176.5), abs=1.0)
    assert own < system < row["arbitrageRevenue"]
    # A battery of size zero in the model is the same as none: the sweep sees the same base prices.
    zero = run_pypsa(_m17_model(tmp_path, p_nom=0.0), _M17_SCENARIO, {**OPTIONS, "essConfig": cfg})
    zero_row = next(r for r in zero["essBusinessCase"]["sizes"] if r["sizeMW"] == 100.0)
    assert zero_row["arbitrageRevenue"] == pytest.approx(row["arbitrageRevenue"], rel=1e-9)
    discharged, _ = _m17_flows(n)
    assert discharged / 400.0 < row["equivalentFullCycles"]                           # 2.35 < 2.85


def test_module_17_kpi_strip_strings_the_lessons_quote(tmp_path: Path) -> None:
    """What the KPI strip prints for the runs the module has the learner make."""
    from backend.app import results_derived as rd
    from backend.pypsa.results import run_pypsa

    def strip(example: str = "training_m17", options: dict | None = None, **battery: object) -> dict:
        model = _m17_model(tmp_path, example, **battery)
        res = run_pypsa(model, _M17_SCENARIO, {**OPTIONS, **(options or {})})
        return rd.compute_kpis(res, model["carriers"], {"battery"}, "$", list)

    def prices(k: dict) -> tuple[float, float]:
        return round(k["minPrice"], 1), round(k["maxPrice"], 1)

    start = strip("training_m17_start")
    assert start["totalCost"] == "$997,894" and prices(start) == (0.0, 140.0)
    assert round(start["avgPrice"], 1) == 71.4 and round(start["dispatchMwh"], 1) == 18_632.2
    batt = strip()
    assert batt["totalCost"] == "$872,718" and prices(batt) == (0.0, 80.0)
    assert round(batt["avgPrice"], 1) == 58.9
    assert round(batt["dispatchMwh"] - start["dispatchMwh"], 1) == pytest.approx(101.7, abs=0.1)   # the round-trip loss
    assert strip(max_hours=1)["totalCost"] == "$957,994"
    assert strip(max_hours=2)["totalCost"] == "$918,876"
    assert strip(max_hours=8)["totalCost"] == "$818,989" and prices(strip(max_hours=8)) == (0.0, 80.0)
    assert strip(p_nom=50, max_hours=8)["totalCost"] == "$890,040"
    double = strip(efficiency_store=0.9025, efficiency_dispatch=0.9025)
    assert double["totalCost"] == "$877,713" and prices(double) == (0.0, 98.2)
    assert strip(efficiency_store=1.0, efficiency_dispatch=1.0)["totalCost"] == "$867,952"
    standing = strip(standing_loss=0.01)
    assert standing["totalCost"] == "$876,704" and prices(standing) == (0.0, 93.2)
    assert strip(cyclic_state_of_charge=False, state_of_charge_initial=200.0)["totalCost"] == "$857,518"
    day1 = strip(options={"snapshotStart": 0, "snapshotCount": 24})
    assert day1["totalCost"] == "$271,976"
    assert strip("training_m17_start", {"snapshotStart": 0, "snapshotCount": 24})["totalCost"] == "$319,003"
    day2 = strip(options={"snapshotStart": 24, "snapshotCount": 24})
    assert day2["totalCost"] == "$326,985" and prices(day2) == (80.0, 88.6)
    rolling = {"enabled": True, "horizonHours": 24, "overlapHours": 0}
    rolled = strip(options={"rollingConfig": {**rolling, "terminalSoc": True}},
                   cyclic_state_of_charge=False, state_of_charge_initial=200.0)
    assert rolled["totalCost"] == "$875,602"
    # re-pinned in step 5 (B1): the terminal target is an explicit option, so the default rolling run has none
    default = strip(options={"rollingConfig": rolling}, cyclic_state_of_charge=False, state_of_charge_initial=200.0)
    assert default["totalCost"] == "$858,347"


def test_module_17_storage_energy_balance_dual_is_the_price_of_the_energy_it_holds(tmp_path: Path) -> None:
    """Step 8: mu_energy_balance = 0.95 x 80 = 76 in 54 snapshots, 0 in the 18 free ones."""
    from backend.pypsa.results import run_pypsa

    res = run_pypsa(_m17_model(tmp_path), _M17_SCENARIO, OPTIONS)
    series = res["outputs"]["series"]
    mu = [float(r["batt"]) for r in series["storage_units-mu_energy_balance"]]
    price = [float(r["grid"]) for r in series["buses-marginal_price"]]
    assert len(mu) == 72
    assert sum(abs(v - 76.0) < 1e-6 for v in mu) == 54
    assert sum(abs(v) < 1e-6 for v in mu) == 18
    # Wherever the CCGT is the marginal unit the stored MWh is worth what it displaces after the discharge loss.
    for m, p in zip(mu, price):
        if abs(p - 80.0) < 1e-6:
            assert m == pytest.approx(0.95 * 80.0, abs=1e-6)
        if abs(p) < 1e-6:
            assert m == pytest.approx(0.0, abs=1e-6)


def test_module_17_capacity_credit_rises_with_duration(tmp_path: Path) -> None:
    """Step 9: ELCC of the 100 MW battery at 200 outage-MC members, seed 42, FOR 5%, MTTR 48 h."""
    from backend.pypsa.results import run_pypsa

    pct, lole = {}, {}
    for hours in (1, 2, 4, 6, 8):
        res = run_pypsa(_m17_model(tmp_path, max_hours=hours), _M17_SCENARIO,
                        {**OPTIONS, "elccConfig": {**_M12_MC, "carriers": ["battery"]}})
        by_carrier = {c["carrier"]: c for c in res["elcc"]["byCarrier"]}
        pct[hours] = by_carrier["battery"]["elccPct"]
        lole[hours] = res["elcc"]["baselineLoleHrs"]
    assert pct[1] == pytest.approx(20.0, abs=0.5)
    assert pct[2] == pytest.approx(20.0, abs=0.5)
    assert pct[4] == pytest.approx(24.2, abs=0.8)
    assert pct[6] == pytest.approx(45.6, abs=1.5)
    assert pct[8] == pytest.approx(92.96, abs=2.5)
    assert [pct[h] for h in (1, 2, 4, 6, 8)] == sorted(pct[h] for h in (1, 2, 4, 6, 8))
    assert lole[1] == pytest.approx(326.07, rel=0.02) and lole[8] == pytest.approx(97.33, rel=0.03)
    assert lole[1] > lole[2] > lole[4] > lole[6] > lole[8]


def test_module_17_storage_unit_versus_store_and_links_sizing(tmp_path: Path) -> None:
    """Step 10: a StorageUnit ties energy to power by max_hours; Store + two Links sizes three things."""
    def storage_unit_model(capital_cost: float = 1_000_000.0, hours: float = 4.0) -> dict:
        model = {k: [dict(r) for r in v] for k, v in _model_from_example("training_m17_start", tmp_path).items()}
        model["storage_units"] = [{
            "name": "batt", "bus": "grid", "carrier": "battery", "p_nom": 0.0, "p_nom_extendable": True,
            "p_nom_min": 0.0, "p_nom_max": 400.0, "max_hours": hours, "efficiency_store": 0.95,
            "efficiency_dispatch": 0.95, "cyclic_state_of_charge": True, "overnight_cost": capital_cost, "discount_rate": 0.05,
            "lifetime": 15.0,
        }]
        return model

    unit = _m17_solve(storage_unit_model())
    assert float(unit.objective) == pytest.approx(950_780.2, rel=1e-6)
    p_opt = float(unit.storage_units.p_nom_opt["batt"])
    assert p_opt == pytest.approx(92.96, abs=0.05)
    assert p_opt * 4.0 == pytest.approx(371.8, abs=0.2)                     # energy follows power: max_hours x p_nom
    store = _m17_solve(_m17_model(tmp_path, "training_m17_store"))
    assert float(store.objective) == pytest.approx(948_727.7, rel=1e-6)
    assert float(store.stores.e_nom_opt["batt_store"]) == pytest.approx(401.41, abs=0.1)
    assert float(store.links.p_nom_opt["batt_charge"]) == pytest.approx(53.56, abs=0.05)
    assert float(store.links.p_nom_opt["batt_discharge"]) == pytest.approx(97.85, abs=0.05)
    # The same unit prices: 2 links x 100,000 + 4 h x 200,000 = 1,000,000 per MW. The freedom is worth 2,052.
    assert float(unit.objective) - float(store.objective) == pytest.approx(2_052.5, abs=0.5)
    assert float(store.links.p_nom_opt["batt_charge"]) < float(store.links.p_nom_opt["batt_discharge"])
    # max_hours moved without moving capital_cost: the energy price silently changes 4x.
    short = _m17_solve(storage_unit_model(hours=2.0))
    long = _m17_solve(storage_unit_model(hours=8.0))
    assert float(short.objective) == pytest.approx(997_308.4, rel=1e-6)       # barely better than no battery
    assert float(long.objective) == pytest.approx(882_153.7, rel=1e-6)
    assert float(long.storage_units.p_nom_opt["batt"]) == pytest.approx(218.44, abs=0.1)
    assert float(long.storage_units.p_nom_opt["batt"]) * 8.0 == pytest.approx(1_747.5, abs=1.0)


# ── Module 18 — Power-to-X ───────────────────────────────────────────────────
#
# `training_m18_start` is one March week of 2030 on one bus: 120 MW solar, 100 MW wind
# (both built 2029) and 400 MW of gas at 70 against 150-205 MW of demand, so gas sets the
# price in every hour. The module adds a P2X plant from Build -> Generators (the plant
# picker's own builder, `plants.catalog.build_plant`, the path `/api/build/plant` takes),
# solves it with RFNBO matching off, monthly and hourly (the P2X tab's settings ride as
# `options.rfnboConfig`), and reads the P2X results (`p2x.results.p2x_results`, the panel's
# `/api/p2x/results/{run}`). `training_m18` is that plant on the start grid.

_M18_SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.05}
_M18_MATCHING = {
    "none": {},
    "monthly": {"rfnboConfig": {"enabled": True, "temporal": "monthly"}},
    "hourly": {"rfnboConfig": {"enabled": True, "temporal": "hourly"}},
}


@functools.lru_cache(maxsize=None)
def _m18_example(example_id: str) -> str:
    """A bundled example read once per session (the model as JSON so the cache hands out fresh copies)."""
    return json.dumps(_model_from_example(example_id, Path(tempfile.mkdtemp(prefix="m18_"))))


def _m18_model(example_id: str = "training_m18") -> dict:
    return json.loads(_m18_example(example_id))


def _m18_product(product: str) -> dict:
    """The checkpoint with its P2X plant re-derived for ``product`` (Build -> Generators -> plant card -> Edit)."""
    from backend.app.plants import catalog, registry

    model = _m18_model()
    return registry.apply_change(model, catalog.edit_plant(model, "p2x", {"product": product}))


@functools.lru_cache(maxsize=None)
def _m18_run(matching: str = "none", product: str = "H2", example_id: str = "training_m18") -> tuple[str, str]:
    """(model, result) of one module-18 solve through ``run_pypsa``, cached: several tests read the same run."""
    from backend.pypsa.results import run_pypsa

    model = _m18_product(product) if product != "H2" else _m18_model(example_id)
    options = {**OPTIONS, **_M18_MATCHING[matching]}
    return json.dumps(model), json.dumps(run_pypsa(model, _M18_SCENARIO, options))


def _m18(matching: str = "none", product: str = "H2", example_id: str = "training_m18") -> tuple[dict, dict, dict]:
    """(model, result, P2X results) - the P2X results only when the model has a chain."""
    from backend.app.p2x import results as p2x_results

    model_s, res_s = _m18_run(matching, product, example_id)
    model, res = json.loads(model_s), json.loads(res_s)
    p2x: dict = {}
    if model.get("RAGNAROK_P2X"):
        bundle = {"model": model, "result": res, "options": {**OPTIONS, **_M18_MATCHING[matching]}, "scenario": _M18_SCENARIO}
        p2x = p2x_results.p2x_results(bundle)
    return model, res, p2x


def _total(res: dict) -> float:
    """Total cost as the KPI strip adds it: the run's cost breakdown."""
    return float(sum(r["value"] for r in res["costBreakdown"]))


def _series(res: dict, sheet: str, name: str) -> list[float]:
    return [float(r[name]) for r in res["outputs"]["series"][sheet]]


def _kpis(model: dict, res: dict) -> dict:
    from backend.app import results_derived as rd

    return rd.compute_kpis(res, model["carriers"], set(), "$", list)


def test_module_18_technology_data_is_what_the_electrolyser_is_built_from() -> None:
    """Step 2: the P2X tab's Technology parameters, and the Link the chain writes from them."""
    from backend.app.p2x import technologies as tech

    cat = tech.catalogue()
    aec = cat["technologies"]["electrolyser_aec"]["parameters"]
    values = {k: aec[k]["value"] for k in ("specific_energy", "capex", "fom", "lifetime", "stack_capex",
                                           "stack_lifetime_hours", "water_use", "availability", "min_load")}
    assert values == pytest.approx({"specific_energy": 53.565843, "capex": 691.534046, "fom": 4.0, "lifetime": 25.0,
                                    "stack_capex": 145.159019, "stack_lifetime_hours": 92_500.0,
                                    "water_use": 185.169748, "availability": 0.939863, "min_load": 15.0}, rel=1e-12)
    assert "technology-data v0.15.0" in aec["capex"]["source"]["document"]
    assert [aec[k]["verified"] for k in ("capex", "availability", "min_load")] == ["file", "derived", "literature-recalled"]
    assert (aec["forced_outage"]["value"], aec["planned_outage"]["value"]) == (3.0, 11.0)       # what availability is derived from
    tank = cat["technologies"]["h2_storage_tank"]["parameters"]
    assert (tank["capex"]["value"], tank["fom"]["value"], tank["lifetime"]["value"]) == pytest.approx((60.0469, 1.1133, 30.0))
    water = cat["technologies"]["water"]["parameters"]["supply_cost"]["value"]
    assert water == pytest.approx(0.7285, rel=1e-12)
    lhv = tech.constants()["h2_lhv_kwh_per_kg"]
    assert lhv == pytest.approx(33.33)
    # What the chain wrote into the checkpoint's electrolyser Link.
    ely = next(r for r in _m18_model()["links"] if r["name"] == "p2x_electrolyser")
    assert (ely["bus0"], ely["bus1"], ely["carrier"]) == ("grid", "p2x_bus_h2", "electrolysis")
    assert float(ely["efficiency"]) == pytest.approx(lhv / 53.565843, abs=1e-8)              # 0.6222
    assert round(float(ely["efficiency"]), 4) == 0.6222
    wear = 145.159019 * 1000.0 / 92_500.0                                                   # 1.569 per MWh_el
    water_cost = 185.169748 / 1000.0 * 0.7285                                              # 0.135 per MWh_el
    assert (round(wear, 3), round(water_cost, 3)) == (1.569, 0.135)
    assert float(ely["marginal_cost"]) == pytest.approx(wear + water_cost, abs=1e-6)        # 1.704
    assert float(ely["overnight_cost"]) == pytest.approx(691_534.046, abs=1e-6)
    assert float(ely["p_max_pu"]) == pytest.approx(0.939863, abs=1e-9)
    assert float(ely["lifetime"]) == 25.0 and float(ely["discount_rate"]) == 0.05


def test_module_18_start_grid_prices_every_hour_at_gas() -> None:
    """Step 1: gas is marginal in all 168 hours and no renewable MWh is thrown away."""
    model, res, _ = _m18(example_id="training_m18_start")
    assert _total(res) == pytest.approx(1_163_072.0, abs=1.0)
    price = _series(res, "buses-marginal_price", "grid")
    assert len(price) == 168 and all(abs(p - 70.0) < 1e-6 for p in price)
    k = _kpis(model, res)
    assert k["totalCost"] == "$1,163,072" and (k["minPrice"], k["maxPrice"]) == pytest.approx((70.0, 70.0))
    assert round(k["renewableSharePct"], 1) == 39.9
    assert k["peakLoadMw"] == pytest.approx(200.0, abs=1e-6)
    used = sum(_series(res, "generators-p", "solar")) + sum(_series(res, "generators-p", "wind"))
    avail = sum(120.0 * float(r["solar"]) + 100.0 * float(r["wind"]) for r in model["generators-p_max_pu"])
    assert used == pytest.approx(avail, abs=1e-6) and avail == pytest.approx(11_035.95, abs=0.01)   # nothing curtailed
    assert float(res["emissionsBreakdown"]["totalTco2"]) == pytest.approx(6_646.12, abs=0.01)


def test_module_18_the_plant_picker_builds_the_chain_the_checkpoint_holds() -> None:
    """Step 3: P2X chain, solver-sized, tank, 30 MW offtake, solar and wind designated: what Apply merges."""
    from backend.app import fragment_merge
    from backend.app.plants import catalog

    start = _m18_model("training_m18_start")
    built = catalog.build_plant("p2x", {"extendable": True, "offtakeMw": 30,
                                        "chain": {"designatedGenerators": ["solar", "wind"]}, "discountRate": 0.05}, start)
    assert built["plantId"] == "p2x"                                                        # blank name -> the type id
    counts = {s: len(v) for s, v in built["fragment"]["sheets"].items() if not s.startswith("RAGNAROK")}
    assert counts == {"buses": 1, "carriers": 3, "links": 1, "stores": 1, "loads": 1}       # the preview's "Creates:" line
    sheets = built["fragment"]["sheets"]
    assert [r["name"] for r in sheets["links"]] == ["p2x_electrolyser"]
    assert [r["name"] for r in sheets["stores"]] == ["p2x_h2_store"]
    assert [(r["name"], r["p_set"]) for r in sheets["loads"]] == [("p2x_load_H2", 30.0)]
    assert sheets["stores"][0]["e_cyclic"] is True and sheets["stores"][0]["e_nom_extendable"] is True
    assert any("fom_cost is written per modelled HORIZON" in w for w in built["warnings"])
    merged = fragment_merge.merge_fragment(start, built["fragment"])
    checkpoint = _m18_model()
    for sheet in ("buses", "carriers", "generators", "links", "stores", "loads"):
        assert merged[sheet] == checkpoint[sheet], sheet
    for sheet in ("RAGNAROK_P2X", "RAGNAROK_PLANTS"):                                       # registry rows: the same JSON
        assert [json.loads(r["json"]) for r in merged[sheet]] == [json.loads(r["json"]) for r in checkpoint[sheet]], sheet


def test_module_18_without_matching_the_electrolyser_runs_flat_on_gas_power() -> None:
    """Step 4: the cheapest hydrogen here runs the electrolyser at its availability every hour, no store."""
    model, res, p2x = _m18("none")
    assert _total(res) == pytest.approx(1_819_359.0, abs=1.0)
    assert _total(res) - 1_163_072.0 == pytest.approx(656_287.0, abs=1.0)
    e = p2x["electrolyser"]
    assert e["capacityMw"] == pytest.approx(51.30, abs=0.005)
    assert e["capacityFactor"] == pytest.approx(0.939863, abs=1e-6)                         # = availability: flat out
    assert e["fullLoadHoursPerYear"] == pytest.approx(8_233.2, abs=0.1)
    assert e["electricityMwh"] == pytest.approx(8_099.97, abs=0.01)
    assert e["h2Tonnes"] == pytest.approx(151.215, abs=0.001)                               # 30 MW x 168 h / 33.33
    assert 30.0 * 168.0 / 33.33 == pytest.approx(e["h2Tonnes"], rel=1e-9)
    assert 30.0 / 33.33 == pytest.approx(0.90, abs=0.001)                                    # t of hydrogen an hour
    assert e["electricityMwh"] / 168.0 == pytest.approx(48.2, abs=0.05)                      # MW drawn in every hour
    assert max(_series(res, "stores-e", "p2x_h2_store")) == pytest.approx(0.0, abs=1e-6)
    assert p2x["lcoh"]["perKg"] == pytest.approx(4.340, abs=0.0005)
    pc = p2x["lcoh"]["perComponent"]
    assert pc["Electricity (electrolyser)"] == pytest.approx(70.0 * 53.565843 / 1000.0, rel=1e-6)   # 3.75 (efficiency stored to 8 digits)
    assert {k: round(v, 2) for k, v in pc.items()} == {
        "Electricity (electrolyser)": 3.75, "Electrolyser capex": 0.32, "Electrolyser FOM": 0.18,
        "Stack replacement": 0.08, "Water": 0.01, "Compression": 0.0, "H2 storage": 0.0}
    assert pc["Electricity (electrolyser)"] / p2x["lcoh"]["perKg"] == pytest.approx(0.86, abs=0.005)
    comp = p2x["rfnbo"]["compliance"]
    assert (comp["hourly"]["compliantOperatingPeriods"], comp["hourly"]["operatingPeriods"]) == (109, 168)
    assert comp["hourly"]["compliantShareOfOperating"] == pytest.approx(0.649, abs=0.0005)
    assert comp["hourly"]["unmatchedMwh"] == pytest.approx(1_327.9, abs=0.05)
    assert comp["monthly"]["compliantShareOfOperating"] == pytest.approx(1.0)
    # Every MWh it draws is a gas MWh at the margin: 0.20 tCO2/MWh_th / 0.5 = 0.4 t per MWh_el.
    emitted = float(res["emissionsBreakdown"]["totalTco2"])
    assert emitted == pytest.approx(9_886.11, abs=0.01)
    assert emitted - 6_646.12 == pytest.approx(0.4 * e["electricityMwh"], abs=0.02)       # 3,240 t
    assert (emitted - 6_646.12) / (e["h2Tonnes"] * 1000.0) * 1000.0 == pytest.approx(21.4, abs=0.05)   # kg CO2 / kg H2


def test_module_18_monthly_matching_on_a_one_week_window_changes_nothing() -> None:
    """Step 5: one calendar month = the whole window; the designated plant made 11,036 MWh, the electrolyser took 8,100."""
    _, base, p_base = _m18("none")
    _, res, p2x = _m18("monthly")
    assert _total(res) == pytest.approx(_total(base), rel=1e-9)
    assert p2x["electrolyser"]["capacityMw"] == pytest.approx(p_base["electrolyser"]["capacityMw"], rel=1e-6)
    assert p2x["lcoh"]["perKg"] == pytest.approx(p_base["lcoh"]["perKg"], rel=1e-9)
    assert p2x["ppa"]["designatedEnergyMwh"] == pytest.approx(11_035.95, abs=0.01)
    assert p2x["electrolyser"]["electricityMwh"] < p2x["ppa"]["designatedEnergyMwh"]
    assert p2x["rfnbo"]["matchingEnabled"] is True


def test_module_18_hourly_matching_buys_electrolyser_and_storage() -> None:
    """Step 6: the same hydrogen, made only when the sun or the wind is there."""
    _, res, p2x = _m18("hourly")
    assert _total(res) == pytest.approx(1_898_786.0, abs=1.0)
    assert _total(res) - 1_819_359.0 == pytest.approx(79_427.0, abs=1.0)
    e = p2x["electrolyser"]
    assert e["capacityMw"] == pytest.approx(66.43, abs=0.005)
    assert e["capacityFactor"] == pytest.approx(0.7258, abs=0.00005)
    assert e["fullLoadHoursPerYear"] == pytest.approx(6_357.6, abs=0.1)
    assert e["electricityMwh"] == pytest.approx(8_099.97, abs=0.01)                         # same energy, more MW
    assert max(_series(res, "stores-e", "p2x_h2_store")) == pytest.approx(651.5, abs=0.05)
    assert 651.49 / 30.0 == pytest.approx(21.7, abs=0.05)                                   # hours of offtake held
    assert 651.49 / 33.33 == pytest.approx(19.5, abs=0.05)                                  # tonnes of hydrogen held
    soc = _series(res, "stores-e", "p2x_h2_store")
    assert soc.index(max(soc)) // 24 == 1                                                   # peaks on day 2
    assert min(soc[72:96]) == pytest.approx(0.0, abs=1e-6)                                  # empty on day 4
    lcoh = p2x["lcoh"]["perKg"]
    assert lcoh == pytest.approx(4.865, abs=0.0005)
    assert lcoh - 4.340 == pytest.approx(0.525, abs=0.001) and lcoh / 4.340089 - 1 == pytest.approx(0.121, abs=0.0005)
    assert {k: round(v, 2) for k, v in p2x["lcoh"]["perComponent"].items()} == {
        "Electricity (electrolyser)": 3.75, "Electrolyser capex": 0.41, "Electrolyser FOM": 0.23,
        "Stack replacement": 0.08, "Water": 0.01, "Compression": 0.0, "H2 storage": 0.38}
    comp = p2x["rfnbo"]["compliance"]
    assert comp["hourly"]["compliantShareOfOperating"] == pytest.approx(1.0) and comp["hourly"]["unmatchedMwh"] == pytest.approx(0.0, abs=1e-6)
    ely = _series(res, "links-p0", "p2x_electrolyser")
    designated = [s + w for s, w in zip(_series(res, "generators-p", "solar"), _series(res, "generators-p", "wind"))]
    assert all(p <= d + 1e-6 for p, d in zip(ely, designated))                             # the constraint, hour by hour


def test_module_18_matching_moves_cost_not_emissions() -> None:
    """Steps 6-7: 9,886.1 t in all three runs; additionality passes on dates; Art. 4(1) fails at 30.9%."""
    emissions = {m: float(_m18(m)[1]["emissionsBreakdown"]["totalTco2"]) for m in ("none", "monthly", "hourly")}
    assert emissions == pytest.approx({"none": 9_886.11, "monthly": 9_886.11, "hourly": 9_886.11}, abs=0.01)
    _, res, p2x = _m18("hourly")
    assert all(abs(p - 70.0) < 1e-6 for p in _series(res, "buses-marginal_price", "grid"))
    checks = p2x["rfnbo"]["checks"]
    assert [(r["generator"], r["status"]) for r in checks["additionality"]] == [("solar", "pass"), ("wind", "pass")]
    assert [(r["generator"], r["status"]) for r in checks["geographic"]] == [("solar", "pass"), ("wind", "pass")]
    art41 = p2x["rfnbo"]["gridAlternatives"]["art41"]
    assert art41["renewableShare"] == pytest.approx(0.309, abs=0.0005) and art41["pass"] is False
    # Curtailment is zero with or without the chain: no renewable MWh was spare for the electrolyser to take.
    model, _, _ = _m18("hourly")
    avail = sum(120.0 * float(r["solar"]) + 100.0 * float(r["wind"]) for r in model["generators-p_max_pu"])
    used = sum(_series(res, "generators-p", "solar")) + sum(_series(res, "generators-p", "wind"))
    assert used == pytest.approx(avail, abs=1e-6)


def test_module_18_ammonia_is_two_processes_and_moves_the_storage_to_the_product() -> None:
    """Step 8: Product NH3 adds an ASU and Haber-Bosch as Processes; hourly matching then stores ammonia, not hydrogen."""
    model = _m18_product("NH3")
    procs = {r["name"]: r for r in model["processes"]}
    hb = procs["p2x_synth_NH3"]
    assert (hb["bus0"], hb["bus1"], hb["bus2"], hb["bus3"]) == ("p2x_bus_h2", "p2x_bus_NH3", "grid", "p2x_bus_n2")
    assert float(hb["rate0"]) == -1.0
    assert float(hb["rate1"]) == pytest.approx(1 / 1.1484, abs=1e-8)                        # 0.8708 MWh NH3 per MWh H2
    assert float(hb["rate2"]) == pytest.approx(-0.2473 / 1.1484, abs=1e-8)                  # -0.2153 MWh_el
    assert float(hb["rate3"]) == pytest.approx(-0.1597 / 1.1484, abs=1e-8)                  # -0.1391 t N2
    asu = procs["p2x_asu"]
    assert (asu["bus0"], asu["bus1"], float(asu["rate0"]), float(asu["rate1"])) == ("grid", "p2x_bus_n2", -1.0, pytest.approx(4.0))
    assert [r["name"] for r in model["loads"] if r.get("plant") == "p2x"] == ["p2x_load_NH3"]
    _, hourly, p_h = _m18("hourly", "NH3")
    _, none, p_n = _m18("none", "NH3")
    assert _total(hourly) == pytest.approx(2_206_577.0, abs=1.0)
    assert _total(none) == pytest.approx(2_128_063.0, abs=1.0)
    lcoa_h, lcoa_n = p_h["products"]["NH3"]["costPerTonne"], p_n["products"]["NH3"]["costPerTonne"]
    assert (lcoa_h, lcoa_n) == pytest.approx((1_070.4, 989.9), abs=0.05)
    assert lcoa_h / lcoa_n - 1 == pytest.approx(0.081, abs=0.0005)
    assert p_h["products"]["NH3"]["producedTonnes"] == pytest.approx(974.85, abs=0.005)      # 30 MW x 168 h / 5.17
    assert p_h["electrolyser"]["capacityMw"] == pytest.approx(89.35, abs=0.005)
    assert p_h["electrolyser"]["capacityFactor"] == pytest.approx(0.6197, abs=0.00005)
    assert p_n["electrolyser"]["capacityMw"] == pytest.approx(58.91, abs=0.005)
    assert p_n["electrolyser"]["capacityFactor"] == pytest.approx(0.939863, abs=1e-6)
    assert max(max(_series(none, "stores-e", n)) for n in ("p2x_h2_store", "p2x_store_NH3")) == pytest.approx(0.0, abs=1e-6)
    stores = {n: max(_series(hourly, "stores-e", n)) for n in ("p2x_h2_store", "p2x_store_NH3")}
    assert stores == pytest.approx({"p2x_h2_store": 107.8, "p2x_store_NH3": 622.5}, abs=0.05)
    nh3_tank = float(next(r for r in model["stores"] if r["name"] == "p2x_store_NH3")["overnight_cost"])
    h2_tank = float(next(r for r in model["stores"] if r["name"] == "p2x_h2_store")["overnight_cost"])
    assert (nh3_tank, h2_tank) == pytest.approx((211.8256, 60_046.9), abs=1e-6)                # per MWh stored
    assert h2_tank / nh3_tank == pytest.approx(283.5, abs=0.05)
    # Switching the product back re-derives exactly the checkpoint's H2 chain.
    from backend.app.plants import catalog, registry

    back = registry.apply_change(model, catalog.edit_plant(model, "p2x", {"product": "H2"}))
    checkpoint = _m18_model()
    for sheet in checkpoint:
        if sheet.startswith("RAGNAROK_P"):
            assert [json.loads(r["json"]) for r in back[sheet]] == [json.loads(r["json"]) for r in checkpoint[sheet]], sheet
        else:
            assert back.get(sheet) == checkpoint[sheet], sheet


def test_module_18_kpi_strip_strings_the_lessons_quote() -> None:
    expected = {("none", "H2"): "$1,819,359", ("monthly", "H2"): "$1,819,359", ("hourly", "H2"): "$1,898,786",
                ("hourly", "NH3"): "$2,206,577", ("none", "NH3"): "$2,128,063"}
    for (matching, product), total in expected.items():
        model, res, _ = _m18(matching, product)
        assert _kpis(model, res)["totalCost"] == total, (matching, product)


# ── Module 19 — gas + H2 co-firing and CCGT operations ───────────────────────
#
# `training_m19_start` is three June days on one bus: 250 MW of solar against a 297 MW
# evening peak, a 400 MW oil peaker at 160 and an `h2` bus with a 50 MW pipeline at 100
# per MWh (the plant data file's own H2 price assumption). The module adds the plant
# picker's CCGT, then its gas + H2 co-firing (fuel network) plant, and edits that plant
# one field at a time (``catalog.edit_plant`` -> change set, what the card's Edit does).
# Plant-level numbers come from ``plants.results.plant_results`` (/api/build/plant/results).

_M19_SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.05}
_M19_COFIRE = {"plantId": "cofire", "pNom": 200, "h2Bus": "h2", "blendMax": 0.3, "blendUnit": "vol",
               "blendScope": "hourly", "discountRate": 0.05}
#: The edits the module makes, in order; each run starts from the one before.
_M19_STEPS: dict[str, tuple[str, dict]] = {
    "cap": ("", {}),
    "mandate": ("cap", {"blendMin": 0.3}),
    "energy": ("mandate", {"blendUnit": "energy"}),
    "period": ("mandate", {"blendScope": "period"}),
    "commit": ("mandate", {"committable": True}),
    "partload": ("commit", {"minLoadEfficiency": 0.52}),
    "warm": ("partload", {"startCostWarm": 120, "startWarmAfterHours": 5}),
}


def _m19_start() -> dict:
    return json.loads(_m18_example("training_m19_start"))


@functools.lru_cache(maxsize=None)
def _m19_model_json(step: str, pipeline_mw: float = 50.0, min_down_h: float | None = None) -> str:
    from backend.app import fragment_merge
    from backend.app.plants import catalog, registry

    if step == "ccgt":
        start = _m19_start()
        model = fragment_merge.merge_fragment(start, catalog.build_plant("ccgt", {"plantId": "ccgt", "pNom": 200, "discountRate": 0.05}, start)["fragment"])
    elif step == "cap":
        start = _m19_start()
        model = fragment_merge.merge_fragment(start, catalog.build_plant("cofiring_network", _M19_COFIRE, start)["fragment"])
    elif step == "start":
        model = _m19_start()
    else:
        parent, patch = _M19_STEPS[step]
        model = json.loads(_m19_model_json(parent))
        model = registry.apply_change(model, catalog.edit_plant(model, "cofire", patch))
    for g in model["generators"]:
        if g["name"] == "h2_pipeline":
            g["p_nom"] = pipeline_mw
    if min_down_h is not None:
        for row in model["RAGNAROK_TimeUnits"]:
            if row["attribute"] == "min_down_time":
                row["value"] = min_down_h
    return json.dumps(model)


@functools.lru_cache(maxsize=None)
def _m19_run(step: str, pipeline_mw: float = 50.0, min_down_h: float | None = None) -> str:
    from backend.pypsa.results import run_pypsa

    return json.dumps(run_pypsa(json.loads(_m19_model_json(step, pipeline_mw, min_down_h)), _M19_SCENARIO, OPTIONS))


def _m19(step: str, pipeline_mw: float = 50.0, min_down_h: float | None = None) -> tuple[dict, dict, dict]:
    """(model, result, plant results of the run's one plant - empty when it has none)."""
    from backend.app.plants import results as plant_results

    model = json.loads(_m19_model_json(step, pipeline_mw, min_down_h))
    res = json.loads(_m19_run(step, pipeline_mw, min_down_h))
    plant: dict = {}
    if model.get("RAGNAROK_PLANTS"):
        bundle = {"model": model, "result": res, "options": OPTIONS, "scenario": _M19_SCENARIO}
        plant = plant_results.plant_results(bundle)["plants"][0]
    return model, res, plant


def _m19_off_hours_by_day(res: dict) -> list[int]:
    status = _series(res, "links-status", "cofire")
    return [sum(1 for s in status[24 * d: 24 * d + 24] if s < 0.5) for d in range(3)]


def test_module_19_vol_to_energy_share_comes_from_the_lhvs_in_the_data_file() -> None:
    """Steps 2 and 5: 30 vol% H2 is 11.43% of the energy; 30% of the energy is 58.7 vol%."""
    from backend.app.plants import cofiring as cf
    from backend.app.plants import technologies as tech

    cat = tech.catalogue()["constants"]
    lh, lg = cat["h2_lhv_mj_per_nm3"]["value"], cat["ch4_lhv_mj_per_nm3"]["value"]
    assert (lh, lg) == (10.78, 35.8)
    assert (cat["h2_lhv_mj_per_nm3"]["verified"], cat["ch4_lhv_mj_per_nm3"]["verified"]) == ("derived", "literature")
    assert 0.3 * lh == pytest.approx(3.234) and 0.7 * lg == pytest.approx(25.06)
    s = cf.vol_to_energy_share(0.3, lh, lg)
    assert s == pytest.approx(3.234 / (3.234 + 25.06), rel=1e-12)
    assert round(s * 100, 2) == 11.43
    assert round(cf.energy_to_vol_share(0.3, lh, lg) * 100, 1) == 58.7
    assert lh / lg == pytest.approx(0.301, abs=0.0005)                                       # a Nm3 of H2 carries 30% of a Nm3 of CH4


def test_module_19_start_system_is_solar_and_a_peaker() -> None:
    """Step 1: 6 free hours, 66 hours at the peaker's 160."""
    model, res, _ = _m19("start")
    assert _total(res) == pytest.approx(1_747_786.0, abs=1.0)
    price = _series(res, "buses-marginal_price", "grid")
    assert sum(abs(p) < 1e-6 for p in price) == 6 and sum(abs(p - 160.0) < 1e-6 for p in price) == 66
    k = _kpis(model, res)
    assert k["totalCost"] == "$1,747,786" and round(k["avgPrice"], 1) == 148.4
    assert k["peakLoadMw"] == pytest.approx(297.0, abs=0.05)
    assert round(k["renewableSharePct"], 1) == 27.5
    assert float(res["emissionsBreakdown"]["totalTco2"]) == pytest.approx(8_426.82, abs=0.01)
    assert sum(_series(res, "generators-p", "h2_pipeline")) == pytest.approx(0.0, abs=1e-6)


def test_module_19_gas_only_ccgt_from_the_plant_picker() -> None:
    """Step 2: the CCGT plant is a gas bus, a gas supplier and a gas -> grid Link with the data file's numbers."""
    from backend.app.plants import technologies as tech

    P = tech.parameter_defaults()
    assert (P["ccgt"]["efficiency"], P["ccgt"]["capex"], P["ccgt"]["vom"], P["ccgt"]["min_load"]) == (0.58, 1108.7166, 5.6104, 0.4)
    assert (P["fuels"]["gas_price"], P["fuels"]["gas_co2"], P["fuels"]["h2_price"]) == (28.4158, 0.198, 100.0)
    assert (P["ccgt"]["fom"], P["ccgt"]["lifetime"], P["ccgt"]["ramp_rate"]) == (3.3494, 25.0, 15.0)
    assert (P["ccgt"]["start_up_cost"], P["ccgt"]["min_up_time"], P["ccgt"]["min_down_time"]) == (60.0, 4.0, 4.0)
    assert (P["ccgt"]["warm_start_time"], P["ccgt"]["cold_start_time"]) == (1.0, 2.5)          # start DURATIONS, not offline thresholds
    ccgt = tech.catalogue()["technologies"]["ccgt"]["parameters"]
    assert [ccgt[k]["verified"] for k in ("efficiency", "min_load", "start_up_cost", "min_up_time")] == ["file", "file", "assumption", "assumption"]
    assert tech.catalogue()["fuels"]["h2_price"]["verified"] == "assumption"
    model, res, plant = _m19("ccgt")
    link = next(r for r in model["links"] if r["name"] == "ccgt")
    assert (link["bus0"], link["bus1"], float(link["efficiency"])) == ("ccgt_bus_gas", "grid", 0.58)
    assert float(link["p_nom"]) == pytest.approx(200 / 0.58, abs=1e-6)                       # 344.8 MW of fuel in
    assert float(link["marginal_cost"]) == pytest.approx(5.6104 * 0.58, abs=1e-6)            # VOM per MWh of fuel
    supply = next(r for r in model["generators"] if r["name"] == "ccgt_gas_supply")
    assert float(supply["marginal_cost"]) == pytest.approx(28.4158)
    assert _total(res) == pytest.approx(720_242.0, abs=1.0)
    price = _series(res, "buses-marginal_price", "grid")
    ccgt_price = 28.4158 / 0.58 + 5.6104
    assert round(ccgt_price, 2) == 54.60
    counts = (sum(abs(p) < 1e-6 for p in price), sum(abs(p - ccgt_price) < 1e-3 for p in price), sum(abs(p - 160.0) < 1e-6 for p in price))
    assert counts == (6, 47, 19)
    assert plant["generationMwh"] == pytest.approx(9_749.3, abs=0.05)
    assert plant["capacityFactor"] == pytest.approx(0.677, abs=0.0005)
    assert (plant["starts"], plant["startsBasis"]) == (3, "counted from dispatch (not committable)")
    assert float(res["emissionsBreakdown"]["totalTco2"]) == pytest.approx(4_234.15, abs=0.01)


def test_module_19_a_blend_cap_alone_burns_no_hydrogen() -> None:
    """Step 3: Maximum H2 share 30 vol% and nothing else: the solver burns gas, H2 at 100 is dearer than gas at 28.4."""
    model, res, plant = _m19("cap")
    from backend.app.plants import catalog

    built = catalog.build_plant("cofiring_network", _M19_COFIRE, _m19_start())
    counts = [(s, len(v)) for s, v in built["fragment"]["sheets"].items() if not s.startswith("RAGNAROK")]
    assert counts == [("carriers", 5), ("buses", 2), ("generators", 1), ("links", 3)]      # the preview's "Creates:" line
    assert sorted(r["name"] for r in model["links"]) == ["cofire", "cofire_gas_feed", "cofire_h2_feed"]
    assert _total(res) == pytest.approx(720_242.0, abs=1.0)                                  # the gas-only CCGT's answer
    assert plant["fuel"]["h2MwhTh"] == pytest.approx(0.0, abs=1e-6)
    assert float(res["emissionsBreakdown"]["totalTco2"]) == pytest.approx(4_234.15, abs=0.01)
    assert (100.0 - 28.4158) / 0.198 == pytest.approx(361.5, abs=0.05)                         # the CO2 price that would close the gap


def test_module_19_a_30_vol_mandate_is_11_4_percent_of_the_energy_every_hour() -> None:
    """Step 4: minimum = maximum = 30 vol%, hourly. CO2 avoided = 0.198 x the hydrogen burned; 361.5 per tonne."""
    model, res, plant = _m19("mandate")
    assert _total(res) == pytest.approx(857_775.0, abs=1.0)
    fuel = plant["fuel"]
    assert fuel["h2EnergyShare"] == pytest.approx(0.1143, abs=0.00005) and fuel["h2VolShare"] == pytest.approx(0.30, abs=1e-9)
    cof = plant["cofiring"]
    assert (cof["minHourlyVolShare"], cof["maxHourlyVolShare"]) == pytest.approx((0.30, 0.30), abs=1e-6)
    assert cof["hoursOn"] == 66
    assert fuel["h2MwhTh"] == pytest.approx(1_921.3, abs=0.05) and fuel["totalMwhTh"] == pytest.approx(16_809.1, abs=0.05)
    assert fuel["h2KgEquivalent"] == pytest.approx(57_644.0, abs=0.5)
    em = plant["emissions"]
    assert em["avoidedT"] == pytest.approx(380.41, abs=0.005)
    assert em["avoidedT"] == pytest.approx(0.198 * fuel["h2MwhTh"], rel=1e-9)
    assert em["gasOnlyBaselineT"] == pytest.approx(3_328.2, abs=0.05)
    system = float(res["emissionsBreakdown"]["totalTco2"])
    assert system == pytest.approx(3_853.74, abs=0.01)
    assert 4_234.15 - system == pytest.approx(em["avoidedT"], abs=0.02)                      # same dispatch: plant = system
    assert plant["generationMwh"] == pytest.approx(9_749.3, abs=0.05)
    premium = _total(res) - 720_242.0
    assert premium == pytest.approx(137_533.0, abs=1.0)
    assert premium / em["avoidedT"] == pytest.approx((100.0 - 28.4158) / 0.198, abs=0.05)    # 361.5 per tonne
    price = _series(res, "buses-marginal_price", "grid")
    blend = (0.8857 * 28.4158 + 0.1143 * 100.0) / 0.58 + 5.6104
    assert round(blend, 1) == 68.7
    assert sum(abs(p - 68.71) < 0.005 for p in price) == 47


def test_module_19_the_same_number_on_the_energy_basis_is_twice_the_hydrogen() -> None:
    """Step 5: 0.3 typed with Share basis 'energy' is 58.7 vol%; the 50 MW pipeline then caps the turbine."""
    _, res, plant = _m19("energy")
    assert _total(res) == pytest.approx(1_367_673.0, abs=1.0)
    assert plant["fuel"]["h2VolShare"] == pytest.approx(0.5873, abs=0.00005)
    assert plant["fuel"]["h2MwhTh"] == pytest.approx(2_875.7, abs=0.05)
    assert max(_series(res, "generators-p", "h2_pipeline")) == pytest.approx(50.0, abs=1e-6)
    assert plant["generationMwh"] == pytest.approx(5_559.6, abs=0.05)
    assert plant["capacityFactor"] == pytest.approx(0.386, abs=0.0005)
    assert 50.0 / 0.3 * 0.58 == pytest.approx(96.7, abs=0.05)                                 # MW_el the pipeline allows


def test_module_19_hourly_or_period_with_a_short_pipeline() -> None:
    """Step 6: a 25 MW pipeline. Hourly derates the turbine and raises system CO2; period burns pure H2 at noon."""
    _, res_h, plant_h = _m19("mandate", pipeline_mw=25.0)
    assert _total(res_h) == pytest.approx(1_108_100.0, abs=1.0)
    assert max(-p for p in _series(res_h, "links-p1", "cofire")) == pytest.approx(126.86, abs=0.005)
    assert 25.0 / 0.11429985 * 0.58 == pytest.approx(126.86, abs=0.005)
    assert 200 / 0.58 * 0.11429985 == pytest.approx(39.4, abs=0.05)                            # H2 needed at full load
    assert plant_h["generationMwh"] == pytest.approx(7_007.2, abs=0.05)
    assert plant_h["emissions"]["avoidedT"] == pytest.approx(273.42, abs=0.005)
    system_h = float(res_h["emissionsBreakdown"]["totalTco2"])
    assert system_h == pytest.approx(5_139.97, abs=0.01)
    assert system_h - 4_234.15 == pytest.approx(905.8, abs=0.05)                              # above the gas-only CCGT
    _, res_p, plant_p = _m19("period", pipeline_mw=25.0)
    assert _total(res_p) == pytest.approx(932_632.0, abs=1.0)
    assert float(res_p["emissionsBreakdown"]["totalTco2"]) == pytest.approx(4_232.45, abs=0.01)
    assert plant_p["fuel"]["h2EnergyShare"] == pytest.approx(0.1143, abs=0.00005)             # over the period, exactly
    assert plant_p["fuel"]["h2MwhTh"] == pytest.approx(1_800.0, abs=1e-3)                    # 25 MW every hour
    assert all(abs(h - 25.0) < 1e-6 for h in _series(res_p, "links-p0", "cofire_h2_feed"))
    assert plant_p["cofiring"]["maxHourlyVolShare"] == pytest.approx(1.0, abs=1e-9)           # pure hydrogen in some hours
    gas = _series(res_p, "links-p0", "cofire_gas_feed")
    assert sum(1 for g in gas if g < 1e-6) >= 6
    assert _total(res_h) - _total(res_p) == pytest.approx(175_468.0, abs=1.0)
    # With the 50 MW pipeline the two scopes cost the same: hydrogen is equally dear in every hour.
    assert _total(_m19("period")[1]) == pytest.approx(857_775.0, abs=1.0)


def test_module_19_commitment_min_load_and_times_stated_in_hours() -> None:
    """Step 7: Unit commitment on. Minimum load 0.4, a 12,000 start, 4 h up and down, stored in hours."""
    model, res, plant = _m19("commit")
    link = next(r for r in model["links"] if r["name"] == "cofire")
    assert (link["committable"], float(link["p_min_pu"]), float(link["start_up_cost"])) == (True, 0.4, 12_000.0)
    rows = {r["attribute"]: (float(r["value"]), r["unit"]) for r in model["RAGNAROK_TimeUnits"] if r["name"] == "cofire"}
    assert rows == {"min_up_time": (4.0, "hours"), "min_down_time": (4.0, "hours"), "up_time_before": (4.0, "hours"),
                    "ramp_limit_up": (0.15, "per_minute"), "ramp_limit_down": (0.15, "per_minute")}
    assert _total(res) == pytest.approx(904_948.0, abs=2.0)
    assert _total(res) - 857_775.0 == pytest.approx(47_173.0, abs=2.0)
    assert (plant["starts"], plant["startsBasis"]) == (2, "solved (committable)")
    assert _m19_off_hours_by_day(res) == [5, 0, 5]                                             # stops at noon on the sunny days
    card = res["commitment"]["generators"][0]                                                  # the Commitment card's row
    assert (card["name"], card["component"], card["starts"], card["startUpCostTotal"]) == ("cofire", "links", 2, 24_000.0)
    assert (card["onlineHours"], card["minUpTime"], card["minDownTime"]) == (62.0, 4, 4)
    out = [-p for p in _series(res, "links-p1", "cofire")]
    assert min(p for p in out if p > 1e-6) == pytest.approx(80.0, abs=1e-4)                    # 0.4 x 200 MW
    assert min(out[24:48]) == pytest.approx(80.0, abs=1e-4)                                     # the cloudy day: held at minimum
    k = _kpis(model, res)
    assert k["totalCost"] == "$904,948" and (k["minPrice"], k["maxPrice"]) == (0.0, 0.0)       # a MILP has no duals
    assert float(res["emissionsBreakdown"]["totalTco2"]) == pytest.approx(3_957.62, abs=0.01)
    # Minimum down time 6 h in the Time units drawer: each noon stop lasts 6 hours.
    from backend.pypsa.network import time_units as tu

    converted = {r["attribute"]: (r["pypsaValue"], r["blank"]) for r in tu.preview(model, _M19_SCENARIO, OPTIONS)}
    assert converted == {"min_up_time": (4.0, False), "min_down_time": (4.0, False), "up_time_before": (4.0, False),
                         "ramp_limit_up": (None, True), "ramp_limit_down": (None, True)}   # 0.15 x 60 > 1: no limit at 1 h
    _, longer, plant6 = _m19("commit", min_down_h=6.0)
    assert _total(longer) == pytest.approx(908_725.0, abs=2.0)
    assert _m19_off_hours_by_day(longer) == [6, 0, 6] and plant6["starts"] == 2
    assert longer["commitment"]["generators"][0]["minDownTime"] == 6


def test_module_19_part_load_efficiency_is_a_piecewise_curve_on_the_link() -> None:
    """Step 8: 0.52 at minimum load (plant data, not in the file): no-load fuel 26.5 MW_th, 1.5915 MW_th per MW_el."""
    from backend.app.plants import partload as pl

    curve = pl.heat_rate_curve(200.0, 0.4, 0.58, 0.52)
    assert curve["fuelFullMw"] == pytest.approx(344.8276, abs=1e-4) and curve["fuelMinMw"] == pytest.approx(153.8462, abs=1e-4)
    assert curve["noLoadFuelMw"] == pytest.approx(26.5252, abs=1e-4)
    assert curve["incrementalHeatRate"] == pytest.approx(1.5915, abs=1e-4)
    assert curve["incrementalEfficiency"] == pytest.approx(0.6283, abs=1e-4)
    assert curve["minLoadPu"] == pytest.approx(0.446154, abs=1e-6)
    model, res, plant = _m19("partload")
    rows = [(r["breakpoint"], float(r["p_pu"]), float(r["efficiency"])) for r in model["links-efficiency-pw"]]
    assert rows == [(0, 0.0, 0.0), (1, pytest.approx(0.446154, abs=1e-6), 0.52), (2, 1.0, 0.58)]
    link = next(r for r in model["links"] if r["name"] == "cofire")
    assert float(link["p_min_pu"]) == pytest.approx(0.446154, abs=1e-6)
    assert _total(res) == pytest.approx(917_524.0, abs=2.0)
    assert _total(res) - 904_948.0 == pytest.approx(12_576.0, abs=3.0)
    assert plant["starts"] == 2 and _m19_off_hours_by_day(res) == [5, 0, 5]
    assert float(res["emissionsBreakdown"]["totalTco2"]) == pytest.approx(4_012.96, abs=0.01)


def test_module_19_a_warm_start_tier_shortens_the_stop_instead_of_being_paid() -> None:
    """Step 9: warm 120 per MW after 5 h offline; the unit stops for 4 h instead, both starts stay hot."""
    model, res, plant = _m19("warm")
    rows = {r["attribute"]: float(r["value"]) for r in model["RAGNAROK_StartCosts"] if r["name"] == "cofire"}
    assert rows == {"hot_cost": 12_000.0, "warm_cost": 24_000.0, "warm_after": 5.0}
    assert _total(res) == pytest.approx(926_779.0, abs=2.0)
    assert _total(res) - 917_524.0 == pytest.approx(9_256.0, abs=3.0)
    assert _m19_off_hours_by_day(res) == [4, 0, 4]
    assert res["commitment"]["generators"][0]["onlineHours"] == 64.0
    _, before, _ = _m19("partload")
    on_now = _series(res, "links-status", "cofire")
    on_before = _series(before, "links-status", "cofire")
    extra = [t for t in range(72) if on_now[t] > 0.5 and on_before[t] < 0.5]
    assert len(extra) == 2 and all(-_series(res, "links-p1", "cofire")[t] == pytest.approx(80.0, abs=1e-4) for t in extra)
    sc = plant["startCosts"]
    assert sc["starts"] == {"hot": 2, "warm": 0}
    assert (sc["startCost"], sc["tierIncrement"]) == (24_000.0, 0.0)
    assert sc["thresholdsSnapshots"] == {"warm": 5}
    assert float(res["emissionsBreakdown"]["totalTco2"]) == pytest.approx(4_052.42, abs=0.01)


def test_module_19_checkpoint_is_what_the_steps_build(tmp_path: Path) -> None:
    """The finished example is the start model after the module's plant edits, row for row."""
    built = json.loads(_m19_model_json("warm"))
    checkpoint = _model_from_example("training_m19", tmp_path)
    assert set(built) == set(checkpoint)
    for sheet in checkpoint:
        if sheet == "RAGNAROK_PLANTS":
            continue
        assert built[sheet] == checkpoint[sheet], sheet
    reg_b = json.loads(built["RAGNAROK_PLANTS"][0]["json"])
    reg_c = json.loads(checkpoint["RAGNAROK_PLANTS"][0]["json"])
    assert reg_b["spec"] == reg_c["spec"] and reg_b["components"] == reg_c["components"]


def test_module_19_kpi_strip_strings_the_lessons_quote() -> None:
    expected = {("start", 50.0): "$1,747,786", ("ccgt", 50.0): "$720,242", ("cap", 50.0): "$720,242",
                ("mandate", 50.0): "$857,775", ("energy", 50.0): "$1,367,673", ("mandate", 25.0): "$1,108,100",
                ("period", 25.0): "$932,632", ("partload", 50.0): "$917,524", ("warm", 50.0): "$926,779"}
    for (step, pipe), total in expected.items():
        model, res, _ = _m19(step, pipeline_mw=pipe)
        assert _kpis(model, res)["totalCost"] == total, (step, pipe)


# ── The checkpoints the course references must exist and be loadable ─────────

def test_every_course_checkpoint_is_a_listable_example() -> None:
    """A checkpoint id the tutorial names but ``/api/examples`` cannot serve gives
    the learner a dead button, which is worse than no button."""
    for example_id in ("training_m1", "training_m2", "training_m3", "training_m4",
                       "training_m5", "training_m6", "training_m7_year", "training_m7",
                       "training_m10", "training_m11",
                       "training_m16_start", "training_m16", "training_m17_start", "training_m17",
                       "training_m17_store", "training_m18_start", "training_m18", "training_m19_start",
                       "training_m19"):
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
