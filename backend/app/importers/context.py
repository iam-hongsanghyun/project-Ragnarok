"""Per-request import context — the only place a user's API key lives.

Built fresh for each ``POST /api/import/run`` from the secrets the
frontend sent in the request body, handed by argument into
``database.fetch(region, filters, ctx)``, and dropped when the response
is written. No module reads ``os.environ`` for a credential and nothing
caches a key, so two concurrent users with different keys never cross.

``ctx.http`` is a shared async HTTP client with retry/backoff and
secret-masking (see ``http.py``). ``ctx.get_secret(name)`` returns the
per-request key or ``None``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImportContext:
    secrets: dict[str, str] = field(default_factory=dict)
    http: Any = None  # AsyncClientWrapper (set by the router)
    request_id: str = ""

    def get_secret(self, name: str) -> str | None:
        v = self.secrets.get(name)
        return v if (isinstance(v, str) and v.strip()) else None

    def require_secret(self, name: str) -> str:
        v = self.get_secret(name)
        if v is None:
            raise PermissionError(
                f"This database needs the '{name}' API key. Add it in "
                f"Settings → API keys and try again."
            )
        return v
