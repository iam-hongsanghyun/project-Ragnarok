"""T1 — bulk series transforms (scale / shift / interpolate / clip / offset).

Pins the pure transform maths in :func:`timeseries.transform_rows`: the value
columns are transformed, the timestamp column is preserved, and non-numeric cells
degrade to ``None``. The store methods are thin read→transform→rewrite wrappers
over this function.
"""
from __future__ import annotations

from backend.app.timeseries import transform_rows


def _rows() -> list[dict]:
    return [
        {"snapshot": "2030-01-01T00:00:00", "a": 10.0, "b": 100.0},
        {"snapshot": "2030-01-01T01:00:00", "a": 20.0, "b": 200.0},
        {"snapshot": "2030-01-01T02:00:00", "a": 30.0, "b": 300.0},
        {"snapshot": "2030-01-01T03:00:00", "a": 40.0, "b": 400.0},
    ]


def test_scale_multiplies_value_columns_only() -> None:
    out = transform_rows(_rows(), "snapshot", "scale", factor=1.5)
    assert [r["a"] for r in out] == [15.0, 30.0, 45.0, 60.0]
    assert [r["b"] for r in out] == [150.0, 300.0, 450.0, 600.0]
    # Timestamp column untouched.
    assert out[0]["snapshot"] == "2030-01-01T00:00:00"


def test_offset_adds_delta() -> None:
    out = transform_rows(_rows(), "snapshot", "offset", delta=5.0)
    assert [r["a"] for r in out] == [15.0, 25.0, 35.0, 45.0]


def test_columns_subset_leaves_others_untouched() -> None:
    out = transform_rows(_rows(), "snapshot", "scale", factor=2.0, columns=["a"])
    assert [r["a"] for r in out] == [20.0, 40.0, 60.0, 80.0]
    assert [r["b"] for r in out] == [100.0, 200.0, 300.0, 400.0]  # unchanged


def test_shift_wraps_cyclically() -> None:
    out = transform_rows(_rows(), "snapshot", "shift", shift=1, wrap=True)
    # roll right by 1: last value wraps to the front.
    assert [r["a"] for r in out] == [40.0, 10.0, 20.0, 30.0]


def test_shift_no_wrap_edge_fills() -> None:
    out = transform_rows(_rows(), "snapshot", "shift", shift=1, wrap=False)
    # shift down by 1, exposed first cell held at the nearest (first) value.
    assert [r["a"] for r in out] == [10.0, 10.0, 20.0, 30.0]


def test_interpolate_fills_gaps_linearly() -> None:
    rows = [
        {"snapshot": "t0", "a": 10.0},
        {"snapshot": "t1", "a": None},
        {"snapshot": "t2", "a": None},
        {"snapshot": "t3", "a": 40.0},
    ]
    out = transform_rows(rows, "snapshot", "interpolate")
    assert [r["a"] for r in out] == [10.0, 20.0, 30.0, 40.0]


def test_clip_bounds_values() -> None:
    out = transform_rows(_rows(), "snapshot", "clip", min_value=15.0, max_value=35.0)
    assert [r["a"] for r in out] == [15.0, 20.0, 30.0, 35.0]


def test_empty_rows_and_bad_op() -> None:
    assert transform_rows([], "snapshot", "scale", factor=2.0) == []
    import pytest
    with pytest.raises(ValueError):
        transform_rows(_rows(), "snapshot", "nonsense")  # type: ignore[arg-type]
