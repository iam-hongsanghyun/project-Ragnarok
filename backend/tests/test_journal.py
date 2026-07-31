"""Mutation-journal tests (Bifrost Phase 1) — capture, diff, NaN semantics, undo.

Runs the journal against the real sqlite store in an isolated tmp session dir.
The facade wrappers are installed once (idempotent, same as production) and the
originals restored per-test isn't needed: wrapping is the production shape.
"""
from __future__ import annotations


import pytest

from backend.app import journal, model_store
from backend.app import session_store as ss

SID = "jtest"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setenv("RAGNAROK_JOURNAL_DIR", str(tmp_path / "journal"))
    journal.wrap_model_store()
    yield


def _base_model() -> dict:
    return {
        "buses": [
            {"name": "b1", "v_nom": 380.0, "carrier": "AC"},
            {"name": "b2", "v_nom": 220.0, "carrier": "AC"},
        ],
        "generators": [
            {"name": "g1", "bus": "b1", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 50.0},
        ],
        "snapshots": [{"snapshot": "2030-01-01 00:00"}, {"snapshot": "2030-01-01 01:00"}],
        "loads-p_set": [
            {"snapshot": "2030-01-01 00:00", "l1": 10.0},
            {"snapshot": "2030-01-01 01:00", "l1": 12.0},
        ],
    }


def _load() -> None:
    model_store.save_model(SID, _base_model())


# ── recording ───────────────────────────────────────────────────────────────────


def test_save_model_records_model_replace() -> None:
    _load()
    entries = journal.list_entries(SID)
    assert len(entries) == 1
    e = entries[0]
    assert e["kind"] == "model-replace"
    assert e["actor"] == "system"  # no HTTP context in unit tests
    assert e["version"] == 1
    names = {s["name"] for s in e["sheets"]}
    assert {"buses", "generators", "snapshots", "loads-p_set"} <= names
    assert journal.current_version(SID) == 1


def test_patch_records_one_entry_with_cell_diffs() -> None:
    _load()
    model_store.patch_sheet(SID, "generators", [
        {"op": "set", "row": 0, "column": "p_nom", "value": 250.0},
        {"op": "addRow", "values": {"name": "g2", "bus": "b2", "carrier": "solar", "p_nom": 50.0}},
    ])
    entries = journal.list_entries(SID)
    assert len(entries) == 2
    e = entries[0]  # newest first
    assert e["kind"] == "patch"
    assert e["sheets"][0]["rowsBefore"] == 1 and e["sheets"][0]["rowsAfter"] == 2
    diff = journal.entry_diff(SID, e["id"])
    assert diff["detail"]["cellDiffs"] == [
        {"row": 0, "column": "p_nom", "before": 100.0, "after": 250.0}
    ]


def test_nan_set_produces_no_phantom_diff() -> None:
    _load()
    model_store.patch_sheet(SID, "generators", [
        {"op": "set", "row": 0, "column": "p_min_pu", "value": None},  # unset → unset
    ])
    e = journal.list_entries(SID)[0]
    diff = journal.entry_diff(SID, e["id"])
    assert diff["detail"]["cellDiffs"] == []  # None == absent == NaN for diffs


def test_values_equal_nan_semantics() -> None:
    assert journal.values_equal(float("nan"), float("nan"))
    assert journal.values_equal(None, float("nan"))
    assert journal.values_equal(1, 1.0)
    assert not journal.values_equal(1.0, 2.0)
    assert not journal.values_equal(None, 0.0)


def test_transform_series_records_summary_not_cells() -> None:
    _load()
    model_store.transform_series(SID, "loads-p_set", "scale", {"factor": 2.0, "columns": ["l1"]})
    e = journal.list_entries(SID)[0]
    assert e["kind"] == "series-transform"
    detail = journal.entry_diff(SID, e["id"])["detail"]
    assert detail["columnsBefore"]["l1"]["sum"] == pytest.approx(22.0)
    assert detail["columnsAfter"]["l1"]["sum"] == pytest.approx(44.0)


def test_clear_records_entry() -> None:
    _load()
    model_store.clear(SID)
    e = journal.list_entries(SID)[0]
    assert e["kind"] == "clear"
    assert e["undo"]["strategy"] == "model-snapshot"


# ── inverse ops ─────────────────────────────────────────────────────────────────


def test_inverse_ops_roundtrip_with_index_shifts() -> None:
    before = [{"name": "a", "x": 1.0}, {"name": "b", "x": 2.0}, {"name": "c", "x": 3.0}]
    ops = [
        {"op": "set", "row": 1, "column": "x", "value": 99.0},
        {"op": "deleteRows", "rows": [0, 2]},
        {"op": "addRow", "values": {"name": "d", "x": 4.0}, "index": 0},
    ]
    after = ss._apply_ops(before, ops)
    inverse, _ = journal.inverse_patch_ops(before, ops)
    assert ss._apply_ops(after, inverse) == before


# ── undo / revert ───────────────────────────────────────────────────────────────


def test_undo_patch_restores_exact_rows() -> None:
    _load()
    orig_rows = model_store.get_sheet_page(SID, "generators", limit=1000)["rows"]
    model_store.patch_sheet(SID, "generators", [
        {"op": "set", "row": 0, "column": "p_nom", "value": 999.0},
        {"op": "addRow", "values": {"name": "gX", "bus": "b1", "carrier": "wind", "p_nom": 5.0}},
    ])
    entry_id = journal.list_entries(SID)[0]["id"]
    result = journal.undo(SID, entry_id)
    assert result["undone"] == [entry_id]
    assert model_store.get_sheet_page(SID, "generators", limit=1000)["rows"] == orig_rows
    # The undo itself is journaled as a revert entry.
    assert journal.list_entries(SID)[0]["kind"] == "revert"


def test_redo_via_undoing_the_revert() -> None:
    _load()
    model_store.patch_sheet(SID, "generators", [
        {"op": "set", "row": 0, "column": "p_nom", "value": 777.0},
    ])
    patched = model_store.get_sheet_page(SID, "generators", limit=1000)["rows"]
    entry_id = journal.list_entries(SID)[0]["id"]
    journal.undo(SID, entry_id)
    revert_id = journal.list_entries(SID)[0]["id"]
    journal.undo(SID, revert_id)  # redo
    assert model_store.get_sheet_page(SID, "generators", limit=1000)["rows"] == patched


def test_undo_snapshot_after_transform() -> None:
    _load()
    orig = model_store.get_sheet_page(SID, "loads-p_set", limit=1000)["rows"]
    model_store.transform_series(SID, "loads-p_set", "scale", {"factor": 3.0})
    entry_id = journal.list_entries(SID)[0]["id"]
    journal.undo(SID, entry_id)
    rows = model_store.get_sheet_page(SID, "loads-p_set", limit=1000)["rows"]
    assert [r["l1"] for r in rows] == [r["l1"] for r in orig]


def test_undo_model_snapshot_after_save_model() -> None:
    _load()
    model2 = _base_model()
    model2["buses"].append({"name": "b3", "v_nom": 110.0, "carrier": "AC"})
    model_store.save_model(SID, model2)
    entry_id = journal.list_entries(SID)[0]["id"]
    journal.undo(SID, entry_id)
    rows = model_store.get_sheet_page(SID, "buses", limit=1000)["rows"]
    assert len(rows) == 2  # back to the original two buses


def test_undo_blocked_by_later_overlapping_entry() -> None:
    _load()
    model_store.patch_sheet(SID, "generators", [{"op": "set", "row": 0, "column": "p_nom", "value": 1.0}])
    first = journal.list_entries(SID)[0]["id"]
    model_store.patch_sheet(SID, "generators", [{"op": "set", "row": 0, "column": "p_nom", "value": 2.0}])
    with pytest.raises(journal.ConflictError):
        journal.undo(SID, first)


def test_undo_allowed_when_later_entry_disjoint() -> None:
    _load()
    model_store.patch_sheet(SID, "generators", [{"op": "set", "row": 0, "column": "p_nom", "value": 1.0}])
    gen_entry = journal.list_entries(SID)[0]["id"]
    model_store.patch_sheet(SID, "buses", [{"op": "set", "row": 0, "column": "v_nom", "value": 500.0}])
    journal.undo(SID, gen_entry)  # different sheet → allowed
    rows = model_store.get_sheet_page(SID, "generators", limit=1000)["rows"]
    assert rows[0]["p_nom"] == 100.0


def test_revert_to_version() -> None:
    _load()  # v1
    model_store.patch_sheet(SID, "generators", [{"op": "set", "row": 0, "column": "p_nom", "value": 1.0}])  # v2
    model_store.patch_sheet(SID, "buses", [{"op": "set", "row": 0, "column": "v_nom", "value": 500.0}])  # v3
    model_store.transform_series(SID, "loads-p_set", "scale", {"factor": 2.0})  # v4
    result = journal.revert_to(SID, 1)
    assert result["undone"] == [4, 3, 2]
    assert model_store.get_sheet_page(SID, "generators", limit=1000)["rows"][0]["p_nom"] == 100.0
    assert model_store.get_sheet_page(SID, "buses", limit=1000)["rows"][0]["v_nom"] == 380.0
    assert [r["l1"] for r in model_store.get_sheet_page(SID, "loads-p_set", limit=1000)["rows"]] == [10.0, 12.0]


def test_merge_static_records_and_none_when_empty() -> None:
    assert model_store.merge_static_model(SID, {"buses": [{"name": "x"}]}) is None
    assert journal.list_entries(SID) == []  # no phantom entry for a no-op
    _load()
    model_store.merge_static_model(SID, {"buses": [{"name": "only"}]})
    e = journal.list_entries(SID)[0]
    assert e["kind"] == "model-replace"


def test_retention_entry_cap(monkeypatch) -> None:
    monkeypatch.setattr(journal, "_MAX_ENTRIES", 5)
    _load()
    for i in range(8):
        model_store.patch_sheet(SID, "generators", [
            {"op": "set", "row": 0, "column": "p_nom", "value": float(i)},
        ])
    entries = journal.list_entries(SID, limit=100)
    assert len(entries) == 5
    assert journal.current_version(SID) == 9  # version keeps counting


def test_large_inverse_spills_to_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(journal, "_INLINE_UNDO_LIMIT", 64)
    _load()
    model_store.patch_sheet(SID, "buses", [
        {"op": "addRow", "values": {"name": f"n{i}", "v_nom": float(i)}} for i in range(20)
    ])
    entry_id = journal.list_entries(SID)[0]["id"]
    journal.undo(SID, entry_id)  # applies the spilled inverse from the snapshot
    assert len(model_store.get_sheet_page(SID, "buses", limit=1000)["rows"]) == 2
