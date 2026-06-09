"""Backend plugin framework — server-side plugins that run *in* the Ragnarok
backend and may import the bundled PyPSA source directly.

Two plugin kinds exist in Ragnarok:

* **frontend plugin** — browser-evaluated JavaScript (``features/plugins`` on the
  client). It may call its *own* local build server (registered in
  ``plugins.env``); it never talks to the Ragnarok backend.
* **backend plugin** — this module. A pure-Python plugin discovered from a
  directory on disk, loaded into the backend process, and run on demand via
  ``/api/plugins``. It can ``import pypsa`` (the bundled source at
  ``backend/pypsa``) and any backend library. No separate server, nothing in
  ``plugins.env``.

A backend plugin is a directory under :data:`BACKEND_PLUGINS_DIR` containing:

* ``manifest.json`` — ``{id, name, version, description?, capabilities?, config?}``
  (the ``config`` schema is rendered by the same frontend form renderer used for
  frontend plugins, so the two look identical in the Plugins tab).
* ``plugin.py`` — a module exposing one or both hooks::

      def build(config: dict) -> dict:        # returns a model {sheet: [rows]}
          ...
      def analyze(result: dict, config: dict) -> dict:   # returns analytics
          ...

Isolation is a hard requirement: discovery never raises, a broken plugin is
logged and skipped, and the core app runs cleanly with zero plugins present.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("pypsa_gui.plugins")

# The INSTALL directory for backend plugins — under backend/data/ (gitignored,
# runtime/user content), NOT in the project tree. Ragnarok ships ZERO plugins;
# plugins are purely 3rd-party and arrive via upload-install (see the plugins
# router). Overridable via env so a remote deployment can mount plugins anywhere
# (no hardcoded path leaks into callers — they always go through this constant).
BACKEND_PLUGINS_DIR = Path(
    os.environ.get("RAGNAROK_BACKEND_PLUGINS_DIR")
    or (Path(__file__).resolve().parents[1] / "data" / "plugins")
)


@dataclass
class BackendPlugin:
    """A discovered, loaded backend plugin."""

    id: str
    name: str
    version: str
    description: str
    capabilities: list[str]
    config_schema: dict[str, Any]
    module: ModuleType = field(repr=False)
    directory: Path = field(repr=False)

    @property
    def has_transform(self) -> bool:
        return callable(getattr(self.module, "transform", None))

    @property
    def has_contribute(self) -> bool:
        return callable(getattr(self.module, "contribute", None))

    @property
    def has_analyze(self) -> bool:
        return callable(getattr(self.module, "analyze", None))

    def to_dict(self) -> dict[str, Any]:
        """The manifest the frontend reads to render the plugin and its form."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "kind": "backend",
            "description": self.description,
            "capabilities": self.capabilities,
            "config": self.config_schema,
            # Unified contract, shared with frontend plugins:
            #   transform(model, config) -> model     (replace)
            #   contribute(model, config) -> {sheets, constraints}  (add)
            #   analyze(result, config) -> data        (read-only output)
            "hooks": {
                "transform": self.has_transform,
                "contribute": self.has_contribute,
                "analyze": self.has_analyze,
            },
        }


def _load_module(plugin_id: str, plugin_py: Path) -> ModuleType:
    """Import ``plugin.py`` under a synthetic, collision-free module name.

    Absolute imports inside the plugin (``import pypsa`` or
    ``from backend.pypsa... import ...``) resolve normally — ``backend`` is a
    package on ``sys.path`` and the bundled source lives at ``backend/pypsa``.
    """
    mod_name = f"_ragnarok_backend_plugin_{plugin_id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, plugin_py)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot build import spec for {plugin_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_one(directory: Path) -> BackendPlugin | None:
    """Load a single plugin directory, or return None (logged) on any failure."""
    manifest_path = directory / "manifest.json"
    plugin_py = directory / "plugin.py"
    if not manifest_path.is_file() or not plugin_py.is_file():
        logger.debug("Skip %s: missing manifest.json or plugin.py", directory.name)
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        module = _load_module(str(manifest.get("id") or directory.name), plugin_py)
        plugin = BackendPlugin(
            id=str(manifest.get("id") or directory.name),
            name=str(manifest.get("name") or directory.name),
            version=str(manifest.get("version") or "0.0.0"),
            description=str(manifest.get("description") or ""),
            capabilities=list(manifest.get("capabilities") or []),
            config_schema=dict(manifest.get("config") or {}),
            module=module,
            directory=directory,
        )
        if not (plugin.has_transform or plugin.has_contribute or plugin.has_analyze):
            logger.warning("Skip backend plugin %s: no transform/contribute/analyze hook", plugin.id)
            return None
        logger.info("Loaded backend plugin %s v%s", plugin.id, plugin.version)
        return plugin
    except Exception:  # noqa: BLE001 — isolation: one bad plugin must not break discovery
        logger.exception("Failed to load backend plugin from %s", directory)
        return None


def discover(plugins_dir: Path | None = None) -> dict[str, BackendPlugin]:
    """Scan the plugins dir and return ``{id: BackendPlugin}``.

    Never raises: a missing directory yields ``{}`` and a broken plugin is
    skipped, so the backend always starts.
    """
    root = plugins_dir or BACKEND_PLUGINS_DIR
    found: dict[str, BackendPlugin] = {}
    if not root.is_dir():
        logger.debug("No backend plugins dir at %s", root)
        return found
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "_")):
            continue
        plugin = _load_one(entry)
        if plugin is not None:
            found[plugin.id] = plugin
    return found


# Warm cache (single process owner). Rebuilt on demand via refresh().
_REGISTRY: dict[str, BackendPlugin] | None = None


def registry(refresh: bool = False) -> dict[str, BackendPlugin]:
    """Return the cached registry, discovering on first use or when refreshed."""
    global _REGISTRY
    if _REGISTRY is None or refresh:
        _REGISTRY = discover()
    return _REGISTRY


def list_plugins(refresh: bool = False) -> list[dict[str, Any]]:
    """Manifests for every loaded backend plugin (for ``GET /api/plugins``)."""
    return [p.to_dict() for p in registry(refresh).values()]


def get(plugin_id: str) -> BackendPlugin | None:
    return registry().get(plugin_id)


def _call(hook: Callable[..., Any], *args: Any) -> Any:
    """Invoke a plugin hook, normalising any error into a ValueError the router
    surfaces as a clean 400 (rather than a 500 stack trace)."""
    try:
        return hook(*args)
    except Exception as exc:  # noqa: BLE001 — plugin code is untrusted/3rd-party
        logger.exception("Backend plugin hook failed")
        raise ValueError(str(exc) or exc.__class__.__name__) from exc


def run_transform(
    plugin_id: str,
    model: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Run a plugin's ``transform(model, config)`` → the replacement model dict."""
    plugin = get(plugin_id)
    if plugin is None:
        raise KeyError(plugin_id)
    if not plugin.has_transform:
        raise ValueError(f"Plugin {plugin_id!r} has no transform hook.")
    out = _call(plugin.module.transform, model or {}, config or {})
    if not isinstance(out, dict):
        raise ValueError(f"Plugin {plugin_id!r} transform() did not return a model dict.")
    return out


def run_contribute(
    plugin_id: str,
    model: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run a plugin's ``contribute(model, config)`` → ``{sheets?, constraints?}``."""
    plugin = get(plugin_id)
    if plugin is None:
        raise KeyError(plugin_id)
    if not plugin.has_contribute:
        raise ValueError(f"Plugin {plugin_id!r} has no contribute hook.")
    out = _call(plugin.module.contribute, model or {}, config or {})
    if not isinstance(out, dict):
        raise ValueError(f"Plugin {plugin_id!r} contribute() did not return a dict.")
    return out


def run_analyze(plugin_id: str, result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Run a plugin's ``analyze(result, config)`` and return its output."""
    plugin = get(plugin_id)
    if plugin is None:
        raise KeyError(plugin_id)
    if not plugin.has_analyze:
        raise ValueError(f"Plugin {plugin_id!r} has no analyze hook.")
    out = _call(plugin.module.analyze, result or {}, config or {})
    if not isinstance(out, dict):
        raise ValueError(f"Plugin {plugin_id!r} analyze() did not return a dict.")
    return out
