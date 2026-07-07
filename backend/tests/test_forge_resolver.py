"""Unit tests for the pure Forge Query & Edit resolver (no session, no HTTP)."""
from __future__ import annotations

import pytest

from backend.app import forge_resolver as fr


def _model() -> dict[str, list[dict]]:
    return {
        "buses": [
            {"name": "b1", "province": "Seoul", "v_nom": 380},
            {"name": "b2", "province": "Busan", "v_nom": 154},
            {"name": "b3", "province": "Seoul", "v_nom": 220},
        ],
        "generators": [
            {"name": "g1", "bus": "b1", "carrier": "gas", "p_nom": 100, "p_nom_max": 0},
            {"name": "g2", "bus": "b2", "carrier": "gas", "p_nom": 200, "p_nom_max": 0},
            {"name": "g3", "bus": "b3", "carrier": "wind", "p_nom": 50, "p_nom_max": 0},
            {"name": "", "bus": "b1", "carrier": "gas", "p_nom": 9},  # blank name → ignored
        ],
        "loads": [
            {"name": "L1", "bus": "b1"},
            {"name": "L2", "bus": "b2"},
            {"name": "L3", "bus": "b3"},
        ],
        "loads-p_set": [
            {"snapshot": "2030-01-01T00:00:00", "L1": 10.0, "L2": 20.0, "L3": 30.0},
            {"snapshot": "2030-01-01T01:00:00", "L1": 12.0, "L2": 24.0, "L3": 36.0},
        ],
    }


# ── operators / coercion ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "cell,op,value,expected",
    [
        ("gas", "eq", "gas", True),
        ("gas", "eq", "wind", False),
        ("gas", "ne", "wind", True),
        (None, "ne", "wind", True),          # missing != concrete → True
        ("onwind", "contains", "wind", True),
        (100, "gt", "50", True),
        ("100", "gt", 50, True),
        ("abc", "gt", 1, False),             # non-numeric never matches, never raises
        (50, "le", 50, True),
    ],
)
def test_coerce_compare(cell, op, value, expected) -> None:
    assert fr.coerce_compare(cell, op, value) is expected


def test_coerce_compare_in() -> None:
    assert fr.coerce_compare("gas", "in", values=["gas", "oil"]) is True
    assert fr.coerce_compare("wind", "in", values=["gas", "oil"]) is False


# ── filtering + joins ───────────────────────────────────────────────────────────

def test_direct_filter_and_blank_name_excluded() -> None:
    names = fr.match_target_names(
        _model(), "generators", [fr.Filter(column="carrier", op="eq", value="gas")]
    )
    assert names == ["g1", "g2"]  # the blank-name gas generator is dropped


def test_one_hop_join_province_to_generators() -> None:
    names = fr.match_target_names(
        _model(),
        "generators",
        [fr.Filter(column="province", op="eq", value="Seoul",
                   join=fr.JoinPath(component="buses", ref_column="bus"))],
    )
    assert names == ["g1", "g3"]  # buses b1,b3 are in Seoul


def test_join_anded_with_direct_filter() -> None:
    names = fr.match_target_names(
        _model(),
        "generators",
        [
            fr.Filter(column="province", op="eq", value="Seoul",
                      join=fr.JoinPath(component="buses", ref_column="bus")),
            fr.Filter(column="carrier", op="eq", value="gas"),
        ],
    )
    assert names == ["g1"]  # Seoul ∩ gas


def test_join_missing_component_raises() -> None:
    with pytest.raises(fr.ForgeQueryError):
        fr.match_target_names(
            _model(), "generators",
            [fr.Filter(column="province", op="eq", value="Seoul",
                       join=fr.JoinPath(component="nope", ref_column="bus"))],
        )


def test_join_missing_column_raises() -> None:
    with pytest.raises(fr.ForgeQueryError):
        fr.match_target_names(
            _model(), "generators",
            [fr.Filter(column="ghost", op="eq", value="x",
                       join=fr.JoinPath(component="buses", ref_column="bus"))],
        )


# ── static ops ──────────────────────────────────────────────────────────────────

def test_static_multiply_emits_indexed_ops() -> None:
    ops = fr.resolve_static_ops(
        _model(), "generators", "p_nom", ["g1", "g3"], fr.Edit(op="multiply", amount=0.8)
    )
    assert ops == [
        {"op": "set", "row": 0, "column": "p_nom", "value": 80.0},
        {"op": "set", "row": 2, "column": "p_nom", "value": 40.0},
    ]


def test_static_add_skips_non_numeric() -> None:
    model = _model()
    model["generators"][0]["p_nom"] = "n/a"  # blank-ish → skipped for add
    ops = fr.resolve_static_ops(model, "generators", "p_nom", ["g1", "g2"], fr.Edit(op="add", amount=5))
    assert ops == [{"op": "set", "row": 1, "column": "p_nom", "value": 205.0}]


def test_static_set_always_writes() -> None:
    ops = fr.resolve_static_ops(
        _model(), "generators", "p_nom_max", ["g1"], fr.Edit(op="set", amount=999)
    )
    assert ops == [{"op": "set", "row": 0, "column": "p_nom_max", "value": 999.0}]


def test_static_derive_from_attribute() -> None:
    ops = fr.resolve_static_ops(
        _model(), "generators", "p_nom_max", ["g1", "g2"],
        fr.Edit(op="derive", source_attr="p_nom", coefficient=3.0, constant=0.0),
    )
    assert ops == [
        {"op": "set", "row": 0, "column": "p_nom_max", "value": 300.0},
        {"op": "set", "row": 1, "column": "p_nom_max", "value": 600.0},
    ]


# ── temporal ────────────────────────────────────────────────────────────────────

def test_temporal_multiply_builds_scale_step() -> None:
    action = fr.resolve_temporal(
        _model(), "loads", "p_set", ["L1", "L3"], fr.Edit(op="multiply", amount=1.1)
    )
    assert action["sheet"] == "loads-p_set"
    assert action["steps"] == [("scale", {"columns": ["L1", "L3"], "factor": 1.1})]
    assert action["present"] == 2


def test_temporal_add_builds_offset_step() -> None:
    action = fr.resolve_temporal(
        _model(), "loads", "p_set", ["L2"], fr.Edit(op="add", amount=5)
    )
    assert action["steps"] == [("offset", {"columns": ["L2"], "delta": 5.0})]


def test_temporal_set_is_single_atomic_step() -> None:
    action = fr.resolve_temporal(
        _model(), "loads", "p_set", ["L1"], fr.Edit(op="set", amount=7)
    )
    # One atomic 'set' transform (not scale-0-then-offset): no partial-failure
    # window, and it overwrites blanks too.
    assert action["steps"] == [("set", {"columns": ["L1"], "value": 7.0})]


def test_temporal_set_preview_matches_apply_on_blank_cell() -> None:
    # A blank series cell: preview must promise what apply delivers. A 'set'
    # fills blanks (amount), while multiply/add leave a blank blank.
    model = _model()
    model["loads-p_set"][0]["L1"] = None
    out = fr.preview(
        model,
        fr.Query(target="loads", attribute="p_set", temporal=True,
                 filters=[fr.Filter(column="name", op="eq", value="L1")],
                 edit=fr.Edit(op="set", amount=7)),
    )
    assert out["sample"][0] == {"name": "L1", "before": None, "after": 7.0}

    out_mul = fr.preview(
        model,
        fr.Query(target="loads", attribute="p_set", temporal=True,
                 filters=[fr.Filter(column="name", op="eq", value="L1")],
                 edit=fr.Edit(op="multiply", amount=2)),
    )
    assert out_mul["sample"][0] == {"name": "L1", "before": None, "after": None}


def test_temporal_derive_rejected() -> None:
    with pytest.raises(fr.ForgeQueryError):
        fr.resolve_temporal(
            _model(), "loads", "p_set", ["L1"], fr.Edit(op="derive", source_attr="x")
        )


def test_temporal_missing_series_sheet_raises() -> None:
    model = _model()
    del model["loads-p_set"]
    with pytest.raises(fr.ForgeQueryError):
        fr.resolve_temporal(model, "loads", "p_set", ["L1"], fr.Edit(op="add", amount=1))


def test_temporal_columns_intersected_with_present() -> None:
    action = fr.resolve_temporal(
        _model(), "loads", "p_set", ["L1", "ghost"], fr.Edit(op="multiply", amount=2)
    )
    assert action["steps"][0][1]["columns"] == ["L1"]  # ghost has no series column
    assert action["present"] == 1


# ── preview ─────────────────────────────────────────────────────────────────────

def test_preview_static_before_after() -> None:
    out = fr.preview(
        _model(),
        fr.Query(target="generators", attribute="p_nom",
                 filters=[fr.Filter(column="carrier", op="eq", value="gas")],
                 edit=fr.Edit(op="multiply", amount=0.5)),
    )
    assert out["matched"] == 2
    assert out["temporal"] is False
    assert {s["name"]: s["after"] for s in out["sample"]} == {"g1": 50.0, "g2": 100.0}


def test_preview_temporal_warns_on_missing_columns() -> None:
    out = fr.preview(
        _model(),
        fr.Query(target="loads", attribute="p_set", temporal=True,
                 filters=[fr.Filter(column="province", op="eq", value="Seoul",
                                    join=fr.JoinPath(component="buses", ref_column="bus"))],
                 edit=fr.Edit(op="add", amount=1)),
    )
    assert out["temporal"] is True
    assert out["seriesSheet"] == "loads-p_set"
    assert out["matched"] == 2  # L1, L3 (Seoul)
    assert out["seriesColumnsPresent"] == 2
    assert {s["name"]: s["after"] for s in out["sample"]} == {"L1": 11.0, "L3": 31.0}
