"""Move a bundled example ``project.db`` written before the cost-basis schema onto PyPSA's semantics.

Examples that ``make_examples.py`` authors are written on the new basis directly. Examples with no
authoring function here (the training checkpoints, e.g. ``training_m7``) are migrated with this script: it
reads the OLD db through the real loader (which runs :func:`backend.pypsa.network.cost_basis.migrate_cost_basis`
and prints what it changed) and rewrites the example's ``project.db`` with its ``example`` metadata kept.

    .venv-pypsa/bin/python -m backend.scripts.migrate_example_cost_basis <example_id> <old_examples_dir>

``old_examples_dir`` holds the pre-change ``<example_id>/project.db``. The discount rate is the one the
workbook states, else the app default (``simulation.migration_discount_rate``).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from backend.app import model_store, session_store, sqlite_store

EXAMPLES = Path(__file__).resolve().parents[1] / "data" / "examples"
AUTHOR_SESSION = "__example_author__"


def migrate(example_id: str, old_dir: Path) -> None:
    source = old_dir / example_id / "project.db"
    meta_kv = sqlite_store.read_kv(source, "example")
    scratch = Path(tempfile.mkdtemp())
    (scratch / "s").mkdir()
    shutil.copy2(source, scratch / "s" / "project.db")
    previous = session_store.SESSION_DIR
    session_store.SESSION_DIR = scratch
    try:
        filename = (sqlite_store.get_meta("s") or {}).get("filename", "")
        model = sqlite_store.load_full_model("s")
        report = sqlite_store.get_cost_basis_migration("s", include_acknowledged=True) or {}
    finally:
        session_store.SESSION_DIR = previous
    print(example_id, "rows converted:", [(r["sheet"], r["name"], r["capital_cost_was"]) for r in report.get("changedRows", [])],
          "review:", report.get("review", []))
    model_store.save_model(AUTHOR_SESSION, model, filename=filename)
    built = session_store.SESSION_DIR / AUTHOR_SESSION / "project.db"
    sqlite_store.write_kv(built, "example", meta_kv)
    shutil.copy2(built, EXAMPLES / example_id / "project.db")
    shutil.rmtree(session_store.SESSION_DIR / AUTHOR_SESSION, ignore_errors=True)
    print("wrote", EXAMPLES / example_id / "project.db")


if __name__ == "__main__":
    migrate(sys.argv[1], Path(sys.argv[2]))
