"""WA3 + WA4: the DSL-sheet precedence and the pre-run guards that used to live in the browser."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from backend.app import main, run_guards
from backend.app.models import RunPayload


def _model(dsl: str | None = None, carriers: tuple[str, ...] = ("gas", "backup")) -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(6)]
    model: dict[str, list[dict[str, Any]]] = {
        "buses": [{"name": "b"}],
        "carriers": [{"name": c} for c in carriers],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
        "generators": [
            {"name": "G_gas", "bus": "b", "carrier": carriers[0], "p_nom": 200.0, "marginal_cost": 10.0},
            {"name": "G_backup", "bus": "b", "carrier": carriers[1], "p_nom": 200.0, "marginal_cost": 100.0},
        ],
    }
    if dsl is not None:
        model["RAGNAROK_CustomDSL"] = [{"text": dsl}]
    return model


def _payload(model, scenario=None, options=None) -> RunPayload:
    return RunPayload(model=model, scenario=scenario or {"discountRate": 0.0, "carbonPrice": 0.0}, options=options)


# ── WA3: precedence ──────────────────────────────────────────────────────────


def test_sheet_dsl_fills_in_when_the_run_names_no_dsl() -> None:
    resolved = main._resolve_payload_model(_payload(_model("gen(gas) <= 300")))
    assert resolved.scenario["customDsl"] == "gen(gas) <= 300"


def test_scenario_constraint_specs_win_over_the_sheet_even_when_empty() -> None:
    for specs in ([], [{"lhs": [], "sense": "<=", "rhs": []}]):
        resolved = main._resolve_payload_model(
            _payload(_model("gen(gas) <= 300"), {"constraintSpecs": specs})
        )
        assert "customDsl" not in resolved.scenario  # sheet not injected


def test_scenario_custom_dsl_wins_over_the_sheet_even_when_blank() -> None:
    resolved = main._resolve_payload_model(_payload(_model("gen(gas) <= 300"), {"customDsl": ""}))
    assert resolved.scenario["customDsl"] == ""
    resolved = main._resolve_payload_model(_payload(_model("gen(gas) <= 300"), {"customDsl": "gen(backup) <= 1"}))
    assert resolved.scenario["customDsl"] == "gen(backup) <= 1"


def test_no_sheet_means_no_change() -> None:
    resolved = main._resolve_payload_model(_payload(_model(None)))
    assert "customDsl" not in resolved.scenario


def test_the_sheet_dsl_actually_binds_in_the_solve() -> None:
    from backend.pypsa.results import run_pypsa

    opts = {"snapshotStart": 0, "snapshotCount": 6, "snapshotWeight": 1}
    free = main._resolve_payload_model(_payload(_model(None), options=opts))
    capped = main._resolve_payload_model(_payload(_model("gen(gas) <= 300"), options=opts))
    free_res = run_pypsa(free.model, free.scenario, free.options)
    capped_res = run_pypsa(capped.model, capped.scenario, capped.options)
    blob = str(capped_res.get("notes") or capped_res)
    assert "gen(gas) <= 300" in blob and "added" in blob
    assert "gen(gas) <= 300" not in str(free_res.get("notes") or free_res)
    # 6 h x 100 MW = 600 MWh of load: unconstrained all gas, capped 300 MWh gas + 300 MWh backup.
    assert capped_res["summary"] != free_res["summary"]


# ── WA4: guards ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "options",
    [
        {"snapshotStart": 10, "snapshotEnd": 10},
        {"snapshotStart": 10, "snapshotEnd": 4},
        {"snapshotStart": 0, "snapshotEnd": 0, "snapshotCount": 0},
        {"snapshotCount": -3},
        {"snapshotEnd": 0},
        {"snapshotStart": 0, "snapshotCount": "abc"},
    ],
)
def test_an_empty_window_refuses_the_run(options: dict[str, Any]) -> None:
    with pytest.raises(HTTPException) as exc:
        main._refuse_invalid_model(_payload(_model(), options=options))
    assert exc.value.status_code == 400 and "snapshot window is empty" in exc.value.detail


@pytest.mark.parametrize(
    "options",
    [None, {}, {"snapshotStart": 0, "snapshotEnd": 6}, {"snapshotCount": 4}, {"snapshotStart": 2, "snapshotEnd": 6, "snapshotCount": 3}],
)
def test_a_usable_window_passes(options: dict[str, Any] | None) -> None:
    main._refuse_invalid_model(_payload(_model(), options=options))


def test_a_dsl_syntax_error_refuses_the_run_and_names_the_line() -> None:
    resolved = main._resolve_payload_model(_payload(_model("gen(gas) <= 300\ngen(gas) 5\nfoo(x) <= 1")))
    with pytest.raises(HTTPException) as exc:
        main._refuse_invalid_model(resolved)
    assert "line 2" in exc.value.detail and "comparator" in exc.value.detail and "line 3" in exc.value.detail


def test_a_dangling_coefficient_is_a_parse_error_not_a_crash() -> None:
    problem = run_guards.dsl_problem({"customDsl": "gen(a) <= 2 *"})
    assert problem and "expected a term after" in problem


def test_good_dsl_passes() -> None:
    main._refuse_invalid_model(main._resolve_payload_model(_payload(_model("# c\ngen(gas) <= 300\n"))))


def test_unresolved_carrier_constraint_refuses_the_run() -> None:
    scenario = {"constraints": [{"enabled": True, "metric": "carrier_max_gen", "carrier": "coall", "value": 10, "label": "Coal cap"}]}
    with pytest.raises(HTTPException) as exc:
        main._refuse_invalid_model(_payload(_model(), scenario))
    detail = exc.value.detail
    assert "coall" in detail and "Coal cap" in detail and "gas, backup" in detail.replace("backup, gas", "gas, backup")


def test_resolved_disabled_and_non_carrier_constraints_pass() -> None:
    scenario = {
        "constraints": [
            {"enabled": True, "metric": "carrier_max_gen", "carrier": "gas", "value": 10},
            {"enabled": False, "metric": "carrier_max_gen", "carrier": "nope", "value": 10},
            {"metric": "carrier_max_gen", "carrier": "nope", "value": 10},  # no 'enabled' = off
            {"enabled": True, "metric": "co2_cap", "carrier": "", "value": 0.4},
        ]
    }
    main._refuse_invalid_model(_payload(_model(), scenario))


def test_carrier_match_is_exact_and_case_sensitive() -> None:
    scenario = {"constraints": [{"enabled": True, "metric": "carrier_min_gen", "carrier": "Gas", "value": 1}]}
    with pytest.raises(HTTPException):
        main._refuse_invalid_model(_payload(_model(), scenario))


def test_all_problems_are_reported_together() -> None:
    scenario = {"constraints": [{"enabled": True, "metric": "carrier_max_gen", "carrier": "x", "value": 1}], "customDsl": "bad"}
    with pytest.raises(HTTPException) as exc:
        main._refuse_invalid_model(_payload(_model(), scenario, {"snapshotStart": 3, "snapshotEnd": 3}))
    assert exc.value.detail.count("snapshot window") == 1 and "syntax errors" in exc.value.detail and "carrier no generator" in exc.value.detail


def test_enqueue_refuses_a_typod_carrier_cap_without_queueing() -> None:
    import asyncio

    before = len(main._run_queue)
    scenario = {"constraints": [{"enabled": True, "metric": "carrier_max_gen", "carrier": "coall", "value": 10}]}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.enqueue_run(_payload(_model(), scenario)))
    assert exc.value.status_code == 400 and "coall" in exc.value.detail
    assert len(main._run_queue) == before
