"""Tests for backend/app/fragment_merge.py — the single merge behind POST /api/session/merge-fragment
(used by the GUI and by MCP).

The agent path has no browser, so an importer/siting/PyPSA-Earth fragment must
merge the way "Add to workbook" does: append with name dedupe (never replace a
whole sheet), union carriers and snapshots, widen temporal sheets.
"""

from __future__ import annotations

from backend.app.fragment_merge import PROVENANCE_SHEET, merge_fragment


def _model() -> dict:
    return {
        "buses": [{"name": "b1"}],
        "generators": [{"name": "gas", "bus": "b1", "carrier": "gas"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.2}],
        "snapshots": [
            {"snapshot": "2024-01-01T00:00:00"},
            {"snapshot": "2024-01-01T01:00:00"},
        ],
        "loads-p_set": [
            {"snapshot": "2024-01-01T00:00:00", "load1": 10},
            {"snapshot": "2024-01-01T01:00:00", "load1": 12},
        ],
    }


def test_static_rows_are_appended_not_replaced() -> None:
    out = merge_fragment(
        _model(), {"sheets": {"generators": [{"name": "wind", "bus": "b1"}]}}
    )
    assert [g["name"] for g in out["generators"]] == ["gas", "wind"]


def test_name_collision_is_suffixed_and_bus_references_follow() -> None:
    frag = {
        "sheets": {
            "buses": [{"name": "b1"}],
            "generators": [{"name": "gas", "bus": "b1"}],
        }
    }
    out = merge_fragment(_model(), frag)
    assert [b["name"] for b in out["buses"]] == ["b1", "b1_2"]
    added = out["generators"][-1]
    assert added == {"name": "gas_2", "bus": "b1_2"}
    # existing rows win
    assert out["generators"][0]["bus"] == "b1"


def test_carriers_union_and_fill_empty_attributes() -> None:
    frag = {
        "sheets": {
            "carriers": [
                {"name": "gas", "co2_emissions": 9, "color": "#f00"},
                {"name": "wind"},
            ]
        }
    }
    out = merge_fragment(_model(), frag)
    # existing non-empty value wins, empty attribute is filled
    assert out["carriers"] == [
        {"name": "gas", "co2_emissions": 0.2, "color": "#f00"},
        {"name": "wind"},
    ]


def test_fuel_price_fragment_overwrites_and_prices_generators() -> None:
    model = _model()
    model["generators"].append(
        {"name": "gas_eff", "bus": "b1", "carrier": "gas", "efficiency": 0.5}
    )
    model["generators"].append(
        {"name": "w", "bus": "b1", "carrier": "wind", "marginal_cost": 0}
    )
    frag = {
        "sheets": {
            "carriers": [
                {"name": "gas", "co2_emissions": 0.25, "fuel_cost_thermal": 30}
            ]
        },
        "provenance": {"database_id": "fuel_prices"},
    }
    out = merge_fragment(model, frag)
    assert out["carriers"][0]["co2_emissions"] == 0.25
    mc = {g["name"]: g.get("marginal_cost") for g in out["generators"]}
    # no efficiency → 1; efficiency 0.5 → 60; other carriers untouched
    assert mc == {"gas": 30.0, "gas_eff": 60.0, "w": 0}


def test_snapshots_union_and_temporal_padding() -> None:
    frag = {
        "snapshots": ["2024-01-01T01:00:00", "2024-01-01T02:00:00"],
        "sheets": {
            "generators": [{"name": "solar", "bus": "b1"}],
            "generators-p_max_pu": [
                {"snapshot": "2024-01-01T01:00:00", "solar": 0.5},
                {"snapshot": "2024-01-01T02:00:00", "solar": 0.7},
            ],
            "loads-p_set": [{"snapshot": "2024-01-01T02:00:00", "load2": 5}],
        },
    }
    out = merge_fragment(_model(), frag)
    assert [r["snapshot"] for r in out["snapshots"]] == [
        "2024-01-01T00:00:00",
        "2024-01-01T01:00:00",
        "2024-01-01T02:00:00",
    ]
    pmax = {r["snapshot"]: r.get("solar") for r in out["generators-p_max_pu"]}
    # hours the import doesn't cover pad with 1.0 (no curtailment)
    assert pmax == {
        "2024-01-01T00:00:00": 1.0,
        "2024-01-01T01:00:00": 0.5,
        "2024-01-01T02:00:00": 0.7,
    }
    loads = {r["snapshot"]: r for r in out["loads-p_set"]}
    # existing load profile is kept; the new load constant-extends
    assert loads["2024-01-01T00:00:00"] == {
        "snapshot": "2024-01-01T00:00:00",
        "load1": 10,
        "load2": 5,
    }
    assert loads["2024-01-01T01:00:00"]["load1"] == 12
    assert "load1" not in loads["2024-01-01T02:00:00"]


def test_renamed_component_keeps_its_profile_column() -> None:
    frag = {
        "snapshots": ["2024-01-01T00:00:00"],
        "sheets": {
            "generators": [{"name": "gas", "bus": "b1"}],
            "generators-p_max_pu": [{"snapshot": "2024-01-01T00:00:00", "gas": 0.3}],
        },
    }
    out = merge_fragment(_model(), frag)
    row = out["generators-p_max_pu"][0]
    assert row.get("gas_2") == 0.3 and "gas" not in row


def test_provenance_row_is_appended_and_input_untouched() -> None:
    model = _model()
    before = {k: list(v) for k, v in model.items()}
    out = merge_fragment(
        model, {"sheets": {}, "provenance": {"database_id": "osm", "country_iso": "KR"}}
    )
    assert out[PROVENANCE_SHEET][-1]["database_id"] == "osm"
    assert out[PROVENANCE_SHEET][-1]["kind"] == "data-import"
    assert model == before
