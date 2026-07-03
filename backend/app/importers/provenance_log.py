"""Persistent import-provenance log (D1) — versioned record of every import.

The per-fragment ``Provenance`` row travels INTO the workbook (round-trips via
the metadata sheets), but the server kept no record of what was fetched when.
This appends one JSON line per import event to an append-only log, giving each
event a monotonically increasing ``version`` — the auditable history behind
"which upstream, which filters, which row counts, when".

    record_import(provenance, source_id=..., dataset_ids=[...])
    recent_imports(limit=50) -> newest-first entries

Log file: ``RAGNAROK_PROVENANCE_LOG`` (default
``backend/data/provenance_log.jsonl``). Best-effort: logging failures never
break an import.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "provenance_log.jsonl"


def _path() -> Path:
    return Path(os.environ.get("RAGNAROK_PROVENANCE_LOG", str(_DEFAULT_PATH)))


def _next_version(path: Path) -> int:
    try:
        with path.open("rb") as fh:
            count = sum(1 for _ in fh)
        return count + 1
    except OSError:
        return 1


def record_import(
    provenance: Any,
    *,
    source_id: str,
    dataset_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """Append one import event; returns the written entry (or None on failure)."""
    path = _path()
    try:
        entry = {
            "version": _next_version(path),
            "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sourceId": source_id,
            "datasetIds": list(dataset_ids or []),
            "databaseId": getattr(provenance, "database_id", ""),
            "countryIso": getattr(provenance, "country_iso", ""),
            "countryName": getattr(provenance, "country_name", ""),
            "filters": getattr(provenance, "filters_json", ""),
            "fetchedAt": getattr(provenance, "fetch_timestamp", ""),
            "rowCounts": getattr(provenance, "row_counts_json", ""),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return entry
    except OSError:
        logger.warning("provenance log write failed (best-effort)")
        return None


def recent_imports(limit: int = 50) -> list[dict[str, Any]]:
    """Newest-first log entries (up to ``limit``)."""
    path = _path()
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines[-max(1, int(limit)) * 2 :]):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out
