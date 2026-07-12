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


def test_temporal_set_preview_energy_counts_blanks() -> None:
    # Preview reports PERIOD ENERGY. A 'set' overwrites blanks too, so its
    # after-energy is amount × n_snapshots × Δt; multiply leaves blanks blank,
    # so its energies only count numeric cells.
    model = _model()
    model["loads-p_set"][0]["L1"] = None  # E_before = 12 MWh (one numeric cell)
    out = fr.preview(
        model,
        fr.Query(target="loads", attribute="p_set", temporal=True,
                 filters=[fr.Filter(column="name", op="eq", value="L1")],
                 edit=fr.Edit(op="set", amount=7)),
    )
    assert out["sample"][0] == {"name": "L1", "before": 12.0, "after": 14.0}
    assert out["sampleKind"] == "energyMwh"

    out_mul = fr.preview(
        model,
        fr.Query(target="loads", attribute="p_set", temporal=True,
                 filters=[fr.Filter(column="name", op="eq", value="L1")],
                 edit=fr.Edit(op="multiply", amount=2)),
    )
    assert out_mul["sample"][0] == {"name": "L1", "before": 12.0, "after": 24.0}


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


def test_preview_temporal_reports_energies() -> None:
    # E over the 2 hourly snapshots: L1 = 22 MWh, L3 = 66 MWh. Adding 1 MW at
    # every snapshot (default unit/scope) adds 2 MWh to each.
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
    assert {s["name"]: (s["before"], s["after"]) for s in out["sample"]} == {
        "L1": (22.0, 24.0), "L3": (66.0, 68.0),
    }
    assert out["energyBeforeMwh"] == pytest.approx(88.0)
    assert out["energyAfterMwh"] == pytest.approx(92.0)


def test_preview_surfaces_plan_error_as_warning() -> None:
    # A plan that would fail on apply (below-zero push) previews as a warning
    # with the match count intact, not as an HTTP-level error.
    out = fr.preview(
        _model(),
        fr.Query(target="loads", attribute="p_set", temporal=True,
                 filters=[fr.Filter(column="name", op="eq", value="L1")],
                 edit=fr.Edit(op="add", amount=-11)),  # L1 min is 10 MW
    )
    assert out["matched"] == 1
    assert out["seriesColumnsPresent"] == 0
    assert out["sample"] == []
    assert any("below zero" in w for w in out["warnings"])


# ── temporal add matrix (unit × scope × split) ──────────────────────────────────
# Fixture energies over the 2 hourly snapshots: L1 = 22, L2 = 44, L3 = 66 MWh
# (E = 132 MWh).

ALL = ["L1", "L2", "L3"]


def _steps_by_column(action: dict) -> dict[str, tuple[str, float]]:
    """Flatten grouped steps to {column: (kind, value)} for easy assertions."""
    out: dict[str, tuple[str, float]] = {}
    for kind, params in action["steps"]:
        value = params.get("factor", params.get("delta", params.get("value")))
        for c in params["columns"]:
            out[c] = (kind, value)
    return out


def test_add_mw_total_proportional_splits_by_energy() -> None:
    action = fr.resolve_temporal(
        _model(), "loads", "p_set", ALL,
        fr.Edit(op="add", amount=30, unit="mw", scope="total", split="proportional"),
    )
    assert _steps_by_column(action) == {
        "L1": ("offset", pytest.approx(5.0)),   # 30 × 22/132
        "L2": ("offset", pytest.approx(10.0)),  # 30 × 44/132
        "L3": ("offset", pytest.approx(15.0)),  # 30 × 66/132
    }


def test_add_mw_total_equal_is_one_grouped_step() -> None:
    action = fr.resolve_temporal(
        _model(), "loads", "p_set", ALL,
        fr.Edit(op="add", amount=30, unit="mw", scope="total", split="equal"),
    )
    assert action["steps"] == [("offset", {"columns": ALL, "delta": pytest.approx(10.0)})]


def test_add_mwh_each_scales_each_column() -> None:
    action = fr.resolve_temporal(
        _model(), "loads", "p_set", ALL,
        fr.Edit(op="add", amount=22, unit="mwh", scope="each"),
    )
    assert _steps_by_column(action) == {
        "L1": ("scale", pytest.approx(2.0)),        # (22+22)/22
        "L2": ("scale", pytest.approx(1.5)),        # (44+22)/44
        "L3": ("scale", pytest.approx(4.0 / 3.0)),  # (66+22)/66
    }


def test_add_mwh_total_proportional_is_uniform_factor() -> None:
    # ΔE_i = A·E_i/E ⇒ factor 1 + A/E is identical for every column, so the
    # grouped action is ONE scale step (the dashboard add_mwh math).
    action = fr.resolve_temporal(
        _model(), "loads", "p_set", ALL,
        fr.Edit(op="add", amount=66, unit="mwh", scope="total", split="proportional"),
    )
    assert action["steps"] == [("scale", {"columns": ALL, "factor": pytest.approx(1.5)})]


def test_add_mwh_total_equal_scales_by_share() -> None:
    action = fr.resolve_temporal(
        _model(), "loads", "p_set", ALL,
        fr.Edit(op="add", amount=66, unit="mwh", scope="total", split="equal"),
    )
    assert _steps_by_column(action) == {
        "L1": ("scale", pytest.approx(2.0)),        # (22+22)/22
        "L2": ("scale", pytest.approx(1.5)),        # (44+22)/44
        "L3": ("scale", pytest.approx(4.0 / 3.0)),  # (66+22)/66
    }


def test_add_mwh_zero_energy_column_falls_back_to_offset() -> None:
    model = _model()
    for row in model["loads-p_set"]:
        row["L1"] = 0.0
    action = fr.resolve_temporal(
        model, "loads", "p_set", ["L1"],
        fr.Edit(op="add", amount=10, unit="mwh", scope="each"),
    )
    # 10 MWh over 2 numeric cells × 1 h → flat +5 MW.
    assert action["steps"] == [("offset", {"columns": ["L1"], "delta": pytest.approx(5.0)})]


def test_add_mw_negative_below_zero_raises() -> None:
    with pytest.raises(fr.ForgeQueryError, match="below zero"):
        fr.resolve_temporal(
            _model(), "loads", "p_set", ["L1"],
            fr.Edit(op="add", amount=-11, unit="mw", scope="each"),  # min(L1)=10
        )


def test_add_mwh_removing_more_than_available_raises() -> None:
    with pytest.raises(fr.ForgeQueryError, match="exceeds"):
        fr.resolve_temporal(
            _model(), "loads", "p_set", ["L1"],
            fr.Edit(op="add", amount=-30, unit="mwh", scope="each"),  # E(L1)=22
        )


def test_add_proportional_on_zero_energy_group_raises() -> None:
    model = _model()
    for row in model["loads-p_set"]:
        row["L1"] = 0.0
    with pytest.raises(fr.ForgeQueryError, match="proportionally"):
        fr.resolve_temporal(
            model, "loads", "p_set", ["L1"],
            fr.Edit(op="add", amount=10, unit="mw", scope="total", split="proportional"),
        )


def test_add_unknown_unit_scope_split_rejected() -> None:
    for bad in (
        fr.Edit(op="add", amount=1, unit="kw"),
        fr.Edit(op="add", amount=1, scope="some"),
        fr.Edit(op="add", amount=1, scope="total", split="fibonacci"),
    ):
        with pytest.raises(fr.ForgeQueryError):
            fr.resolve_temporal(_model(), "loads", "p_set", ["L1"], bad)
