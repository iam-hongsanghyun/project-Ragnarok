"""Every temporal sheet must align to the model's ONE shared snapshot axis.

`_apply_ts_sheet` reindexes each series onto `network.snapshots`, which drops rows
whose label is off the axis and leaves the uncovered snapshots undefined. The solve
reports NEITHER: a `loads-p_set` covering half the window returns "Optimal" with
the missing hours dispatched as ZERO demand, so the run produces a plausible wrong
answer. A row-count comparison cannot catch it — a sheet can have exactly the right
number of rows and still be for the wrong year.
"""
from __future__ import annotations

from typing import Any

from backend.app.models import RunPayload
from backend.pypsa.network.validators import validate_model

SNAPS = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]


def _model(ts_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "buses": [{"name": "b"}],
        "snapshots": [{"snapshot": s} for s in SNAPS],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "generators": [
            {"name": "g", "bus": "b", "p_nom": 500.0, "marginal_cost": 10.0, "carrier": "gas"}
        ],
        "carriers": [{"name": "gas"}],
        "loads-p_set": ts_rows,
    }


def _report(ts_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return validate_model(
        RunPayload(model=_model(ts_rows), scenario={"discountRate": 0.05}, options={})
    )


def _for_sheet(messages: list[str]) -> list[str]:
    return [m for m in messages if "loads-p_set" in m]


def test_uncovered_snapshots_are_an_error_not_a_silent_zero() -> None:
    report = _report([{"snapshot": SNAPS[0], "L": 10.0}, {"snapshot": SNAPS[1], "L": 20.0}])
    errors = _for_sheet(report["errors"])
    assert report["valid"] is False
    assert any("2 of 4 snapshots have no row" in e for e in errors), errors
    # The message has to name the consequence — the run looks Optimal either way.
    assert any("ZERO" in e for e in errors), errors


def test_off_axis_labels_are_reported_as_dropped() -> None:
    report = _report(
        [{"snapshot": s, "L": 10.0} for s in SNAPS]
        + [{"snapshot": "2029-06-01T00:00:00", "L": 999.0}]
    )
    errors = _for_sheet(report["errors"])
    assert report["valid"] is False
    assert any("not in the `snapshots` sheet" in e and "DROPPED" in e for e in errors), errors
    assert any("2029-06-01" in e for e in errors), errors


def test_a_fully_aligned_sheet_is_clean() -> None:
    report = _report([{"snapshot": s, "L": 10.0} for s in SNAPS])
    assert _for_sheet(report["errors"]) == []
    assert _for_sheet(report["warnings"]) == []


def test_the_same_instant_spelled_differently_is_still_aligned() -> None:
    """`2030-01-01T00:00:00` and `2030-01-01 00:00:00` are the same snapshot.

    Comparing raw strings would flag every well-aligned sheet, since the snapshots
    sheet is ISO-`T` and a hand-made CSV usually is not.
    """
    report = _report([{"snapshot": s.replace("T", " "), "L": 10.0} for s in SNAPS])
    assert _for_sheet(report["errors"]) == []
    assert _for_sheet(report["warnings"]) == []


def test_a_right_sized_sheet_for_the_wrong_year_is_still_caught() -> None:
    """The case a row-count check is blind to: 4 rows, 4 snapshots, zero overlap."""
    wrong_year = [{"snapshot": s.replace("2030", "2029"), "L": 10.0} for s in SNAPS]
    report = _report(wrong_year)
    errors = _for_sheet(report["errors"])
    assert report["valid"] is False
    assert any("DROPPED" in e for e in errors), errors
    assert any("4 of 4 snapshots have no row" in e for e in errors), errors
    # The old count check would have said nothing at all.
    assert not any("Row count" in w for w in _for_sheet(report["warnings"]))


def test_non_datetime_labels_fall_back_to_the_count_check() -> None:
    """An integer/`now` axis has no comparable timestamp; keep the old behaviour."""
    model = _model([{"snapshot": "1", "L": 1.0}, {"snapshot": "2", "L": 2.0}])
    model["snapshots"] = [{"snapshot": "1"}, {"snapshot": "2"}, {"snapshot": "3"}]
    report = validate_model(
        RunPayload(model=model, scenario={"discountRate": 0.05}, options={})
    )
    msgs = _for_sheet(report["errors"]) + _for_sheet(report["warnings"])
    assert any("snapshots have no row" in m or "Row count" in m for m in msgs), msgs
