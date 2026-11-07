"""Control-panel module: switch rules turn PyPSA attributes off for filtered rows in the run's copy, values kept.

Pins: rule validation and group expansion; what "off" writes (PyPSA's default, the series column dropped, the
time-unit row dropped) and only for the filtered rows; the workbook untouched; the submit hook reading the project's
app state or a stated option; and, end to end, a ramp that binds with the switch on and is gone with it off.
"""
from __future__ import annotations

import copy
import json
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from backend.app import app_state
from backend.app import control_panel as cp
from backend.app.control_panel import hooks
from backend.pypsa.network import time_units as tu
from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
LOADS = [20.0, 20.0, 100.0, 100.0, 20.0, 20.0, 100.0, 100.0]


def _model() -> dict[str, Any]:
    snaps = [t.strftime("%Y-%m-%d %H:%M") for t in pd.date_range("2025-01-01", periods=len(LOADS), freq="h")]
    return {
        "buses": [{"name": "b0"}],
        "carriers": [{"name": "gas"}, {"name": "coal"}, {"name": "peaker"}],
        "snapshots": [{"snapshot": s, "objective": 1.0, "stores": 1.0, "generators": 1.0} for s in snaps],
        "generators": [
            {"name": "g1", "bus": "b0", "carrier": "gas", "region": "north", "p_nom": 100.0, "marginal_cost": 10.0,
             "committable": True, "p_min_pu": 0.1},
            {"name": "c1", "bus": "b0", "carrier": "coal", "region": "south", "p_nom": 0.0, "marginal_cost": 5.0,
             "ramp_limit_up": 0.2},
            {"name": "peaker", "bus": "b0", "carrier": "peaker", "region": "north", "p_nom": 200.0, "marginal_cost": 90.0},
        ],
        "generators-ramp_limit_down": [{"snapshot": s, "c1": 0.2, "g1": 0.5} for s in snaps],
        "loads": [{"name": "load", "bus": "b0", "p_set": 20.0}],
        "loads-p_set": [{"snapshot": s, "load": v} for s, v in zip(snaps, LOADS)],
        tu.SHEET: [
            {"component": "generators", "name": "g1", "attribute": "ramp_limit_up", "value": 0.3, "unit": "per_hour"},
            {"component": "generators", "name": "g1", "attribute": "ramp_limit_down", "value": 0.3, "unit": "per_hour"},
            {"component": "generators", "name": "g1", "attribute": "min_up_time", "value": 2, "unit": "hours"},
        ],
    }


def _rule(**kw: Any) -> dict[str, Any]:
    return {"id": "r1", "component": "generators", "attributes": ["ramps"], "column": "carrier", "values": ["gas"],
            "on": False, **kw}


# ── validation ──────────────────────────────────────────────────────────────────────────

def test_groups_expand_and_values_are_text() -> None:
    (rule,) = cp.parse_rules([_rule(attributes=["ramp_up_down", "ramp_limit_up", "uc_times"], values=[1.0, "gas"])])
    assert rule.attributes == ("ramp_limit_up", "ramp_limit_down", *tu.TIME_ATTRS)
    assert rule.values == ("1", "gas")
    assert rule.on is False


def test_app_state_object_and_json_string_are_accepted() -> None:
    value = json.dumps({"version": 1, "rules": [_rule()]})
    assert cp.parse_rules(value)[0].component == "generators"
    assert cp.parse_rules(json.loads(value))[0].id == "r1"


@pytest.mark.parametrize("bad,needle", [
    ({"component": "nonsense"}, "not a PyPSA component"),
    ({"attributes": ["not_an_attr"]}, "not an input attribute"),
    ({"attributes": []}, "no attributes"),
    ({"column": ""}, "no filter column"),
])
def test_bad_rules_are_named(bad: dict[str, Any], needle: str) -> None:
    with pytest.raises(ValueError, match=needle):
        cp.parse_rules([_rule(**bad)])


def test_off_value_is_pypsas_default() -> None:
    assert cp.off_value("generators", "ramp_limit_up") is None
    assert cp.off_value("generators", "committable") is False
    assert cp.off_value("generators", "p_min_pu") == 0.0
    assert cp.off_value("generators", "min_up_time") == 0


# ── what "off" writes ───────────────────────────────────────────────────────────────────

def test_switch_on_changes_nothing() -> None:
    model = _model()
    out, effects = cp.apply_rules(model, cp.parse_rules([_rule(on=True)]))
    assert out == model and effects == []


def test_off_clears_static_series_and_time_units_for_matched_rows_only() -> None:
    model = _model()
    before = copy.deepcopy(model)
    out, (effect,) = cp.apply_rules(model, cp.parse_rules([_rule()]))
    assert model == before  # the workbook is untouched
    assert effect.names == ["g1"]
    # time-unit ramp rows of g1 gone, its min_up_time row (not a ramp) kept
    assert [r["attribute"] for r in out[tu.SHEET]] == ["min_up_time"]
    assert effect.time_unit_rows == 2
    # g1's series column dropped, c1's kept
    assert all("g1" not in r and r["c1"] == 0.2 for r in out["generators-ramp_limit_down"])
    assert effect.series_columns == 1
    # coal's static ramp untouched
    assert next(r for r in out["generators"] if r["name"] == "c1")["ramp_limit_up"] == 0.2


def test_user_column_filter_and_empty_values_match_all() -> None:
    model = _model()
    (rule,) = cp.parse_rules([_rule(attributes=["committable", "p_min_pu"], column="region", values=["north"])])
    out, (effect,) = cp.apply_rules(model, [rule])
    assert effect.names == ["g1", "peaker"]
    g1 = next(r for r in out["generators"] if r["name"] == "g1")
    assert g1["committable"] is False and g1["p_min_pu"] == 0.0
    assert effect.cells == 2  # peaker had neither cell
    (all_rows,) = cp.parse_rules([_rule(values=[])])
    assert cp.matching_names(model, all_rows) == ["g1", "c1", "peaker"]


def test_column_values_counts() -> None:
    assert cp.column_values(_model(), "generators", "region") == [{"value": "north", "count": 2}, {"value": "south", "count": 1}]


# ── submit hook ─────────────────────────────────────────────────────────────────────────

def test_submit_hook_reads_project_app_state_and_records_effect() -> None:
    state = {cp.STATE_KEY: json.dumps({"version": 1, "rules": [_rule()]})}
    data = {"model": {**_model(), app_state.SHEET: app_state.to_rows(state)}, "scenario": {}, "options": {}}
    out = hooks._apply(data)
    assert [r["attribute"] for r in out["model"][tu.SHEET]] == ["min_up_time"]
    (applied,) = out["options"][cp.APPLIED_KEY]
    assert applied["names"] == ["g1"] and applied["matched"] == 1


def test_stated_option_wins_over_project_state() -> None:
    state = {cp.STATE_KEY: json.dumps({"version": 1, "rules": [_rule()]})}
    data = {"model": {**_model(), app_state.SHEET: app_state.to_rows(state)}, "options": {cp.OPTION_KEY: []}}
    out = hooks._apply(data)
    assert len(out["model"][tu.SHEET]) == 3 and cp.APPLIED_KEY not in out["options"]


def test_submit_hook_refuses_a_bad_rule() -> None:
    with pytest.raises(HTTPException) as exc:
        hooks._apply({"model": _model(), "options": {cp.OPTION_KEY: [_rule(component="nope")]}})
    assert exc.value.status_code == 400


# ── end to end: the ramp binds with the switch on, and is gone with it off ───────────────

def _dispatch(model: dict[str, Any], options: dict[str, Any]) -> tuple[np.ndarray, list[str]]:
    data = hooks._apply({"model": model, "scenario": dict(SCENARIO), "options": options})
    res = run_pypsa(data["model"], data["scenario"], data["options"])
    return np.array([row["values"].get("g1", 0.0) for row in res["generatorDispatchSeries"]]), res.get("narrative") or []


def test_ramp_switch_end_to_end() -> None:
    model = _model()
    model["generators"][0].update(committable=False, p_min_pu=0.0)
    model[tu.SHEET] = model[tu.SHEET][:2]  # the two ramp rows
    del model["generators-ramp_limit_down"]
    p_on, _ = _dispatch(copy.deepcopy(model), {cp.OPTION_KEY: [_rule(on=True)]})
    # Algorithm: |p_t - p_{t-1}| <= r * w * p_nom = 0.3 * 1 h * 100 MW = 30 MW, and it binds on the 20 -> 100 MW step
    assert np.max(np.abs(np.diff(p_on))) == pytest.approx(30.0, abs=1e-6)
    p_off, notes = _dispatch(copy.deepcopy(model), {cp.OPTION_KEY: [_rule()]})
    # no ramp: the cheap unit follows the load (capped at p_nom = 100 MW)
    np.testing.assert_allclose(p_off, np.minimum(LOADS, 100.0), rtol=0, atol=1e-6)
    assert any("Control panel" in n and "ramp_limit_up" in n for n in notes)
