"""Thermal forced-outage Monte Carlo — pure sampler + integration checks.

Mirrors test_reserves.py's model-builder pattern for the integration tests
(build a small model dict, call run_pypsa, inspect the payload) and
test_adequacy.py's style for the pure numerical checks.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.results import run_pypsa
from backend.pypsa.results.outage_mc import (
    _distribution,
    _per_member_metrics,
    build_outage_mc,
    sample_outage_masks,
)

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


def _outage_options(**overrides: Any) -> dict[str, Any]:
    cfg = {
        "enabled": True,
        "nMembers": 300,
        "seed": 42,
        "forcedOutageRate": 0.1,
        "mttrHours": 24.0,
    }
    cfg.update(overrides)
    return {"outageMcConfig": cfg}


# ── Pure sampler checks ──────────────────────────────────────────────────────


def test_sampler_is_deterministic_with_seed() -> None:
    for_rates = np.array([0.1, 0.2])
    mttr = np.array([24.0, 48.0])
    weights = np.ones(200)
    a = sample_outage_masks(for_rates, mttr, weights, n_members=100, seed=7)
    b = sample_outage_masks(for_rates, mttr, weights, n_members=100, seed=7)
    np.testing.assert_array_equal(a, b)


def test_sampler_different_seed_gives_different_draws_similar_means() -> None:
    for_rates = np.array([0.1])
    mttr = np.array([24.0])
    weights = np.ones(2000)
    a = sample_outage_masks(for_rates, mttr, weights, n_members=200, seed=1)
    b = sample_outage_masks(for_rates, mttr, weights, n_members=200, seed=2)
    assert not np.array_equal(a, b)
    # Empirical FOR (fraction of time down) should land close to the
    # configured rate for both, and be similar to each other.
    for_a = 1.0 - a.mean()
    for_b = 1.0 - b.mean()
    assert abs(for_a - 0.1) < 0.02
    assert abs(for_b - 0.1) < 0.02
    assert abs(for_a - for_b) < 0.02


def test_sampler_empirical_for_matches_configured_rate() -> None:
    """Long-run down-fraction of the chain should converge to the configured
    FOR — the stationary-distribution identity the transition probabilities
    were derived from."""
    for_rates = np.array([0.05, 0.15, 0.3])
    mttr = np.array([48.0, 12.0, 6.0])
    weights = np.ones(5000)
    mask = sample_outage_masks(for_rates, mttr, weights, n_members=40, seed=3)
    empirical_for = 1.0 - mask.mean(axis=(0, 2))
    np.testing.assert_allclose(empirical_for, for_rates, atol=0.02)


def test_sampler_high_for_stays_at_configured_rate_not_half() -> None:
    """High FOR (>=0.5) with a large Δt/MTTR must still converge to the configured
    FOR, not drift toward 0.5 — the p_fail-clip regression. Δt=48h, MTTR=6h makes
    the raw p_fail exceed 1, so both rates must be scaled to preserve stationary FOR."""
    for_rates = np.array([0.7, 0.9])
    mttr = np.array([6.0, 6.0])
    weights = np.full(5000, 48.0)  # Δt/MTTR = 8 → raw p_fail >> 1
    mask = sample_outage_masks(for_rates, mttr, weights, n_members=40, seed=7)
    empirical_for = 1.0 - mask.mean(axis=(0, 2))
    np.testing.assert_allclose(empirical_for, for_rates, atol=0.03)


def test_sampler_zero_members_or_generators_returns_all_up() -> None:
    weights = np.ones(10)
    mask_no_gens = sample_outage_masks(np.array([]), np.array([]), weights, n_members=5, seed=1)
    assert mask_no_gens.shape == (5, 0, 10)
    mask_no_members = sample_outage_masks(np.array([0.1]), np.array([24.0]), weights, n_members=0, seed=1)
    assert mask_no_members.shape == (0, 1, 10)


# ── Pure per-member metric checks ────────────────────────────────────────────


def test_per_member_metrics_zero_when_always_covered() -> None:
    load = np.full(24, 80.0)
    available = np.full((10, 24), 100.0)
    lole, eue = _per_member_metrics(available, load, np.ones(24), annual_scale=365.0)
    np.testing.assert_allclose(lole, 0.0)
    np.testing.assert_allclose(eue, 0.0)


def test_distribution_ordering_p95_ge_p50_max_ge_p95() -> None:
    rng = np.random.default_rng(0)
    values = rng.exponential(scale=10.0, size=500)
    dist = _distribution(values)
    assert dist["p95"] >= dist["p50"]
    assert dist["max"] >= dist["p95"]
    assert dist["mean"] >= 0.0


# ── Integration: determinism ─────────────────────────────────────────────────


def test_integration_same_seed_identical_distribution() -> None:
    model = _thermal_model()
    options_a = _outage_options(seed=11)
    options_b = _outage_options(seed=11)
    result_a = run_pypsa(model, SCENARIO, options_a)
    result_b = run_pypsa(model, SCENARIO, options_b)
    assert result_a["outageMc"]["loleDistribution"] == result_b["outageMc"]["loleDistribution"]
    assert result_a["outageMc"]["eueDistribution"] == result_b["outageMc"]["eueDistribution"]
    assert result_a["outageMc"]["lolpSeries"] == result_b["outageMc"]["lolpSeries"]


def test_integration_different_seed_differs_but_similar_mean() -> None:
    model = _thermal_model(n_snaps=24 * 10, load_mw=95.0, gen_cap=100.0, n_gens=1)
    result_a = run_pypsa(model, SCENARIO, _outage_options(seed=1, nMembers=400))
    result_b = run_pypsa(model, SCENARIO, _outage_options(seed=2, nMembers=400))
    mc_a, mc_b = result_a["outageMc"], result_b["outageMc"]
    assert mc_a["lolpSeries"] != mc_b["lolpSeries"]
    # Means should be in the same ballpark (both drawing from the same FOR/MTTR).
    mean_a = mc_a["eueDistribution"]["mean"]
    mean_b = mc_b["eueDistribution"]["mean"]
    if mean_a > 0 or mean_b > 0:
        assert abs(mean_a - mean_b) < 0.5 * max(mean_a, mean_b, 1.0) + 500.0


# ── Integration: EFOR monotonicity ───────────────────────────────────────────


def test_integration_higher_efor_raises_lole_and_eue() -> None:
    """A tight system (load close to capacity) should show rising unserved
    energy as the forced-outage rate rises."""
    model = _thermal_model(n_snaps=24 * 14, load_mw=95.0, gen_cap=100.0, n_gens=1)
    results = {}
    for for_rate in (0.02, 0.1, 0.25):
        result = run_pypsa(
            model, SCENARIO,
            _outage_options(seed=5, nMembers=500, forcedOutageRate=for_rate),
        )
        results[for_rate] = result["outageMc"]

    lole_means = [results[f]["loleDistribution"]["mean"] for f in (0.02, 0.1, 0.25)]
    eue_means = [results[f]["eueDistribution"]["mean"] for f in (0.02, 0.1, 0.25)]
    assert lole_means[0] <= lole_means[1] <= lole_means[2]
    assert eue_means[0] <= eue_means[1] <= eue_means[2]
    # The gap between the lowest and highest FOR must be meaningfully positive
    # (not just noise) given this is a tight (load 95 / capacity 100) system.
    assert eue_means[2] > eue_means[0]


# ── Integration: overbuilt system → ~0 LOLE sanity floor ────────────────────


def test_integration_overbuilt_system_near_zero_lole() -> None:
    """Generous reserve margin (3 x 100 MW vs 50 MW load — two independent
    units must fail simultaneously before there's any shortfall) with a
    modest FOR should show ~0 LOLE even with outages sampled."""
    model = _thermal_model(n_snaps=24 * 7, load_mw=50.0, gen_cap=100.0, n_gens=3)
    result = run_pypsa(model, SCENARIO, _outage_options(seed=3, nMembers=500, forcedOutageRate=0.05))
    mc = result["outageMc"]
    assert mc["loleDistribution"]["p50"] == 0.0
    assert mc["loleDistribution"]["mean"] < 5.0
    assert mc["eueDistribution"]["p50"] == 0.0


# ── Integration: per-member distribution shape + consistency ───────────────


def test_integration_distribution_shape_and_aggregate_consistency() -> None:
    model = _thermal_model(n_snaps=24 * 10, load_mw=95.0, gen_cap=100.0, n_gens=1)
    n, _ = build_network(
        model, SCENARIO,
        {"snapshotStart": 0, "snapshotCount": 24 * 10, "snapshotWeight": 1.0},
    )
    n.optimize(solver_name="highs")
    options = _outage_options(seed=9, nMembers=500, forcedOutageRate=0.15)
    mc = build_outage_mc(n, options)
    assert mc is not None
    lole = mc["loleDistribution"]
    eue = mc["eueDistribution"]
    assert lole["p95"] >= lole["p50"]
    assert lole["max"] >= lole["p95"]
    assert eue["p95"] >= eue["p50"]
    assert eue["max"] >= eue["p95"]

    # The per-member mean must equal the aggregate LOLE/EENS from
    # compute_adequacy (both average shortfall-hours/energy across the exact
    # same M members drawn by the exact same sampler with the same seed) —
    # recomputed here independently of build_outage_mc's internals.
    weights = n.snapshot_weightings["generators"].reindex(n.snapshots).fillna(1.0).to_numpy()
    load = n.get_switchable_as_dense("Load", "p_set").sum(axis=1).to_numpy()
    for_rates = np.full(1, 0.15)
    mttr = np.full(1, 24.0)
    mask = sample_outage_masks(for_rates, mttr, weights, n_members=500, seed=9)
    gen_cap = float(n.generators.at["g0", "p_nom"])
    pmax = n.get_switchable_as_dense("Generator", "p_max_pu")["g0"].to_numpy()
    available = gen_cap * pmax[None, :] * mask[:, 0, :]
    from backend.pypsa.results.adequacy import compute_adequacy

    aggregate = compute_adequacy(available, load, weights, modeled_hours=float(weights.sum()))
    # Both sides are independently rounded to 3 decimals (_distribution and
    # compute_adequacy round separately) — allow for that rounding, not just
    # float noise.
    assert lole["mean"] == pytest.approx(aggregate["lole"], abs=2e-3, rel=1e-5)
    assert eue["mean"] == pytest.approx(aggregate["eens"], abs=2e-2, rel=1e-5)


def test_integration_by_carrier_and_histogram_present_when_shortfall() -> None:
    model = _thermal_model(n_snaps=24 * 10, load_mw=98.0, gen_cap=100.0, n_gens=1)
    result = run_pypsa(model, SCENARIO, _outage_options(seed=13, nMembers=500, forcedOutageRate=0.2))
    mc = result["outageMc"]
    assert mc["eueDistribution"]["mean"] > 0.0
    assert mc["byCarrierLostLoad"], "expected a non-empty per-carrier lost-load breakdown"
    assert mc["byCarrierLostLoad"][0]["label"] == "gas"
    assert mc["byCarrierLostLoad"][0]["value"] > 0.0
    assert "color" in mc["byCarrierLostLoad"][0]
    assert mc["eueHistogram"], "expected a non-empty EUE histogram"
    total_count = sum(row["count"] for row in mc["eueHistogram"])
    assert total_count == 500


# ── Integration: disabled → no outageMc block, run unchanged ───────────────


def test_integration_disabled_gives_no_outage_mc_block() -> None:
    model = _thermal_model()
    result_disabled = run_pypsa(model, SCENARIO, {"outageMcConfig": {"enabled": False}})
    result_absent = run_pypsa(model, SCENARIO, {})

    assert result_disabled["outageMc"] is None
    assert result_absent["outageMc"] is None
    # Dispatch/cost identical whether outageMcConfig is explicitly disabled or
    # simply absent from options (strict parity no-op).
    assert result_disabled["summary"] == result_absent["summary"]
    assert result_disabled["dispatchSeries"] == result_absent["dispatchSeries"]
    assert result_disabled["costBreakdown"] == result_absent["costBreakdown"]


def test_integration_no_thermal_generators_returns_none() -> None:
    """An all-renewable (solar) fleet has nothing subject to forced outage —
    build_outage_mc must degrade to None rather than fabricate a result."""
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
    result = run_pypsa(model, SCENARIO, _outage_options())
    assert result["outageMc"] is None


def test_build_outage_mc_returns_none_when_config_missing_or_disabled() -> None:
    """Direct unit check of the thin assembler against a solved network: no
    config, and an explicit enabled=False, both short-circuit to None."""
    n, _ = build_network(
        _thermal_model(n_snaps=4), SCENARIO,
        {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0},
    )
    n.optimize(solver_name="highs")
    assert build_outage_mc(n, {}) is None
    assert build_outage_mc(n, {"outageMcConfig": {"enabled": False}}) is None
    assert build_outage_mc(n, None) is None


def test_build_outage_mc_returns_none_when_unsolved() -> None:
    """A network that was never optimize()'d must not be sampled (is_solved
    guard) — build_outage_mc degrades to None rather than reading garbage
    dispatch/availability off an un-optimized network."""
    n, _ = build_network(
        _thermal_model(n_snaps=4), SCENARIO,
        {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0},
    )
    assert build_outage_mc(n, _outage_options()) is None
