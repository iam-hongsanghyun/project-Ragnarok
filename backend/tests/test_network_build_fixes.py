"""Build/solve fixes from the 2026-10-27 review (RS1-RS4, RS6, RB9).

Each test pins an analytical result or an exact contract; tolerances are explicit.
"""
from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi import HTTPException

from backend.pypsa.network import build_network
from backend.pypsa.network.constraint_dsl import apply_dsl_constraints
from backend.pypsa.network.custom_constraints import apply_custom_constraints

logging.disable(logging.WARNING)


def _snaps(n: int) -> list[dict[str, str]]:
    return [{"snapshot": f"2025-01-01 {h:02d}:00"} for h in range(n)]


def _dispatch_model(hours: int = 8) -> dict[str, Any]:
    return {
        "snapshots": _snaps(hours),
        "carriers": [{"name": "gas", "co2_emissions": 1.0}, {"name": "dear"}],
        "buses": [{"name": "b"}],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "generators": [
            {"name": "g", "bus": "b", "carrier": "gas", "p_nom": 200, "marginal_cost": 10},
            {"name": "d", "bus": "b", "carrier": "dear", "p_nom": 200, "marginal_cost": 100},
        ],
    }


# ── RS1: capex pro-rated to the modelled window in the LP ────────────────────


def test_overnight_cost_is_scaled_to_the_window_by_pypsa_so_expansion_does_not_depend_on_length() -> None:
    """Analytical. Overnight 5e6 over 10 y at r = 0 is 500 000 /MW/yr; building saves (100 - 10) /MWh.
    PyPSA scales an overnight_cost by n.nyears, so over H hours the capex is 500 000·H/8760 /MW, which is
    below 90·H for every H: 100 MW is built for ANY window length. Ragnarok does none of that scaling."""
    m = _dispatch_model(24)
    m["generators"] = [
        {"name": "new", "bus": "b", "carrier": "gas", "p_nom": 0, "p_nom_extendable": True,
         "overnight_cost": 5_000_000, "discount_rate": 0.0, "lifetime": 10, "marginal_cost": 10},
        {"name": "peaker", "bus": "b", "carrier": "dear", "p_nom": 200, "marginal_cost": 100},
    ]
    n, notes = build_network(m, {}, {})
    assert "ragnarok_capex_window_scale" not in n.meta
    assert float(n.nyears) == pytest.approx(24.0 / 8760.0, rel=1e-12)
    assert float(n.components.generators.capital_cost["new"]) == pytest.approx(500_000 * 24.0 / 8760.0, rel=1e-9)
    assert not any("CAPEX" in x for x in notes)
    n.optimize(solver_name="highs")
    assert n.generators.at["new", "p_nom_opt"] == pytest.approx(100.0, abs=1e-6)


def test_no_window_scale_is_recorded_and_capital_cost_stays_raw() -> None:
    m = _dispatch_model(4)
    m["generators"][0].update(p_nom_extendable=True, capital_cost=1000, lifetime=10)
    n, _ = build_network(m, {"discountRate": 0.05}, {})
    assert "ragnarok_capex_window_scale" not in n.meta
    assert float(n.generators.at["g", "capital_cost"]) == 1000


# ── RS2: DSL / spec constraints apportioned like the structured path ─────────


def _rolling(m: dict[str, Any], hook, horizon: int, overlap: int):
    n, _ = build_network(
        m, {}, {"rollingConfig": {"enabled": True, "horizonSnapshots": horizon, "overlapSnapshots": overlap}}
    )
    n.optimize.optimize_with_rolling_horizon(
        horizon=horizon, overlap=overlap, solver_name="highs", extra_functionality=hook
    )
    return n


def test_dsl_budget_is_apportioned_across_rolling_windows() -> None:
    """Whole-run cap 200 MWh on gas, demand 800 MWh, gas cheaper: exactly 200 MWh.
    Unapportioned, each of the 4 windows spent the full 200 -> 800 MWh."""
    notes: list[str] = []
    n = _rolling(
        _dispatch_model(8),
        lambda nn, sns: apply_dsl_constraints(nn, "gen(gas) <= 200", {"gas": 1.0}, notes, sns),
        horizon=2, overlap=0,
    )
    assert float(n.generators_t.p["g"].sum()) == pytest.approx(200.0, abs=1e-6)


def test_structured_and_dsl_budgets_never_exceed_the_cap_with_overlap() -> None:
    """With overlap each window commits only horizon - overlap rows, so the
    per-window shares sum to exactly 1 and the whole-run cap holds."""
    for kind in ("structured", "dsl"):
        notes: list[str] = []

        def hook(nn, sns, kind=kind):
            if kind == "structured":
                apply_custom_constraints(
                    nn, [{"enabled": True, "metric": "carrier_max_gen", "carrier": "gas", "value": 200}],
                    {"gas": 1.0}, notes, sns,
                )
            else:
                apply_dsl_constraints(nn, "gen(gas) <= 200", {"gas": 1.0}, notes, sns)

        n = _rolling(_dispatch_model(8), hook, horizon=4, overlap=2)
        assert float(n.generators_t.p["g"].sum()) <= 200.0 + 1e-6, kind


def test_window_fraction_counts_only_committed_rows() -> None:
    from backend.pypsa.network.custom_constraints import build_model_context

    n, _ = build_network(
        _dispatch_model(8), {}, {"rollingConfig": {"enabled": True, "horizonSnapshots": 4, "overlapSnapshots": 2}}
    )
    assert n.meta["ragnarok_rolling_step"] == 2
    seen: list[float] = []

    def hook(nn, sns):
        seen.append(build_model_context(nn, {"gas": 1.0}, sns).window_fraction)

    n.optimize.optimize_with_rolling_horizon(horizon=4, overlap=2, solver_name="highs", extra_functionality=hook)
    # windows start at 0, 2, 4, 6: each commits 2 of 8 rows
    assert seen == pytest.approx([0.25] * 4)


def test_dsl_capacity_constraint_is_not_apportioned() -> None:
    """Capacity (MW) is a stock: window_fraction must not scale it."""
    m = _dispatch_model(8)
    m["generators"][0].update(p_nom=0, p_nom_extendable=True, capital_cost=0)
    notes: list[str] = []
    n = _rolling(
        m, lambda nn, sns: apply_dsl_constraints(nn, "cap(gas) <= 150", {"gas": 1.0}, notes, sns),
        horizon=4, overlap=0,
    )
    assert float(n.generators_t.p["g"].max()) <= 150.0 + 1e-6


# ── RS2/RS6: constraint compile failures stop the run ────────────────────────


def test_dsl_parse_error_fails_the_run_with_400() -> None:
    n, _ = build_network(_dispatch_model(4), {}, {})
    n.optimize.create_model()
    with pytest.raises(HTTPException) as exc:
        apply_dsl_constraints(n, "gen(gas) <=", {"gas": 1.0}, [], None)
    assert exc.value.status_code == 400 and "could not be compiled" in exc.value.detail


def test_selector_matching_nothing_is_still_a_note_not_a_failure() -> None:
    n, _ = build_network(_dispatch_model(4), {}, {})
    n.optimize.create_model()
    notes: list[str] = []
    apply_dsl_constraints(n, "gen(nonexistent) <= 5", {"gas": 1.0}, notes, None)
    assert any("could not be added" in x for x in notes)


def test_structured_constraint_failure_fails_the_run() -> None:
    n, _ = build_network(_dispatch_model(4), {}, {})
    n.optimize.create_model()
    with pytest.raises(HTTPException) as exc:
        # a non-numeric value cannot be compiled
        apply_custom_constraints(n, [{"enabled": True, "metric": "carrier_max_gen", "carrier": "gas",
                                      "value": "abc"}], {"gas": 1.0}, [], None)
    assert exc.value.status_code == 400


def test_stochastic_with_constraints_is_a_clear_400() -> None:
    options = {"stochasticConfig": {"enabled": True, "scenarios": [
        {"name": "a", "weight": 0.5, "overrides": []}, {"name": "b", "weight": 0.5, "overrides": []}]}}
    with pytest.raises(HTTPException) as exc:
        build_network(_dispatch_model(4), {"customDsl": "gen(gas) <= 5"}, options)
    assert exc.value.status_code == 400 and "Stochastic" in exc.value.detail


# ── RS3: series gaps, timezone suffixes ──────────────────────────────────────


def _solar_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "snapshots": _snaps(4),
        "carriers": [{"name": "solar"}, {"name": "gas"}],
        "buses": [{"name": "b"}],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "generators": [
            {"name": "s", "bus": "b", "carrier": "solar", "p_nom": 200, "marginal_cost": 0},
            {"name": "g", "bus": "b", "carrier": "gas", "p_nom": 200, "marginal_cost": 50},
        ],
        "generators-p_max_pu": rows,
    }


def test_series_missing_snapshots_refuses_the_run() -> None:
    rows = [{"snapshot": "2025-01-01 00:00", "s": 0.0}, {"snapshot": "2025-01-01 01:00", "s": 0.0}]
    with pytest.raises(HTTPException) as exc:
        build_network(_solar_model(rows), {}, {})
    assert exc.value.status_code == 400
    assert "generators-p_max_pu" in exc.value.detail and "2 of the 4" in exc.value.detail


def test_series_gap_outside_the_modelled_window_is_fine() -> None:
    rows = [{"snapshot": f"2025-01-01 {h:02d}:00", "s": 0.0} for h in range(2)]
    n, _ = build_network(_solar_model(rows), {}, {"snapshotStart": 0, "snapshotCount": 2})
    assert n.generators_t.p_max_pu["s"].tolist() == [0.0, 0.0]


def test_timezone_suffixed_series_labels_line_up_with_the_snapshots() -> None:
    rows = [{"snapshot": f"2025-01-01T{h:02d}:00:00Z", "s": 0.25} for h in range(4)]
    n, _ = build_network(_solar_model(rows), {}, {})
    assert n.generators_t.p_max_pu["s"].tolist() == pytest.approx([0.25] * 4)


def test_blank_cell_in_a_covered_row_uses_the_static_value() -> None:
    rows = [{"snapshot": f"2025-01-01 {h:02d}:00", "s": (None if h == 2 else 0.5)} for h in range(4)]
    n, notes = build_network(_solar_model(rows), {}, {})
    assert n.generators_t.p_max_pu["s"].tolist() == pytest.approx([0.5, 0.5, 1.0, 0.5])
    assert any("blank cell" in x for x in notes)


# ── RS4: force-LP and string booleans ────────────────────────────────────────


def _commit_model() -> dict[str, Any]:
    m = _dispatch_model(4)
    m["buses"].append({"name": "b2"})
    m["generators"][0].update(committable=True, p_min_pu=0.5)
    m["generators-p_min_pu"] = [{"snapshot": s["snapshot"], "g": 0.5} for s in _snaps(4)]
    m["links"] = [{"name": "lk", "bus0": "b", "bus1": "b2", "p_nom": 10, "committable": True, "p_min_pu": 0.5}]
    return m


def test_force_lp_clears_dynamic_floors_and_decommits_links() -> None:
    n, notes = build_network(_commit_model(), {}, {"forceLp": True})
    assert n.generators_t.p_min_pu["g"].tolist() == [0.0] * 4
    assert not bool(n.links.at["lk", "committable"])
    assert float(n.links.at["lk", "p_min_pu"]) == 0.0
    n.optimize(solver_name="highs")
    assert "Link-status" not in list(n.model.variables)  # an LP, not a MIP
    # g would have had a 100 MW floor (0.5 x 200); as an LP it is merit-ordered normally
    assert n.generators_t.p["g"].tolist() == pytest.approx([100.0] * 4)


@pytest.mark.parametrize(
    "token, expected",
    [("FALSE", False), ("false", False), ("0", False), ("no", False), ("No ", False),
     ("TRUE", True), ("1", True), ("yes", True), ("", False), (None, False)],
)
def test_string_booleans_are_read_as_booleans(token: Any, expected: bool) -> None:
    m = _dispatch_model(2)
    m["generators"][0]["committable"] = token
    m["generators"][0]["p_nom_extendable"] = token
    n, _ = build_network(m, {"discountRate": 0.05}, {})
    assert bool(n.generators.at["g", "committable"]) is expected
    assert bool(n.generators.at["g", "p_nom_extendable"]) is expected


# ── RS6: discount rate, lifetime fallback, carbon price ──────────────────────


@pytest.mark.parametrize("rate", [5, 5.0, -0.1, 1.0])
def test_discount_rate_must_be_a_fraction(rate: float) -> None:
    with pytest.raises(HTTPException) as exc:
        build_network(_dispatch_model(2), {"discountRate": rate}, {})
    assert exc.value.status_code == 400 and "0 <= r < 1" in exc.value.detail


def test_missing_lifetime_is_pypsas_infinity_and_no_fallback_is_applied() -> None:
    from pypsa.costs import annuity

    m = _dispatch_model(24)
    m["generators"][0].update(p_nom=0, p_nom_extendable=True, overnight_cost=1_000_000, discount_rate=0.05)
    n, notes = build_network(m, {}, {})
    expected = 1_000_000 * float(annuity(0.05, float("inf"))) * 24.0 / 8760.0       # annuity(r, inf) = r
    assert float(n.components.generators.capital_cost["g"]) == pytest.approx(expected, rel=1e-9)
    assert not any("system default" in x for x in notes)


def test_carbon_adder_follows_time_varying_efficiency() -> None:
    """Analytical: adder_t = price x co2 / eta_t  (50 x 1.0 / [1.0, 0.5] = [50, 100])."""
    m = _dispatch_model(2)
    m["generators"][0].update(efficiency=1.0, marginal_cost=0)
    m["generators-efficiency"] = [
        {"snapshot": "2025-01-01 00:00", "g": 1.0}, {"snapshot": "2025-01-01 01:00", "g": 0.5}]
    n, _ = build_network(m, {"carbonPrice": 50.0}, {})
    assert n.generators_t.marginal_cost["g"].to_numpy() == pytest.approx([50.0, 100.0], rel=1e-9)
    assert float(n.generators.at["g", "marginal_cost"]) == pytest.approx(0.0, abs=1e-12)


def test_carbon_schedule_notes_snapshots_before_the_first_year() -> None:
    m = _dispatch_model(2)
    n, notes = build_network(
        m, {"carbonPrice": 0.0}, {"carbonPriceSchedule": [{"year": 2030, "price": 10}, {"year": 2040, "price": 20}]}
    )
    assert any("precede the first carbon-price schedule year" in x for x in notes)


# ── RB9: authored snapshot weightings survive ────────────────────────────────


def _weighted_model(w: float, n: int = 6) -> dict[str, Any]:
    m = _dispatch_model(n)
    m["snapshots"] = [{**s, "objective": w, "stores": w, "generators": w} for s in m["snapshots"]]
    return m


def test_imported_snapshot_weightings_are_kept() -> None:
    n, _ = build_network(_weighted_model(3.0), {}, {})
    for col in ("objective", "stores", "generators"):
        assert n.snapshot_weightings[col].to_numpy() == pytest.approx([3.0] * 6)
    n.optimize(solver_name="highs")
    # 100 MW served 6 x 3 h = 1800 MWh by the cheap unit
    energy = float((n.generators_t.p["g"] * n.snapshot_weightings["generators"]).sum())
    assert energy == pytest.approx(1800.0, rel=1e-9)


def test_stride_sums_imported_weightings_over_each_block() -> None:
    n, _ = build_network(_weighted_model(3.0), {}, {"snapshotWeight": 2})
    assert len(n.snapshots) == 3
    assert n.snapshot_weightings["objective"].to_numpy() == pytest.approx([6.0] * 3)
    assert float(n.snapshot_weightings["objective"].sum()) == pytest.approx(18.0)


def test_unweighted_model_keeps_the_legacy_stride() -> None:
    n, _ = build_network(_dispatch_model(6), {}, {"snapshotWeight": 2})
    assert n.snapshot_weightings["objective"].to_numpy() == pytest.approx([2.0] * 3)
    assert n.snapshot_weightings["stores"].to_numpy() == pytest.approx([2.0] * 3)


def test_non_uniform_imported_weights_follow_their_rows() -> None:
    m = _dispatch_model(4)
    for s, w in zip(m["snapshots"], [1.0, 2.0, 3.0, 4.0]):
        s["objective"] = w
    n, _ = build_network(m, {}, {})
    assert n.snapshot_weightings["objective"].to_numpy() == pytest.approx([1.0, 2.0, 3.0, 4.0])
    strided, _ = build_network(m, {}, {"snapshotWeight": 2})
    assert strided.snapshot_weightings["objective"].to_numpy() == pytest.approx([3.0, 7.0])


def test_weightings_round_trip_through_network_to_model() -> None:
    from backend.pypsa.network.serialize import network_to_model

    n, _ = build_network(_weighted_model(3.0), {}, {})
    model = network_to_model(n)
    assert [r["objective"] for r in model["snapshots"]] == [3.0] * 6
    again, _ = build_network(model, {}, {})
    assert again.snapshot_weightings["objective"].to_numpy() == pytest.approx([3.0] * 6)
    hourly, _ = build_network(_dispatch_model(4), {}, {})
    assert all("objective" not in r for r in network_to_model(hourly)["snapshots"])
