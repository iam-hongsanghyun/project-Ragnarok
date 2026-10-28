"""Session-scoped RFNBO run settings kept OUTSIDE the model workbook.

The P2X tab edits the RFNBO matching settings (on/off, hourly or monthly, enforce
additionality / geography). They are a *run option*, not model data, and the browser's
model mirror re-merges its static sheets into the session on every resync, so a setting
written into the workbook by the backend would be overwritten by a stale mirror. They
therefore live in one small JSON file per session under ``<RAGNAROK_DATA_DIR>/p2x/``.

At submit time :func:`apply_session_rfnbo` copies the stored settings into
``options.rfnboConfig`` when the run does not carry its own (an explicit
``options.rfnboConfig``, even ``{"enabled": false}``, always wins). The frozen run options
record what the run used, so a re-run reproduces it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.app.p2x import rfnbo as rf
from ..data_root import data_root

_SAFE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _path(session_id: str) -> Path | None:
    if not _SAFE.match(session_id or ""):
        return None
    return data_root() / "p2x" / f"rfnbo_{session_id}.json"


def get_rfnbo_config(session_id: str) -> dict[str, Any] | None:
    """The stored (normalised) settings of a session, or ``None`` when never set."""
    p = _path(session_id)
    if p is None or not p.exists():
        return None
    try:
        return rf.normalise_config(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def set_rfnbo_config(session_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate (``normalise_config``) and store the settings; returns the normalised dict."""
    p = _path(session_id)
    if p is None:
        raise ValueError(f"Unsafe session id {session_id!r}.")
    norm = rf.normalise_config(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(norm, indent=2), encoding="utf-8")
    return norm


def apply_session_rfnbo(session_id: str | None, options: dict[str, Any] | None) -> dict[str, Any] | None:
    """``options`` with the session's stored RFNBO settings when the run has none (a copy); else unchanged."""
    if options is not None and "rfnboConfig" in options:
        return options
    stored = get_rfnbo_config(session_id) if session_id else None
    if not stored or not stored.get("enabled"):
        return options
    return {**(options or {}), "rfnboConfig": stored}
