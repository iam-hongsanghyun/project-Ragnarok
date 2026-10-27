"""Tiny ``backend/.env`` loader (stdlib only; no python-dotenv dependency).

Called once at process start (``backend/app/__init__.py`` and the MCP entrypoint)
*before* any module reads ``os.environ`` — several settings are read at import
time. A variable already present in the process environment always wins, so a
shell ``export`` or a launcher override beats the file.

Format: ``NAME=value`` per line; ``#`` comment lines and blank lines are ignored;
an optional leading ``export``; values may be wrapped in single or double quotes.
No interpolation, no multi-line values.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"


def parse_env_text(text: str) -> dict[str, str]:
    """Parse ``NAME=value`` lines into a dict (later lines override earlier ones)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, sep, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or not name:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[name] = value
    return out


def load_env_file(path: Path | None = None) -> list[str]:
    """Load ``path`` (default ``backend/.env``) into ``os.environ``.

    Existing environment variables are never overwritten. Returns the names that
    were set (empty when the file is missing or unreadable).
    """
    target = path or ENV_FILE
    try:
        parsed = parse_env_text(target.read_text(encoding="utf-8"))
    except OSError:
        return []
    applied = [k for k, v in parsed.items() if k not in os.environ]
    for k in applied:
        os.environ[k] = parsed[k]
    return applied
