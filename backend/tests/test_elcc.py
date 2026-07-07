"""ELCC / capacity credit — pure bisection checks + integration checks.

Mirrors test_outage_mc.py's model-builder / options-builder pattern for the
integration tests, and test_adequacy.py's style for the pure numerical checks.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.results import run_pypsa
from backend.pypsa.results.elcc import _elcc_for_carrier, _lole_of, build_elcc
from backend.pypsa.results.outage_mc import sample_outage_masks

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _hourly_snapshots(n_snaps: int, start_day: int = 1) -> list[str]:
    labels = []
    day, hour = start_day, 0
    for _ in range(n_snaps):
        labels.append(f"2025-01-{day:02d}T{hour:02d}:00:00")
        hour += 1
        if hour == 24:
            hour = 0
            day += 1
    return labels


def _elcc_options(**overrides: Any) -> dict[str, Any]:
    cfg = {
        "enabled": True,
        "nMembers": 300,
        "seed": 42,
        "forcedOutageRate": 0.08,
        "mttrHours": 24.0,
    }
    cfg.update(overrides)
    return {"elccConfig": cfg}


def _thermal_plus_variable_model(
    *,
    n_snaps: int,
    load_profile: list[float],
    thermal_cap: float,
    variable_cap: float,
    variable_carrier: str,
    variable_profile: list[float],
    n_thermal: int = 2,
) -> dict[str, list[dict[str, Any]]]:
    """A 1-bus system: n_thermal identical thermal units + one variable-output
    generator of ``variable_carrier`` (solar/wind), against a load profile."""
    snaps = _hourly_snapshots(n_snaps)
    gens = [
        {"name": f"g{i}", "bus": "b0", "carrier": "gas", "p_nom": thermal_cap,
         "marginal_cost": 10.0 + i}
        for i in range(n_thermal)
    ]
    gens.append(
        {"name": "vre0", "bus": "b0", "carrier": variable_carrier, "p_nom": variable_cap,
         "marginal_cost": 0.5}
    )
    return {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": variable_carrier}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": gens,
        "generators-p_max_pu": [
            {"snapshot": s, "vre0": v} for s, v in zip(snaps, variable_profile)
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": load_profile[0]}],
        "loads-p_set": [{"snapshot": s, "load": v} for s, v in zip(snaps, load_profile)],
    }


# ── Pure bisection / LOLE-wrapper checks ─────────────────────────────────────


def test_lole_of_matches_compute_adequacy_zero_when_covered() -> None:
    load = np.full(24, 80.0)
    available = np.full((10, 24), 100.0)
    assert _lole_of(available, load, np.ones(24), modeled_hours=24.0) == 0.0


def test_elcc_perfectly_firm_resource_recovers_full_nameplate() -> None:
    """A perfectly firm resource (present at every member/snapshot, no
    outage) evaluated against a load pattern that stresses the system across
    its full capacity range should have ELCC == its own nameplate exactly:
    removing it and adding back a firm F == nameplate must, by construction,
    reproduce the baseline exactly, and no smaller F suffices (the load
    profile is built to bind the full range 0..nameplate)."""
    T = 24 * 20
    weights = np.ones(T)
    rng = np.random.default_rng(0)
    load = 90.0 + 15.0 * np.sin(np.linspace(0, 8 * np.pi, T)) + rng.normal(0.0, 2.0, T)

    for_rates = np.full(2, 0.08)
    mttr = np.full(2, 24.0)
    mask = sample_outage_masks(for_rates, mttr, weights, n_members=400, seed=5)
    other = 40.0 * mask.sum(axis=1)  # (M, T) — 2 x 40 MW thermal units under outage

    nameplate = 50.0
    target_firm = np.full((400, T), nameplate)
    baseline_available = other + target_firm
    baseline = _lole_of(baseline_available, load, weights, modeled_hours=float(T))

    available_without = other
    elcc = _elcc_for_carrier(available_without, load, weights, float(T), nameplate, baseline)
    assert elcc == pytest.approx(nameplate, rel=1e-3)


def test_elcc_zero_when_removing_carrier_never_changes_lole() -> None:
    """A resource whose removal doesn't change LOLE at all (over-built system,
    plenty of slack even without it) has ELCC exactly 0."""
    T = 240
    weights = np.ones(T)
    load = np.full(T, 50.0)
    other = np.full((100, T), 200.0)  # always far more than load, even alone
    baseline = _lole_of(other + 30.0, load, weights, modeled_hours=float(T))
    assert baseline == 0.0
    elcc = _elcc_for_carrier(other, load, weights, float(T), nameplate_mw=30.0, baseline_lole=baseline)
    assert elcc == 0.0


def test_elcc_zero_nameplate_returns_zero_without_calling_lole() -> None:
    elcc = _elcc_for_carrier(
        np.zeros((5, 4)), np.zeros(4), np.ones(4), 4.0, nameplate_mw=0.0, baseline_lole=0.0,
    )
    assert elcc == 0.0


def test_elcc_monotonic_bigger_reliable_resource_bigger_elcc_mw() -> None:
    """A bigger perfectly-firm resource (larger nameplate, same shape) must
    have a bigger absolute ELCC MW than a smaller one, holding the background
    system and load fixed."""
    T = 24 * 15
    weights = np.ones(T)
    rng = np.random.default_rng(3)
    load = 100.0 + 20.0 * np.sin(np.linspace(0, 6 * np.pi, T)) + rng.normal(0.0, 2.0, T)

    for_rates = np.full(2, 0.1)
    mttr = np.full(2, 24.0)
    mask = sample_outage_masks(for_rates, mttr, weights, n_members=400, seed=8)
    other = 45.0 * mask.sum(axis=1)

    small_nameplate, big_nameplate = 20.0, 60.0
    baseline_small = _lole_of(other + small_nameplate, load, weights, modeled_hours=float(T))
    baseline_big = _lole_of(other + big_nameplate, load, weights, modeled_hours=float(T))

    elcc_small = _elcc_for_carrier(other, load, weights, float(T), small_nameplate, baseline_small)
    elcc_big = _elcc_for_carrier(other, load, weights, float(T), big_nameplate, baseline_big)
    assert elcc_big >= elcc_small


def test_elcc_bisection_is_deterministic() -> None:
    T = 240
    weights = np.ones(T)
    rng = np.random.default_rng(4)
    load = 90.0 + rng.normal(0.0, 5.0, T)
    other = np.full((50, T), 60.0)
    baseline = _lole_of(other + 40.0, load, weights, modeled_hours=float(T))
    a = _elcc_for_carrier(other, load, weights, float(T), 40.0, baseline)
    b = _elcc_for_carrier(other, load, weights, float(T), 40.0, baseline)
    assert a == b


# ── Integration: perfectly-firm carrier (FOR=0) → ELCC% ~ 100 ──────────────


def test_integration_perfectly_firm_carrier_elcc_near_nameplate() -> None:
    """A "renewable-named" carrier (so it's a default ELCC target) with
    p_max_pu == 1 for all snapshots behaves as perfectly firm — its ELCC%
    should land close to 100%. Load swings widely (75-135 MW) so removing the
    solar block creates a shortfall across a wide capacity range — otherwise
    the thermal backdrop alone would already cover most outcomes and the test
    couldn't distinguish "perfectly firm" from "occasionally helpful"."""
    T = 24 * 20
    rng = np.random.default_rng(21)
    load_profile = list(
        np.clip(
            105.0 + 20.0 * np.sin(np.linspace(0.0, 10 * np.pi, T)) + rng.normal(0.0, 2.0, T),
            60.0, 124.0,
        )
    )
    model = _thermal_plus_variable_model(
        n_snaps=T,
        load_profile=load_profile,
        thermal_cap=45.0,
        variable_cap=40.0,
        variable_carrier="solar",  # default ELCC target (variable-renewable marker)
        variable_profile=[1.0] * T,  # flat, always-on — "perfectly firm" stand-in
        n_thermal=2,
    )
    result = run_pypsa(model, SCENARIO, _elcc_options(seed=21, nMembers=400, forcedOutageRate=0.1))
    elcc = result["elcc"]
    assert elcc is not None
    solar_row = next(r for r in elcc["byCarrier"] if r["carrier"] == "solar")
    assert solar_row["elccPct"] >= 85.0, solar_row


# ── Integration: zero-at-scarcity resource → ELCC ~ 0 ───────────────────────


def test_integration_zero_at_scarcity_gives_near_zero_elcc() -> None:
    """A variable resource that outputs ZERO exactly when the system is at
    scarcity (peak load hours) contributes nothing to reliability there —
    ELCC should be close to 0, even though its nameplate is large. The LP
    itself must stay feasible without load shedding (thermal nameplate alone
    covers the evening peak); the *post-process* forced-outage sampler is
    what creates scarcity at those hours, and solar (zero at night AND at the
    evening peak) never helps cover it."""
    T = 24 * 10
    load_profile = []
    solar_profile = []
    for t in range(T):
        hour = t % 24
        if 17 <= hour <= 21:
            load_profile.append(115.0)  # evening peak — within thermal nameplate (120 MW)
        else:
            load_profile.append(65.0)
        solar_profile.append(1.0 if 9 <= hour <= 15 else 0.0)  # midday only

    model = _thermal_plus_variable_model(
        n_snaps=T,
        load_profile=load_profile,
        thermal_cap=60.0,  # 2 x 60 = 120 MW thermal, feasible at the 115 MW evening peak
        variable_cap=80.0,
        variable_carrier="solar",
        variable_profile=solar_profile,
        n_thermal=2,
    )
    result = run_pypsa(model, SCENARIO, _elcc_options(seed=7, nMembers=400, forcedOutageRate=0.2, mttrHours=48.0))
    elcc = result["elcc"]
    assert elcc is not None
    solar_row = next(r for r in elcc["byCarrier"] if r["carrier"] == "solar")
    assert solar_row["elccPct"] <= 15.0, solar_row


# ── Integration: partially-correlated renewable → 0 < ELCC% < 100 ──────────


def test_integration_partially_correlated_renewable_gives_intermediate_elcc() -> None:
    """A wind-like resource that is UP roughly half the time, uncorrelated
    with the exact scarcity hours, should land strictly between 0 and 100%
    capacity credit."""
    T = 24 * 20
    rng = np.random.default_rng(11)
    raw_load = 90.0 + 20.0 * np.sin(np.linspace(0, 10 * np.pi, T)) + rng.normal(0.0, 3.0, T)
    wind_profile_arr = np.clip(0.5 + 0.5 * np.sin(np.linspace(0, 37 * np.pi, T)), 0.0, 1.0)
    thermal_cap, wind_cap = 50.0, 60.0
    # Clip demand to the LP's own nameplate ceiling (thermal + wind at its
    # solved availability) so the solve is feasible without load shedding —
    # the reliability *stress* this test exercises comes from the post-
    # process outage sampler removing thermal MW, not from LP infeasibility.
    nameplate_ceiling = 2 * thermal_cap + wind_cap * wind_profile_arr
    load_profile = list(np.minimum(raw_load, nameplate_ceiling - 1.0))
    wind_profile = list(wind_profile_arr)

    model = _thermal_plus_variable_model(
        n_snaps=T,
        load_profile=load_profile,
        thermal_cap=thermal_cap,
        variable_cap=wind_cap,
        variable_carrier="wind",
        variable_profile=wind_profile,
        n_thermal=2,
    )
    result = run_pypsa(model, SCENARIO, _elcc_options(seed=13, nMembers=400, forcedOutageRate=0.08))
    elcc = result["elcc"]
    assert elcc is not None
    wind_row = next(r for r in elcc["byCarrier"] if r["carrier"] == "wind")
    assert 0.0 < wind_row["elccPct"] < 100.0, wind_row


# ── Integration: determinism ────────────────────────────────────────────────


def test_integration_same_seed_identical_elcc() -> None:
    T = 24 * 10
    load_profile = [90.0 + 10.0 * ((t % 24) / 23.0) for t in range(T)]
    wind_profile = [0.3 + 0.2 * ((t % 5) / 4.0) for t in range(T)]
    model = _thermal_plus_variable_model(
        n_snaps=T, load_profile=load_profile, thermal_cap=50.0, variable_cap=40.0,
        variable_carrier="wind", variable_profile=wind_profile, n_thermal=2,
    )
    result_a = run_pypsa(model, SCENARIO, _elcc_options(seed=99))
    result_b = run_pypsa(model, SCENARIO, _elcc_options(seed=99))
    assert result_a["elcc"]["byCarrier"] == result_b["elcc"]["byCarrier"]
    assert result_a["elcc"]["baselineLoleHrs"] == result_b["elcc"]["baselineLoleHrs"]


# ── Integration: monotonicity (bigger reliable resource -> bigger ELCC MW) ──


def test_integration_bigger_firm_like_resource_has_bigger_elcc_mw() -> None:
    """Two otherwise-identical systems differing only in the nameplate of a
    near-firm (flat, high-availability) target carrier: the bigger one must
    have a bigger absolute ELCC MW (not necessarily bigger %, but bigger MW)."""
    T = 24 * 15
    load_profile = [95.0 + 20.0 * ((t % 24) / 23.0) for t in range(T)]
    flat_profile = [0.9] * T

    small_model = _thermal_plus_variable_model(
        n_snaps=T, load_profile=load_profile, thermal_cap=50.0, variable_cap=20.0,
        variable_carrier="solar", variable_profile=flat_profile, n_thermal=2,
    )
    big_model = _thermal_plus_variable_model(
        n_snaps=T, load_profile=load_profile, thermal_cap=50.0, variable_cap=60.0,
        variable_carrier="solar", variable_profile=flat_profile, n_thermal=2,
    )
    opts = _elcc_options(seed=17, nMembers=400, forcedOutageRate=0.08)
    result_small = run_pypsa(small_model, SCENARIO, opts)
    result_big = run_pypsa(big_model, SCENARIO, opts)
    small_row = next(r for r in result_small["elcc"]["byCarrier"] if r["carrier"] == "solar")
    big_row = next(r for r in result_big["elcc"]["byCarrier"] if r["carrier"] == "solar")
    assert big_row["elccMw"] >= small_row["elccMw"]


# ── Integration: disabled -> no elcc block ──────────────────────────────────


def test_integration_disabled_gives_no_elcc_block() -> None:
    T = 24 * 3
    load_profile = [80.0] * T
    wind_profile = [0.4] * T
    model = _thermal_plus_variable_model(
        n_snaps=T, load_profile=load_profile, thermal_cap=60.0, variable_cap=30.0,
        variable_carrier="wind", variable_profile=wind_profile, n_thermal=2,
    )
    result_disabled = run_pypsa(model, SCENARIO, {"elccConfig": {"enabled": False}})
    result_absent = run_pypsa(model, SCENARIO, {})
    assert result_disabled["elcc"] is None
    assert result_absent["elcc"] is None
    assert result_disabled["summary"] == result_absent["summary"]
    assert result_disabled["dispatchSeries"] == result_absent["dispatchSeries"]
    assert result_disabled["costBreakdown"] == result_absent["costBreakdown"]


def test_build_elcc_returns_none_when_config_missing_or_disabled() -> None:
    T = 4
    load_profile = [40.0] * T
    solar_profile = [0.5] * T
    model = _thermal_plus_variable_model(
        n_snaps=T, load_profile=load_profile, thermal_cap=30.0, variable_cap=20.0,
        variable_carrier="solar", variable_profile=solar_profile, n_thermal=1,
    )
    n, _ = build_network(
        model, SCENARIO, {"snapshotStart": 0, "snapshotCount": T, "snapshotWeight": 1.0},
    )
    n.optimize(solver_name="highs")
    assert build_elcc(n, {}) is None
    assert build_elcc(n, {"elccConfig": {"enabled": False}}) is None
    assert build_elcc(n, None) is None


def test_build_elcc_returns_none_when_unsolved() -> None:
    T = 4
    load_profile = [40.0] * T
    solar_profile = [0.5] * T
    model = _thermal_plus_variable_model(
        n_snaps=T, load_profile=load_profile, thermal_cap=30.0, variable_cap=20.0,
        variable_carrier="solar", variable_profile=solar_profile, n_thermal=1,
    )
    n, _ = build_network(
        model, SCENARIO, {"snapshotStart": 0, "snapshotCount": T, "snapshotWeight": 1.0},
    )
    assert build_elcc(n, _elcc_options()) is None


def test_build_elcc_returns_none_when_no_target_carrier_present() -> None:
    """An all-thermal fleet (no variable-renewable or storage carrier) has no
    default ELCC target — build_elcc must degrade to None."""
    T = 24
    snaps = _hourly_snapshots(T)
    model = {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "g0", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0},
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": 50.0}],
        "loads-p_set": [{"snapshot": s, "load": 50.0} for s in snaps],
    }
    result = run_pypsa(model, SCENARIO, _elcc_options())
    assert result["elcc"] is None


def test_elcc_result_contract_shape() -> None:
    """Direct contract check: keys, types, JSON-safety (no NaN/inf)."""
    T = 24 * 10
    load_profile = [90.0 + 10.0 * ((t % 24) / 23.0) for t in range(T)]
    wind_profile = [0.3 + 0.4 * ((t % 7) / 6.0) for t in range(T)]
    model = _thermal_plus_variable_model(
        n_snaps=T, load_profile=load_profile, thermal_cap=50.0, variable_cap=40.0,
        variable_carrier="wind", variable_profile=wind_profile, n_thermal=2,
    )
    result = run_pypsa(model, SCENARIO, _elcc_options(seed=3))
    elcc = result["elcc"]
    assert elcc["enabled"] is True
    assert isinstance(elcc["nMembers"], int)
    assert isinstance(elcc["seed"], int)
    assert isinstance(elcc["baselineLoleHrs"], float)
    assert isinstance(elcc["byCarrier"], list) and elcc["byCarrier"]
    for row in elcc["byCarrier"]:
        assert set(row) == {"carrier", "nameplateMw", "elccMw", "elccPct", "color"}
        assert 0.0 <= row["elccMw"] <= row["nameplateMw"] + 1e-6
        assert 0.0 <= row["elccPct"] <= 100.0 + 1e-6
        assert np.isfinite(row["nameplateMw"])
        assert np.isfinite(row["elccMw"])
        assert np.isfinite(row["elccPct"])
    assert np.isfinite(elcc["baselineLoleHrs"])
    assert isinstance(elcc["summary"], list) and elcc["summary"]
    for row in elcc["summary"]:
        assert set(row) == {"label", "value", "detail"}
    assert elcc["note"] is None or isinstance(elcc["note"], str)
