"""Ramp-rate limits (core cleanup step 5, D11): PyPSA's NATIVE ramp constraints, in time units.

Ragnarok no longer builds a ramp constraint of its own (it used to blank PyPSA's columns and add
``dp <= r p_nom dt`` rows). The native ``ramp_limit_up`` / ``_down`` / ``_start_up`` / ``_shut_down`` are the only ramp
rows; the time-units module (``RAGNAROK_TimeUnits``) writes them from a rate per hour at the weights the run uses, and the
``rampConfig`` run option is a default rate that fills that sheet. Pins:

    1. A tight ramp forces smoother dispatch and never lowers cost; the ``ramp`` result reads the native bound.
    2. The weights decide: the same rate per hour that binds at 1 h is slack at 4 h (blank, >= 1 of p_nom per snapshot).
    3. ``appliesTo="thermal"`` leaves a solar generator unbounded.
    4. Disabled config is a strict parity no-op.
    5. Only PyPSA's own constraint names exist in the LP; an extendable unit's ramp scales with its capacity variable.
    6. Ramp composes with rolling horizon (PyPSA carries the dispatch across windows) and with stochastic scenarios.
    7. A per-generator value is a rate per hour (a RAGNAROK_TimeUnits row), not a per-snapshot number.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _two_gen_swing_model(
    n_snaps: int = 4,
    highs: tuple[int, ...] = (2,),
    load_low: float = 20.0,
    load_high: float = 100.0,
    hourly: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """1 bus; cheap 100 MW gas (``g1``) + expensive 100 MW peaker (``peaker``);
    load jumps low->high at `highs` snapshot indices then back down. The
    peaker is the ramp-unconstrained backstop that a tight ramp on ``g1``
    forces into service, so the model stays feasible under a tight ramp
    limit instead of load-shedding or going infeasible."""
    if hourly:
        snaps = [f"2025-01-01T{h:02d}:00:00" for h in range(n_snaps)]
    else:
        snaps = [f"2025-01-0{1 + 4 * h // 24}T{(4 * h) % 24:02d}:00:00" for h in range(n_snaps)]
    loads = [load_high if i in highs else load_low for i in range(n_snaps)]
    return {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": "peaker", "co2_emissions": 0.9}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "g1", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0},
            # Per-generator override (ramp_limit_up/down = 1.0, i.e. 100%/h) so
            # the config default doesn't also throttle the fast-ramping peaker
            # backstop — only g1 is meant to be smoothed in this test.
            {
                "name": "peaker", "bus": "b0", "carrier": "peaker", "p_nom": 100.0, "marginal_cost": 80.0,
                "ramp_limit_up": 1.0, "ramp_limit_down": 1.0,
            },
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": load_low}],
        "loads-p_set": [{"snapshot": s, "load": load} for s, load in zip(snaps, loads)],
    }


def _solar_thermal_model(n_snaps: int = 4) -> dict[str, list[dict[str, Any]]]:
    """1 bus; solar (free, capped, swings with an exogenous p_max_pu) + a
    thermal gas generator; flat load so solar's swing is unconstrained by
    load and only ramp (if applied) would bound it.

    ``gas1`` gets a per-generator ramp-rate override (100%/h — effectively
    unconstrained at this p_nom) so that when the config default (a tiny
    5%/h) is applied to "thermal" generators, it is ``gas1``'s OWN limit
    being exercised that is checked, not an indirect throttle on solar via
    the energy balance (a thermal backstop that can't move fast enough would
    otherwise force solar's dispatch down too, confounding the "is solar
    itself ramp-constrained" question this test asks).
    """
    snaps = [f"2025-01-01T{h:02d}:00:00" for h in range(n_snaps)]
    # p_max_pu alternates 0 / 1 so an unconstrained solar unit swings the full
    # 50 MW between snapshots if ramp does not apply to it.
    pmax = [1.0 if i % 2 == 0 else 0.0 for i in range(n_snaps)]
    return {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "solar"}, {"name": "gas", "co2_emissions": 0.4}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "solar1", "bus": "b0", "carrier": "solar", "p_nom": 50.0, "marginal_cost": 0.0},
            {
                "name": "gas1", "bus": "b0", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 50.0,
                "ramp_limit_up": 1.0, "ramp_limit_down": 1.0,
            },
        ],
        "generators-p_max_pu": [{"snapshot": s, "solar1": v} for s, v in zip(snaps, pmax)],
        # Load matches solar's own swing (50 when solar is available, 40
        # otherwise) so the free solar unit is always fully dispatched to its
        # p_max_pu ceiling rather than curtailed by a flat, lower load — its
        # forced 0 <-> 50 MW swing is then unambiguous.
        "loads": [{"name": "load", "bus": "b0", "p_set": 50.0}],
        "loads-p_set": [{"snapshot": s, "load": (50.0 if v > 0 else 40.0)} for s, v in zip(snaps, pmax)],
    }



# ── 1. Tight ramp forces smoother dispatch; cost never drops below baseline ──


def test_tight_ramp_limit_smooths_dispatch_and_never_lowers_cost() -> None:
    model = _two_gen_swing_model(n_snaps=4, highs=(2,), load_low=20.0, load_high=100.0)
    options_ramp = {"rampConfig": {"enabled": True, "rampLimitUp": 0.2, "rampLimitDown": 0.2, "appliesTo": "all"}}

    result_baseline = run_pypsa(model, SCENARIO, {})
    result_ramp = run_pypsa(model, SCENARIO, options_ramp)

    def _peak_abs_delta(result: dict[str, Any]) -> float:
        values = [row["values"].get("g1", 0.0) for row in result["generatorDispatchSeries"]]
        return max((abs(values[i] - values[i - 1]) for i in range(1, len(values))), default=0.0)

    assert _peak_abs_delta(result_baseline) > 60.0
    assert _peak_abs_delta(result_ramp) <= 20.0 + 1e-6  # 0.2/h x 1 h x 100 MW
    assert result_ramp["ramp"]["enabled"] is True and result_ramp["ramp"]["bindingHours"] >= 1
    assert any(s["label"] == "Time step" and s["value"] == "1 h" for s in result_ramp["ramp"]["summary"])
    total = lambda r: sum(row["value"] for row in r["costBreakdown"])  # noqa: E731
    assert total(result_ramp) >= total(result_baseline) - 1e-6


# ── 2. The weights decide ──


def _single_gen_step_model(weight_hours: float, n_snaps: int = 4, high_at: int = 1) -> dict[str, list[dict[str, Any]]]:
    """One 100 MW unit and no backstop; the load jumps 20 -> 80 MW at ``high_at`` and the workbook is at ``weight_hours``."""
    import pandas as pd

    snaps = [t.strftime("%Y-%m-%d %H:%M") for t in pd.date_range("2025-01-01", periods=n_snaps, freq=pd.Timedelta(hours=weight_hours))]
    loads = [80.0 if i == high_at else 20.0 for i in range(n_snaps)]
    return {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s, "objective": weight_hours, "stores": weight_hours, "generators": weight_hours} for s in snaps],
        "generators": [{"name": "g1", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0}],
        "loads": [{"name": "load", "bus": "b0", "p_set": 20.0}],
        "loads-p_set": [{"snapshot": s, "load": v} for s, v in zip(snaps, loads)],
    }


def test_same_rate_per_hour_binds_at_1h_and_is_slack_at_4h() -> None:
    """0.2/h of 100 MW: 20 MW per 1 h snapshot (a 60 MW jump is infeasible) but 80 MW per 4 h snapshot (blank: >= 1)."""
    cfg = {"rampConfig": {"enabled": True, "rampLimitUp": 0.2, "rampLimitDown": 0.2, "appliesTo": "all"}}
    four = run_pypsa(_single_gen_step_model(4.0), SCENARIO, cfg)
    assert max(row["values"].get("g1", 0.0) for row in four["generatorDispatchSeries"]) >= 80.0 - 1e-6
    n, _ = build_network(_single_gen_step_model(4.0), SCENARIO, cfg)
    assert n.generators.at["g1", "ramp_limit_up"] == pytest.approx(0.8)  # 0.2 x 4 h
    with pytest.raises(Exception) as exc:
        run_pypsa(_single_gen_step_model(1.0), SCENARIO, cfg)
    assert "infeasible" in str(exc.value).lower() or "solver" in str(exc.value).lower()


# ── 3. appliesTo="thermal" leaves a solar generator unconstrained ──


def test_thermal_applies_to_excludes_solar() -> None:
    model = _solar_thermal_model(n_snaps=4)
    options = {"rampConfig": {"enabled": True, "rampLimitUp": 0.05, "rampLimitDown": 0.05, "appliesTo": "thermal"}}
    result = run_pypsa(model, SCENARIO, options)
    solar_values = [row["values"].get("solar1", 0.0) for row in result["generatorDispatchSeries"]]
    deltas = [abs(solar_values[i] - solar_values[i - 1]) for i in range(1, len(solar_values))]
    assert max(deltas) > 40.0
    assert "solar" not in {row["label"] for row in result["ramp"]["byCarrier"]}


# ── 4. Disabled config is a strict parity no-op ──


def test_disabled_ramp_config_is_a_parity_noop() -> None:
    model = _two_gen_swing_model(n_snaps=4, highs=(2,))
    disabled = run_pypsa(model, SCENARIO, {"rampConfig": {"enabled": False, "rampLimitUp": 0.01, "rampLimitDown": 0.01}})
    absent = run_pypsa(model, SCENARIO, {})
    assert disabled["ramp"] == absent["ramp"]  # the option off changes nothing (the fixture's peaker carries its own native value)
    plain = _two_gen_swing_model(n_snaps=4, highs=(2,))
    del plain["generators"][1]["ramp_limit_up"], plain["generators"][1]["ramp_limit_down"]
    assert run_pypsa(plain, SCENARIO, {"rampConfig": {"enabled": False, "rampLimitUp": 0.01}})["ramp"]["enabled"] is False
    assert disabled["summary"] == absent["summary"]
    assert disabled["dispatchSeries"] == absent["dispatchSeries"]
    assert disabled["costBreakdown"] == absent["costBreakdown"]


# ── 5. Only PyPSA's own constraints ──


def test_only_pypsas_native_ramp_constraints_exist() -> None:
    cfg = {"enabled": True, "rampLimitUp": 0.2, "rampLimitDown": 0.2, "appliesTo": "all"}
    n, _ = build_network(_two_gen_swing_model(n_snaps=4), SCENARIO, {"rampConfig": cfg})
    n.optimize(solver_name="highs", include_objective_constant=False)
    names = set(iter(n.model.constraints))
    assert {"Generator-p-ramp_limit_up", "Generator-p-ramp_limit_down"} <= names
    assert not {"ramp_up_fixed", "ramp_down_fixed", "ramp_up_extendable", "ramp_down_extendable"} & names


def test_extendable_generator_ramp_scales_with_the_capacity_variable() -> None:
    """A p_nom_extendable unit must build enough capacity that its 0.5/h ramp covers a 130 MW jump in one hour."""
    snaps = [f"2025-01-01T{h:02d}:00:00" for h in range(3)]
    loads = [20.0, 150.0, 20.0]
    model: dict[str, list[dict[str, Any]]] = {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [{"name": "g1", "bus": "b0", "carrier": "gas", "p_nom": 10.0, "p_nom_extendable": True, "p_nom_max": 500.0,
                        "marginal_cost": 10.0, "capital_cost": 5.0}],
        "loads": [{"name": "load", "bus": "b0", "p_set": 20.0}],
        "loads-p_set": [{"snapshot": s, "load": v} for s, v in zip(snaps, loads)],
    }
    result = run_pypsa(model, SCENARIO, {"rampConfig": {"enabled": True, "rampLimitUp": 0.5, "rampLimitDown": 0.5, "appliesTo": "all"}})
    values = [row["values"].get("g1", 0.0) for row in result["generatorDispatchSeries"]]
    assert max(values) >= 150.0 - 1e-6
    p_nom_opt = {row["name"]: row["p_nom_opt_mw"] for row in result["expansionResults"]}["g1"]
    assert p_nom_opt * 0.5 >= 130.0 - 1e-6


# ── 6. Rolling horizon and stochastic ──


def test_ramp_composes_with_rolling_horizon_smoke() -> None:
    model = _two_gen_swing_model(n_snaps=8, highs=(2, 6), load_low=20.0, load_high=60.0)
    options = {
        "rampConfig": {"enabled": True, "rampLimitUp": 0.3, "rampLimitDown": 0.3, "appliesTo": "all"},
        "rollingConfig": {"enabled": True, "horizonHours": 4, "overlapHours": 0},
    }
    result = run_pypsa(model, SCENARIO, options)
    assert result["ramp"]["enabled"] is True
    assert len(result["generatorDispatchSeries"]) == 8


def test_ramp_with_stochastic_scenarios_runs_on_the_native_constraint() -> None:
    model = _two_gen_swing_model(n_snaps=4, highs=(2,))
    options = {
        "rampConfig": {"enabled": True, "rampLimitUp": 0.2, "rampLimitDown": 0.2, "appliesTo": "all"},
        "stochasticConfig": {"enabled": True, "scenarios": [{"name": "s1", "weight": 0.5}, {"name": "s2", "weight": 0.5}]},
    }
    result = run_pypsa(model, SCENARIO, options)
    assert len(result["generatorDispatchSeries"]) == 4


# ── 7. A per-generator value is a rate per hour ──


def test_per_generator_rate_per_hour_is_converted_for_the_weights_in_use() -> None:
    """The unit with its own rate (a time-units row) ramps by rate x p_nom x dt; a PER-SNAPSHOT number typed in the
    column would be PyPSA's and is not rescaled."""
    from backend.pypsa.network import time_units as tu

    model = _single_gen_step_model(4.0)
    model[tu.SHEET] = [{"component": "generators", "name": "g1", "attribute": "ramp_limit_up", "value": 0.5, "unit": "per_hour"}]
    n, _ = build_network(model, SCENARIO, {})
    assert np.isnan(n.generators.at["g1", "ramp_limit_up"])  # 0.5 x 4 h = 2 >= 1: blank
    model[tu.SHEET][0]["value"] = 0.1
    n, _ = build_network(model, SCENARIO, {})
    assert n.generators.at["g1", "ramp_limit_up"] == pytest.approx(0.4)
    typed = _single_gen_step_model(4.0)
    typed["generators"][0]["ramp_limit_up"] = 0.5  # PyPSA's per-snapshot semantics, passed through untouched
    n, _ = build_network(typed, SCENARIO, {})
    assert n.generators.at["g1", "ramp_limit_up"] == pytest.approx(0.5)
