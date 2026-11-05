"""RFNBO run settings, kept in the project's app state (not in the model workbook).

The P2X tab edits the RFNBO matching settings (on/off, hourly or monthly, enforce
additionality / geography). They are a *run option*, not model data, and the browser's
model mirror re-merges its static sheets into the session on every resync, so a setting
written into the workbook by the backend would be overwritten by a stale mirror. They
therefore live in the project's app state under ``ragnarok:p2x:rfnbo`` (so they travel with
the project); a per-session file under ``<RAGNAROK_DATA_DIR>/p2x/`` written by an older build
is moved there on first read.

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


#: Key of the RFNBO settings in the project's app state (they travel with the project, see app_state.py).
APP_STATE_KEY = "ragnarok:p2x:rfnbo"


def get_rfnbo_config(session_id: str) -> dict[str, Any] | None:
    """The project's (normalised) RFNBO settings, or ``None`` when never set.

    They live in the project's app state; a per-session file written by an older build is read once and moved there.
    """
    from backend.app import model_store

    state = model_store.get_app_state(session_id) if _SAFE.match(session_id or "") else None
    raw = (state or {}).get(APP_STATE_KEY)
    if raw:
        try:
            return rf.normalise_config(json.loads(raw))
        except (TypeError, ValueError):
            return None
    p = _path(session_id)
    if p is None or not p.exists():
        return None
    try:
        legacy = rf.normalise_config(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
    if state is not None:
        model_store.set_app_state(session_id, {APP_STATE_KEY: json.dumps(legacy)}, replace=False)
        p.unlink(missing_ok=True)
    return legacy


def set_rfnbo_config(session_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate (``normalise_config``) and store the settings in the project; returns the normalised dict."""
    from backend.app import model_store

    if not _SAFE.match(session_id or ""):
        raise ValueError(f"Unsafe session id {session_id!r}.")
    norm = rf.normalise_config(cfg)
    if model_store.set_app_state(session_id, {APP_STATE_KEY: json.dumps(norm)}, replace=False) is None:
        raise ValueError("No project is loaded in this session; load or build a model first.")
    legacy = _path(session_id)
    if legacy is not None:
        legacy.unlink(missing_ok=True)
    return norm


def apply_session_rfnbo(session_id: str | None, options: dict[str, Any] | None) -> dict[str, Any] | None:
    """``options`` with the session's stored RFNBO settings when the run has none (a copy); else unchanged."""
    if options is not None and "rfnboConfig" in options:
        return options
    stored = get_rfnbo_config(session_id) if session_id else None
    if not stored or not stored.get("enabled"):
        return options
    return {**(options or {}), "rfnboConfig": stored}
