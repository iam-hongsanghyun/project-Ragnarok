from __future__ import annotations

import importlib.util
import io
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .config import load_module_host_config

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _cfg() -> dict[str, Any]:
    return load_module_host_config()


def _sdk_version() -> str:
    return str(_cfg().get("sdk_version", "1"))


def _supported_capabilities() -> list[str]:
    return [str(item) for item in _cfg().get("capabilities", [])]


def _supported_permissions() -> list[str]:
    return [str(item) for item in _cfg().get("permissions", [])]


def _expand_path(raw: str) -> Path:
    text = str(raw)
    text = text.replace("${HOME}", str(Path.home()))
    text = text.replace("${PROJECT_ROOT}", str(PROJECT_ROOT))
    return Path(text).expanduser().resolve()


def _managed_root_cfg() -> dict[str, Any]:
    return _cfg().get("managed_root", {})


def _managed_root() -> Path:
    raw_path = str(_managed_root_cfg().get("path", "${PROJECT_ROOT}/.ragnarok/modules"))
    return _expand_path(raw_path)


def _managed_root_descriptor() -> dict[str, Any]:
    managed_root = _managed_root()
    return {
        "label": str(_managed_root_cfg().get("label", "Installed local modules")),
        "path": str(managed_root),
        "configuredPath": str(_managed_root_cfg().get("path", "${PROJECT_ROOT}/.ragnarok/modules")),
        "exists": managed_root.exists(),
        "isDirectory": managed_root.is_dir(),
        "managed": True,
    }


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_manifest(manifest: dict[str, Any], module_dir: Path | None = None) -> dict[str, Any]:
    diagnostics: list[str] = []
    supported_capabilities = set(_supported_capabilities())
    supported_permissions = set(_supported_permissions())

    module_id = str(manifest.get("id", "")).strip()
    name = str(manifest.get("name", "")).strip()
    version = str(manifest.get("version", "")).strip()
    sdk_version = str(manifest.get("sdkVersion", "")).strip()
    entry = str(manifest.get("entry", "")).strip()
    description = str(manifest.get("description", "")).strip()
    capabilities = [str(item).strip() for item in manifest.get("capabilities", []) if str(item).strip()]
    permissions = [str(item).strip() for item in manifest.get("permissions", []) if str(item).strip()]

    for field_name, value in (
        ("id", module_id),
        ("name", name),
        ("version", version),
        ("sdkVersion", sdk_version),
        ("entry", entry),
    ):
        if not value:
            diagnostics.append(f"Missing required field '{field_name}'.")

    if not capabilities:
        diagnostics.append("Manifest must declare at least one capability.")

    unsupported_capabilities = sorted(set(capabilities) - supported_capabilities)
    if unsupported_capabilities:
        diagnostics.append(
            "Unsupported capabilities: " + ", ".join(unsupported_capabilities) + "."
        )

    unsupported_permissions = sorted(set(permissions) - supported_permissions)
    if unsupported_permissions:
        diagnostics.append(
            "Unsupported permissions: " + ", ".join(unsupported_permissions) + "."
        )

    compatible = sdk_version == _sdk_version()
    if sdk_version and not compatible:
        diagnostics.append(
            f"Incompatible sdkVersion '{sdk_version}' (host supports '{_sdk_version()}')."
        )

    entry_exists = False
    entry_path = ""
    if entry:
        if Path(entry).is_absolute():
            diagnostics.append("Manifest entry must be a relative path inside the module directory.")
        elif module_dir is not None:
            candidate = (module_dir / entry).resolve()
            entry_path = str(candidate)
            entry_exists = candidate.exists() and candidate.is_file()
            if not entry_exists:
                diagnostics.append(f"Entrypoint file not found: {candidate}")

    valid = len([d for d in diagnostics if not d.startswith("Incompatible sdkVersion")]) == 0
    status = "ready"
    if not valid:
        status = "invalid"
    elif not compatible:
        status = "incompatible"

    return {
        "id": module_id,
        "name": name,
        "version": version,
        "sdkVersion": sdk_version,
        "entry": entry,
        "entryPath": entry_path,
        "entryExists": entry_exists,
        "description": description,
        "capabilities": capabilities,
        "permissions": permissions,
        "compatible": compatible,
        "valid": valid,
        "status": status,
        "diagnostics": diagnostics,
    }


def discover_modules() -> dict[str, Any]:
    """Scan the managed root directory and return all installed modules."""
    managed_root = _managed_root()
    modules: list[dict[str, Any]] = []

    if managed_root.exists() and managed_root.is_dir():
        candidates: list[Path] = []
        # A bare module.json at the root itself counts
        if (managed_root / "module.json").exists():
            candidates.append(managed_root)
        for child in sorted(managed_root.iterdir()):
            if child.is_dir() and (child / "module.json").exists():
                candidates.append(child)

        for module_dir in candidates:
            manifest_path = module_dir / "module.json"
            try:
                manifest = json.loads(manifest_path.read_text())
            except Exception as exc:  # noqa: BLE001
                modules.append({
                    "id": module_dir.name,
                    "name": module_dir.name,
                    "version": "",
                    "sdkVersion": "",
                    "entry": "",
                    "entryPath": "",
                    "entryExists": False,
                    "description": "",
                    "capabilities": [],
                    "permissions": [],
                    "compatible": False,
                    "valid": False,
                    "status": "invalid",
                    "diagnostics": [f"Could not parse module.json: {exc}"],
                    "manifestPath": str(manifest_path),
                    "modulePath": str(module_dir),
                    "isManaged": True,
                })
                continue

            validated = validate_manifest(manifest, module_dir=module_dir)
            modules.append({
                **validated,
                "manifestPath": str(manifest_path),
                "modulePath": str(module_dir),
                "isManaged": True,
                "config": manifest.get("config", {}),
                "panel": manifest.get("panel", {}),
            })

    summary = {
        "discovered": len(modules),
        "ready": sum(1 for m in modules if m["status"] == "ready"),
        "invalid": sum(1 for m in modules if m["status"] == "invalid"),
        "incompatible": sum(1 for m in modules if m["status"] == "incompatible"),
    }

    return {
        "host": {
            "sdkVersion": _sdk_version(),
            "supportedCapabilities": _supported_capabilities(),
            "supportedPermissions": _supported_permissions(),
            "managedRoot": _managed_root_descriptor(),
        },
        "modules": modules,
        "summary": summary,
    }


def install_module_from_upload(zip_bytes: bytes) -> dict[str, Any]:
    """Extract a zip upload into the managed module root and validate it.

    The zip may have a single top-level directory (the module folder) or be
    flat with ``module.json`` at the root — both layouts are handled.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid zip archive.") from exc

    names = zf.namelist()
    if not names:
        raise ValueError("Zip archive is empty.")

    # Determine the prefix to strip — if all entries share a single top-level
    # directory we unwrap it so the module installs cleanly.
    top_dirs = {n.split("/")[0] for n in names if n}
    manifest_at_root = any(n == "module.json" or n.endswith("/module.json") and n.count("/") == 1 for n in names)

    prefix = ""
    if not any(n == "module.json" for n in names):
        # No flat module.json — look for <dir>/module.json
        candidates = [n for n in names if n.endswith("/module.json") and n.count("/") == 1]
        if not candidates:
            raise ValueError("No module.json found in the zip archive.")
        prefix = candidates[0][: -len("module.json")]  # e.g. "myplugin/"

    # Read and parse module.json
    manifest_name = prefix + "module.json"
    try:
        manifest_bytes = zf.read(manifest_name)
        manifest = json.loads(manifest_bytes)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Could not parse module.json: {exc}") from exc

    validated = validate_manifest(manifest)
    if not validated["id"]:
        raise ValueError("module.json must have a non-empty 'id' field.")

    module_id = validated["id"]
    managed_root = _managed_root()
    managed_root.mkdir(parents=True, exist_ok=True)

    target = (managed_root / module_id).resolve()
    if not _is_relative_to(target, managed_root):
        raise ValueError("Refusing to install a module outside the managed module root.")
    if target.exists():
        raise ValueError(f"A module with id '{module_id}' is already installed. Uninstall it first.")

    # Extract files into target directory, stripping the prefix
    target.mkdir(parents=True)
    for member in zf.infolist():
        member_name = member.filename
        if not member_name.startswith(prefix):
            continue
        rel = member_name[len(prefix):]
        if not rel or rel.endswith("/"):
            # Directory entry
            (target / rel).mkdir(parents=True, exist_ok=True)
            continue
        dest = (target / rel).resolve()
        if not _is_relative_to(dest, target):
            continue  # skip any path traversal entries
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(member_name))

    # Re-validate with the actual extracted path for entrypoint existence check
    final_validated = validate_manifest(manifest, module_dir=target)

    return {
        **final_validated,
        "manifestPath": str(target / "module.json"),
        "modulePath": str(target),
        "isManaged": True,
        "installed": True,
    }


def uninstall_module(module_id: str) -> dict[str, Any]:
    module_id = str(module_id).strip()
    if not module_id:
        raise ValueError("Module id is required.")

    managed_root = _managed_root()
    target = (managed_root / module_id).resolve()
    if not _is_relative_to(target, managed_root):
        raise ValueError("Refusing to uninstall a module outside the managed module root.")
    if not target.exists():
        raise ValueError(f"Installed module '{module_id}' was not found.")
    if not (target / "module.json").exists():
        raise ValueError(f"Refusing to remove '{target}' because it does not look like a module.")

    shutil.rmtree(target)
    return {
        "uninstalled": True,
        "moduleId": module_id,
        "removedPath": str(target),
    }


def get_module_metadata(module_id: str) -> dict[str, Any]:
    """Return display metadata from a module's manifest (name, ui hints).

    Reads ``name`` and the optional ``ui`` dict from ``module.json``.  The
    ``ui`` dict maps data-key → ``{label, unit, format}`` so the frontend can
    render plugin results without any hardcoded knowledge of the plugin.

    Returns an empty dict on any read failure (caller falls back to raw keys).
    """
    manifest_path = _managed_root() / module_id / "module.json"
    try:
        manifest = json.loads(manifest_path.read_text())
        return {
            "name": str(manifest.get("name", module_id)),
            "ui": manifest.get("ui", {}),
        }
    except Exception:  # noqa: BLE001
        return {"name": module_id, "ui": {}}


# ── Generic plugin execution ──────────────────────────────────────────────────
#
# Plugins declare two fields in module.json:
#   "stage" — one of: pre-build | post-build | in-solve | post-solve
#   "hook"  — the function name to call in the entry file (default: "run")
#
# Stage kwargs contracts (what each hook receives):
#   pre-build  : fn(model, scenario, options)        → return dict replaces model
#   post-build : fn(network, scenario, options)      → return value ignored (in-place)
#   in-solve   : fn(network, model, scenario, options) → return value ignored (in-place)
#   post-solve : fn(network, results, scenario, options) → return dict stored in pluginAnalytics
#
# The backend knows nothing about capability types — it only routes by stage.

_STAGE_KWARGS: dict[str, tuple[str, ...]] = {
    "pre-build":  ("model", "scenario", "options"),
    "post-build": ("network", "scenario", "options"),
    "in-solve":   ("network", "model", "scenario", "options"),
    "post-solve": ("network", "results", "scenario", "options"),
}


def _load_module_entry(module_id: str):  # type: ignore[return]
    """Import a module's entry file and return the (module_object, manifest) pair.

    Returns ``(None, None)`` on any failure.
    """
    managed_root = _managed_root()
    module_dir = managed_root / module_id
    manifest_path = module_dir / "module.json"
    if not manifest_path.exists():
        logger.warning("Module '%s' not found — skipped.", module_id)
        return None, None

    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read manifest for '%s': %s — skipped.", module_id, exc)
        return None, None

    entry = str(manifest.get("entry", "")).strip()
    if not entry:
        logger.warning("Module '%s' has no 'entry' in manifest — skipped.", module_id)
        return None, None

    entry_path = (module_dir / entry).resolve()
    if not entry_path.exists():
        logger.warning("Entry not found for '%s': %s — skipped.", module_id, entry_path)
        return None, None

    try:
        spec = importlib.util.spec_from_file_location(
            f"ragnarok_module_{module_id}", entry_path
        )
        if spec is None or spec.loader is None:
            raise ImportError("Could not create module spec.")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod, manifest
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to import '%s': %s — skipped.", module_id, exc)
        return None, None


def execute_plugins_at_stage(
    stage: str,
    enabled_ids: list[str],
    **kwargs: Any,
) -> dict[str, Any]:
    """Run all enabled plugins registered for ``stage``.

    The caller passes stage-specific keyword arguments (see ``_STAGE_KWARGS``).
    Return values are collected in a dict keyed by module_id; plugins that
    return ``None`` are omitted.  Errors per module are caught, logged, and
    stored as ``{"error": "..."}`` so the pipeline always continues.

    Args:
        stage:       Pipeline stage name (``pre-build``, ``post-build``,
                     ``in-solve``, ``post-solve``).
        enabled_ids: Module IDs that are currently enabled by the user.
        **kwargs:    Stage-specific context (``model``, ``network``, etc.).

    Returns:
        Dict of ``{module_id: return_value}`` for modules that returned a value.
    """
    outputs: dict[str, Any] = {}
    for module_id in enabled_ids:
        mod, manifest = _load_module_entry(module_id)
        if mod is None or manifest is None:
            continue

        module_stage = str(manifest.get("stage", "")).strip()
        if module_stage != stage:
            continue

        hook_name = str(manifest.get("hook", "run")).strip()
        fn = getattr(mod, hook_name, None)
        if fn is None or not callable(fn):
            logger.debug("Module '%s' has no callable '%s' — skipped.", module_id, hook_name)
            continue

        # Pass only the kwargs the stage contract defines.
        # Inject this module's own config as options["moduleConfig"] so the
        # plugin reads options.get("moduleConfig", {}) without knowing its id.
        allowed = _STAGE_KWARGS.get(stage, ())
        call_kwargs = {k: kwargs[k] for k in allowed if k in kwargs}
        if "options" in call_kwargs:
            all_configs = (call_kwargs["options"] or {}).get("moduleConfigs", {})
            call_kwargs["options"] = {
                **call_kwargs["options"],
                "moduleConfig": all_configs.get(module_id, {}),
            }

        try:
            result = fn(**call_kwargs)
            logger.info("Plugin '%s' executed at stage '%s'.", module_id, stage)
            if result is not None:
                outputs[module_id] = result
        except Exception as exc:  # noqa: BLE001
            logger.error("Plugin '%s' at stage '%s' failed: %s.", module_id, stage, exc)
            if stage == "in-solve":
                # Constraint-registration failures must propagate — swallowing them
                # would let the solver run WITHOUT the constraint, silently producing
                # wrong results.  Re-raise so extra_functionality aborts.
                raise
            outputs[module_id] = {"error": str(exc)}

    return outputs


def execute_module_action(
    module_id: str,
    hook_name: str,
    stage_kwargs_for: str = "pre-build",
    **kwargs: Any,
) -> Any:
    """Invoke a named hook on a single module, bypassing the manifest stage filter.

    Used by the action-button preview endpoint, which calls the hook
    declared on an ``action`` config field (currently always ``transform``)
    regardless of what stage the manifest declares for the plugin's
    regular pipeline contribution.  This lets a plugin whose main stage
    is e.g. ``in-solve`` still expose a "Send model" action that runs
    its ``transform`` hook in isolation.

    Args:
        module_id:        Module to invoke.
        hook_name:        Python function name to call on the module entry.
        stage_kwargs_for: Stage whose kwarg contract to apply when calling
                          the hook.  Defaults to ``"pre-build"`` because
                          that is the only contract that returns a model.
        **kwargs:         Stage context (``model``, ``scenario``, ``options``).

    Returns:
        Whatever the hook returns, or ``None`` if the module / hook cannot
        be loaded.  Exceptions are NOT caught — the caller decides how to
        surface them (typically as an HTTP error).
    """
    mod, manifest = _load_module_entry(module_id)
    if mod is None or manifest is None:
        return None
    fn = getattr(mod, hook_name, None)
    if fn is None or not callable(fn):
        logger.debug("Module '%s' has no callable '%s' — action skipped.", module_id, hook_name)
        return None

    allowed = _STAGE_KWARGS.get(stage_kwargs_for, ())
    call_kwargs = {k: kwargs[k] for k in allowed if k in kwargs}
    if "options" in call_kwargs:
        all_configs = (call_kwargs["options"] or {}).get("moduleConfigs", {})
        call_kwargs["options"] = {
            **call_kwargs["options"],
            "moduleConfig": all_configs.get(module_id, {}),
        }
    return fn(**call_kwargs)
