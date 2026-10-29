#!/usr/bin/env python3
"""Bring every bundled example ``project.db`` up to the current workbook schema.

An example written before the current ``RAGNAROK_Schema`` version is migrated every time
someone opens it (``sqlite_store._ensure_cost_basis``), and an example with composites
(``RAGNAROK_PLANTS``) but no ``RAGNAROK_Composites`` sheet opens with the "older workbook"
sync bar. This script runs those same two steps once, offline, and writes the result back,
so opening an example changes nothing:

  1. the schema migration, through the app's own ``_ensure_cost_basis``;
  2. ``catalog.sync_composites``, which adds the missing ``RAGNAROK_Composites`` rows.

Only the ``_kv`` keys an example ships with (``meta``, ``tables``, ``example``) are kept, so no
migration notice or journal entry is bundled. Run it after a schema bump:

    PYTHONPATH=. .venv-pypsa/bin/python scripts/restamp_examples.py [example_id ...]
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "backend" / "data" / "examples"
KEEP_KV = {"meta", "tables", "example"}


def restamp(example_id: str) -> str:
    """Migrate one example in a scratch session and copy it back; returns a one-line summary."""
    from backend.app import session_store, sqlite_store
    from backend.app.routers import plants as plants_router
    from backend.pypsa.network import cost_basis as cb

    src = EXAMPLES / example_id / "project.db"
    sid = f"restamp{abs(hash(example_id)) % 10**8}"
    work = session_store.SESSION_DIR / sid
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    shutil.copy2(src, work / "project.db")

    sqlite_store._ensure_cost_basis(sid)
    out = plants_router.sync_composites(plants_router.SyncRequest(sessionId=sid, apply=True))
    added = list(out.get("added") or [])

    with sqlite3.connect(work / "project.db") as conn:
        conn.executemany("DELETE FROM _kv WHERE k = ?", [(k,) for (k,) in conn.execute("SELECT k FROM _kv") if k not in KEEP_KV])
        conn.commit()
    with sqlite3.connect(work / "project.db") as conn:
        conn.execute("VACUUM")
    shutil.copy2(work / "project.db", src)
    shutil.rmtree(work, ignore_errors=True)
    return f"{example_id}: schema {cb.CURRENT_SCHEMA_VERSION}" + (f", composites rows added for {', '.join(added)}" if added else "")


def main(argv: list[str]) -> int:
    ids = argv or sorted(p.parent.name for p in EXAMPLES.glob("*/project.db"))
    with tempfile.TemporaryDirectory() as data_dir:
        os.environ["RAGNAROK_DATA_DIR"] = data_dir
        sys.path.insert(0, str(REPO))
        for example_id in ids:
            print(restamp(example_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
