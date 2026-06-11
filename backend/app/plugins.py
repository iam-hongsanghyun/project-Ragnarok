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
* ``plugin.py`` — a module exposing one or more hooks::

      def transform(model: dict, config: dict) -> dict:   # replace the model
      def contribute(model: dict, config: dict) -> dict:  # {sheets?, constraints?}
      def analyze(result: dict, config: dict) -> dict:    # read-only analytics
      def options(name: str, config: dict, ctx) -> list:  # on-demand dropdowns
      def <action>(config: dict) -> dict:                 # named form actions

Isolation is a hard requirement:

* Discovery never raises — a broken plugin is logged and skipped, and the core
  app runs cleanly with zero plugins present.
* Hook errors are contained — :func:`_call` turns any plugin exception into a
  clean ``ValueError`` (HTTP 400), never a crashed request.
* Model handoff is one-way and *return-value only* — ``transform``/``contribute``
  receive a defensive copy of the session model (:func:`_copy_model`); in-place
  mutation of the ``model`` argument is never persisted. Only the returned dict
  (transform) or fragment (contribute) reaches the session store.
* Module namespaces must not collide — ``plugin.py`` is imported under a
  synthetic per-id name (:func:`_load_module`), and a plugin that vendors its
  own library must load it the same way (aliased under a plugin-unique name,
  no ``sys.path`` mutation) so two plugins shipping equally-named packages
  never swap each other's code. See the dashboard-importer's ``_lib`` loader
  for the reference pattern.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
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

# Per-plugin SERVER-SIDE scratch dir for uploaded data files (e.g. a dashboard
# model workbook). The browser uploads a file here ONCE and thereafter only
# references it by name — the bytes never live in the plugin config / browser
# memory. Gitignored; removed when the plugin is uninstalled.
PLUGIN_FILES_DIR = Path(
    os.environ.get("RAGNAROK_PLUGIN_FILES_DIR")
    or (Path(__file__).resolve().parents[1] / "data" / "plugin_files")
)

# The reserved config key the framework injects so a plugin can resolve its
# uploaded files to absolute server paths (see run_transform/run_contribute).
PLUGIN_DATA_DIR_KEY = "__plugin_data_dir__"


def _mb_env(name: str, default_mb: int) -> int:
    """Env-configurable size limit in MB → bytes (non-positive disables = 0)."""
    try:
        mb = int(os.environ.get(name, "") or default_mb)
    except ValueError:
        mb = default_mb
    return max(0, mb) * 1024 * 1024

# Upload resource guards (0 disables a limit). Files are NOT moved by these —
# plugin code still lands in BACKEND_PLUGINS_DIR and data files in
# PLUGIN_FILES_DIR; the guards only bound how much an upload may consume so a
# fat or hostile request can't exhaust server memory/disk.
MAX_PLUGIN_ZIP_BYTES = _mb_env("RAGNAROK_MAX_PLUGIN_ZIP_MB", 50)
MAX_PLUGIN_FILE_BYTES = _mb_env("RAGNAROK_MAX_PLUGIN_FILE_MB", 200)
# Zip-bomb guard: total UNCOMPRESSED size an install zip may expand to.
MAX_PLUGIN_UNZIPPED_BYTES = _mb_env("RAGNAROK_MAX_PLUGIN_UNZIPPED_MB", 500)


def _safe_name(name: str) -> str:
    """Filesystem-safe basename — strips any path components and odd chars."""
    base = os.path.basename(str(name)).strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return cleaned or "file"


def plugin_files_dir(plugin_id: str) -> Path:
    return PLUGIN_FILES_DIR / _safe_name(plugin_id)


def save_plugin_file(plugin_id: str, filename: str, data: bytes) -> dict[str, Any]:
    """Store an uploaded data file under the plugin's scratch dir."""
    d = plugin_files_dir(plugin_id)
    d.mkdir(parents=True, exist_ok=True)
    name = _safe_name(filename)
    (d / name).write_bytes(data)
    return {"name": name, "size": len(data)}


def list_plugin_files(plugin_id: str) -> list[dict[str, Any]]:
    """List the plugin's uploaded data files (for the picker dropdown)."""
    d = plugin_files_dir(plugin_id)
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for f in sorted(d.iterdir()):
        if f.is_file():
            out.append({"name": f.name, "size": f.stat().st_size})
    return out


def delete_plugin_file(plugin_id: str, filename: str) -> bool:
    target = plugin_files_dir(plugin_id) / _safe_name(filename)
    if target.is_file():
        target.unlink()
        return True
    return False


def remove_plugin_files(plugin_id: str) -> None:
    """Remove the plugin's entire scratch dir (on uninstall)."""
    import shutil

    shutil.rmtree(plugin_files_dir(plugin_id), ignore_errors=True)


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

    @property
    def has_options(self) -> bool:
        return callable(getattr(self.module, "options", None))

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
            #   options(name, config, ctx) -> [opt]    (on-demand dropdown values)
            "hooks": {
                "transform": self.has_transform,
                "contribute": self.has_contribute,
                "analyze": self.has_analyze,
                "options": self.has_options,
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


def _with_data_dir(plugin_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """Inject the plugin's scratch-dir path so it can resolve uploaded files to
    server paths (the browser only passes a filename reference)."""
    return {**(config or {}), PLUGIN_DATA_DIR_KEY: str(plugin_files_dir(plugin_id))}


def _call(hook: Callable[..., Any], *args: Any) -> Any:
    """Invoke a plugin hook, normalising any error into a ValueError the router
    surfaces as a clean 400 (rather than a 500 stack trace)."""
    try:
        return hook(*args)
    except Exception as exc:  # noqa: BLE001 — plugin code is untrusted/3rd-party
        logger.exception("Backend plugin hook failed")
        raise ValueError(str(exc) or exc.__class__.__name__) from exc


def _copy_model(model: dict[str, list[dict[str, Any]]] | None) -> dict[str, list[dict[str, Any]]]:
    """Defensive sheet+row copy of the session model handed to a plugin hook.

    The contract is *return-value only*: whatever a plugin does to its ``model``
    argument in place is never persisted — only the dict it returns is saved
    (transform) or merged (contribute). Copying the sheets and rows enforces
    that, so a contribute plugin can't smuggle session changes past the merge
    by mutating the input while returning an innocent-looking fragment.

    Rows are copied one level deep (``dict(row)``) — cheap even for an
    8760-snapshot model (small per-row dicts of scalars) versus a deepcopy.
    Cell values are shared, which is safe for the scalar cells the model
    schema uses.
    """
    return {
        sheet: [dict(r) if isinstance(r, dict) else r for r in rows]
        for sheet, rows in (model or {}).items()
    }


def run_transform(
    plugin_id: str,
    model: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Run a plugin's ``transform(model, config)`` → the replacement model dict.

    The plugin receives a defensive copy of the session model (see
    :func:`_copy_model`): only the returned dict is ever persisted.
    """
    plugin = get(plugin_id)
    if plugin is None:
        raise KeyError(plugin_id)
    if not plugin.has_transform:
        raise ValueError(f"Plugin {plugin_id!r} has no transform hook.")
    out = _call(plugin.module.transform, _copy_model(model), _with_data_dir(plugin_id, config))
    if not isinstance(out, dict):
        raise ValueError(f"Plugin {plugin_id!r} transform() did not return a model dict.")
    return out


def run_contribute(
    plugin_id: str,
    model: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run a plugin's ``contribute(model, config)`` → ``{sheets?, constraints?}``.

    The plugin receives a defensive copy of the session model (see
    :func:`_copy_model`): only the returned fragment is ever merged.
    """
    plugin = get(plugin_id)
    if plugin is None:
        raise KeyError(plugin_id)
    if not plugin.has_contribute:
        raise ValueError(f"Plugin {plugin_id!r} has no contribute hook.")
    out = _call(plugin.module.contribute, _copy_model(model), _with_data_dir(plugin_id, config))
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
    out = _call(plugin.module.analyze, result or {}, _with_data_dir(plugin_id, config))
    if not isinstance(out, dict):
        raise ValueError(f"Plugin {plugin_id!r} analyze() did not return a dict.")
    return out


# Hook names with their own runners/contracts — not callable through run_action.
_RESERVED_HOOKS = frozenset({"transform", "contribute", "analyze", "options"})


def run_action(plugin_id: str, hook: str, config: dict[str, Any]) -> dict[str, Any]:
    """Run a named action hook ``hook(config) -> {ok?, message?, config?}``.

    The backend counterpart of the frontend-plugin action contract (see
    ``PluginDetail.handleAction``): a manifest ``action`` field with a hook name
    other than transform/contribute invokes the same-named function exported by
    ``plugin.py``. The function receives the current form config (plus the
    injected scratch-dir path) and may return a ``config`` patch — a map of
    field → value the frontend writes back into the form (e.g. a "Fill table"
    button populating an editable table).

    Args:
        plugin_id: The plugin to dispatch to.
        hook: Exported function name from the manifest's action field. Private
            (``_``-prefixed) and reserved hook names are rejected.
        config: Current form state.

    Returns:
        ``{"ok": bool, "message": str}`` plus ``"config"`` when the hook
        returned a patch.
    """
    plugin = get(plugin_id)
    if plugin is None:
        raise KeyError(plugin_id)
    if not hook or hook.startswith("_") or hook in _RESERVED_HOOKS:
        raise ValueError(f"Invalid action hook name {hook!r}.")
    fn = getattr(plugin.module, hook, None)
    if not callable(fn):
        raise ValueError(f"Plugin {plugin_id!r} has no {hook!r} hook.")
    out = _call(fn, _with_data_dir(plugin_id, config))
    if out is None:
        out = {}
    if not isinstance(out, dict):
        raise ValueError(f"Plugin {plugin_id!r} {hook}() did not return a dict.")
    result: dict[str, Any] = {
        "ok": out.get("ok") is not False,
        "message": str(out.get("message") or ""),
    }
    patch = out.get("config")
    if isinstance(patch, dict):
        result["config"] = patch
    return result


@dataclass
class PluginContext:
    """Read-only session access handed to a plugin's ``options`` hook.

    Lets a plugin answer a dropdown WITHOUT Ragnarok knowing anything
    plugin-specific: the plugin computes its own option list from either the
    session (``ctx.distinct`` / ``ctx.sheet_page`` — generic SQL-backed reads) or
    its own uploaded files (``ctx.data_dir``). Ragnarok just dispatches + injects
    this context; it owns zero plugin filter logic.
    """

    session_id: str
    data_dir: str

    def distinct(self, sheet: str, column: str) -> list[str]:
        """Sorted distinct non-empty values of a column in a session sheet."""
        from . import model_store

        return model_store.distinct_values(self.session_id, sheet, column) or []

    def sheet_page(self, sheet: str, offset: int = 0, limit: int | None = None) -> dict[str, Any] | None:
        """One page of a session sheet's rows (or None if absent)."""
        from . import model_store

        return model_store.get_sheet_page(self.session_id, sheet, offset=offset, limit=limit)


def _as_option_rows(out: Any, plugin_id: str) -> list[dict[str, Any]]:
    """Coerce an ``options()`` return into a list of option *rows*.

    Rows mirror the shape the old per-plugin HTTP server returned (``{rows:[…]}``)
    so the frontend reuses its existing row→option resolution (``optionsFromRows``:
    ``column``/``labelColumn``/``filter`` from the manifest). A list of scalars is
    wrapped as ``{"name": value}`` so the default ``column: 'name'`` still works.
    """
    if not isinstance(out, list):
        raise ValueError(f"Plugin {plugin_id!r} options() must return a list.")
    return [item if isinstance(item, dict) else {"name": str(item)} for item in out]


def run_options(
    plugin_id: str,
    name: str,
    config: dict[str, Any],
    session_id: str = "default",
) -> list[dict[str, Any]]:
    """Run a plugin's ``options(name, config, ctx)`` → option rows.

    On-demand dropdown population (when a select opens / its dependency changes),
    never per-keystroke. ``name`` selects which option-set the plugin should
    return; ``config`` is the current form state; ``ctx`` gives read-only session
    access (see :class:`PluginContext`).
    """
    plugin = get(plugin_id)
    if plugin is None:
        raise KeyError(plugin_id)
    if not plugin.has_options:
        raise ValueError(f"Plugin {plugin_id!r} has no options hook.")
    ctx = PluginContext(session_id=session_id, data_dir=str(plugin_files_dir(plugin_id)))
    out = _call(plugin.module.options, name, _with_data_dir(plugin_id, config), ctx)
    return _as_option_rows(out, plugin_id)
