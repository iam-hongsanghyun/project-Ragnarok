"""Correlated multi-driver Monte Carlo — pure sampler + integration checks.

Mirrors test_outage_mc.py's pattern: pure numerical checks on the sampler,
then integration checks that build a small model dict, call run_pypsa, and
inspect the payload.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.stats import spearmanr

from backend.pypsa.network import build_network
from backend.pypsa.results import run_pypsa
from backend.pypsa.results.correlated_sampling import (
    build_correlated_sampling,
    sample_driver_multipliers,
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


def _mixed_model(
    *,
    n_snaps: int = 48,
    load_mw: float = 80.0,
    thermal_cap: float = 60.0,
    wind_cap: float = 60.0,
    wind_cf: float = 0.5,
) -> dict[str, list[dict[str, Any]]]:
    """A 1-bus system: one thermal unit + one wind unit vs a flat load."""
    snaps = _hourly_snapshots(n_snaps)
    wind_pmax_rows = [
        {"snapshot": s, "g_wind": wind_cf} for s in snaps
    ]
    return {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": "wind"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "g_thermal", "bus": "b0", "carrier": "gas", "p_nom": thermal_cap,
             "marginal_cost": 20.0},
            {"name": "g_wind", "bus": "b0", "carrier": "wind", "p_nom": wind_cap,
             "marginal_cost": 0.0, "p_max_pu": wind_cf},
        ],
        "generators-p_max_pu": wind_pmax_rows,
        "loads": [{"name": "load", "bus": "b0", "p_set": load_mw}],
        "loads-p_set": [{"snapshot": s, "load": load_mw} for s in snaps],
    }


def _cs_options(**overrides: Any) -> dict[str, Any]:
    cfg = {
        "enabled": True,
        "nMembers": 500,
        "seed": 42,
        "loadSensitivity": 0.15,
        "renewableSensitivity": 0.3,
        "inflowSensitivity": 0.2,
        "loadStd": 0.05,
        "renewableStd": 0.1,
        "inflowStd": 0.1,
    }
    cfg.update(overrides)
    return {"correlatedSamplingConfig": cfg}


# ── Pure sampler checks ──────────────────────────────────────────────────────


def test_sampler_is_deterministic_with_seed() -> None:
    cfg = _cs_options()["correlatedSamplingConfig"]
    a = sample_driver_multipliers(cfg, seed=7, n_members=200)
    b = sample_driver_multipliers(cfg, seed=7, n_members=200)
    for key in ("z", "load_mult", "cf_mult", "inflow_mult"):
        np.testing.assert_array_equal(a[key], b[key])


def test_sampler_different_seed_gives_different_draws() -> None:
    cfg = _cs_options()["correlatedSamplingConfig"]
    a = sample_driver_multipliers(cfg, seed=1, n_members=200)
    b = sample_driver_multipliers(cfg, seed=2, n_members=200)
    assert not np.array_equal(a["z"], b["z"])
    assert not np.array_equal(a["load_mult"], b["load_mult"])
    assert not np.array_equal(a["cf_mult"], b["cf_mult"])


def test_sampler_zero_members_returns_empty_arrays() -> None:
    cfg = _cs_options()["correlatedSamplingConfig"]
    result = sample_driver_multipliers(cfg, seed=1, n_members=0)
    for key in ("z", "load_mult", "cf_mult", "inflow_mult"):
        assert result[key].shape == (0,)


def test_sampler_multipliers_centered_near_one_on_average() -> None:
    """With zero-mean z and idiosyncratic noise, the population mean of each
    multiplier should sit close to 1 (no systematic bias from the one-factor
    construction alone), modulo the one-sided clip on cf/inflow."""
    cfg = _cs_options(nMembers=20000)["correlatedSamplingConfig"]
    result = sample_driver_multipliers(cfg, seed=3, n_members=20000)
    assert abs(result["load_mult"].mean() - 1.0) < 0.02
    # cf/inflow are clipped at 0 but with these modest sensitivities/stds the
    # clip rarely binds, so the mean should still be close to 1.
    assert abs(result["cf_mult"].mean() - 1.0) < 0.05
    assert abs(result["inflow_mult"].mean() - 1.0) < 0.05


def test_sampler_renewable_and_inflow_never_negative() -> None:
    cfg = _cs_options(renewableSensitivity=2.0, renewableStd=2.0,
                       inflowSensitivity=2.0, inflowStd=2.0)["correlatedSamplingConfig"]
    result = sample_driver_multipliers(cfg, seed=5, n_members=5000)
    assert (result["cf_mult"] >= 0.0).all()
    assert (result["inflow_mult"] >= 0.0).all()


# ── CORRELATION: the whole point ────────────────────────────────────────────


def test_correlation_high_load_multiplier_coincides_with_low_renewable_cf() -> None:
    """With meaningful sensitivities, members drawing a high load multiplier
    should tend to draw a LOW renewable CF multiplier — the shared stress
    factor z is what correlates them. Assert a clearly negative Spearman rank
    correlation across members (not just "not positive")."""
    cfg = _cs_options(
        nMembers=5000, loadSensitivity=0.3, renewableSensitivity=0.5,
        loadStd=0.02, renewableStd=0.02,
    )["correlatedSamplingConfig"]
    result = sample_driver_multipliers(cfg, seed=11, n_members=5000)
    rho, pvalue = spearmanr(result["load_mult"], result["cf_mult"])
    assert rho < -0.5, f"expected strongly negative rank correlation, got {rho}"
    assert pvalue < 1e-6

    # Same story for hydro inflow.
    rho_inflow, _ = spearmanr(result["load_mult"], result["inflow_mult"])
    assert rho_inflow < -0.3


def test_correlation_absent_when_sensitivities_are_zero() -> None:
    """Sanity check on the mechanism: with sensitivities set to zero, load and
    renewable multipliers are driven purely by independent idiosyncratic
    noise and should show ~no rank correlation."""
    cfg = _cs_options(
        nMembers=5000, loadSensitivity=0.0, renewableSensitivity=0.0,
        loadStd=0.1, renewableStd=0.1,
    )["correlatedSamplingConfig"]
    result = sample_driver_multipliers(cfg, seed=13, n_members=5000)
    rho, _ = spearmanr(result["load_mult"], result["cf_mult"])
    assert abs(rho) < 0.05


# ── Integration: determinism ─────────────────────────────────────────────────


def test_integration_same_seed_identical_distribution() -> None:
    model = _mixed_model()
    result_a = run_pypsa(model, SCENARIO, _cs_options(seed=11))
    result_b = run_pypsa(model, SCENARIO, _cs_options(seed=11))
    cs_a, cs_b = result_a["correlatedSampling"], result_b["correlatedSampling"]
    assert cs_a["loleDistribution"] == cs_b["loleDistribution"]
    assert cs_a["eueDistribution"] == cs_b["eueDistribution"]
    assert cs_a["driverSummary"] == cs_b["driverSummary"]


def test_integration_different_seed_gives_different_distribution() -> None:
    model = _mixed_model(n_snaps=24 * 5, load_mw=95.0, thermal_cap=90.0, wind_cap=60.0)
    result_a = run_pypsa(model, SCENARIO, _cs_options(seed=1))
    result_b = run_pypsa(model, SCENARIO, _cs_options(seed=2))
    cs_a, cs_b = result_a["correlatedSampling"], result_b["correlatedSampling"]
    assert cs_a["eueHistogram"] != cs_b["eueHistogram"] or cs_a["eueDistribution"] != cs_b["eueDistribution"]


# ── Integration: higher stress sensitivities -> higher LOLE/EUE tail ───────


def test_integration_higher_sensitivities_raise_p95_on_tight_system() -> None:
    """A tight system (thermal + wind barely covering load) should show a
    rising P95 LOLE/EUE tail as stress sensitivities increase — more extreme
    coincident high-load/low-wind members."""
    model = _mixed_model(
        n_snaps=24 * 10, load_mw=95.0, thermal_cap=90.0, wind_cap=60.0, wind_cf=0.6,
    )
    results = {}
    for sens in (0.02, 0.2, 0.45):
        result = run_pypsa(
            model, SCENARIO,
            _cs_options(seed=5, nMembers=800, loadSensitivity=sens,
                        renewableSensitivity=sens * 1.5, loadStd=0.03, renewableStd=0.03),
        )
        results[sens] = result["correlatedSampling"]

    p95_lole = [results[s]["loleDistribution"]["p95"] for s in (0.02, 0.2, 0.45)]
    p95_eue = [results[s]["eueDistribution"]["p95"] for s in (0.02, 0.2, 0.45)]
    assert p95_lole[0] <= p95_lole[1] <= p95_lole[2]
    assert p95_eue[0] <= p95_eue[1] <= p95_eue[2]
    assert p95_eue[2] > p95_eue[0]


# ── Integration: distribution ordering ──────────────────────────────────────


def test_integration_distribution_ordering_p95_ge_p50_max_ge_p95() -> None:
    model = _mixed_model(n_snaps=24 * 7, load_mw=95.0, thermal_cap=90.0, wind_cap=60.0)
    result = run_pypsa(model, SCENARIO, _cs_options(seed=9, nMembers=600))
    cs = result["correlatedSampling"]
    for dist_key in ("loleDistribution", "eueDistribution"):
        dist = cs[dist_key]
        assert dist["p95"] >= dist["p50"]
        assert dist["max"] >= dist["p95"]
        assert dist["mean"] >= 0.0


def test_integration_driver_summary_and_histogram_present() -> None:
    model = _mixed_model(n_snaps=24 * 5, load_mw=95.0, thermal_cap=90.0, wind_cap=60.0)
    result = run_pypsa(model, SCENARIO, _cs_options(seed=9, nMembers=400))
    cs = result["correlatedSampling"]
    drivers = {row["driver"] for row in cs["driverSummary"]}
    assert drivers == {"Demand", "Renewable CF", "Hydro inflow"}
    assert cs["eueHistogram"], "expected a non-empty EUE histogram"
    total_count = sum(row["count"] for row in cs["eueHistogram"])
    assert total_count == 400
    assert cs["summary"], "expected a non-empty summary block"


def test_direct_build_correlated_sampling_matches_run_pypsa() -> None:
    model = _mixed_model(n_snaps=24 * 5, load_mw=90.0, thermal_cap=60.0, wind_cap=60.0)
    n, _ = build_network(
        model, SCENARIO,
        {"snapshotStart": 0, "snapshotCount": 24 * 5, "snapshotWeight": 1.0},
    )
    n.optimize(solver_name="highs")
    options = _cs_options(seed=17, nMembers=300)
    cs = build_correlated_sampling(n, options)
    assert cs is not None
    assert cs["nMembers"] == 300
    assert cs["seed"] == 17
    assert cs["loleDistribution"]["p95"] >= cs["loleDistribution"]["p50"]


# ── Integration: disabled -> no block ───────────────────────────────────────


def test_integration_disabled_gives_no_correlated_sampling_block() -> None:
    model = _mixed_model()
    result_disabled = run_pypsa(model, SCENARIO, {"correlatedSamplingConfig": {"enabled": False}})
    result_absent = run_pypsa(model, SCENARIO, {})

    assert result_disabled["correlatedSampling"] is None
    assert result_absent["correlatedSampling"] is None
    assert result_disabled["summary"] == result_absent["summary"]
    assert result_disabled["dispatchSeries"] == result_absent["dispatchSeries"]
    assert result_disabled["costBreakdown"] == result_absent["costBreakdown"]


def test_build_correlated_sampling_returns_none_when_config_missing_or_disabled() -> None:
    n, _ = build_network(
        _mixed_model(n_snaps=4), SCENARIO,
        {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0},
    )
    n.optimize(solver_name="highs")
    assert build_correlated_sampling(n, {}) is None
    assert build_correlated_sampling(n, {"correlatedSamplingConfig": {"enabled": False}}) is None
    assert build_correlated_sampling(n, None) is None


def test_build_correlated_sampling_returns_none_when_unsolved() -> None:
    n, _ = build_network(
        _mixed_model(n_snaps=4), SCENARIO,
        {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0},
    )
    assert build_correlated_sampling(n, _cs_options()) is None


def test_build_correlated_sampling_returns_none_with_no_loads_or_snapshots() -> None:
    """No-load / no-snapshot guard, mirroring build_outage_mc / build_adequacy."""
    model = _mixed_model(n_snaps=4)
    model["loads"] = []
    model["loads-p_set"] = []
    n, _ = build_network(
        model, SCENARIO, {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0},
    )
    n.optimize(solver_name="highs")
    assert build_correlated_sampling(n, _cs_options()) is None
