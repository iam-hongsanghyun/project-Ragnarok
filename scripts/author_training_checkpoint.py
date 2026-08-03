#!/usr/bin/env python3
"""Author a training-course checkpoint as a bundled example ``project.db``.

Every module of the "Power market modelling" course after the first opens from a
checkpoint: the model exactly as it stood at the END of the previous module. Those
checkpoints ship as bundled examples under ``backend/data/examples/<id>/`` and
load through ``/api/examples`` like any other.

Module 1's checkpoint was authored by hand, which meant module 2 had to
reverse-engineer the file format from the committed binary. This script is that
knowledge written down, so module 3 does not have to do it a third time.

    python3 scripts/author_training_checkpoint.py training_m2

The format, as the app requires it (see ``backend/app/sqlite_store.py`` and
``routers/examples.py``):

  * one ``sheet_<n>`` table per sheet, each row a JSON object in column ``d``
  * ``_kv['tables']``  — sheet name → table name
  * ``_kv['meta']``    — the session meta the client rehydrates from. Every
    sheet needs ``kind``: ``'static'`` for a component sheet AND for
    ``snapshots``; ``'series'`` only for a genuine temporal sheet
    (``loads-p_set``, ``generators-p_max_pu``). Marking ``snapshots`` as
    ``'series'`` makes the static-only rehydrate drop it and the session opens
    with zero snapshots — the bug that shipped in module 1's first pass.
  * ``_kv['example']`` — label / description / order for the examples list

Every number here is the model the course has the learner type, and each
checkpoint's objective is asserted against a real solve before it is committed
(see the module's own docstring for the values).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "backend" / "data" / "examples"

SNAPSHOTS = ["2030-01-01T00:00:00", "2030-01-01T01:00:00", "2030-01-01T02:00:00"]

# ── Module 2 — the model at the end of "2 · Economic dispatch" ────────────────
# Four generators on one bus, a demand profile and a wind availability profile.
# Solves to 8,980 with prices 0 / 50 / 120 and 14 MWh of wind curtailed.
TRAINING_M2: dict = {
    "filename": "Training module 2 — economic dispatch",
    "example": {
        "label": "Training: module 2 model (end of module)",
        "description": (
            "The model the \"Power market modelling\" course has built by the end of module 2 — one bus, "
            "four generators (coal, gas, oil peaker, wind), a demand profile of 40/80/170 MW and a wind "
            "availability profile. Solves to 8,980 with prices of 0, 50 and 120. Module 3 opens from this."
        ),
        "order": 91,
    },
    "sheets": [
        ("snapshots", "static", [{"snapshot": s} for s in SNAPSHOTS]),
        ("network", "static", [{"name": "my-first-model"}]),
        ("carriers", "static", [
            {"name": "AC", "co2_emissions": 0.0},
            {"name": "gas", "co2_emissions": 0.2},
            {"name": "coal", "co2_emissions": 0.34},
            {"name": "oil", "co2_emissions": 0.27},
            {"name": "wind", "co2_emissions": 0.0},
        ]),
        ("buses", "static", [
            {"name": "bus_1", "v_nom": 380.0, "x": 127.0, "y": 37.5, "carrier": "AC"},
        ]),
        # Row order follows the order the course adds them, so a learner comparing
        # their own sheet against the checkpoint sees the same table.
        ("generators", "static", [
            {"name": "gas_1", "bus": "bus_1", "carrier": "gas",
             "p_nom": 100.0, "marginal_cost": 50.0, "efficiency": 0.5},
            {"name": "coal_1", "bus": "bus_1", "carrier": "coal",
             "p_nom": 50.0, "marginal_cost": 20.0, "efficiency": 0.4},
            {"name": "oil_1", "bus": "bus_1", "carrier": "oil",
             "p_nom": 40.0, "marginal_cost": 120.0, "efficiency": 0.35},
            {"name": "wind_1", "bus": "bus_1", "carrier": "wind",
             "p_nom": 60.0, "marginal_cost": 0.0, "efficiency": 1.0},
        ]),
        # The static p_set stays at the module-1 value. The profile below overrides
        # it — verified against a solve, not assumed — and the course says so.
        ("loads", "static", [
            {"name": "load_1", "bus": "bus_1", "carrier": "AC", "p_set": 80.0},
        ]),
        ("loads-p_set", "series", [
            {"snapshot": SNAPSHOTS[0], "load_1": 40.0},
            {"snapshot": SNAPSHOTS[1], "load_1": 80.0},
            {"snapshot": SNAPSHOTS[2], "load_1": 170.0},
        ]),
        # Only wind_1 carries a profile. A thermal unit with no column keeps its
        # static default of 1 (fully available), which is what the course teaches.
        ("generators-p_max_pu", "series", [
            {"snapshot": SNAPSHOTS[0], "wind_1": 0.9},
            {"snapshot": SNAPSHOTS[1], "wind_1": 0.4},
            {"snapshot": SNAPSHOTS[2], "wind_1": 0.1},
        ]),
    ],
    "componentCounts": {"buses": 1, "generators": 4, "loads": 1, "carriers": 5},
}

CHECKPOINTS = {"training_m2": TRAINING_M2}


def write_checkpoint(example_id: str, spec: dict) -> Path:
    """Write ``<example_id>/project.db``, replacing any existing one."""
    out_dir = EXAMPLES / example_id
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "project.db"
    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE _kv (k TEXT PRIMARY KEY, v TEXT)")

    tables: dict[str, str] = {}
    sheet_meta: list[dict] = []
    for i, (name, kind, rows) in enumerate(spec["sheets"]):
        table = f"sheet_{i}"
        tables[name] = table
        con.execute(f"CREATE TABLE {table} (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT)")
        con.executemany(
            f"INSERT INTO {table} (d) VALUES (?)",
            [(json.dumps(r),) for r in rows],
        )
        # Column order is taken from the first row, so authored dicts must be
        # written in the order the learner sees the columns in the grid.
        sheet_meta.append({
            "name": name,
            "kind": kind,
            "rowCount": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
        })

    meta = {
        "sessionId": "__example_author__",
        "filename": spec["filename"],
        "scenarioName": "",
        "savedAt": "2026-08-03T00:00:00+00:00",
        "sheets": sheet_meta,
        "snapshotCount": len(SNAPSHOTS),
        "snapshotStart": SNAPSHOTS[0].replace("T", " "),
        "snapshotEnd": SNAPSHOTS[-1].replace("T", " "),
        "scenarioYear": 2030,
        "componentCounts": spec["componentCounts"],
    }
    for key, value in (("meta", meta), ("tables", tables), ("example", spec["example"])):
        con.execute("INSERT INTO _kv (k, v) VALUES (?, ?)", (key, json.dumps(value)))

    con.commit()
    con.close()
    return db_path


def main() -> int:
    ids = sys.argv[1:] or list(CHECKPOINTS)
    for example_id in ids:
        spec = CHECKPOINTS.get(example_id)
        if spec is None:
            print(f"unknown checkpoint {example_id!r}; known: {', '.join(CHECKPOINTS)}")
            return 1
        path = write_checkpoint(example_id, spec)
        print(f"wrote {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
