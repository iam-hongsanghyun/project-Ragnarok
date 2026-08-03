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


def _solved(example_id: str, tmp_path: Path):
    model = _model_from_example(example_id, tmp_path)
    n, _notes = build_network(model, SCENARIO, OPTIONS)
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


def _solve_model(model: dict):
    n, _notes = build_network(model, SCENARIO, OPTIONS)
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


# ── The checkpoints the course references must exist and be loadable ─────────

def test_every_course_checkpoint_is_a_listable_example() -> None:
    """A checkpoint id the tutorial names but ``/api/examples`` cannot serve gives
    the learner a dead button, which is worse than no button."""
    for example_id in ("training_m1", "training_m2", "training_m3", "training_m4", "training_m5"):
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
