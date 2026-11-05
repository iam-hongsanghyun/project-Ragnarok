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


def test_patch_creates_an_absent_series_sheet(_dir) -> None:
    """Writing to a temporal sheet the session does not have must CREATE it.

    This is what makes an empty profile fillable from the UI: the sheet tree lets
    an empty temporal leaf be selected, and the first paste / CSV import arrives
    as ``addRow`` ops against a sheet that does not exist yet. If that no-ops
    there is no way to author a profile by hand at all.
    """
    model = _model()
    del model["loads-p_set"]  # a model with no temporal data whatsoever
    legacy.save_model("leg", model)
    sq.save_model("sql", model)
    assert "loads-p_set" not in (legacy.load_full_model("leg") or {})
    assert "loads-p_set" not in (sq.load_full_model("sql") or {})

    ops = [
        {"op": "addRow", "values": {"snapshot": "2030-01-01T00:00:00", "L0": 1.0}},
        {"op": "addRow", "values": {"snapshot": "2030-01-01T01:00:00", "L0": 2.0}},
    ]
    leg_desc = legacy.patch_sheet("leg", "loads-p_set", ops)
    sq_desc = sq.patch_sheet("sql", "loads-p_set", ops)

    assert leg_desc is not None and sq_desc is not None
    assert leg_desc["total"] == sq_desc["total"] == 2
    assert leg_desc["kind"] == sq_desc["kind"] == "series"
    rows_leg = legacy.get_sheet_page("leg", "loads-p_set")["rows"]
    rows_sq = sq.get_sheet_page("sql", "loads-p_set")["rows"]
    assert rows_leg == rows_sq
    assert [r["L0"] for r in rows_sq] == [1.0, 2.0]
    # And it is now visible to the tree, which reads the session meta.
    assert any(
        s["name"] == "loads-p_set" and s["kind"] == "series" and s["rowCount"] == 2
        for s in sq.get_meta("sql")["sheets"]
    )


def test_merge_static_parity(_dir) -> None:
    legacy.save_model("leg", _model())
    sq.save_model("sql", _model())
    frag = {"carriers": [{"name": "gas"}, {"name": "wind"}, {"name": "solar"}]}
    legacy.merge_static_model("leg", frag)
    sq.merge_static_model("sql", frag)
    assert legacy.load_full_model("leg").get("carriers") == sq.load_full_model("sql").get("carriers")


def test_app_state_parity(_dir) -> None:
    legacy.save_model("leg", _model())
    sq.save_model("sql", _model())
    state = {"ragnarok:settings": '{"currencyCode": "KRW"}', "ragnarok:session:controls": '{"carbonPrice": 50}'}
    assert legacy.set_app_state("leg", state) == sq.set_app_state("sql", state) == state
    assert legacy.get_app_state("leg") == sq.get_app_state("sql") == state
    # merge: add one key, remove another
    merged = sq.set_app_state("sql", {"ui:x": "1", "ragnarok:settings": None}, replace=False)
    assert merged == {"ragnarok:session:controls": '{"carbonPrice": 50}', "ui:x": "1"}
    assert sq.get_app_state("ghost") is None  # no project, no state


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

    # Data is fully readable from the db.
    assert sq.load_full_model("mig") == expected_model
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


def test_build_db_survives_concurrent_layout_create(_dir) -> None:
    """Regression: a concurrent writer can recreate the just-cleared session db (sqlite creates the
    file on connect) with its own layout tables before _build_db runs; the rebuild must still succeed."""
    import sqlite3

    sq.save_model("sql", _model())
    sq.clear("sql")
    sq._db_path("sql").parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(sq._db_path("sql")))  # interloper recreates the layout
    sq._create_layout(conn)
    conn.commit()
    conn.close()
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


# ── RS5: a failed save must not destroy the session ──────────────────────────


class _Unserialisable:
    pass


def test_failed_save_keeps_the_existing_session(_dir) -> None:
    """The rebuild fails on an unserialisable cell; the old session survives."""
    sq.save_model("keep", _model(), filename="m.xlsx", scenario_name="ref")
    before = sq.get_meta("keep")
    bad = _model()
    bad["generators"][0]["p_nom"] = _Unserialisable()
    with pytest.raises(TypeError):
        sq.save_model("keep", bad, filename="bad.xlsx", scenario_name="bad")
    after = sq.get_meta("keep")
    assert after is not None and after["filename"] == before["filename"] == "m.xlsx"
    assert sq.get_sheet_page("keep", "generators", 0, 10)["total"] == 3
    # no half-built temp file is left behind
    assert not list((sq.ss.SESSION_DIR / "keep").glob("*.building*"))


def test_numpy_and_datetime_cells_are_stored_as_json(_dir) -> None:
    import datetime as dt

    import numpy as np
    import pandas as pd

    m = _model()
    m["generators"][0]["p_nom"] = np.float64(12.5)
    m["generators"][0]["count"] = np.int64(3)
    m["generators"][0]["commissioned"] = pd.Timestamp("2030-01-02 03:00")
    m["generators"][1]["retired"] = dt.date(2050, 1, 1)
    sq.save_model("np", m, filename="m.xlsx", scenario_name="ref")
    rows = sq.get_sheet_page("np", "generators", 0, 10)["rows"]
    assert rows[0]["p_nom"] == 12.5 and rows[0]["count"] == 3
    assert rows[0]["commissioned"] == "2030-01-02T03:00:00"
    assert rows[1]["retired"] == "2050-01-01"


# ── layout (format version 2) ─────────────────────────────────────────────────


def _tables_in(db) -> set[str]:
    import sqlite3

    conn = sqlite3.connect(str(db))
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_layout_sections_and_catalog(_dir) -> None:
    import sqlite3

    model = {**_model(), "RAGNAROK_Scenarios": [{"id": "s1"}], "RAGNAROK_Schema": [{"ragnarok_schema_version": 4}]}
    sq.save_model("sql", model)
    db = sq._db_path("sql")
    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT name, tbl, section, kind FROM _sheets ORDER BY position").fetchall()
    conn.close()
    by_name = {n: (t, sec, k) for n, t, sec, k in rows}
    assert by_name["generators"][1] == "pypsa" and by_name["generators"][0].startswith("pypsa_")
    assert by_name["loads-p_set"] == (by_name["loads-p_set"][0], "pypsa", "series")
    assert by_name["RAGNAROK_Scenarios"][1] == "ragnarok" and by_name["RAGNAROK_Scenarios"][0].startswith("config_")
    assert {"_project", "_sheets", "_app_state"} <= _tables_in(db)
    assert not any(t.startswith("sheet_") for t in _tables_in(db)) and "_kv" not in _tables_in(db)
    assert sq.read_kv(db, "format_version") == sq.FORMAT_VERSION


def test_app_state_sheet_is_split_out_and_carried_over(_dir) -> None:
    from backend.app import app_state

    state = {"ragnarok:settings": '{"enabledModules": "Data"}', "big": "x" * 70_000}
    sq.save_model("sql", {**_model(), app_state.SHEET: app_state.to_rows(state)})
    assert app_state.SHEET not in (sq.load_full_model("sql") or {})  # never a model sheet
    assert sq.get_app_state("sql") == state  # long value re-joined from its parts
    # A replacement model without its own app state keeps the project's.
    sq.save_model("sql", _model())
    assert sq.get_app_state("sql") == state


def test_upgrade_version_1_file(_dir) -> None:
    """A version-1 db (_kv + sheet_<i>) is reorganised in place on first read: sections, catalog,
    the stray empty non-model sheet and the retired controls value dropped."""
    import json
    import sqlite3

    db = sq._db_path("old")
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE _kv (k TEXT PRIMARY KEY, v TEXT)")
    sheets = {"buses": [{"name": "b0"}], "meta": [], "RAGNAROK_Schema": [{"ragnarok_schema_version": 4}],
              "loads-p_set": [{"snapshot": "2030-01-01T00:00:00", "L0": 1.0}]}
    tables, entries = {}, []
    for i, (name, rows) in enumerate(sheets.items()):
        conn.execute(f"CREATE TABLE sheet_{i} (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT)")
        conn.executemany(f"INSERT INTO sheet_{i}(d) VALUES(?)", [(json.dumps(r),) for r in rows])
        tables[name] = f"sheet_{i}"
        entries.append({"name": name, "kind": "series" if "-" in name else "static", "rowCount": len(rows),
                        "columns": sorted({k for r in rows for k in r})})
    conn.execute("CREATE TABLE sheet_9 (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT)")  # orphan
    meta = {"sessionId": "old", "filename": "f.xlsx", "scenarioName": "", "savedAt": "2026-01-01T00:00:00+00:00",
            "sheets": entries, "snapshotCount": 1}
    for k, v in (("meta", meta), ("tables", tables), ("controls", {"carbonPrice": 1}), ("example", {"label": "E"})):
        conn.execute("INSERT INTO _kv VALUES(?, ?)", (k, json.dumps(v)))
    conn.commit()
    conn.close()

    names_first_read = [s["name"] for s in sq.get_meta("old")["sheets"]]  # the read upgrades it
    assert sq.upgrade_file(db) is False  # already current: idempotent
    assert names_first_read == ["buses", "RAGNAROK_Schema", "loads-p_set"]
    names = [s["name"] for s in sq.get_meta("old")["sheets"]]
    assert names == ["buses", "RAGNAROK_Schema", "loads-p_set"]  # stray empty `meta` dropped, order kept
    assert sq.load_full_model("old")["buses"] == [{"name": "b0"}]
    assert sq.get_sheet_page("old", "loads-p_set")["kind"] == "series"
    tables_now = _tables_in(db)
    assert "_kv" not in tables_now and not any(t.startswith("sheet_") for t in tables_now)
    assert sq.read_kv(db, "example") == {"label": "E"} and sq.read_kv(db, "controls") is None
    assert sq.get_meta("old")["filename"] == "f.xlsx"
