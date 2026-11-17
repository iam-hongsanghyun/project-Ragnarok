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


# ── 8. Fixed MW requirement, spinning rule, provider selector, unit ceiling, storage units ──
#
# One bus, load 90 MW, cheap 100 MW @ 10 and peaker 100 MW @ 80. Without reserve: cheap 90, peaker 0.
# Each case below has a closed-form dispatch, worked out in its docstring.


def _dispatch(result: dict[str, Any], gen: str) -> list[float]:
    return [float(row["values"].get(gen, 0.0)) for row in result["generatorDispatchSeries"]]


def _reserve(result: dict[str, Any]) -> dict[str, float]:
    return {row["name"]: float(row["meanReserveMw"]) for row in result["reserve"]["byGenerator"]}


def _fixed(**extra: Any) -> dict[str, Any]:
    return {"reserveConfig": {"enabled": True, "requirementType": "fixed", "requirementMw": 30.0, "providers": "all",
                              "reserveCost": 0.0, **extra}}


def test_fixed_requirement_is_the_mw_given() -> None:
    """requirementType fixed: R_t = requirementMw at every snapshot, whatever the load."""
    result = run_pypsa(_two_gen_model(load_mw=90.0), SCENARIO, _fixed())
    reserve = result["reserve"]
    assert reserve["requirementType"] == "fixed"
    assert [row["value"] for row in reserve["requirementMwSeries"]] == [30.0, 30.0]
    assert all(row["value"] >= 30.0 - 1e-6 for row in reserve["providedMwSeries"])
    # An idle peaker may hold it all: dispatch is the no-reserve one.
    assert all(abs(p - 90.0) < 1e-6 for p in _dispatch(result, "cheap"))
    assert all(abs(p) < 1e-6 for p in _dispatch(result, "peaker"))


def test_requirement_mw_adds_to_the_fraction() -> None:
    """fraction 10 % of 90 MW + 30 MW fixed = 39 MW."""
    options = {"reserveConfig": {"enabled": True, "requirementType": "fraction", "fraction": 0.1, "requirementMw": 30.0}}
    result = run_pypsa(_two_gen_model(load_mw=90.0), SCENARIO, options)
    assert all(abs(row["value"] - 39.0) < 1e-6 for row in result["reserve"]["requirementMwSeries"])


def test_spinning_rule_keeps_the_peaker_running() -> None:
    """Spinning, m = 0.5, so r <= p and p + r <= 100 for each unit; R = 30 MW.

    With the peaker at x MW: cheap = 90 - x holds min(90 - x, 10 + x), the peaker holds min(x, 100 - x) = x.
    (10 + x) + x >= 30 gives x >= 10, and the peaker is the dear unit, so x = 10: cheap 80 (20 MW reserve),
    peaker 10 (10 MW reserve). An idle peaker holds nothing.
    """
    result = run_pypsa(_two_gen_model(load_mw=90.0), SCENARIO, _fixed(spinning=True, minStableLoad=0.5))
    assert all(abs(p - 80.0) < 1e-5 for p in _dispatch(result, "cheap"))
    assert all(abs(p - 10.0) < 1e-5 for p in _dispatch(result, "peaker"))
    held = _reserve(result)
    assert abs(held["cheap"] - 20.0) < 1e-5 and abs(held["peaker"] - 10.0) < 1e-5


def test_spinning_min_load_column_overrides_the_default() -> None:
    """The peaker's own reserve_min_load_pu = 0.8 gives it r <= 0.25 p; the cheap unit keeps m = 0.5 (r <= p).

    cheap = 90 - x holds min(90 - x, 10 + x); the peaker holds 0.25 x. (10 + x) + 0.25 x >= 30 gives x >= 16.
    """
    model = _two_gen_model(load_mw=90.0)
    model["generators"][1]["reserve_min_load_pu"] = 0.8
    result = run_pypsa(model, SCENARIO, _fixed(spinning=True, minStableLoad=0.5))
    assert all(abs(p - 16.0) < 1e-5 for p in _dispatch(result, "peaker"))
    assert all(abs(p - 74.0) < 1e-5 for p in _dispatch(result, "cheap"))


def test_spinning_uses_the_status_of_a_committable_unit() -> None:
    """A committable peaker with p_min_pu 0.5 (binary status u): p >= 50 u and p + r <= 100 u.

    u = 0 leaves the cheap unit alone at 90 MW, where r <= min(90, 10) = 10 < 30: infeasible. So u = 1 and the
    peaker runs at its minimum 50 MW; cheap 40 MW holds the 30 MW.
    """
    model = _two_gen_model(load_mw=90.0)
    model["generators"][1].update({"committable": True, "p_min_pu": 0.5})
    result = run_pypsa(model, SCENARIO, _fixed(spinning=True, minStableLoad=0.5))
    assert all(abs(p - 50.0) < 1e-4 for p in _dispatch(result, "peaker"))
    assert all(abs(p - 40.0) < 1e-4 for p in _dispatch(result, "cheap"))


def test_provider_selector_names_the_units_that_hold_reserve() -> None:
    """fuel=coal: only the peaker (sheet column fuel) is in the pool; it holds all 30 MW, idle."""
    model = _two_gen_model(load_mw=90.0)
    model["generators"][0]["fuel"] = "lng"
    model["generators"][1]["fuel"] = "coal"
    result = run_pypsa(model, SCENARIO, _fixed(providerSelector="fuel=coal"))
    held = _reserve(result)
    assert set(held) == {"peaker"}
    assert abs(held["peaker"] - 30.0) < 1e-6


def test_unit_ceiling_caps_what_one_unit_holds() -> None:
    """reserve_max_pu 0.1 on the peaker: r_peaker <= 10 MW, so cheap holds 20 MW and runs at 80; peaker 10."""
    model = _two_gen_model(load_mw=90.0)
    model["generators"][1]["reserve_max_pu"] = 0.1
    result = run_pypsa(model, SCENARIO, _fixed())
    assert all(abs(p - 80.0) < 1e-5 for p in _dispatch(result, "cheap"))
    assert all(abs(p - 10.0) < 1e-5 for p in _dispatch(result, "peaker"))
    assert _reserve(result)["peaker"] <= 10.0 + 1e-6


def _with_storage(soc_mwh: float) -> dict[str, list[dict[str, Any]]]:
    """A 50 MW store that cannot charge (p_min_pu 0), so its energy is what it starts with."""
    model = _two_gen_model(load_mw=90.0)
    model["carriers"].append({"name": "phs"})
    model["storage_units"] = [{"name": "phs1", "bus": "b0", "carrier": "phs", "p_nom": 50.0, "max_hours": 4.0,
                               "state_of_charge_initial": soc_mwh, "marginal_cost": 500.0, "p_min_pu": 0.0}]
    return model


def test_storage_unit_holds_reserve_from_standstill() -> None:
    """Spinning, m = 0.5, R = 30 MW, a 50 MW store holding 100 MWh: cheap at 90 holds 10 MW, the store the other
    20 MW without discharging, so the peaker stays off (it ran at 10 MW without the store)."""
    result = run_pypsa(_with_storage(100.0), SCENARIO, _fixed(spinning=True, minStableLoad=0.5, includeStorageUnits=True))
    assert all(abs(p) < 1e-5 for p in _dispatch(result, "peaker"))
    assert all(abs(p - 90.0) < 1e-5 for p in _dispatch(result, "cheap"))
    held = _reserve(result)
    assert held["phs1"] >= 20.0 - 1e-5
    assert any(row["label"] == "phs" for row in result["reserve"]["byCarrier"])


def test_storage_reserve_is_bounded_by_stored_energy() -> None:
    """The store holds 12 MWh, cannot charge, and the reserve must last 1 h: r_phs <= 12 MW. cheap = 90 - x holds
    10 + x, the peaker x: (10 + x) + x + 12 >= 30 gives x = 4."""
    result = run_pypsa(_with_storage(12.0), SCENARIO, _fixed(spinning=True, minStableLoad=0.5, includeStorageUnits=True))
    assert _reserve(result)["phs1"] <= 12.0 + 1e-5
    assert all(abs(p - 4.0) < 1e-4 for p in _dispatch(result, "peaker"))


def test_bad_reserve_plan_is_refused() -> None:
    import pytest

    model = _two_gen_model(load_mw=90.0)
    for bad in (
        {"requirementType": "fixed"},  # fixed with no MW
        {"requirementType": "fixed", "requirementMw": -5},
        {"requirementType": "fixed", "requirementMw": 30, "spinning": True},  # spinning with no minimum stable load
        {"requirementType": "fixed", "requirementMw": 30, "spinning": True, "minStableLoad": 1.2},
        {"requirementType": "fixed", "requirementMw": 30, "providerSelector": "coal"},  # not column=value
        {"requirementType": "nonsense"},
    ):
        with pytest.raises(Exception) as exc:
            run_pypsa(model, SCENARIO, {"reserveConfig": {"enabled": True, **bad}})
        assert "reserveconfig" in str(getattr(exc.value, "detail", exc.value)).lower(), bad
