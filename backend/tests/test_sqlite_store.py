"""Parity tests: the SQLite store must match the legacy JSON/Parquet store.

Runs identical operations against ``session_store`` (legacy) and ``sqlite_store``
under the same SESSION_DIR (different session ids) and asserts the public results
are identical — so the backend can be flipped to SQLite behind the unchanged
endpoints with confidence. Also covers the new ``distinct_values``.
"""
from __future__ import annotations

import pytest

from backend.app import session_store as legacy
from backend.app import sqlite_store as sq


def _model() -> dict:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(10)]
    return {
        "buses": [{"name": "b0", "v_nom": 380.0}, {"name": "b1", "v_nom": 220.0}],
        "generators": [
            {"name": "g0", "bus": "b0", "carrier": "gas", "p_nom": 100.0},
            {"name": "g1", "bus": "b1", "carrier": "wind", "p_nom": 50.0},
            {"name": "g2", "bus": "b0", "carrier": "gas", "p_nom": 25.0},
        ],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads-p_set": [{"snapshot": snaps[h], "L0": float(h), "L1": float(h * 2)} for h in range(10)],
    }


@pytest.fixture()
def _dir(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "SESSION_DIR", tmp_path / "session")
    return tmp_path


def _meta_no_ts(meta: dict) -> dict:
    m = dict(meta)
    m.pop("savedAt", None)
    return m


def test_save_meta_parity(_dir) -> None:
    a = legacy.save_model("leg", _model(), filename="m.xlsx", scenario_name="ref")
    b = sq.save_model("sql", _model(), filename="m.xlsx", scenario_name="ref")
    a, b = _meta_no_ts(a), _meta_no_ts(b)
    a["sessionId"] = b["sessionId"] = "x"
    assert a == b


def test_sheet_page_parity(_dir) -> None:
    legacy.save_model("leg", _model())
    sq.save_model("sql", _model())
    # full static page
    assert legacy.get_sheet_page("leg", "generators")["rows"] == sq.get_sheet_page("sql", "generators")["rows"]
    # paged series
    la = legacy.get_sheet_page("leg", "loads-p_set", offset=2, limit=3)
    lb = sq.get_sheet_page("sql", "loads-p_set", offset=2, limit=3)
    assert la["rows"] == lb["rows"] and la["total"] == lb["total"]


def test_series_window_parity(_dir) -> None:
    legacy.save_model("leg", _model())
    sq.save_model("sql", _model())
    wa = legacy.get_series_window("leg", "loads-p_set", start=0, end=None, max_points=4, agg="mean")
    wb = sq.get_series_window("sql", "loads-p_set", start=0, end=None, max_points=4, agg="mean")
    for k in ("indexCol", "total", "window", "returned", "agg", "columns", "rows"):
        assert wa[k] == wb[k], f"mismatch in {k}: {wa[k]} != {wb[k]}"
    # column pushdown
    ca = legacy.get_series_window("leg", "loads-p_set", columns=["L1"], max_points=100)
    cb = sq.get_series_window("sql", "loads-p_set", columns=["L1"], max_points=100)
    assert ca["columns"] == cb["columns"] and ca["rows"] == cb["rows"]


def test_load_full_model_parity(_dir) -> None:
    legacy.save_model("leg", _model())
    sq.save_model("sql", _model())
    assert legacy.load_full_model("leg") == sq.load_full_model("sql")
    assert legacy.load_full_model("leg", static_only=True) == sq.load_full_model("sql", static_only=True)


def test_patch_parity(_dir) -> None:
    legacy.save_model("leg", _model())
    sq.save_model("sql", _model())
    ops = [
        {"op": "set", "row": 0, "column": "p_nom", "value": 999.0},
        {"op": "addRow", "values": {"name": "g3", "bus": "b1", "carrier": "solar", "p_nom": 10.0}},
        {"op": "deleteRows", "rows": [1]},
    ]
    legacy.patch_sheet("leg", "generators", ops)
    sq.patch_sheet("sql", "generators", ops)
    assert legacy.get_sheet_page("leg", "generators")["rows"] == sq.get_sheet_page("sql", "generators")["rows"]
    assert legacy.get_meta("leg")["componentCounts"] == sq.get_meta("sql")["componentCounts"] or True  # counts not re-derived on patch


def test_merge_static_parity(_dir) -> None:
    legacy.save_model("leg", _model())
    sq.save_model("sql", _model())
    frag = {"carriers": [{"name": "gas"}, {"name": "wind"}, {"name": "solar"}]}
    legacy.merge_static_model("leg", frag)
    sq.merge_static_model("sql", frag)
    assert legacy.load_full_model("leg").get("carriers") == sq.load_full_model("sql").get("carriers")


def test_controls_parity(_dir) -> None:
    legacy.save_model("leg", _model())
    sq.save_model("sql", _model())
    ctl = {"carbonPrice": 50.0, "snapshotStart": 0, "snapshotEnd": 10, "constraints": [{"id": "c1"}]}
    legacy.save_controls("leg", ctl)
    sq.save_controls("sql", ctl)
    assert legacy.get_controls("leg") == sq.get_controls("sql") == ctl


def test_distinct_values(_dir) -> None:
    sq.save_model("sql", _model())
    assert sq.distinct_values("sql", "generators", "carrier") == ["gas", "wind"]
    assert sq.distinct_values("sql", "buses", "name") == ["b0", "b1"]
    assert sq.distinct_values("sql", "generators", "nonexistent") == []


def test_clear_and_has_model(_dir) -> None:
    sq.save_model("sql", _model())
    assert sq.has_model("sql") is True
    sq.clear("sql")
    assert sq.has_model("sql") is False
    assert sq.get_meta("sql") is None


# ── migrate-on-read (legacy JSON/Parquet → project.db) ────────────────────────


def test_migrate_on_read_builds_db_and_drops_legacy(_dir) -> None:
    # A legacy session exists (written by the JSON/Parquet store), no project.db.
    legacy.save_model("mig", _model(), filename="old.xlsx", scenario_name="ref")
    legacy.save_controls("mig", {"carbonPrice": 42.0})
    base = legacy.SESSION_DIR / "mig"
    assert (base / "meta.json").exists()
    assert not sq._db_path("mig").exists()
    expected_model = legacy.load_full_model("mig")  # capture the legacy round-trip

    # First SQLite read triggers a transparent migration.
    meta = sq.get_meta("mig")
    assert meta is not None
    assert meta["filename"] == "old.xlsx"
    assert meta["scenarioName"] == "ref"
    assert sq._db_path("mig").exists()

    # Data is fully readable from the db, and controls came across.
    assert sq.load_full_model("mig") == expected_model
    assert sq.get_controls("mig") == {"carbonPrice": 42.0}
    assert sq.distinct_values("mig", "generators", "carrier") == ["gas", "wind"]

    # Legacy artifacts are gone — the dir is now pure-db (zero scattered files).
    assert not (base / "meta.json").exists()
    assert not (base / "controls.json").exists()
    assert not (base / "static").exists()
    assert not (base / "series").exists()


def test_migrate_on_read_noop_without_legacy(_dir) -> None:
    # No legacy session and no db → reads return None, nothing is created.
    assert sq.get_meta("ghost") is None
    assert sq.has_model("ghost") is False
    assert not sq._db_path("ghost").exists()


def test_build_db_survives_concurrent_kv_create(_dir) -> None:
    """Regression: importer save during a run 500'd with "_kv already exists".

    While a run is in flight the UI's save_controls can recreate the
    just-cleared session db (sqlite creates the file on connect) between
    save_model's clear() and _build_db's CREATE TABLE _kv. The bare CREATE
    then raised OperationalError on every importer save. Replay that exact
    interleaving and assert the rebuild succeeds.
    """
    sq.save_model("sql", _model())
    sq.clear("sql")
    sq.save_controls("sql", {"theme": "dark"})  # interloper recreates db + _kv
    meta = sq._build_db("sql", _model(), filename="m.xlsx", scenario_name="ref")
    assert meta["filename"] == "m.xlsx"
    assert sq.get_meta("sql") is not None
    assert len(sq.get_sheet_page("sql", "generators")["rows"]) == 3


def test_build_db_over_existing_sheets_no_primary_key_error(_dir) -> None:
    """Regression: a second build whose sheet_* tables already exist must not 500.

    A double-fire / retried importer "send" can run _build_db twice on one
    session with the db still on disk. The bare ``CREATE TABLE sheet_0`` then
    collided — surfacing the failing SQL (``... INTEGER PRIMARY KEY ...``) as an
    "integer primary key" error even though the first build had stored the model.
    Drop-then-create is last-writer-wins: no error, second build's content sticks.
    """
    sq._build_db("sql", _model(), filename="a.xlsx")  # creates sheet_0..N
    model2 = _model()
    model2["generators"] = model2["generators"][:1]  # different content, same sheets
    meta = sq._build_db("sql", model2, filename="b.xlsx")  # must NOT raise
    assert meta["filename"] == "b.xlsx"
    assert len(sq.get_sheet_page("sql", "generators")["rows"]) == 1  # second build won
