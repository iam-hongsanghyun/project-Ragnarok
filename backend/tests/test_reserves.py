"""In-solve operating-reserve (spinning reserve) co-optimization.

Pins:
    1. Requirement met + headroom respected on every snapshot.
    2. A reserveCost > 0 makes the reserve requirement a genuine opportunity
       cost — the requirement dual is exactly reserveCost, and total system
       cost with reserve is >= the no-reserve baseline.
    3. ``providers="thermal"`` excludes a solar generator from the reserve
       pool (its r == 0 at every snapshot).
    4. Disabled config is a strict parity no-op: no ``Generator-r`` variable,
       identical dispatch/objective to a run with no reserveConfig at all.
    5. Rolling horizon: provision covers every snapshot across every window,
       not just the last one solved (the "prove the windows ran" trap —
       n.model is rebuilt per window, so provision must be read from the
       persistent n.generators_t.r, not from n.model directly).
"""
from __future__ import annotations

from typing import Any

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _two_gen_model(load_mw: float = 120.0, n_snaps: int = 2) -> dict[str, list[dict[str, Any]]]:
    """1 bus; cheap 100 MW @ EUR10 + peaker 100 MW @ EUR80; flat load."""
    snaps = [f"2025-01-01T{h:02d}:00:00" for h in range(n_snaps)]
    return {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [
            {"name": "gas", "co2_emissions": 0.4},
            {"name": "coal", "co2_emissions": 0.9},
        ],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "cheap", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0},
            {"name": "peaker", "bus": "b0", "carrier": "coal", "p_nom": 100.0, "marginal_cost": 80.0},
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": load_mw}],
        "loads-p_set": [{"snapshot": s, "load": load_mw} for s in snaps],
    }


def _solar_thermal_model(load_mw: float = 120.0, n_snaps: int = 2) -> dict[str, list[dict[str, Any]]]:
    """1 bus; solar (free, capped) + cheap gas + peaker coal; flat load."""
    snaps = [f"2025-01-01T{h:02d}:00:00" for h in range(n_snaps)]
    return {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [
            {"name": "solar"},
            {"name": "gas", "co2_emissions": 0.4},
            {"name": "coal", "co2_emissions": 0.9},
        ],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "solar1", "bus": "b0", "carrier": "solar", "p_nom": 40.0, "marginal_cost": 0.0},
            {"name": "cheap", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0},
            {"name": "peaker", "bus": "b0", "carrier": "coal", "p_nom": 100.0, "marginal_cost": 80.0},
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": load_mw}],
        "loads-p_set": [{"snapshot": s, "load": load_mw} for s in snaps],
    }


# ── 1. Requirement met + headroom respected ─────────────────────────────────


def test_reserve_requirement_met_and_headroom_respected() -> None:
    model = _two_gen_model(load_mw=120.0)
    options = {
        "reserveConfig": {
            "enabled": True,
            "requirementType": "fraction",
            "fraction": 0.1,
            "providers": "all",
            "reserveCost": 0.0,
        }
    }
    result = run_pypsa(model, SCENARIO, options)
    reserve = result["reserve"]
    assert reserve["enabled"] is True
    assert reserve["requirementType"] == "fraction"

    req_by_label = {row["label"]: row["value"] for row in reserve["requirementMwSeries"]}
    prov_by_label = {row["label"]: row["value"] for row in reserve["providedMwSeries"]}
    # fraction 0.1 * load 120 == 12 MW at every snapshot.
    for label, req in req_by_label.items():
        assert abs(req - 12.0) < 1e-6
        assert prov_by_label[label] >= req - 1e-6

    # Headroom: p_g + r_g <= p_nom_g * p_max_pu_g,t at every snapshot, for
    # every generator (dispatch + reserve provision).
    gen_dispatch = {
        row["name"]: row for row in result["generatorEnergy"]
    }
    assert set(gen_dispatch) == {"cheap", "peaker"}
    by_gen_reserve = {row["name"]: row["meanReserveMw"] for row in reserve["byGenerator"]}
    p_nom = {"cheap": 100.0, "peaker": 100.0}
    # Use the raw per-snapshot dispatch/reserve series via generatorDispatchSeries
    # and byGenerator's mean reserve (constant across snapshots in this model
    # since load and requirement are flat).
    for gen, cap in p_nom.items():
        r = by_gen_reserve.get(gen, 0.0)
        # Reconstruct dispatch from the dispatch series (flat load -> flat dispatch).
        disp_rows = [
            row["values"].get(gen, 0.0) for row in result["generatorDispatchSeries"]
        ]
        for disp in disp_rows:
            assert disp + r <= cap + 1e-6, f"{gen}: p={disp} + r={r} exceeds p_nom={cap}"


# ── 2. Reserve cost creates a genuine opportunity cost / positive price ─────


def test_reserve_cost_creates_positive_price_and_raises_system_cost() -> None:
    model = _two_gen_model(load_mw=120.0, n_snaps=1)
    reserve_cost = 3.0
    options_with_reserve = {
        "reserveConfig": {
            "enabled": True,
            "requirementType": "fraction",
            "fraction": 0.1,
            "providers": "all",
            "reserveCost": reserve_cost,
        }
    }
    options_baseline: dict[str, Any] = {}

    result_reserve = run_pypsa(model, SCENARIO, options_with_reserve)
    result_baseline = run_pypsa(model, SCENARIO, options_baseline)

    reserve = result_reserve["reserve"]
    assert reserve["enabled"] is True
    price_values = [row["value"] for row in reserve["priceSeries"]]
    assert price_values, "expected a non-empty price series for an LP solve"
    for price in price_values:
        assert price >= -1e-6
    # With reserveCost added straight into the objective, the shadow price of
    # the requirement equals reserveCost exactly (r has no other cost driver
    # in this toy network, so the LP holds r at the requirement with dual ==
    # marginal cost of relaxing it by 1 MW == reserveCost).
    assert max(price_values) > 0.0
    for price in price_values:
        assert abs(price - reserve_cost) < 1e-4

    # Total system cost with reserve (dispatch cost + reserveCost * reserve) is
    # at least the no-reserve baseline's dispatch cost — the reserve product
    # is never free once it has an explicit price.
    def _total_dispatch_cost(result: dict[str, Any]) -> float:
        return sum(row["value"] for row in result["costBreakdown"])

    baseline_cost = _total_dispatch_cost(result_baseline)
    mean_provided_mw = sum(row["value"] for row in reserve["providedMwSeries"]) / len(
        reserve["providedMwSeries"]
    )
    reserve_line_cost = reserve_cost * mean_provided_mw
    assert reserve_line_cost > 0.0
    total_cost_with_reserve = _total_dispatch_cost(result_reserve) + reserve_line_cost
    assert total_cost_with_reserve >= baseline_cost - 1e-6


# ── 3. providers="thermal" excludes solar from the reserve pool ────────────


def test_thermal_providers_excludes_solar() -> None:
    model = _solar_thermal_model(load_mw=120.0)
    options = {
        "reserveConfig": {
            "enabled": True,
            "requirementType": "fraction",
            "fraction": 0.1,
            "providers": "thermal",
            "reserveCost": 0.0,
        }
    }
    result = run_pypsa(model, SCENARIO, options)
    reserve = result["reserve"]
    assert reserve["enabled"] is True
    by_gen = {row["name"]: row["meanReserveMw"] for row in reserve["byGenerator"]}
    assert "solar1" not in by_gen
    by_carrier = {row["label"] for row in reserve["byCarrier"]}
    assert "solar" not in by_carrier


# ── 4. Disabled config is a strict no-op ────────────────────────────────────


def test_disabled_reserve_config_is_a_parity_noop() -> None:
    model = _two_gen_model(load_mw=120.0)
    result_disabled = run_pypsa(
        model, SCENARIO, {"reserveConfig": {"enabled": False, "fraction": 0.5}}
    )
    result_absent = run_pypsa(model, SCENARIO, {})

    assert result_disabled["reserve"]["enabled"] is False
    assert result_disabled["reserve"]["requirementMwSeries"] == []
    assert result_disabled["reserve"]["priceSeries"] == []

    # Dispatch/cost identical whether reserveConfig is explicitly disabled or
    # simply absent from options.
    assert result_disabled["summary"] == result_absent["summary"]
    assert result_disabled["dispatchSeries"] == result_absent["dispatchSeries"]
    assert result_disabled["costBreakdown"] == result_absent["costBreakdown"]


# ── 5. Rolling horizon: provision spans every window, not just the last ────


def test_rolling_horizon_reserve_provision_covers_every_window() -> None:
    """8 snapshots solved as 2 rolling-horizon windows of 4. n.model is rebuilt
    from scratch for each window's extra_functionality call, so a naive
    ``n.model["Generator-r"].solution`` read would only ever see the LAST
    window (snapshots 4-7) and silently zero-fill the rest. Provision must
    come from n.generators_t.r, which PyPSA persists across windows."""
    model = _two_gen_model(load_mw=120.0, n_snaps=8)
    options = {
        "reserveConfig": {
            "enabled": True,
            "requirementType": "fraction",
            "fraction": 0.1,
            "providers": "all",
            "reserveCost": 0.0,
        },
        "rollingConfig": {"enabled": True, "horizonSnapshots": 4, "overlapSnapshots": 0},
    }
    result = run_pypsa(model, SCENARIO, options)
    reserve = result["reserve"]
    assert reserve["enabled"] is True
    assert len(reserve["requirementMwSeries"]) == 8
    assert len(reserve["providedMwSeries"]) == 8
    # Every snapshot (both windows) must satisfy the requirement — including
    # the FIRST window (snapshots 0-3), which a model-only read would miss.
    for req_row, prov_row in zip(reserve["requirementMwSeries"], reserve["providedMwSeries"]):
        assert req_row["label"] == prov_row["label"]
        assert prov_row["value"] >= req_row["value"] - 1e-6, (
            f"snapshot {req_row['label']}: provided {prov_row['value']} < "
            f"required {req_row['value']} — window not solved with reserves?"
        )


# ── 6. largestUnit keys to installed capacity, consistently (review fix) ──────

def test_largest_unit_uses_installed_capacity_not_pnom_max() -> None:
    """The N-1 'largest unit' requirement must key to the largest INSTALLED unit
    (p_nom), identically in the enforced constraint and the reported series — not
    an extendable unit's p_nom_max (which balloons the requirement) or p_nom_opt
    (which diverges from what was enforced)."""
    model = {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "snapshots": [{"snapshot": "2025-01-01T00:00:00"}, {"snapshot": "2025-01-01T01:00:00"}],
        "generators": [
            {"name": "g1", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0},
            {"name": "g2", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 20.0},
            {"name": "g3", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 30.0},
            # Extendable with a large buildable ceiling — must NOT set the target.
            {"name": "flex", "bus": "b0", "carrier": "gas", "p_nom": 10.0, "p_nom_extendable": True,
             "p_nom_max": 500.0, "marginal_cost": 15.0, "capital_cost": 1000.0},
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": 60.0}],
        "loads-p_set": [{"snapshot": "2025-01-01T00:00:00", "load": 60.0},
                        {"snapshot": "2025-01-01T01:00:00", "load": 60.0}],
    }
    options = {
        "snapshotStart": 0, "snapshotEnd": 2, "snapshotWeight": 1,
        "reserveConfig": {"enabled": True, "requirementType": "largestUnit", "providers": "all", "reserveCost": 0.0},
    }
    result = run_pypsa(model, SCENARIO, options)  # must be feasible (no p_nom_max blow-up)
    reserve = result["reserve"]
    # Largest installed unit = 100 MW; requirement is that at every snapshot.
    for row in reserve["requirementMwSeries"]:
        assert abs(row["value"] - 100.0) < 1e-6, f"requirement {row['value']} != 100 (installed largest)"
    # Provision meets it, and the enforced==reported invariant holds.
    for req_row, prov_row in zip(reserve["requirementMwSeries"], reserve["providedMwSeries"]):
        assert prov_row["value"] >= req_row["value"] - 1e-6


# ── 7. reserve + stochastic is rejected with a clear error (review fix) ───────

def test_reserve_with_stochastic_is_rejected() -> None:
    import pytest
    model = _two_gen_model(load_mw=60.0)
    options = {
        "snapshotStart": 0, "snapshotEnd": 2, "snapshotWeight": 1,
        "reserveConfig": {"enabled": True, "requirementType": "fraction", "fraction": 0.1, "providers": "all"},
        "stochasticConfig": {"enabled": True, "scenarios": [
            {"name": "s1", "weight": 0.5}, {"name": "s2", "weight": 0.5},
        ]},
    }
    with pytest.raises(Exception) as exc:
        run_pypsa(model, SCENARIO, options)
    assert "reserve" in str(exc.value).lower()
