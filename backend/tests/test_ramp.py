"""In-solve, timestep-weighted ramp-rate limits.

Pins:
    1. A tight ramp limit forces smoother dispatch than the unconstrained
       baseline (peak |Δp| reduced), and never lowers total system cost below
       the baseline's (ramping is a restriction, never a relaxation).
    2. Δt-weighting: at a 4-hour snapshot weight the allowed |Δp| is 4x the
       1-hour case for the same fractional rate — a swing that is feasible at
       Δt=4h is infeasible at Δt=1h for an identical rate.
    3. ``appliesTo="thermal"`` leaves a solar generator's dispatch unbounded by
       ramp (it can jump freely between snapshots).
    4. Disabled config is a strict parity no-op vs. no rampConfig at all.
    5. Ramp + stochastic scenarios is rejected with a clear error (same
       reason reserve is guarded — the `scenario` dim breaks the constraint
       builder's snapshot-shift selection).

Also directly verifies "no double enforcement": with rampConfig enabled and
ramp_limit_up/down left unset on every generator, PyPSA's own native ramp
constraints ("Generator-p-ramp_limit_up" / "...-ramp_limit_down") never
appear in the solved model — only this module's own ramp_up_fixed /
ramp_down_fixed constraints do.

Regression (test 8): the EXTENDABLE-generator ramp path multiplies the
``Generator-p_nom`` linopy variable by a per-snapshot rate. Building that
rate as a plain, unnamed-axis ``pandas.DataFrame`` made linopy invent
``dim_0``/``dim_1`` dimensions during the pandas->xarray conversion and
raise ``force_dim_names``-related ``ValueError`` — caught by this module's
top-level ``try/except`` and silently degraded to a run note, so an
extendable generator's ramp was NEVER ACTUALLY ENFORCED even though
`enabled: True` and a non-empty ``ramp`` result came back (the post-hoc
"binding hours" diff doesn't know the constraint failed to build). Fixed by
building the rate as an explicitly-dimensioned ``xr.DataArray``
(``snapshot``, the model's generator dim) before it ever multiplies a
linopy variable.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network.ramp import apply_ramp_constraints
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
    options_baseline: dict[str, Any] = {}
    options_ramp = {
        "rampConfig": {
            "enabled": True,
            "rampLimitUp": 0.2,  # 20%/h * 100 MW = 20 MW/h allowed swing
            "rampLimitDown": 0.2,
            "appliesTo": "all",
        }
    }

    result_baseline = run_pypsa(model, SCENARIO, options_baseline)
    result_ramp = run_pypsa(model, SCENARIO, options_ramp)

    def _peak_abs_delta(result: dict[str, Any]) -> float:
        rows = result["generatorDispatchSeries"]
        values = [row["values"].get("g1", 0.0) for row in rows]
        deltas = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
        return max(deltas) if deltas else 0.0

    peak_baseline = _peak_abs_delta(result_baseline)
    peak_ramp = _peak_abs_delta(result_ramp)
    # Baseline swings the full 80 MW (20 -> 100) in one snapshot; the ramp run
    # must be held to (approximately) the 20 MW/h limit.
    assert peak_baseline > 60.0
    assert peak_ramp <= 20.0 + 1e-6
    assert peak_ramp < peak_baseline

    ramp_result = result_ramp["ramp"]
    assert ramp_result["enabled"] is True
    assert ramp_result["bindingHours"] >= 1

    def _total_dispatch_cost(result: dict[str, Any]) -> float:
        return sum(row["value"] for row in result["costBreakdown"])

    # A single generator serving the same total load under a ramp restriction
    # can only match or exceed the unconstrained baseline's cost (never below
    # it — load shedding is available as backstop but is far more expensive
    # than gas at 10/MWh, and the LP would only use it if physically forced).
    assert _total_dispatch_cost(result_ramp) >= _total_dispatch_cost(result_baseline) - 1e-6


# ── 2. Δt-weighting: 4h snapshot weight allows 4x the swing of the 1h case ──


def _single_gen_step_model(n_raw_snaps: int, high_at_raw_index: int) -> dict[str, list[dict[str, Any]]]:
    """1 bus, single 100 MW gas generator with a fast (unconstrained-by-load)
    backstop peaker removed — this model exists purely to probe ramp
    feasibility, so both generators share the SAME ramp rate (config
    default, no override) and load jumps once from 20 to 80 MW at
    ``high_at_raw_index`` before falling back to 20 MW, on an hourly raw
    snapshot grid later strided by ``snapshotWeight``."""
    snaps = [f"2025-01-01T{h:02d}:00:00" for h in range(n_raw_snaps)]
    loads = [20.0] * n_raw_snaps
    loads[high_at_raw_index] = 80.0
    return {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "g1", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0},
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": 20.0}],
        "loads-p_set": [{"snapshot": s, "load": load} for s, load in zip(snaps, loads)],
    }


def test_snapshot_weight_scales_allowed_ramp_linearly() -> None:
    """Same fractional rate, same absolute MW swing demanded by load: feasible
    at Δt=4h (allowed swing = 4 * rate * p_nom), infeasible at Δt=1h.

    ``snapshotWeight`` (the app's downsample stride) both subsamples the raw
    snapshot grid and sets each surviving snapshot's weight (hours) to the
    stride length — this is the same Δt that feeds the ramp RHS. 16 raw
    hourly rows strided by 4 yields 4 modelled snapshots at Δt=4h each; the
    load jump at raw index 4 lands on strided snapshot 1.
    """
    # p_nom=100, rate=0.2/h -> allowed swing = 20 MW at Δt=1h, 80 MW at Δt=4h.
    # The load jumps the full 20 -> 80 MW (60 MW) at one strided snapshot.
    model = _single_gen_step_model(n_raw_snaps=16, high_at_raw_index=4)
    ramp_cfg = {
        "enabled": True,
        "rampLimitUp": 0.2,
        "rampLimitDown": 0.2,
        "appliesTo": "all",
    }

    options_4h = {"rampConfig": ramp_cfg, "snapshotWeight": 4}
    result_4h = run_pypsa(model, SCENARIO, options_4h)
    rows_4h = result_4h["generatorDispatchSeries"]
    values_4h = [row["values"].get("g1", 0.0) for row in rows_4h]
    # At Δt=4h the 60 MW swing (well under the 80 MW allowance) is fully met —
    # dispatch actually reaches the load's high value with only one generator
    # and no shedding backstop, so this ALSO proves the run is feasible.
    assert max(values_4h) >= 80.0 - 1e-6

    # The identical rate/model at Δt=1h (no striding) only allows a 20 MW
    # swing per snapshot — a single generator cannot meet an instantaneous
    # 60 MW jump, so the very same configuration is infeasible.
    options_1h = {"rampConfig": ramp_cfg, "snapshotWeight": 1}
    with pytest.raises(Exception) as exc:
        run_pypsa(model, SCENARIO, options_1h)
    assert "infeasible" in str(exc.value).lower() or "solver" in str(exc.value).lower()


# ── 3. appliesTo="thermal" leaves a solar generator unconstrained ──────────


def test_thermal_applies_to_excludes_solar() -> None:
    model = _solar_thermal_model(n_snaps=4)
    options = {
        "rampConfig": {
            "enabled": True,
            "rampLimitUp": 0.05,  # tiny — would forbid solar's 50 MW swing
            "rampLimitDown": 0.05,
            "appliesTo": "thermal",
        }
    }
    result = run_pypsa(model, SCENARIO, options)
    rows = result["generatorDispatchSeries"]
    solar_values = [row["values"].get("solar1", 0.0) for row in rows]
    # Solar swings the full 0 <-> 50 MW every snapshot (p_max_pu alternates
    # 0/1) — ramp is not applied to it under "thermal".
    deltas = [abs(solar_values[i] - solar_values[i - 1]) for i in range(1, len(solar_values))]
    assert max(deltas) > 40.0

    by_carrier = {row["label"] for row in result["ramp"]["byCarrier"]}
    assert "solar" not in by_carrier


# ── 4. Disabled config is a strict parity no-op ─────────────────────────────


def test_disabled_ramp_config_is_a_parity_noop() -> None:
    model = _two_gen_swing_model(n_snaps=4, highs=(2,))
    result_disabled = run_pypsa(
        model, SCENARIO, {"rampConfig": {"enabled": False, "rampLimitUp": 0.01, "rampLimitDown": 0.01}}
    )
    result_absent = run_pypsa(model, SCENARIO, {})

    assert result_disabled["ramp"]["enabled"] is False
    assert result_disabled["ramp"]["byCarrier"] == []
    assert result_disabled["ramp"]["summary"] == []

    assert result_disabled["summary"] == result_absent["summary"]
    assert result_disabled["dispatchSeries"] == result_absent["dispatchSeries"]
    assert result_disabled["costBreakdown"] == result_absent["costBreakdown"]


# ── 5. ramp + stochastic is rejected with a clear error ────────────────────


def test_ramp_with_stochastic_is_rejected() -> None:
    model = _two_gen_swing_model(n_snaps=4, highs=(2,))
    options = {
        "rampConfig": {"enabled": True, "rampLimitUp": 0.2, "rampLimitDown": 0.2, "appliesTo": "all"},
        "stochasticConfig": {
            "enabled": True,
            "scenarios": [{"name": "s1", "weight": 0.5}, {"name": "s2", "weight": 0.5}],
        },
    }
    with pytest.raises(Exception) as exc:
        run_pypsa(model, SCENARIO, options)
    assert "ramp" in str(exc.value).lower()


# ── 6. No double enforcement with PyPSA's native ramp constraints ──────────


def test_no_double_enforcement_even_with_per_generator_override() -> None:
    """The important case: a generator WITH a native ramp_limit_up/down override
    (which the loader keeps on n.generators). strip_native_ramp_columns must cache
    it and blank the columns so PyPSA's own unweighted ramp constraint no-ops and
    only this module's Δt-weighted one is in the LP.
    """
    from backend.pypsa.network.ramp import strip_native_ramp_columns

    snaps = [f"2025-01-01T{h:02d}:00:00" for h in range(4)]
    model: dict[str, list[dict[str, Any]]] = {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            # A REAL per-generator override on the model row (the bug trigger).
            {"name": "g1", "bus": "b0", "carrier": "gas", "p_nom": 100.0,
             "marginal_cost": 10.0, "ramp_limit_up": 1.0, "ramp_limit_down": 1.0},
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": 20.0}],
        "loads-p_set": [{"snapshot": s, "load": 20.0} for s in snaps],
    }
    options = {"snapshotStart": 0, "snapshotCount": 4, "snapshotWeight": 1.0}
    n, _ = build_network(model, SCENARIO, options)
    # Precondition: the loader DID land the override on the network (this is why
    # the native constraint would otherwise fire).
    assert float(n.generators.at["g1", "ramp_limit_up"]) == 1.0

    ramp_cfg = {"enabled": True, "rampLimitUp": 0.2, "rampLimitDown": 0.2, "appliesTo": "all"}
    strip_native_ramp_columns(n)
    # The override is cached on n.meta (NOT the options dict) and the live
    # columns are blanked. ramp_cfg is left untouched (no leaked internal keys).
    assert n.meta["_ragnarok_ramp_overrides"]["up"]["g1"] == 1.0
    assert bool(n.generators["ramp_limit_up"].isna().all())
    assert "_perGenUp" not in ramp_cfg

    notes: list[str] = []

    def extra_functionality(net, snapshots):
        apply_ramp_constraints(net, ramp_cfg, snapshots, notes)

    n.optimize(solver_name="highs", extra_functionality=extra_functionality, include_objective_constant=False)

    # Iterate constraint NAMES directly (`iter(n.model.constraints)`), not the
    # `.labels` xarray join — the join aligns every constraint's coordinates
    # together and warns/outer-joins when they differ in length, which they
    # legitimately do here (this module's ramp constraints span one fewer
    # snapshot than PyPSA's own fixed-output constraints).
    constraint_names = set(iter(n.model.constraints))
    native_names = {
        "Generator-p-ramp_limit_up",
        "Generator-p-ramp_limit_down",
    }
    assert not (native_names & constraint_names), (
        f"native PyPSA ramp constraints leaked into the model: {native_names & constraint_names}"
    )
    assert "ramp_up_fixed" in constraint_names
    assert "ramp_down_fixed" in constraint_names


# ── 7. Composes with rolling horizon without raising ────────────────────────


def test_ramp_composes_with_rolling_horizon_smoke() -> None:
    model = _two_gen_swing_model(n_snaps=8, highs=(2, 6), load_low=20.0, load_high=60.0)
    options = {
        "rampConfig": {"enabled": True, "rampLimitUp": 0.3, "rampLimitDown": 0.3, "appliesTo": "all"},
        "rollingConfig": {"enabled": True, "horizonSnapshots": 4, "overlapSnapshots": 0},
    }
    result = run_pypsa(model, SCENARIO, options)
    assert result["ramp"]["enabled"] is True
    assert len(result["generatorDispatchSeries"]) == 8


# ── 8. Extendable-generator ramp path is actually enforced (regression) ────


def test_extendable_generator_ramp_is_enforced_via_capacity_variable() -> None:
    """A single p_nom_extendable generator must build enough capacity that
    ramping at the configured per-hour rate can still meet a step-change in
    load — i.e. the constraint is genuinely wired to the Generator-p_nom
    variable, not silently dropped (see module docstring regression note)."""
    n_snaps = 3
    snaps = [f"2025-01-01T{h:02d}:00:00" for h in range(n_snaps)]
    loads = [20.0, 150.0, 20.0]  # a 130 MW jump at snapshot 1
    model: dict[str, list[dict[str, Any]]] = {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {
                "name": "g1", "bus": "b0", "carrier": "gas", "p_nom": 10.0,
                "p_nom_extendable": True, "p_nom_max": 500.0,
                "marginal_cost": 10.0, "capital_cost": 5.0,
            },
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": 20.0}],
        "loads-p_set": [{"snapshot": s, "load": load} for s, load in zip(snaps, loads)],
    }
    options = {"rampConfig": {"enabled": True, "rampLimitUp": 0.5, "rampLimitDown": 0.5, "appliesTo": "all"}}

    result = run_pypsa(model, SCENARIO, options)
    # The ramp note must confirm the constraint was actually added (never a
    # "could not be added" failure note swallowed by the top-level try/except).
    ramp_notes = [n for n in result["narrative"] if "ramp" in n.lower()]
    assert any("applied" in n.lower() for n in ramp_notes), ramp_notes
    assert not any("could not be added" in n.lower() for n in ramp_notes), ramp_notes

    # Dispatch must reach the full 150 MW load — feasible only because p_nom
    # was built up enough for the 50%/h rate to cover a 130 MW jump in 1h
    # (p_nom_opt * 0.5 >= 130 => p_nom_opt >= 260).
    rows = result["generatorDispatchSeries"]
    values = [row["values"].get("g1", 0.0) for row in rows]
    assert max(values) >= 150.0 - 1e-6

    p_nom_opt = {row["name"]: row["p_nom_opt_mw"] for row in result["expansionResults"]}["g1"]
    assert p_nom_opt * 0.5 >= 130.0 - 1e-6


def test_per_generator_override_uses_dt_weighting_not_native_cap() -> None:
    """End-to-end regression for the double-enforcement bug through run_pypsa: a
    single unit with a per-generator ramp override must ramp by rate*p_nom*Δt,
    not PyPSA's native unweighted rate*p_nom. 16 raw hourly rows strided by
    snapshotWeight=4 → 4 modelled snapshots at Δt=4h; the load jumps 20->80 MW
    (60 MW) at one strided snapshot. Under the bug the native unweighted cap
    (0.5*100=50 MW) makes that 60 MW step INFEASIBLE with no other supply; with
    the Δt-weighted allowance (0.5*100*4=200 MW) run_pypsa (which strips the
    native columns before the solve) solves it and g1 reaches 80."""
    snaps = [f"2025-01-01T{h:02d}:00:00" for h in range(16)]
    loads = [80.0 if i == 4 else 20.0 for i in range(16)]
    model: dict[str, list[dict[str, Any]]] = {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "g1", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0,
             "ramp_limit_up": 0.5, "ramp_limit_down": 0.5},
        ],
        "loads": [{"name": "load", "bus": "b0"}],
        "loads-p_set": [{"snapshot": s, "load": v} for s, v in zip(snaps, loads)],
    }
    options = {
        "snapshotWeight": 4,
        "rampConfig": {"enabled": True, "rampLimitUp": 0.5, "rampLimitDown": 0.5, "appliesTo": "all"},
    }
    result = run_pypsa(model, SCENARIO, options)
    rows = result["generatorDispatchSeries"]
    assert max(row["values"].get("g1", 0.0) for row in rows) >= 80.0 - 1e-6


def test_strip_blanks_all_native_ramp_columns_including_startup() -> None:
    """Regression: strip must blank ramp_limit_start_up / ramp_limit_shut_down
    too, or PyPSA's up/down native early-return (which inspects them) fails and
    the native unweighted constraint fires for committable units on top of ours."""
    from backend.pypsa.network.ramp import strip_native_ramp_columns
    snaps = [f"2025-01-01T{h:02d}:00:00" for h in range(3)]
    model: dict[str, list[dict[str, Any]]] = {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "g1", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0,
             "committable": True, "ramp_limit_start_up": 0.5, "ramp_limit_shut_down": 0.5},
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": 20.0}],
        "loads-p_set": [{"snapshot": s, "load": 20.0} for s in snaps],
    }
    n, _ = build_network(model, SCENARIO, {"snapshotWeight": 1})
    strip_native_ramp_columns(n)
    for col in ("ramp_limit_up", "ramp_limit_down", "ramp_limit_start_up", "ramp_limit_shut_down"):
        if col in n.generators.columns:
            assert bool(n.generators[col].isna().all()), f"{col} not blanked"
