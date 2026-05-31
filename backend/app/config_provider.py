"""In-memory bundle of the shared backend↔frontend configs.

Owned by the backend; served to the frontend via ``GET /api/config`` at
boot. The four payloads carried here are the ones both sides must agree
on:

  • ``schema``                — the PyPSA component schema
  • ``standard_types``        — built-in line / transformer catalogues
  • ``network_import_policy`` — workbook-side runtime / metadata rules
  • ``capabilities``          — what the live solver backends declare

Frontend-only configs (``app_config.json``, ``currencies.json``) stay on
the frontend; backend-only configs (rate-limit knobs, cache TTLs, log
buffer sizes) stay in ``backend/app/config.py`` and never reach the
client.

The bundle is loaded once at process startup and held in module scope.
A ``build_id`` derived from the file mtimes + ``backend_version`` lets
the frontend cache its copy keyed on a stable token and invalidate on
the next deploy.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


# ── File locations (all under backend/data/config/) ─────────────────────────


def _backend_config_dir() -> Path:
    """``backend/data/config/`` resolved from this file's location.

    ``backend/app/config_provider.py`` → ``app`` → ``backend`` → ``data/config``,
    so ``parents[1]`` is the backend root. Hosts only the configs that
    aren't derivable from the installed ``pypsa`` package — currently
    just ``network_import_policy.json`` (curated rule table).
    """
    return Path(__file__).resolve().parents[1] / "data" / "config"


def _network_import_policy_path() -> Path:
    return _backend_config_dir() / "network_import_policy.json"


# ── Bundle dataclass ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ConfigBundle:
    """The exact JSON shape returned by ``GET /api/config``."""

    schema: dict[str, Any]
    standard_types: dict[str, Any]
    network_import_policy: dict[str, Any]
    capabilities: list[dict[str, Any]]
    build_id: str
    backend_version: str

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "standard_types": self.standard_types,
            "network_import_policy": self.network_import_policy,
            "capabilities": self.capabilities,
            "build_id": self.build_id,
            "backend_version": self.backend_version,
        }


# ── Build the bundle (cached for the life of the process) ───────────────────


def _backend_version() -> str:
    """Resolve the running backend's own version string for the bundle.

    Tries ``importlib.metadata`` first (installed package), falls back to
    a static ``"dev"`` token for editable installs.
    """
    for distribution_name in ("pypsa-gui-backend", "ragnarok-backend", "ragnarok"):
        try:
            return importlib.metadata.version(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "dev"


def _build_id(
    schema: dict[str, Any],
    standard_types: dict[str, Any],
    network_import_policy: dict[str, Any],
    backend_version: str,
) -> str:
    """Deterministic short id over the bundle's content.

    The frontend keys its cache by this value, so any change in the
    schema / types / policy / backend version flips the id and triggers
    a fresh fetch on next page load.
    """
    payload = json.dumps(
        {
            "schema": schema,
            "standard_types": standard_types,
            "network_import_policy": network_import_policy,
            "backend_version": backend_version,
        },
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{backend_version}-{digest[:12]}"


@lru_cache(maxsize=1)
def load_bundle() -> ConfigBundle:
    """Build the bundle the frontend fetches at boot.

    Two halves:

    * ``schema`` + ``standard_types`` are computed **from the installed
      pypsa package** (see ``pypsa_schema_builder.py``) at startup. No
      JSON file involved — bumping PyPSA automatically bumps the schema
      the next time the backend boots.
    * ``network_import_policy`` is a hand-curated rule table — not
      derivable from PyPSA — so it stays as a checked-in JSON file under
      ``backend/data/config/``.

    Cached for the life of the process. ``reset_cache()`` drops it so the
    next ``load_bundle()`` re-reads disk + re-imports PyPSA.
    """
    # Local imports to avoid circular deps at module-import time.
    from .backends.registry import available_backends
    from .pypsa_schema_builder import build_pypsa_schema, build_standard_types

    schema = build_pypsa_schema()
    standard_types = build_standard_types()
    network_import_policy = json.loads(_network_import_policy_path().read_text())
    capabilities = available_backends()
    backend_version = _backend_version()
    return ConfigBundle(
        schema=schema,
        standard_types=standard_types,
        network_import_policy=network_import_policy,
        capabilities=capabilities,
        build_id=_build_id(
            schema, standard_types, network_import_policy, backend_version,
        ),
        backend_version=backend_version,
    )


def reset_cache() -> None:
    """Drop the cached bundle so the next ``load_bundle()`` re-reads disk.

    Used by tests and by the future hot-reload hook.
    """
    load_bundle.cache_clear()
