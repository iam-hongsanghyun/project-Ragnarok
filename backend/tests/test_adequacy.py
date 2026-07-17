"""A1 stochastic ensemble + A2 adequacy metrics — analytical checks."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pypsa
import pytest

from backend.pypsa.results.adequacy import (
    build_adequacy,
    compute_adequacy,
    ensemble_stats,
    generate_renewable_ensemble,
)


def test_ensemble_preserves_zeros_and_shape() -> None:
    # A solar-like base: zero at night, peak midday.
    base = np.array([0, 0, 0, 0.2, 0.6, 0.9, 0.6, 0.2, 0, 0] * 3, dtype=float)
    ens = generate_renewable_ensemble(base, n_members=100, variability=0.2, seed=1)
    assert ens.shape == (100, base.size)
    # Multiplicative noise keeps base-zero hours exactly zero (night stays dark).
    zero_cols = base == 0
    assert np.all(ens[:, zero_cols] == 0.0)
    # Never exceeds the CF cap.
    assert ens.max() <= 1.0 + 1e-9


def test_variability_knob_controls_spread() -> None:
    # A varying base so R² is well-defined (flat base → zero variance denominator).
    base = 0.5 + 0.4 * np.sin(np.linspace(0, 6 * np.pi, 72))
    base = np.clip(base, 0, 1)
    calm = generate_renewable_ensemble(base, n_members=200, variability=0.05, seed=2)
    wild = generate_renewable_ensemble(base, n_members=200, variability=0.4, seed=2)
    assert wild.std() > calm.std()
    # Higher similarity (lower variability) → higher mean R².
    assert ensemble_stats(base, calm)["meanR2"] > ensemble_stats(base, wild)["meanR2"]


def test_zero_variability_reproduces_the_base() -> None:
    base = np.array([0.1, 0.5, 0.9, 0.3])
    ens = generate_renewable_ensemble(base, n_members=10, variability=0.0, seed=3)
    for m in range(10):
        np.testing.assert_allclose(ens[m], base)


def test_ensemble_is_reproducible_with_seed() -> None:
    base = np.linspace(0.1, 0.9, 24)
    a = generate_renewable_ensemble(base, n_members=20, variability=0.2, seed=7)
    b = generate_renewable_ensemble(base, n_members=20, variability=0.2, seed=7)
    np.testing.assert_allclose(a, b)


def test_adequacy_no_shortfall_when_supply_always_covers() -> None:
    load = np.full(24, 80.0)
    available = np.full((50, 24), 100.0)  # always ≥ load
    m = compute_adequacy(available, load, np.ones(24))
    assert m["lole"] == 0.0
    assert m["eens"] == 0.0
    assert m["worstPeriods"] == []


def test_adequacy_lole_and_eens_scale_to_a_year() -> None:
    # One snapshot short in every member; 24 h window, weight 1 → scale 365×.
    load = np.array([100.0] + [50.0] * 23)
    available = np.vstack([np.array([90.0] + [100.0] * 23)] * 10)  # 10 MW short at t0, always
    m = compute_adequacy(available, load, np.ones(24))
    # LOLP at t0 = 1.0 (all members short), 0 elsewhere. Window LOLE = 1 h;
    # annual scale = 8760/24 = 365 → LOLE ≈ 365 h/yr.
    assert m["loloProbability"][0] == pytest.approx(1.0)
    assert m["lole"] == pytest.approx(365.0, rel=1e-3)
    # EENS: 10 MWh short per member per year-window × 365.
    assert m["eens"] == pytest.approx(10.0 * 365.0, rel=1e-3)
    assert m["worstPeriods"][0]["snapshot"] == 0


def test_adequacy_partial_lolp_across_members() -> None:
    load = np.full(4, 100.0)
    # Half the members short at t0.
    avail = np.vstack([np.full((5, 4), 90.0), np.full((5, 4), 110.0)])
    m = compute_adequacy(avail, load, np.ones(4), modeled_hours=4)
    assert m["loloProbability"][0] == pytest.approx(0.5)


def _tight_network(with_shedding: bool) -> pypsa.Network:
    """A deliberately capacity-short system: 100 MW flat load against 60 MW firm
    plus 50 MW wind whose CF dips to ~0.1 — shortfall is guaranteed. Optionally
    add the injected load-shedding backstop (peak-sized, time-varying
    p_max_pu = 1.0) exactly as ``add_load_shedding`` does."""
    n = pypsa.Network()
    snaps = pd.date_range("2030-01-01", periods=24, freq="h")
    n.set_snapshots(snaps)
    n.add("Bus", "b")
    n.add("Load", "L", bus="b", p_set=100.0)
    n.add("Generator", "firm", bus="b", p_nom=60.0)
    cf = np.clip(0.5 + 0.4 * np.sin(np.linspace(0, 2 * np.pi, 24)), 0.0, 1.0)
    n.add("Generator", "wind", bus="b", p_nom=50.0, p_max_pu=pd.Series(cf, index=snaps))
    if with_shedding:
        n.add("Generator", "load_shedding_b", bus="b", p_nom=100.0, marginal_cost=10000.0)
        n.generators_t.p_max_pu.loc[:, "load_shedding_b"] = 1.0
    n._objective = 0.0  # mark solved (build_adequacy gates on is_solved)
    n.generators["p_nom_opt"] = n.generators["p_nom"]  # as a real solve fills it
    return n


def test_build_adequacy_ignores_load_shedding_backstop() -> None:
    """The VOLL backstop must be excluded entirely: it carries a time-varying
    p_max_pu column, so counting it as a stochastic renewable adds ~peak-load
    fake capacity and collapses LOLE/EENS to 0 exactly when shedding is on."""
    base = build_adequacy(_tight_network(False), members=50, seed=11)
    shed = build_adequacy(_tight_network(True), members=50, seed=11)
    assert base is not None and shed is not None
    # The system is genuinely short — the backstop must not hide that.
    assert base["eens"] > 0.0
    assert base["lole"] > 0.0
    # Identical metrics with and without the backstop present.
    np.testing.assert_allclose(shed["lole"], base["lole"], rtol=1e-9, atol=0.0)
    np.testing.assert_allclose(shed["eens"], base["eens"], rtol=1e-9, atol=0.0)
    np.testing.assert_allclose(
        shed["firmCapacityMW"], base["firmCapacityMW"], rtol=1e-9, atol=0.0
    )
    np.testing.assert_allclose(
        shed["renewableCapacityMW"], base["renewableCapacityMW"], rtol=1e-9, atol=0.0
    )
