"""Tests for the server-side session store (backend/app/session_store.py).

Exercises save → meta → page → series-window (incl. downsample correctness) →
full-model round-trip → clear against a temporary SESSION_DIR so nothing touches
the real backend/data/session.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.app import session_store


@pytest.fixture()
def _session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "session"
    monkeypatch.setattr(session_store, "SESSION_DIR", target)
    return target


def _model(n_snapshots: int = 10) -> dict[str, list[dict]]:
    """Tiny model: 2 static sheets + snapshots + one time-series sheet.

    The series column ``g1`` carries values 0..n-1 so downsample maths is exact.
    """
    snaps = [{"snapshot": f"2030-01-01T{h:02d}:00:00"} for h in range(n_snapshots)]
    return {
        "buses": [{"name": "B1", "v_nom": 380.0}, {"name": "B2", "v_nom": 220.0}],
        "generators": [
            {"name": "g1", "bus": "B1", "carrier": "wind", "p_nom": 100.0},
            {"name": "g2", "bus": "B2", "carrier": "gas", "p_nom": 50.0},
            {"name": "g3", "bus": "B2", "carrier": "solar", "p_nom": 25.0},
        ],
        "snapshots": snaps,
        "generators-p_max_pu": [
            {"snapshot": snaps[i]["snapshot"], "g1": float(i), "g2": float(i) * 2.0}
            for i in range(n_snapshots)
        ],
    }


def test_save_model_builds_meta(_session_dir: Path) -> None:
    meta = session_store.save_model("default", _model(), filename="case.xlsx", scenario_name="ref")
    assert meta["filename"] == "case.xlsx"
    assert meta["scenarioName"] == "ref"
    assert meta["snapshotCount"] == 10
    assert meta["scenarioYear"] == 2030
    assert meta["componentCounts"] == {"buses": 2, "generators": 3}
    kinds = {s["name"]: s["kind"] for s in meta["sheets"]}
    assert kinds["generators"] == "static"
    assert kinds["snapshots"] == "static"
    assert kinds["generators-p_max_pu"] == "series"


def test_is_series_sheet_classification() -> None:
    assert session_store.is_series_sheet("generators-p_max_pu")
    assert session_store.is_series_sheet("loads-p_set")
    assert not session_store.is_series_sheet("snapshots")
    assert not session_store.is_series_sheet("generators")


def test_get_sheet_page_static_pagination(_session_dir: Path) -> None:
    session_store.save_model("default", _model())
    page = session_store.get_sheet_page("default", "generators", offset=1, limit=1)
    assert page is not None
    assert page["total"] == 3
    assert page["offset"] == 1
    assert len(page["rows"]) == 1
    assert page["rows"][0]["name"] == "g2"
    assert "carrier" in page["columns"]


def test_get_sheet_page_missing_returns_none(_session_dir: Path) -> None:
    session_store.save_model("default", _model())
    assert session_store.get_sheet_page("default", "nope") is None


def test_series_window_full_no_downsample(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    win = session_store.get_series_window("default", "generators-p_max_pu", max_points=100)
    assert win is not None
    assert win["total"] == 10
    assert win["returned"] == 10
    assert win["indexCol"] == "snapshot"
    g1 = [row["g1"] for row in win["rows"]]
    np.testing.assert_allclose(g1, np.arange(10.0))


def test_series_window_column_subset(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    win = session_store.get_series_window(
        "default", "generators-p_max_pu", columns=["g1"], max_points=100
    )
    assert win is not None
    assert set(win["columns"]) == {"snapshot", "g1"}
    assert "g2" not in win["columns"]


def test_series_window_slice(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    win = session_store.get_series_window(
        "default", "generators-p_max_pu", start=2, end=5, max_points=100
    )
    assert win is not None
    assert win["window"] == {"start": 2, "end": 5}
    np.testing.assert_allclose([r["g1"] for r in win["rows"]], [2.0, 3.0, 4.0])


def test_downsample_mean(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    win = session_store.get_series_window(
        "default", "generators-p_max_pu", max_points=5, agg="mean"
    )
    assert win is not None and win["returned"] == 5
    # arange(10) split into 5 contiguous buckets of 2 -> bucket means.
    np.testing.assert_allclose([r["g1"] for r in win["rows"]], [0.5, 2.5, 4.5, 6.5, 8.5])
    np.testing.assert_allclose([r["g2"] for r in win["rows"]], [1.0, 5.0, 9.0, 13.0, 17.0])


def test_downsample_point_max_min(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    pt = session_store.get_series_window("default", "generators-p_max_pu", max_points=5, agg="point")
    mx = session_store.get_series_window("default", "generators-p_max_pu", max_points=5, agg="max")
    mn = session_store.get_series_window("default", "generators-p_max_pu", max_points=5, agg="min")
    assert pt and mx and mn
    np.testing.assert_allclose([r["g1"] for r in pt["rows"]], [0.0, 2.0, 4.0, 6.0, 8.0])
    np.testing.assert_allclose([r["g1"] for r in mx["rows"]], [1.0, 3.0, 5.0, 7.0, 9.0])
    np.testing.assert_allclose([r["g1"] for r in mn["rows"]], [0.0, 2.0, 4.0, 6.0, 8.0])


def test_invalid_agg_falls_back_to_mean(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    win = session_store.get_series_window(
        "default", "generators-p_max_pu", max_points=5, agg="bogus"  # type: ignore[arg-type]
    )
    assert win is not None and win["agg"] == "mean"


def test_series_window_on_static_returns_none(_session_dir: Path) -> None:
    session_store.save_model("default", _model())
    assert session_store.get_series_window("default", "generators") is None


def test_load_full_model_roundtrip(_session_dir: Path) -> None:
    original = _model(10)
    session_store.save_model("default", original)
    restored = session_store.load_full_model("default")
    assert restored is not None
    assert {r["name"] for r in restored["generators"]} == {"g1", "g2", "g3"}
    np.testing.assert_allclose(
        [r["g1"] for r in restored["generators-p_max_pu"]], np.arange(10.0)
    )


def test_load_full_model_static_only_excludes_series(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    full = session_store.load_full_model("default")
    static = session_store.load_full_model("default", static_only=True)
    assert full is not None and "generators-p_max_pu" in full
    assert static is not None and "generators-p_max_pu" not in static
    assert "generators" in static and "snapshots" in static


def test_merge_static_keeps_series(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    # Merge an edited static sheet; the heavy series must survive untouched.
    edited = {"generators": [{"name": "g1", "p_nom": 999.0}], "snapshots": [{"snapshot": "x"}] * 10}
    meta = session_store.merge_static_model("default", edited)
    assert meta is not None
    page = session_store.get_sheet_page("default", "generators")
    assert page is not None and page["rows"][0]["p_nom"] == 999.0
    # Series still intact.
    win = session_store.get_series_window("default", "generators-p_max_pu", max_points=100)
    assert win is not None and win["total"] == 10


def test_merge_static_ignores_series_sheets_in_payload(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    # A series sheet in the merge payload must be ignored (series are PATCH-only).
    session_store.merge_static_model(
        "default", {"generators-p_max_pu": [{"snapshot": "z", "g1": -1.0}]}
    )
    win = session_store.get_series_window("default", "generators-p_max_pu", max_points=100)
    assert win is not None and win["total"] == 10 and win["rows"][0]["g1"] == 0.0


def test_clear_and_has_model(_session_dir: Path) -> None:
    session_store.save_model("default", _model())
    assert session_store.has_model("default")
    assert session_store.clear("default") is True
    assert not session_store.has_model("default")
    assert session_store.get_meta("default") is None
    assert session_store.clear("default") is False  # already gone


def test_save_replaces_previous_model(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    session_store.save_model("default", _model(4))
    meta = session_store.get_meta("default")
    assert meta is not None and meta["snapshotCount"] == 4


def test_unsafe_session_id_rejected(_session_dir: Path) -> None:
    with pytest.raises(ValueError):
        session_store.save_model("../escape", _model())
    assert session_store.get_meta("../escape") is None


def test_patch_sheet_set_cell(_session_dir: Path) -> None:
    session_store.save_model("default", _model())
    res = session_store.patch_sheet(
        "default", "generators", [{"op": "set", "row": 0, "column": "p_nom", "value": 250.0}]
    )
    assert res is not None and res["total"] == 3
    page = session_store.get_sheet_page("default", "generators")
    assert page is not None and page["rows"][0]["p_nom"] == 250.0


def test_patch_sheet_add_and_delete_rows(_session_dir: Path) -> None:
    session_store.save_model("default", _model())
    session_store.patch_sheet(
        "default", "generators", [{"op": "addRow", "values": {"name": "g4", "carrier": "bio"}}]
    )
    page = session_store.get_sheet_page("default", "generators")
    assert page is not None and page["total"] == 4 and page["rows"][3]["name"] == "g4"
    # Delete the first two rows.
    session_store.patch_sheet("default", "generators", [{"op": "deleteRows", "rows": [0, 1]}])
    page = session_store.get_sheet_page("default", "generators")
    assert page is not None and page["total"] == 2
    assert {r["name"] for r in page["rows"]} == {"g3", "g4"}


def test_patch_series_sheet_set_cell(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    res = session_store.patch_sheet(
        "default", "generators-p_max_pu", [{"op": "set", "row": 2, "column": "g1", "value": 99.0}]
    )
    assert res is not None and res["kind"] == "series"
    win = session_store.get_series_window("default", "generators-p_max_pu", max_points=100)
    assert win is not None and win["rows"][2]["g1"] == 99.0


def test_patch_snapshots_updates_meta_count(_session_dir: Path) -> None:
    session_store.save_model("default", _model(10))
    session_store.patch_sheet("default", "snapshots", [{"op": "deleteRows", "rows": [9]}])
    meta = session_store.get_meta("default")
    assert meta is not None and meta["snapshotCount"] == 9


def test_patch_sheet_missing_returns_none(_session_dir: Path) -> None:
    session_store.save_model("default", _model())
    assert session_store.patch_sheet("default", "nope", [{"op": "set", "row": 0, "column": "x", "value": 1}]) is None


def test_controls_roundtrip(_session_dir: Path) -> None:
    session_store.save_model("default", _model())
    session_store.save_controls("default", {"carbonPrice": 50, "snapshotStart": 0})
    assert session_store.get_controls("default") == {"carbonPrice": 50, "snapshotStart": 0}
