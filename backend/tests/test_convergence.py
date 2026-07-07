"""Convergence-controlled Monte Carlo sampling + maintenance placement.

Mirrors test_outage_mc.py's model-builder / options-builder pattern for the
integration tests, and test_elcc.py's style for the pure numerical checks.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.results import run_pypsa
from backend.pypsa.results.convergence import (
    _maintenance_window_length,
    _running_se,
    build_convergence,
    place_maintenance,
    run_convergence_sampling,
)

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _hourly_snapshots(n_snaps: int, start_day: int = 1) -> list[str]:
    """Hourly ISO timestamps starting at 2025-01-{start_day}T00:00:00.

    Uses ``pd.date_range`` (rather than manual day/month arithmetic) so
    horizons longer than one month roll over correctly.
    """
    start = pd.Timestamp(f"2025-01-{start_day:02d}T00:00:00")
    return [ts.isoformat() for ts in pd.date_range(start, periods=n_snaps, freq="h")]


def _thermal_model(
    *,
    n_snaps: int = 48,
    load_mw: float = 80.0,
    gen_cap: float = 100.0,
    n_gens: int = 2,
) -> dict[str, list[dict[str, Any]]]:
    """A tight 1-bus system: n_gens identical thermal units vs a flat load."""
    snaps = _hourly_snapshots(n_snaps)
    gens = [
        {"name": f"g{i}", "bus": "b0", "carrier": "gas", "p_nom": gen_cap,
         "marginal_cost": 10.0 + i}
        for i in range(n_gens)
    ]
    return {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": gens,
        "loads": [{"name": "load", "bus": "b0", "p_set": load_mw}],
        "loads-p_set": [{"snapshot": s, "load": load_mw} for s in snaps],
    }


def _convergence_options(**overrides: Any) -> dict[str, Any]:
    cfg = {
        "enabled": True,
        "targetMetric": "eue",
        "tolerance": 0.1,
        "batchSize": 50,
        "maxMembers": 2000,
        "seed": 42,
        "forcedOutageRate": 0.1,
        "mttrHours": 24.0,
    }
    cfg.update(overrides)
    return {"convergenceConfig": cfg}


# ── Pure helper checks ───────────────────────────────────────────────────────


def test_running_se_shrinks_as_n_grows() -> None:
    rng = np.random.default_rng(0)
    values = rng.normal(loc=10.0, scale=3.0, size=2000)
    _, se_small = _running_se(values[:50])
    _, se_large = _running_se(values[:1000])
    assert se_large < se_small


def test_running_se_zero_for_n_below_two() -> None:
    mean0, se0 = _running_se(np.empty(0))
    assert mean0 == 0.0 and se0 == 0.0
    mean1, se1 = _running_se(np.array([5.0]))
    assert mean1 == 5.0 and se1 == 0.0


def test_maintenance_window_length_covers_requested_weeks() -> None:
    weights = np.ones(24 * 30)  # 30 days hourly
    n_snap = _maintenance_window_length(weights, maintenance_weeks=3.0)
    # 3 weeks = 504 hours, hourly steps → 504 snapshots.
    assert n_snap == 504


def test_maintenance_window_length_clamped_to_horizon() -> None:
    weights = np.ones(24 * 10)  # only 10 days available
    n_snap = _maintenance_window_length(weights, maintenance_weeks=3.0)
    assert n_snap == 24 * 10


# ── Pure convergence-sampling checks ─────────────────────────────────────────


def test_convergence_low_tolerance_draws_more_members_than_high_tolerance() -> None:
    for_rates = np.array([0.15])
    mttr = np.array([24.0])
    n_snaps = 24 * 14
    weights = np.ones(n_snaps)
    load = np.full(n_snaps, 95.0)
    thermal_cap = np.array([100.0])
    thermal_pmax = np.ones((n_snaps, 1))
    renewable_floor = np.zeros(n_snaps)
    modeled_hours = float(weights.sum())

    tight = run_convergence_sampling(
        for_rates, mttr, weights, load, thermal_cap, thermal_pmax, renewable_floor,
        target_metric="eue", tolerance=0.02, batch_size=50, max_members=5000,
        seed=1, modeled_hours=modeled_hours,
    )
    loose = run_convergence_sampling(
        for_rates, mttr, weights, load, thermal_cap, thermal_pmax, renewable_floor,
        target_metric="eue", tolerance=0.3, batch_size=50, max_members=5000,
        seed=1, modeled_hours=modeled_hours,
    )
    assert tight["achievedMembers"] > loose["achievedMembers"]
    assert tight["achievedMembers"] <= 5000
    assert loose["achievedMembers"] <= 5000


def test_convergence_trace_se_decreases_as_members_grow() -> None:
    for_rates = np.array([0.2])
    mttr = np.array([24.0])
    n_snaps = 24 * 14
    weights = np.ones(n_snaps)
    load = np.full(n_snaps, 95.0)
    thermal_cap = np.array([100.0])
    thermal_pmax = np.ones((n_snaps, 1))
    renewable_floor = np.zeros(n_snaps)
    modeled_hours = float(weights.sum())

    result = run_convergence_sampling(
        for_rates, mttr, weights, load, thermal_cap, thermal_pmax, renewable_floor,
        target_metric="eue", tolerance=0.01, batch_size=50, max_members=3000,
        seed=3, modeled_hours=modeled_hours,
    )
    trace = result["trace"]
    assert len(trace) >= 3
    ses = [row["se"] for row in trace]
    members = [row["members"] for row in trace]
    assert members == sorted(members)
    # SE should be non-increasing in the tail (allow the first couple of noisy
    # batches, but the overall trend across the whole trace must be downward).
    assert ses[-1] <= ses[0]


def test_convergence_achieved_members_never_exceeds_max() -> None:
    for_rates = np.array([0.5])
    mttr = np.array([6.0])
    n_snaps = 24 * 7
    weights = np.ones(n_snaps)
    load = np.full(n_snaps, 99.0)
    thermal_cap = np.array([100.0])
    thermal_pmax = np.ones((n_snaps, 1))
    renewable_floor = np.zeros(n_snaps)
    modeled_hours = float(weights.sum())

    result = run_convergence_sampling(
        for_rates, mttr, weights, load, thermal_cap, thermal_pmax, renewable_floor,
        target_metric="lole", tolerance=1e-6, batch_size=100, max_members=250,
        seed=5, modeled_hours=modeled_hours,
    )
    assert result["achievedMembers"] <= 250
    # An unreachable tolerance with a capped maxMembers must not converge.
    assert result["converged"] is False


def test_convergence_zero_estimate_converges_immediately() -> None:
    """A perfectly firm unit (FOR=0, i.e. never on forced outage) with ample
    capacity guarantees zero shortfall on every draw, so the estimate is
    exactly 0. The |estimate| ~ 0 early-exit fires only once the minimum-member
    floor is cleared (min_stop = max(2*batch_size, 100) = 100 here), never on a
    single lucky batch."""
    for_rates = np.array([0.0])
    mttr = np.array([24.0])
    n_snaps = 24 * 7
    weights = np.ones(n_snaps)
    load = np.full(n_snaps, 10.0)
    thermal_cap = np.array([1000.0])
    thermal_pmax = np.ones((n_snaps, 1))
    renewable_floor = np.zeros(n_snaps)
    modeled_hours = float(weights.sum())

    result = run_convergence_sampling(
        for_rates, mttr, weights, load, thermal_cap, thermal_pmax, renewable_floor,
        target_metric="eue", tolerance=0.05, batch_size=50, max_members=2000,
        seed=7, modeled_hours=modeled_hours,
    )
    assert result["converged"] is True
    assert result["achievedMembers"] == 100
    assert result["estimate"] == 0.0


def test_convergence_no_premature_zero_on_lucky_first_batch() -> None:
    """A tight-margin, low-FOR system whose first batch can luckily read zero
    shortfall must NOT declare converged-to-zero: the min-member floor forces
    enough draws that the true (non-zero) EUE surfaces. Regression for the
    zero-estimate-floor premature-convergence trap."""
    for_rates = np.array([0.02])
    mttr = np.array([48.0])
    n_snaps = 48  # 2-day horizon — short enough that a batch of 10 is often all-zero
    weights = np.ones(n_snaps)
    load = np.full(n_snaps, 99.5)
    thermal_cap = np.array([100.0])
    thermal_pmax = np.ones((n_snaps, 1))
    renewable_floor = np.zeros(n_snaps)
    modeled_hours = float(weights.sum())

    # seed 0 happens to draw an all-zero first batch of 10 under the old code.
    result = run_convergence_sampling(
        for_rates, mttr, weights, load, thermal_cap, thermal_pmax, renewable_floor,
        target_metric="eue", tolerance=0.05, batch_size=10, max_members=5000,
        seed=0, modeled_hours=modeled_hours,
    )
    # It must draw at least the floor before it can stop, and the accumulated
    # sample reveals the genuine (positive) risk rather than a false zero.
    assert result["achievedMembers"] >= 100
    assert result["estimate"] > 0.0


def test_convergence_batch_size_one_no_single_sample_stop() -> None:
    """batch_size=1 must not converge after a single draw with a zero-width CI
    (se=0 from the n<2 guard makes the relative-SE test trivially true).
    Regression for the single-sample collapse."""
    for_rates = np.array([0.15, 0.2])
    mttr = np.array([24.0, 48.0])
    n_snaps = 24 * 5
    weights = np.ones(n_snaps)
    load = np.full(n_snaps, 95.0)
    thermal_cap = np.array([60.0, 60.0])
    thermal_pmax = np.ones((n_snaps, 2))
    renewable_floor = np.zeros(n_snaps)
    modeled_hours = float(weights.sum())

    result = run_convergence_sampling(
        for_rates, mttr, weights, load, thermal_cap, thermal_pmax, renewable_floor,
        target_metric="eue", tolerance=0.05, batch_size=1, max_members=5000,
        seed=3, modeled_hours=modeled_hours,
    )
    # Never stop on one sample; if it converges the CI must have real width.
    assert result["achievedMembers"] >= 100
    if result["converged"]:
        assert result["ciHigh"] > result["ciLow"]


def test_convergence_determinism_same_seed_identical_estimate() -> None:
    for_rates = np.array([0.15, 0.2])
    mttr = np.array([24.0, 48.0])
    n_snaps = 24 * 10
    weights = np.ones(n_snaps)
    load = np.full(n_snaps, 95.0)
    thermal_cap = np.array([60.0, 60.0])
    thermal_pmax = np.ones((n_snaps, 2))
    renewable_floor = np.zeros(n_snaps)
    modeled_hours = float(weights.sum())

    a = run_convergence_sampling(
        for_rates, mttr, weights, load, thermal_cap, thermal_pmax, renewable_floor,
        target_metric="eue", tolerance=0.05, batch_size=50, max_members=1000,
        seed=11, modeled_hours=modeled_hours,
    )
    b = run_convergence_sampling(
        for_rates, mttr, weights, load, thermal_cap, thermal_pmax, renewable_floor,
        target_metric="eue", tolerance=0.05, batch_size=50, max_members=1000,
        seed=11, modeled_hours=modeled_hours,
    )
    assert a["achievedMembers"] == b["achievedMembers"]
    assert a["estimate"] == b["estimate"]
    assert a["trace"] == b["trace"]


def test_convergence_ci_brackets_estimate() -> None:
    for_rates = np.array([0.2])
    mttr = np.array([24.0])
    n_snaps = 24 * 10
    weights = np.ones(n_snaps)
    load = np.full(n_snaps, 96.0)
    thermal_cap = np.array([100.0])
    thermal_pmax = np.ones((n_snaps, 1))
    renewable_floor = np.zeros(n_snaps)
    modeled_hours = float(weights.sum())

    result = run_convergence_sampling(
        for_rates, mttr, weights, load, thermal_cap, thermal_pmax, renewable_floor,
        target_metric="eue", tolerance=0.05, batch_size=50, max_members=2000,
        seed=13, modeled_hours=modeled_hours,
    )
    assert result["ciLow"] <= result["estimate"] <= result["ciHigh"]


# ── Pure maintenance-placement checks ────────────────────────────────────────


def test_place_maintenance_schedules_each_unit_once() -> None:
    n_snaps = 24 * 60  # 60 days
    net_load = 50.0 + 20.0 * np.sin(np.linspace(0, 8 * np.pi, n_snaps))
    weights = np.ones(n_snaps)
    names = ["u0", "u1", "u2"]
    caps = np.array([100.0, 80.0, 60.0])

    mask, schedule = place_maintenance(names, caps, net_load, weights, maintenance_weeks=2.0)
    assert mask.shape == (3, n_snaps)
    assert len(schedule) == 3
    scheduled_names = {row[0] for row in schedule}
    assert scheduled_names == set(names)
    # Each unit's window length matches ~2 weeks (336 hourly snapshots).
    for _name, _start, length in schedule:
        assert length == 336


def test_place_maintenance_start_is_valid_index() -> None:
    n_snaps = 24 * 40
    net_load = np.full(n_snaps, 70.0)
    weights = np.ones(n_snaps)
    names = ["u0", "u1"]
    caps = np.array([50.0, 50.0])
    _mask, schedule = place_maintenance(names, caps, net_load, weights, maintenance_weeks=1.0)
    for _name, start, length in schedule:
        assert 0 <= start
        assert start + length <= n_snaps


def test_place_maintenance_staggers_units_not_all_same_start() -> None:
    """With a flat net load (no natural low point), the stagger logic must
    still spread units across different windows rather than piling them all
    onto the same start."""
    n_snaps = 24 * 30
    net_load = np.full(n_snaps, 80.0)
    weights = np.ones(n_snaps)
    names = [f"u{i}" for i in range(4)]
    caps = np.array([50.0, 50.0, 50.0, 50.0])
    _mask, schedule = place_maintenance(names, caps, net_load, weights, maintenance_weeks=2.0)
    starts = [row[1] for row in schedule]
    assert len(set(starts)) > 1, "expected units to be staggered across different windows"


# ── Integration: convergence via build_convergence / run_pypsa ──────────────


def test_integration_disabled_gives_no_convergence_block() -> None:
    model = _thermal_model()
    result_disabled = run_pypsa(model, SCENARIO, {"convergenceConfig": {"enabled": False}})
    result_absent = run_pypsa(model, SCENARIO, {})
    assert result_disabled["convergenceSampling"] is None
    assert result_absent["convergenceSampling"] is None
    assert result_disabled["summary"] == result_absent["summary"]
    assert result_disabled["dispatchSeries"] == result_absent["dispatchSeries"]


def test_integration_convergence_enabled_returns_contract_shape() -> None:
    model = _thermal_model(n_snaps=24 * 10, load_mw=95.0, gen_cap=100.0, n_gens=1)
    result = run_pypsa(model, SCENARIO, _convergence_options())
    cs = result["convergenceSampling"]
    assert cs is not None
    assert cs["enabled"] is True
    assert cs["targetMetric"] == "eue"
    assert isinstance(cs["achievedMembers"], int)
    assert isinstance(cs["converged"], bool)
    assert cs["unit"] == "MWh/yr"
    assert cs["ciLow"] <= cs["estimate"] <= cs["ciHigh"]
    assert cs["maintenance"] is None
    assert isinstance(cs["trace"], list) and cs["trace"]
    for row in cs["trace"]:
        assert set(row.keys()) == {"members", "estimate", "se"}


def test_integration_lole_target_metric_uses_hours_unit() -> None:
    model = _thermal_model(n_snaps=24 * 10, load_mw=95.0, gen_cap=100.0, n_gens=1)
    result = run_pypsa(model, SCENARIO, _convergence_options(targetMetric="lole"))
    cs = result["convergenceSampling"]
    assert cs["targetMetric"] == "lole"
    assert cs["unit"] == "h/yr"


def test_integration_no_thermal_generators_returns_none() -> None:
    snaps = _hourly_snapshots(24)
    model = {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "solar"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "solar1", "bus": "b0", "carrier": "solar", "p_nom": 100.0, "marginal_cost": 1.0},
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": 10.0}],
        "loads-p_set": [{"snapshot": s, "load": 10.0} for s in snaps],
    }
    result = run_pypsa(model, SCENARIO, _convergence_options())
    assert result["convergenceSampling"] is None


def test_build_convergence_returns_none_when_config_missing_or_disabled() -> None:
    n, _ = build_network(
        _thermal_model(n_snaps=4), SCENARIO,
        {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0},
    )
    n.optimize(solver_name="highs")
    assert build_convergence(n, {}) is None
    assert build_convergence(n, {"convergenceConfig": {"enabled": False}}) is None
    assert build_convergence(n, None) is None


def test_build_convergence_returns_none_when_unsolved() -> None:
    n, _ = build_network(
        _thermal_model(n_snaps=4), SCENARIO,
        {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0},
    )
    assert build_convergence(n, _convergence_options()) is None


# ── Integration: maintenance placement ───────────────────────────────────────


def _maintenance_options(**overrides: Any) -> dict[str, Any]:
    cfg = {
        "enabled": True,
        "targetMetric": "eue",
        "tolerance": 0.2,
        "batchSize": 50,
        "maxMembers": 500,
        "seed": 42,
        "forcedOutageRate": 0.05,
        "mttrHours": 24.0,
        "maintenanceEnabled": True,
        "maintenanceWeeks": 2.0,
    }
    cfg.update(overrides)
    return {"convergenceConfig": cfg}


def test_integration_maintenance_schedules_each_eligible_unit_once() -> None:
    model = _thermal_model(n_snaps=24 * 60, load_mw=150.0, gen_cap=100.0, n_gens=4)
    result = run_pypsa(model, SCENARIO, _maintenance_options())
    cs = result["convergenceSampling"]
    maint = cs["maintenance"]
    assert maint is not None
    assert maint["enabled"] is True
    assert len(maint["schedule"]) == 4
    units = {row["unit"] for row in maint["schedule"]}
    assert units == {"g0", "g1", "g2", "g3"}
    for row in maint["schedule"]:
        assert row["carrier"] == "gas"
        assert isinstance(row["startLabel"], str) and row["startLabel"]
        assert row["weeks"] == pytest.approx(2.0)


def test_integration_maintenance_starts_are_staggered() -> None:
    model = _thermal_model(n_snaps=24 * 60, load_mw=150.0, gen_cap=100.0, n_gens=4)
    result = run_pypsa(model, SCENARIO, _maintenance_options())
    schedule = result["convergenceSampling"]["maintenance"]["schedule"]
    starts = {row["startLabel"] for row in schedule}
    assert len(starts) > 1, "expected staggered maintenance start labels"


def test_integration_maintenance_raises_eue_vs_no_maintenance() -> None:
    """Planned outages remove capacity on top of forced outages, so a tight
    system's EUE with maintenance enabled must be >= the no-maintenance EUE
    at the same seed/tolerance."""
    model = _thermal_model(n_snaps=24 * 60, load_mw=150.0, gen_cap=100.0, n_gens=4)
    no_maint = run_pypsa(
        model, SCENARIO,
        _maintenance_options(maintenanceEnabled=False, tolerance=0.05, maxMembers=1500),
    )
    with_maint = run_pypsa(
        model, SCENARIO,
        _maintenance_options(maintenanceEnabled=True, tolerance=0.05, maxMembers=1500),
    )
    eue_no_maint = no_maint["convergenceSampling"]["estimate"]
    eue_with_maint = with_maint["convergenceSampling"]["estimate"]
    assert eue_with_maint >= eue_no_maint


def test_integration_maintenance_disabled_gives_null_block() -> None:
    model = _thermal_model(n_snaps=24 * 10, load_mw=95.0, gen_cap=100.0, n_gens=1)
    result = run_pypsa(model, SCENARIO, _convergence_options(maintenanceEnabled=False))
    assert result["convergenceSampling"]["maintenance"] is None
