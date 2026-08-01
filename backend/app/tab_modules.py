"""Tab-module store — third-party MODULES installed on the SERVER.

A module is a whole Ragnarok tab (see ``docs/module.md``); a plugin is a small
extension (:mod:`backend.app.plugins`). This module owns the *third-party* half
of the tab-module system: the package on disk and its enabled flag.

**Why server-side.** The first cut kept installed modules in browser
localStorage, which two separate wipes destroy: the build-id reset in
``index.tsx`` (fires on EVERY app update / dev restart) and the "Clear cache"
button. A module is user-installed content that belongs to the project, not
browser cache, so it lives here — under ``backend/data/modules/`` — and survives
cache clears, app updates and a different browser.

Layout, mirroring :data:`backend.app.plugins.BACKEND_PLUGINS_DIR`::

    backend/data/modules/
      <id>/
        tabmodule.json     manifest: {id, label, hint?, description?, order?, entry?}
        index.js           CommonJS entry exporting mount(el, ctx)
        …                  any other files the entry needs
      .state.json          {"<id>": {"enabled": true}}

Discovery never raises: a malformed module is logged and skipped so the app
always starts. The frontend reads this list, merges it with the built-in modules
and renders the activity bar from the result.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger("pypsa_gui.tab_modules")

MANIFEST_NAME = "tabmodule.json"
_STATE_FILE = ".state.json"

# Install directory for third-party tab-modules. Under backend/data/ (gitignored
# runtime content), overridable so a deployment can mount modules anywhere.
TAB_MODULES_DIR = Path(
    os.environ.get("RAGNAROK_TAB_MODULES_DIR")
    or (Path(__file__).resolve().parents[1] / "data" / "modules")
)

# Ids that a third-party module may never take: they would shadow a core tab or
# a built-in module. Kept in sync with frontend/src/modules/registry.ts (the
# frontend re-checks too — this is the authoritative gate).
RESERVED_IDS: frozenset[str] = frozenset({
    # core tabs
    "Welcome", "Build", "Model", "Market", "Settings", "Analytics", "History", "Plugins",
    # built-in modules
    "Data", "Forge", "PhysicalRisk", "Siting", "PostAnalysis", "Training",
})

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

# Where an external module lands on the activity bar when its manifest is silent
# (core occupies 10–110, built-in modules interleave).
DEFAULT_ORDER = 200


def _mb_env(name: str, default_mb: int) -> int:
    try:
        mb = int(os.environ.get(name, "") or default_mb)
    except ValueError:
        mb = default_mb
    return max(0, mb) * 1024 * 1024


MAX_MODULE_ZIP_BYTES = _mb_env("RAGNAROK_MAX_MODULE_ZIP_MB", 50)
MAX_MODULE_UNZIPPED_BYTES = _mb_env("RAGNAROK_MAX_MODULE_UNZIPPED_MB", 200)


class ModuleError(ValueError):
    """A module package is unusable — surfaced to the caller as HTTP 400."""


# ── enabled-flag state ──────────────────────────────────────────────────────────

def _state_path() -> Path:
    return TAB_MODULES_DIR / _STATE_FILE


def _read_state() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(_state_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 — absent or corrupt: start clean
        return {}


def _write_state(state: dict[str, dict[str, Any]]) -> None:
    TAB_MODULES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(_state_path())


def set_enabled(module_id: str, enabled: bool) -> None:
    """Persist a module's enabled flag (server-side, so a cache clear can't reset it)."""
    state = _read_state()
    entry = state.get(module_id) or {}
    entry["enabled"] = bool(enabled)
    state[module_id] = entry
    _write_state(state)


# ── manifest validation ─────────────────────────────────────────────────────────

def validate_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise + check a ``tabmodule.json`` body. Raises :class:`ModuleError`."""
    module_id = str(raw.get("id") or "").strip()
    if not module_id:
        raise ModuleError(f"{MANIFEST_NAME} is missing an \"id\".")
    if not _ID_RE.match(module_id):
        raise ModuleError(
            f"Module id {module_id!r} must start with a letter and use only "
            "letters, digits, dashes or underscores."
        )
    if module_id in RESERVED_IDS:
        raise ModuleError(f"Module id {module_id!r} collides with a built-in Ragnarok tab.")
    label = str(raw.get("label") or module_id).strip()
    try:
        order = int(raw.get("order"))
    except (TypeError, ValueError):
        order = DEFAULT_ORDER
    entry = str(raw.get("entry") or "index.js").strip() or "index.js"
    if entry != os.path.basename(entry) and ".." in entry:
        raise ModuleError(f"Entry path {entry!r} must stay inside the package.")
    return {
        "id": module_id,
        "label": label,
        "hint": str(raw.get("hint") or label),
        "description": str(raw.get("description") or ""),
        "order": order,
        "entry": entry,
    }


# ── discovery ───────────────────────────────────────────────────────────────────

def _read_module_dir(directory: Path, state: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """One installed module as a JSON-safe dict, or None when unusable."""
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    try:
        manifest = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001 — never break discovery
        logger.warning("Skipping module at %s: %s", directory, exc)
        return None
    if manifest["id"] != directory.name:
        logger.warning(
            "Skipping module at %s: manifest id %r does not match its directory name.",
            directory, manifest["id"],
        )
        return None
    entry_path = directory / manifest["entry"]
    if not entry_path.is_file():
        logger.warning("Skipping module %r: entry file %r missing.", manifest["id"], manifest["entry"])
        return None
    files: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name == _STATE_FILE:
            continue
        try:
            files[str(path.relative_to(directory))] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # Binary or unreadable asset — the browser host only evaluates text.
            continue
    enabled = bool((state.get(manifest["id"]) or {}).get("enabled", True))
    return {
        "manifest": manifest,
        "files": files,
        "enabled": enabled,
        "installedAt": _installed_at(directory),
    }


def _installed_at(directory: Path) -> str:
    from datetime import datetime, timezone
    try:
        ts = directory.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def list_modules() -> list[dict[str, Any]]:
    """Every usable installed module, ordered by activity-bar position then id."""
    if not TAB_MODULES_DIR.is_dir():
        return []
    state = _read_state()
    out: list[dict[str, Any]] = []
    for directory in sorted(TAB_MODULES_DIR.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        entry = _read_module_dir(directory, state)
        if entry is not None:
            out.append(entry)
    out.sort(key=lambda m: (m["manifest"]["order"], m["manifest"]["id"]))
    return out


def get_module(module_id: str) -> dict[str, Any] | None:
    directory = module_dir(module_id)
    if not directory.is_dir():
        return None
    return _read_module_dir(directory, _read_state())


def module_dir(module_id: str) -> Path:
    """The install directory for an id — always inside TAB_MODULES_DIR."""
    if not _ID_RE.match(str(module_id)):
        raise ModuleError(f"Unsafe module id {module_id!r}.")
    return TAB_MODULES_DIR / str(module_id)


# ── install / remove ────────────────────────────────────────────────────────────

def _manifest_from_zip(entries: dict[str, bytes]) -> tuple[str, dict[str, Any]]:
    """``(prefix, manifest)`` — locate tabmodule.json at the root or one level in."""
    candidates = [n for n in entries if n == MANIFEST_NAME or n.endswith(f"/{MANIFEST_NAME}")]
    if not candidates:
        raise ModuleError(f"The package has no {MANIFEST_NAME} manifest.")
    # Prefer the shallowest manifest so a nested duplicate can't shadow the root.
    manifest_path = min(candidates, key=lambda n: n.count("/"))
    prefix = manifest_path[: len(manifest_path) - len(MANIFEST_NAME)]
    try:
        raw = json.loads(entries[manifest_path].decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ModuleError(f"{MANIFEST_NAME} is not valid JSON.") from exc
    return prefix, validate_manifest(raw)


def install_from_zip(data: bytes) -> dict[str, Any]:
    """Install (or update in place) a module from ``.zip`` bytes.

    Re-installing an id REPLACES its directory and keeps its enabled flag — the
    iteration loop while developing a module.
    """
    import zipfile
    from io import BytesIO

    if MAX_MODULE_ZIP_BYTES and len(data) > MAX_MODULE_ZIP_BYTES:
        raise ModuleError(
            f"Module .zip is larger than the {MAX_MODULE_ZIP_BYTES // (1024 * 1024)} MB limit."
        )
    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ModuleError("Not a readable .zip archive.") from exc

    total = 0
    entries: dict[str, bytes] = {}
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise ModuleError(f"Refusing entry with an unsafe path: {info.filename!r}")
            total += info.file_size
            if MAX_MODULE_UNZIPPED_BYTES and total > MAX_MODULE_UNZIPPED_BYTES:
                raise ModuleError(
                    "Module contents exceed the "
                    f"{MAX_MODULE_UNZIPPED_BYTES // (1024 * 1024)} MB unpacked limit."
                )
            entries[name] = zf.read(info)

    prefix, manifest = _manifest_from_zip(entries)
    payload = {
        name[len(prefix):]: body
        for name, body in entries.items()
        if name.startswith(prefix) and name[len(prefix):]
    }
    if manifest["entry"] not in payload:
        raise ModuleError(f"Entry file {manifest['entry']!r} not found in the package.")

    target = module_dir(manifest["id"])
    shutil.rmtree(target, ignore_errors=True)
    for rel, body in payload.items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    # Rewrite the manifest normalised, so the id/entry the app reads back is
    # exactly what was validated here.
    (target / MANIFEST_NAME).write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    installed = get_module(manifest["id"])
    if installed is None:  # pragma: no cover — validated above
        shutil.rmtree(target, ignore_errors=True)
        raise ModuleError(f"Module {manifest['id']!r} installed but could not be loaded.")
    logger.info("Installed tab-module %r (%d files)", manifest["id"], len(installed["files"]))
    return installed


def install_from_path(source: str | Path) -> dict[str, Any]:
    """Install from a DIRECTORY on the server's filesystem.

    The path form an agent uses (MCP ``install_tab_module``): scaffold a module
    in a directory, then register it without packing a zip first.
    """
    src = Path(source).expanduser().resolve()
    if not src.is_dir():
        raise ModuleError(f"{src} is not a directory.")
    manifest_path = src / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ModuleError(f"{src} has no {MANIFEST_NAME}.")
    try:
        manifest = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    except ModuleError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ModuleError(f"{MANIFEST_NAME} is not valid JSON.") from exc
    if not (src / manifest["entry"]).is_file():
        raise ModuleError(f"Entry file {manifest['entry']!r} not found in {src}.")

    target = module_dir(manifest["id"])
    if target.resolve() == src:
        raise ModuleError("The module is already installed at that location.")
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(src, target)
    (target / MANIFEST_NAME).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    installed = get_module(manifest["id"])
    if installed is None:  # pragma: no cover
        shutil.rmtree(target, ignore_errors=True)
        raise ModuleError(f"Module {manifest['id']!r} installed but could not be loaded.")
    logger.info("Installed tab-module %r from %s", manifest["id"], src)
    return installed


def remove_module(module_id: str) -> bool:
    """Uninstall a module (directory + its enabled flag). False when absent."""
    target = module_dir(module_id)
    root = TAB_MODULES_DIR.resolve()
    resolved = target.resolve()
    # Only ever delete a direct child of the install dir.
    if resolved.parent != root or not resolved.is_dir():
        return False
    shutil.rmtree(resolved)
    state = _read_state()
    if state.pop(str(module_id), None) is not None:
        _write_state(state)
    logger.info("Removed tab-module %r", module_id)
    return True
