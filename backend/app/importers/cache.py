"""General importer cache (D1) — multi-source, opt-in, licence-aware.

The Open-Meteo weather cache (``databases/openmeteo_renewable/cache.py``) proved
the shape: immutable upstream data keyed by request → cached JSON on disk. This
generalises it for any source:

    cache_get("ember", {"iso": "KOR", "from": "2023-01", "to": "2023-12"})
    cache_put("ember", key, payload, ttl_days=7)

- Directory: ``RAGNAROK_IMPORT_CACHE`` (default ``backend/data/import_cache``),
  one subdirectory per source, one JSON file per SHA-256 of the sorted key.
- TTL: ``ttl_days=None`` means immutable (cache forever — ERA5/GloFAS archives,
  closed price ranges); expired entries read as a miss and are deleted.
- **Licence guard**: sources whose terms forbid redistribution/bulk caching are
  hard-blocked (``NEVER_CACHE``) — a put is a silent no-op and a get always
  misses, so a coding mistake cannot violate the licence.
- Best-effort: any I/O or JSON error degrades to a miss / no-op, never an error
  (same policy as the weather cache).

The Open-Meteo cache keeps its own directory/env for back-compat; new sources
use this module.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "import_cache"

# Sources whose licence forbids server-side caching (fetch-per-user only).
NEVER_CACHE = frozenset({"renewables_ninja"})


def _dir() -> Path:
    return Path(os.environ.get("RAGNAROK_IMPORT_CACHE", str(_DEFAULT_DIR)))


def _path(source_id: str, key: dict[str, Any]) -> Path:
    digest = hashlib.sha256(
        json.dumps(key, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:32]
    safe_source = "".join(c if c.isalnum() or c in "-_" else "_" for c in source_id)
    return _dir() / safe_source / f"{digest}.json"


def cache_get(source_id: str, key: dict[str, Any]) -> Any | None:
    """Cached payload for ``(source_id, key)``, or ``None`` on miss/expiry."""
    if source_id in NEVER_CACHE:
        return None
    path = _path(source_id, key)
    try:
        envelope = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    ttl_days = envelope.get("ttlDays")
    if ttl_days is not None:
        age_days = (time.time() - float(envelope.get("cachedAt", 0.0))) / 86400.0
        if age_days > float(ttl_days):
            try:
                path.unlink()
            except OSError:
                pass
            return None
    return envelope.get("payload")


def cache_put(source_id: str, key: dict[str, Any], payload: Any, *, ttl_days: float | None = None) -> None:
    """Store ``payload`` (no-op for licence-blocked sources; best-effort I/O)."""
    if source_id in NEVER_CACHE:
        logger.debug("cache_put blocked for %s (licence)", source_id)
        return
    path = _path(source_id, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"cachedAt": time.time(), "ttlDays": ttl_days, "payload": payload},
            default=str,
        ))
    except OSError:
        logger.debug("cache_put failed for %s (best-effort)", source_id)
