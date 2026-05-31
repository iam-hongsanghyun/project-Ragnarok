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
from pathlib import Path
from typing import Any, Callable

ProgressCallback = Callable[[str, str], None]


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
    """The exact JSON shape returned by ``GET /api/config``.

    Six payloads, each owned by the backend and computed (or read) on
    demand:

    * ``schema`` — PyPSA component schema (built live, see
      ``pypsa_schema_builder.build_pypsa_schema``).
    * ``standard_types`` — PyPSA line + transformer catalogues (built
      live).
    * ``network_import_policy`` — curated rule table, read from disk.
    * ``capabilities`` — solver-backend capability list (from the
      backend registry — also dynamic).
    * ``simulation_defaults`` — server-side simulation knobs (max
      snapshots, default snapshot count, default snapshot weight).
      Backend authoritative so the frontend doesn't need to ship its
      own defaults.
    * ``build_id`` + ``backend_version`` — for the frontend cache key.
    """

    schema: dict[str, Any]
    standard_types: dict[str, Any]
    network_import_policy: dict[str, Any]
    capabilities: list[dict[str, Any]]
    simulation_defaults: dict[str, Any]
    build_id: str
    backend_version: str

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "standard_types": self.standard_types,
            "network_import_policy": self.network_import_policy,
            "capabilities": self.capabilities,
            "simulation_defaults": self.simulation_defaults,
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


# ── Build steps (one per progress tick the frontend can render) ─────────────

# Each step is (key, human label). The startup warm runs them in order and
# the frontend draws a checklist + progress bar from the live status.
BUILD_STEPS: list[tuple[str, str]] = [
    ("schema", "Building PyPSA component schema"),
    ("standard_types", "Reading standard line / transformer types"),
    ("policy", "Loading network-import policy"),
    ("capabilities", "Querying solver capabilities"),
    ("finalize", "Finalising configuration bundle"),
]

# Manual single-slot cache (replaces lru_cache so the builder can emit
# progress as it goes).
_BUNDLE: ConfigBundle | None = None


def build_bundle(progress: ProgressCallback | None = None) -> ConfigBundle:
    """Build the config bundle, invoking ``progress(step_key, label)``
    before each step.

    Two halves:

    * ``schema`` + ``standard_types`` are computed **from the installed
      pypsa package** (see ``pypsa_schema_builder.py``). No JSON file
      involved — bumping PyPSA automatically bumps the schema the next
      time the backend boots.
    * ``network_import_policy`` is a hand-curated rule table — not
      derivable from PyPSA — so it stays as a checked-in JSON file under
      ``backend/data/config/``.

    Pure: does not touch the module cache. ``load_bundle`` wraps this and
    memoises the result.
    """
    # Local imports to avoid circular deps at module-import time.
    from .backends.registry import available_backends
    from .config import load_system_defaults
    from .pypsa_schema_builder import build_pypsa_schema, build_standard_types

    def tick(key: str) -> None:
        if progress is not None:
            label = dict(BUILD_STEPS).get(key, key)
            progress(key, label)

    tick("schema")
    schema = build_pypsa_schema()
    tick("standard_types")
    standard_types = build_standard_types()
    tick("policy")
    network_import_policy = json.loads(_network_import_policy_path().read_text())
    tick("capabilities")
    capabilities = available_backends()
    tick("finalize")
    sim_cfg = load_system_defaults().get("simulation", {})
    simulation_defaults = {
        "maxSnapshots": int(sim_cfg.get("max_snapshots", 8760)),
        "defaultSnapshotCount": int(sim_cfg.get("default_snapshot_count", 24)),
        "defaultSnapshotWeight": float(sim_cfg.get("default_snapshot_weight", 1.0)),
    }
    backend_version = _backend_version()
    return ConfigBundle(
        schema=schema,
        standard_types=standard_types,
        network_import_policy=network_import_policy,
        capabilities=capabilities,
        simulation_defaults=simulation_defaults,
        build_id=_build_id(
            schema, standard_types, network_import_policy, backend_version,
        ),
        backend_version=backend_version,
    )


def load_bundle(progress: ProgressCallback | None = None) -> ConfigBundle:
    """Return the memoised config bundle, building it on first call.

    Pass ``progress`` (a ``(step_key, label) -> None`` callable) to watch
    the build — used by the startup warm task to drive the frontend
    progress bar. Subsequent calls return the cached bundle and ignore
    the callback.
    """
    global _BUNDLE
    if _BUNDLE is None:
        _BUNDLE = build_bundle(progress)
    return _BUNDLE


def reset_cache() -> None:
    """Drop the cached bundle so the next ``load_bundle()`` rebuilds.

    Used by tests and by ``POST /api/config/reload``.
    """
    global _BUNDLE
    _BUNDLE = None
