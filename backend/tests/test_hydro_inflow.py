"""I4 hydro inflow — target resolution, scaling, shape expansion."""
from __future__ import annotations

import pytest

from backend.app.importers.databases.openmeteo_renewable.inflow import (
    build_inflow_rows,
    is_hydro_carrier,
    resolve_hydro_targets,
)

MODEL = {
    "buses": [{"name": "b1", "x": 127.5, "y": 37.5}],
    "storage_units": [
        {"name": "dam1", "bus": "b1", "carrier": "hydro", "p_nom": 100},          # bus coords
        {"name": "ror1", "bus": "b1", "carrier": "ror", "p_nom": 50, "x": 128.0, "y": 36.0},
        {"name": "phs1", "bus": "b1", "carrier": "PHS", "p_nom": 200},            # excluded
        {"name": "batt", "bus": "b1", "carrier": "battery", "p_nom": 30},         # not hydro
        {"name": "dry", "bus": "nope", "carrier": "hydro", "p_nom": 80},          # no coords
    ],
}


def test_carrier_classification() -> None:
    assert is_hydro_carrier("hydro") and is_hydro_carrier("Hydro_Reservoir") and is_hydro_carrier("ror")
    assert not is_hydro_carrier("PHS") and not is_hydro_carrier("pumped_hydro")
    assert not is_hydro_carrier("battery")


def test_resolve_targets_coord_chain_and_exclusions() -> None:
    targets, skipped = resolve_hydro_targets(MODEL)
    names = {t[0] for t in targets}
    assert names == {"dam1", "ror1"}           # PHS + battery excluded
    assert skipped == ["dry"]                  # hydro but no resolvable coords
    dam = next(t for t in targets if t[0] == "dam1")
    assert dam[1] == 100 and dam[2] == 37.5 and dam[3] == 127.5  # p_nom + bus coords


def test_explicit_carriers_override_name_hint() -> None:
    # A custom carrier the substring classifier can't recognise is picked up
    # when the user selects it explicitly (the Forge "Hydro carriers" picker).
    model = {
        "buses": [{"name": "b", "x": 127.5, "y": 37.5}],
        "storage_units": [
            {"name": "dam", "bus": "b", "carrier": "\uc218\ub825", "p_nom": 100},  # non-English name
            {"name": "batt", "bus": "b", "carrier": "battery", "p_nom": 50},
        ],
    }
    assert resolve_hydro_targets(model)[0] == []                 # name-hint misses it
    picked, _ = resolve_hydro_targets(model, ["\uc218\ub825"])  # explicit selection
    assert [t[0] for t in picked] == ["dam"]
    # Explicit selection is exact: a battery carrier is never swept in even if listed elsewhere.
    picked2, _ = resolve_hydro_targets(model, ["\uc218\ub825", "battery"])
    assert sorted(t[0] for t in picked2) == ["batt", "dam"]


def test_inflow_scaled_to_target_cf_and_daily_expansion() -> None:
    targets, _ = resolve_hydro_targets({
        "buses": [{"name": "b", "x": 127.5, "y": 37.5}],
        "storage_units": [{"name": "dam", "bus": "b", "carrier": "hydro", "p_nom": 100}],
    })
    key = "37.5,127.5"
    discharge = {key: {"time": ["2019-01-01", "2019-01-02"], "discharge": [10.0, 30.0]}}
    rows, snapshots, attached, notes = build_inflow_rows(targets, discharge, target_cf=0.4)
    assert attached == ["dam"] and notes == []
    assert len(rows) == 48                      # 2 days × 24 h
    # Window mean == cf × p_nom = 40 MW; day-2 (3× day-1 discharge) = 60 MW.
    vals = [r["dam"] for r in rows]
    assert sum(vals) / len(vals) == pytest.approx(40.0, rel=1e-6)
    assert vals[0] == pytest.approx(20.0, rel=1e-6)   # 40 × 10/20
    assert vals[24] == pytest.approx(60.0, rel=1e-6)  # 40 × 30/20
    assert rows[0]["snapshot"] == "2019-01-01 00:00"


def test_dry_series_falls_back_flat_with_note() -> None:
    targets = [("dam", 100.0, 37.5, 127.5)]
    discharge = {"37.5,127.5": {"time": ["2019-01-01"], "discharge": [0.0]}}
    rows, _, attached, notes = build_inflow_rows(targets, discharge, target_cf=0.35)
    assert attached == ["dam"]
    assert all(r["dam"] == pytest.approx(35.0) for r in rows)
    assert any("dry" in n for n in notes)


def test_utc_offset_shifts_labels() -> None:
    targets = [("dam", 10.0, 37.5, 127.5)]
    discharge = {"37.5,127.5": {"time": ["2019-01-01"], "discharge": [5.0]}}
    rows, _, _, _ = build_inflow_rows(targets, discharge, utc_offset=9)
    assert rows[0]["snapshot"] == "2019-01-01 09:00"  # KST shift
