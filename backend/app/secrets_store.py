"""Server-side secrets store — shared by importers and the embedded agent.

Two layers (values never leave the server):

1. env: any ``RAGNAROK_SECRET_<NAME>`` provides the secret ``<name>``
   (lowercased) — set in the gitignored ``backend/.env``.
2. stored: keys the user typed into Settings → API keys are recorded in
   ``backend/data/secrets.json`` (gitignored, 0600) via the
   ``/api/import/secrets`` endpoints, and win over env.

Extracted from ``routers/importers.py`` so the agent's auth resolver
(:mod:`backend.app.agent.auth`) can read the same store without importing the
whole importer router.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_SERVER_SECRET_PREFIX = "RAGNAROK_SECRET_"
SECRET_NAME_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_REPO_ROOT = Path(__file__).resolve().parents[2]
SECRETS_PATH = _REPO_ROOT / "backend" / "data" / "secrets.json"


def env_secrets() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith(_SERVER_SECRET_PREFIX) and value.strip():
            out[key[len(_SERVER_SECRET_PREFIX):].lower()] = value.strip()
    return out


def stored_secrets() -> dict[str, str]:
    try:
        if not SECRETS_PATH.exists():
            return {}
        data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items() if str(v).strip()} if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — a corrupt file must not break callers
        return {}


def write_stored_secrets(secrets: dict[str, str]) -> None:
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_PATH.write_text(json.dumps(secrets, indent=2), encoding="utf-8")
    try:
        os.chmod(SECRETS_PATH, 0o600)  # owner-only — these are credentials
    except OSError:
        pass


def server_secrets() -> dict[str, str]:
    """All secrets the server provides: env, overridden by stored."""
    return {**env_secrets(), **stored_secrets()}
