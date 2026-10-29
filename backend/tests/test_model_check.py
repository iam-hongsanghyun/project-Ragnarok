"""Reading the model back, so "is this what I asked for?" has an answer.

Every trap here has actually cost this project time. The alignment one is the
reason the check exists at all: a temporal sheet whose labels do not match
`snapshots` solves cleanly, reports Optimal, and answers with the uncovered hours
treated as zero — a confidently wrong result with nothing on screen to question.
"""
from __future__ import annotations

from typing import Any

from backend.pypsa.model_check import check_model


def _codes(result: dict[str, Any]) -> set[str]:
    return {f["code"] for f in result["findings"]}


def _base() -> dict[str, Any]:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]
    return {
        "snapshots": [{"snapshot": s} for s in snaps],
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}],
        "loads": [{"name": "L", "bus": "b"}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
        "generators": [
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 200, "marginal_cost": 50},
        ],
    }


def test_back_brief_reports_what_is_there_not_what_was_intended() -> None:
    result = check_model(_base())
    brief = result["backBrief"]
    assert brief["counts"]["generators"] == 1
    assert brief["snapshots"] == {"count": 4, "first": "2030-01-01T00:00:00",
                                  "last": "2030-01-01T03:00:00"}
    assert brief["load"]["peakMW"] == 100.0
    assert brief["load"]["energyMWh"] == 400.0
    assert brief["generators"][0]["p_nom"] == 200.0
    assert brief["extendableCount"] == 0


def test_a_clean_model_raises_no_warnings() -> None:
    result = check_model(_base())
    assert result["warnCount"] == 0
    assert "check the back-brief" in result["verdict"]


def test_partial_snapshot_cover_is_caught() -> None:
    """The headline trap: it solves, reports Optimal, and is wrong."""
    model = _base()
    model["generators-p_max_pu"] = [
        {"snapshot": "2030-01-01T00:00:00", "gas1": 1.0},
        {"snapshot": "2030-01-01T01:00:00", "gas1": 1.0},
    ]
    result = check_model(model)
    assert "snapshot_partial_cover" in _codes(result)
    message = next(f for f in result["findings"] if f["code"] == "snapshot_partial_cover")
    assert "ZERO" in message["message"]  # says what actually happens, not "check your data"
    assert result["warnCount"] >= 1


def test_off_axis_snapshot_labels_are_caught() -> None:
    model = _base()
    model["generators-p_max_pu"] = [{"snapshot": "2031-06-01T00:00:00", "gas1": 1.0}]
    result = check_model(model)
    assert "snapshot_off_axis" in _codes(result)


def test_pinned_generator_is_reported_as_an_input() -> None:
    model = _base()
    model["generators"][0]["p_set"] = 120
    result = check_model(model)
    assert "generator_pinned" in _codes(result)


def test_min_pu_without_commitment_is_an_unconditional_floor() -> None:
    model = _base()
    model["generators"][0]["p_min_pu"] = 0.4
    assert "min_pu_without_commitment" in _codes(check_model(model))
    # …and NOT reported when unit commitment is on, where it means what it says.
    model["generators"][0]["committable"] = True
    assert "min_pu_without_commitment" not in _codes(check_model(model))


def test_extendable_without_capital_cost_builds_free() -> None:
    model = _base()
    model["generators"].append(
        {"name": "solar", "bus": "b", "carrier": "gas", "p_nom_extendable": True, "p_nom_max": 500}
    )
    result = check_model(model)
    assert "free_expansion" in _codes(result)
    assert result["warnCount"] >= 1


def test_a_composite_fuel_supplier_is_not_flagged_as_free_expansion() -> None:
    """A CCGT composite's gas supplier is extendable at zero capital cost on purpose (a fuel market priced by marginal cost)."""
    from backend.app.plants import catalog, registry

    model = _base()
    built = catalog.build_plant("ccgt", {"bus": model["buses"][0]["name"], "p_nom": 100}, model)
    model = registry.apply_change(model, {"remove": {}, "release": [], "fragment": built["fragment"]})
    suppliers = [g["name"] for g in model["generators"] if g.get("p_nom_extendable") and not g.get("capital_cost")]
    assert suppliers, "the composite should add an extendable, zero-capex gas supplier"
    assert "free_expansion" not in _codes(check_model(model))


def test_isolated_bus_and_missing_load_are_reported() -> None:
    model = _base()
    model["buses"].append({"name": "orphan"})
    assert "isolated_bus" in _codes(check_model(model))

    model["loads"] = []
    model["loads-p_set"] = []
    assert "no_load" in _codes(check_model(model))


def test_load_shedding_is_flagged_because_feasible_is_not_adequate() -> None:
    model = _base()
    model["generators"].append(
        {"name": "load_shedding_b", "bus": "b", "carrier": "load_shedding",
         "p_nom": 9999, "marginal_cost": 10000}
    )
    assert "load_shedding_present" in _codes(check_model(model))


def test_the_check_never_mutates_the_model() -> None:
    """It is read-only by contract: the agent runs it on the user's live session."""
    import copy

    model = _base()
    model["generators"][0]["p_set"] = 120
    before = copy.deepcopy(model)
    check_model(model)
    assert model == before


def test_the_endpoint_checks_the_model_a_session_holds_and_an_inline_one() -> None:
    """Q3: /api/model-check passed the request itself to the check, not its workbook — HTTP 500
    on every call. Both ways a model reaches it are answered with the back-brief."""
    from fastapi.testclient import TestClient

    from backend.app import model_store
    from backend.app.main import app

    c = TestClient(app)
    inline = c.post("/api/model-check", json={"model": _base()})
    assert inline.status_code == 200 and inline.json()["backBrief"]["counts"]["generators"] == 1
    sid = "test-q3-model-check"
    model_store.save_model(sid, _base())
    try:
        held = c.post("/api/model-check", json={"sessionId": sid})
        assert held.status_code == 200 and held.json()["backBrief"]["load"]["peakMW"] == 100.0
    finally:
        model_store.clear(sid)
    gone = c.post("/api/model-check", json={"sessionId": "test-q3-no-such-session"})
    assert gone.status_code == 400 and "No model loaded" in gone.json()["detail"]
