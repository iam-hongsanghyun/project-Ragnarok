"""Time-units module (core cleanup step 5): ramps and UC times in time units, written for PyPSA per snapshot.

Pins the conversions as equations at the weights the solve uses, the start-up convention, the native PyPSA
constraints (no Ragnarok ramp rows), window coupling under rolling horizon, and the schema 3 -> 4 migration.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network import time_units as tu
from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _model(n: int = 8, step_hours: float = 1.0, loads: list[float] | None = None, **gen: Any) -> dict[str, Any]:
    import pandas as pd

    snaps = [t.strftime("%Y-%m-%d %H:%M") for t in pd.date_range("2025-01-01", periods=n, freq=pd.Timedelta(hours=step_hours))]
    loads = loads or [20.0] * n
    base = {"name": "g1", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0}
    base.update(gen)
    return {
        "buses": [{"name": "b0"}],
        "carriers": [{"name": "gas"}, {"name": "peaker"}],
        "snapshots": [{"snapshot": s, "objective": step_hours, "stores": step_hours, "generators": step_hours} for s in snaps],
        "generators": [base, {"name": "peaker", "bus": "b0", "carrier": "peaker", "p_nom": 200.0, "marginal_cost": 90.0}],
        "loads": [{"name": "load", "bus": "b0", "p_set": 20.0}],
        "loads-p_set": [{"snapshot": s, "load": v} for s, v in zip(snaps, loads)],
    }


def _rows(*rows: tuple[str, float, str]) -> list[dict[str, Any]]:
    return [{"component": "generators", "name": "g1", "attribute": a, "value": v, "unit": u} for a, v, u in rows]


def _built(model: dict[str, Any], rows: list[dict[str, Any]], options: dict[str, Any] | None = None):
    model = dict(model)
    model[tu.SHEET] = rows
    return build_network(model, SCENARIO, options or {})


# ── conversions ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("step,rate,expected", [
    (1.0, 0.3, 0.3),          # min(1, r w)
    (4.0, 0.1, 0.4),
    (0.25, 1.2, 0.3),         # a 15-minute snapshot of a 120 %/h unit
    (4.0, 0.5, float("nan")),  # r w = 2 >= 1: blank
    (1.0, 1.0, float("nan")),  # exactly 1: blank
])
def test_ramp_is_rate_times_the_solve_step_and_blank_at_one(step: float, rate: float, expected: float) -> None:
    n, notes = _built(_model(4, step), _rows(("ramp_limit_up", rate, "per_hour")))
    got = n.generators.at["g1", "ramp_limit_up"]
    if np.isnan(expected):
        assert np.isnan(got)
    else:
        assert got == pytest.approx(expected, rel=1e-12)
    assert any(x.startswith("Time units:") for x in notes)


def test_per_minute_rate_is_sixty_times_per_hour() -> None:
    n, _ = _built(_model(4, 0.25), _rows(("ramp_limit_up", 0.02, "per_minute"), ("ramp_limit_down", 0.02, "per_minute")))
    # 0.02/min = 1.2/h; a 15 min snapshot reaches 0.3 of p_nom
    assert n.generators.at["g1", "ramp_limit_up"] == pytest.approx(0.3)
    assert n.generators.at["g1", "ramp_limit_down"] == pytest.approx(0.3)


@pytest.mark.parametrize("step,hours,unit,expected,rounded", [
    (1.0, 4.0, "hours", 4, False),
    (4.0, 4.0, "hours", 1, False),
    (3.0, 4.0, "hours", 2, True),    # ceil(4/3)
    (0.25, 4.0, "hours", 16, False),
    (1.0, 90.0, "minutes", 2, True),  # ceil(1.5)
    (1.0, 0.0, "hours", 0, False),
])
def test_uc_times_are_ceil_hours_over_step(step: float, hours: float, unit: str, expected: int, rounded: bool) -> None:
    n, notes = _built(
        _model(4, step, committable=True, p_min_pu=0.3),
        _rows(("min_up_time", hours, unit), ("min_down_time", hours, unit), ("up_time_before", hours, unit), ("down_time_before", hours, unit)),
    )
    for attr in tu.TIME_ATTRS:
        assert int(n.generators.at["g1", attr]) == expected
    assert any("rounded UP" in x for x in notes) is rounded


def test_start_up_limit_is_reach_in_one_snapshot_never_below_p_min_pu() -> None:
    # 0.5 /h at 1 h reaches 0.5 of p_nom, below the 0.6 minimum load: raised to 0.6 and said so
    n, notes = _built(
        _model(4, 1.0, committable=True, p_min_pu=0.6),
        _rows(("ramp_limit_start_up", 0.5, "per_hour"), ("ramp_limit_shut_down", 0.9, "per_hour")),
    )
    assert n.generators.at["g1", "ramp_limit_start_up"] == pytest.approx(0.6)
    assert n.generators.at["g1", "ramp_limit_shut_down"] == pytest.approx(0.9)
    assert any("raised to 0.6" in x for x in notes)
    # 4 h snapshots reach 2.0 >= 1: blank
    n4, _ = _built(_model(4, 4.0, committable=True, p_min_pu=0.6), _rows(("ramp_limit_start_up", 0.5, "per_hour")))
    assert np.isnan(n4.generators.at["g1", "ramp_limit_start_up"])


def test_conversion_uses_the_actual_weights_not_the_timestamp_spacing() -> None:
    m = _model(4, 1.0)  # timestamps 1 h apart ...
    for r in m["snapshots"]:
        r["stores"] = 2.0  # ... but the solve steps are 2 h
    n, _ = _built(m, _rows(("ramp_limit_up", 0.2, "per_hour")))
    assert n.generators.at["g1", "ramp_limit_up"] == pytest.approx(0.4)


def test_non_uniform_weights_use_the_smallest_step_and_say_so() -> None:
    m = _model(4, 1.0)
    m["snapshots"][2]["stores"] = 3.0
    n, notes = _built(m, _rows(("ramp_limit_up", 0.2, "per_hour"), ("min_up_time", 4, "hours")))
    assert n.generators.at["g1", "ramp_limit_up"] == pytest.approx(0.2)
    assert int(n.generators.at["g1", "min_up_time"]) == 4
    assert any("not uniform" in x for x in notes)


def test_rows_override_the_native_column_and_are_declared() -> None:
    n, notes = _built(_model(4, 1.0, ramp_limit_up=0.9), _rows(("ramp_limit_up", 0.1, "per_hour")))
    assert n.generators.at["g1", "ramp_limit_up"] == pytest.approx(0.1)
    assert any("replaced a number typed directly" in x for x in notes)
    assert n.meta[tu.META_KEY][0]["pypsaValue"] == pytest.approx(0.1)


def test_native_column_without_a_row_passes_through_unchanged() -> None:
    n, _ = _built(_model(4, 4.0, ramp_limit_up=0.9), [])
    assert n.generators.at["g1", "ramp_limit_up"] == pytest.approx(0.9)


@pytest.mark.parametrize("row,message", [
    ({"component": "buses", "name": "g1", "attribute": "ramp_limit_up", "value": 1, "unit": "per_hour"}, "component"),
    ({"component": "generators", "name": "g1", "attribute": "p_nom", "value": 1, "unit": "per_hour"}, "attribute"),
    ({"component": "generators", "name": "g1", "attribute": "ramp_limit_up", "value": 1, "unit": "hours"}, "unit"),
    ({"component": "generators", "name": "g1", "attribute": "min_up_time", "value": -1, "unit": "hours"}, ">= 0"),
])
def test_invalid_rows_are_refused_with_the_reason(row: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        tu.read_rows({tu.SHEET: [row]})


def test_unknown_component_name_is_refused() -> None:
    m = _model(4)
    m[tu.SHEET] = [{"component": "generators", "name": "ghost", "attribute": "ramp_limit_up", "value": 0.1, "unit": "per_hour"}]
    from fastapi import HTTPException

    with pytest.raises(HTTPException, match="ghost"):
        build_network(m, SCENARIO, {})


def test_link_and_process_rows_reach_pypsa() -> None:
    m = _model(4, 2.0)
    m["buses"].append({"name": "b1"})
    m["links"] = [{"name": "l1", "bus0": "b0", "bus1": "b1", "p_nom": 10.0, "committable": True, "p_min_pu": 0.1}]
    m[tu.SHEET] = [
        {"component": "links", "name": "l1", "attribute": "ramp_limit_up", "value": 0.1, "unit": "per_hour"},
        {"component": "links", "name": "l1", "attribute": "min_up_time", "value": 4, "unit": "hours"},
    ]
    n, _ = build_network(m, SCENARIO, {})
    assert n.links.at["l1", "ramp_limit_up"] == pytest.approx(0.2)
    assert int(n.links.at["l1", "min_up_time"]) == 2


# ── the constraints are PyPSA's ─────────────────────────────────────────────────────────

def _swing(step: float, rate: float) -> dict[str, Any]:
    loads = [20.0, 20.0, 100.0, 100.0, 20.0, 20.0, 100.0, 100.0]
    m = _model(8, step, loads=loads, p_nom=100.0)
    m[tu.SHEET] = _rows(("ramp_limit_up", rate, "per_hour"), ("ramp_limit_down", rate, "per_hour"))
    return m


def test_native_ramp_constraint_is_the_only_one_and_enforces_rate_times_step() -> None:
    res = run_pypsa(_swing(1.0, 0.3), SCENARIO, {})
    p = np.array([row["values"].get("g1", 0.0) for row in res["generatorDispatchSeries"]])
    assert np.max(np.abs(np.diff(p))) <= 0.3 * 100.0 + 1e-6
    assert np.max(np.abs(np.diff(p))) >= 0.3 * 100.0 - 1e-6  # and it binds


def test_same_rate_at_4h_resolution_is_not_binding() -> None:
    # 0.3/h x 4 h = 1.2 of p_nom per snapshot: blank, the unit may swing freely
    n, _ = build_network(_swing(4.0, 0.3), SCENARIO, {})
    assert np.isnan(n.generators.at["g1", "ramp_limit_up"])


def test_no_ragnarok_ramp_constraint_names_in_the_model() -> None:
    import backend.pypsa.network.ramp as ramp

    assert not hasattr(ramp, "apply_ramp_constraints")
    assert not hasattr(ramp, "strip_native_ramp_columns")


def test_ramp_is_coupled_across_rolling_windows_natively() -> None:
    # the load steps up exactly at the first snapshot of the second window: without coupling g1 would jump 20 -> 100
    m = _model(8, 1.0, loads=[20.0] * 4 + [100.0] * 4, p_nom=100.0)
    m[tu.SHEET] = _rows(("ramp_limit_up", 0.3, "per_hour"), ("ramp_limit_down", 0.3, "per_hour"))
    res = run_pypsa(m, SCENARIO, {"rollingConfig": {"enabled": True, "horizonHours": 4, "overlapHours": 0}})
    p = np.array([row["values"].get("g1", 0.0) for row in res["generatorDispatchSeries"]])
    assert p[3] == pytest.approx(20.0, abs=1e-6) and p[4] == pytest.approx(50.0, abs=1e-6)
    assert np.max(np.abs(np.diff(p))) <= 30.0 + 1e-6


# ── default ramp (rampConfig) ───────────────────────────────────────────────────────────

def test_ramp_config_writes_default_rows_for_thermal_only_and_never_over_an_explicit_row() -> None:
    m = _model(4)
    m["carriers"].append({"name": "solar"})
    m["generators"].append({"name": "pv", "bus": "b0", "carrier": "solar", "p_nom": 10.0})
    m[tu.SHEET] = _rows(("ramp_limit_up", 0.7, "per_hour"))
    rows = tu.ramp_config_rows(m, {"enabled": True, "rampLimitUp": 0.5, "rampLimitDown": 0.4, "appliesTo": "thermal"})
    keys = {(r["name"], r["attribute"]): r["value"] for r in rows}
    assert ("g1", "ramp_limit_up") not in keys  # explicit row wins
    assert keys[("g1", "ramp_limit_down")] == 0.4
    assert ("pv", "ramp_limit_up") not in keys  # variable renewable excluded under "thermal"
    assert tu.ramp_config_rows(m, {"enabled": False, "rampLimitUp": 0.5}) == []


def test_ramp_config_run_option_reaches_the_native_columns() -> None:
    n, notes = build_network(_model(4), SCENARIO, {"rampConfig": {"enabled": True, "rampLimitUp": 0.5, "rampLimitDown": 0.25, "appliesTo": "all"}})
    assert n.generators.at["g1", "ramp_limit_up"] == pytest.approx(0.5)
    assert n.generators.at["g1", "ramp_limit_down"] == pytest.approx(0.25)
    assert any("Time units" in x for x in notes)


# ── migration (schema 3 -> 4) ───────────────────────────────────────────────────────────

def test_migration_turns_plant_template_values_into_time_units() -> None:
    m = _model(4, 0.25, committable=True, plant="ccgt-1", min_up_time=16, min_down_time=8, up_time_before=16, down_time_before=0,
               ramp_limit_up=0.3, ramp_limit_down=0.3)
    out, moved = tu.migrate_to_time_units(m)
    rows = {(r["name"], r["attribute"]): r for r in out[tu.SHEET]}
    assert rows[("g1", "min_up_time")]["value"] == pytest.approx(4.0) and rows[("g1", "min_up_time")]["unit"] == "hours"
    assert rows[("g1", "min_down_time")]["value"] == pytest.approx(2.0)
    assert rows[("g1", "ramp_limit_up")]["value"] == pytest.approx(1.2) and rows[("g1", "ramp_limit_up")]["unit"] == "per_hour"
    assert ("g1", "down_time_before") not in rows  # zero stays zero
    g1 = next(r for r in out["generators"] if r["name"] == "g1")
    assert g1["min_up_time"] == 0 and g1["up_time_before"] == 1 and g1["ramp_limit_up"] is None  # PyPSA defaults
    assert moved and "plant template" in moved[0]["why"]
    # the input is untouched
    assert next(r for r in m["generators"] if r["name"] == "g1")["min_up_time"] == 16


def test_migration_leaves_pypsa_native_values_alone_without_the_old_ramp_module() -> None:
    m = _model(4, 1.0, ramp_limit_up=0.3, committable=True, min_up_time=3)
    out, moved = tu.migrate_to_time_units(m)
    assert moved == [] and tu.SHEET not in out


def test_migration_reads_per_hour_overrides_of_an_enabled_ramp_preset() -> None:
    import json

    m = _model(4, 1.0, ramp_limit_up=0.3)
    m["RAGNAROK_Scenarios"] = [{"name": "p", "json": json.dumps({"rampConfig": {"enabled": True, "rampLimitUp": 0.5}})}]
    out, moved = tu.migrate_to_time_units(m)
    assert [(r["attribute"], r["value"], r["unit"]) for r in out[tu.SHEET]] == [("ramp_limit_up", 0.3, "per_hour")]
    assert next(r for r in out["generators"] if r["name"] == "g1")["ramp_limit_up"] is None
    assert moved[0]["why"].startswith("was a rate per hour")


def test_cost_basis_migration_chain_reaches_schema_4_and_is_idempotent() -> None:
    from backend.pypsa.network import cost_basis as cb

    m = _model(4, 0.25, committable=True, plant="ccgt-1", min_up_time=16, up_time_before=16)
    out, report = cb.migrate_cost_basis(m)
    assert cb.schema_version(out) == cb.CURRENT_SCHEMA_VERSION == 4
    assert report.time_units and report.noteworthy
    again, report2 = cb.migrate_cost_basis(out)
    assert not report2.migrated and again[tu.SHEET] == out[tu.SHEET]


def test_a_stamped_older_workbook_migrates_even_when_the_loader_says_pypsa_native() -> None:
    """The session store passes ``pypsa_native=True`` for anything that is not an old-Ragnarok upload; a Ragnarok workbook
    stamped schema 3 must still go through the 3 -> 4 step, while an UNSTAMPED PyPSA file is only stamped."""
    from backend.pypsa.network import cost_basis as cb

    m = _model(4, 0.25, committable=True, plant="ccgt-1", min_up_time=16, ramp_limit_up=0.3)
    cb.stamp(m, 3)
    out, report = cb.migrate_cost_basis(m, pypsa_native=True)
    assert report.time_units and cb.schema_version(out) == 4
    unstamped = _model(4, 0.25, committable=True, plant="ccgt-1", min_up_time=16, ramp_limit_up=0.3)
    out2, report2 = cb.migrate_cost_basis(unstamped, pypsa_native=True)
    assert not report2.time_units and cb.schema_version(out2) == 4
    assert next(r for r in out2["generators"] if r["name"] == "g1")["min_up_time"] == 16  # PyPSA-native values untouched


def test_a_pypsa_default_is_not_reported_as_a_typed_value_that_was_replaced() -> None:
    """``up_time_before`` defaults to 1 in PyPSA: replacing the default is not 'replaced a number typed directly'."""
    _, notes = _built(_model(4, 1.0, committable=True), _rows(("min_up_time", 4, "hours"), ("up_time_before", 4, "hours"), ("ramp_limit_up", 0.1, "per_hour")))
    assert not any("replaced a number typed directly" in x for x in notes)
