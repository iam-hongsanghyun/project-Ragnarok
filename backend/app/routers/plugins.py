"""``/api/plugins`` — backend (server-side) plugins.

Backend plugins run inside the Ragnarok backend and may import the bundled
PyPSA source directly. They share ONE hook contract with frontend plugins:

* ``transform(model, config) -> model``                — replace the working model
* ``contribute(model, config) -> {sheets, constraints}`` — add sheets/constraints
* ``analyze(result, config) -> data``                   — read-only Output data

``transform``/``contribute`` write into the session (the source of truth), so the
produced model never travels through the browser.

Ragnarok ships NO plugins. They are purely 3rd-party and arrive via upload-install
(``POST /install``); ``DELETE /{id}`` removes one. Installed plugins live under
``backend/data/plugins/`` (gitignored).

Endpoints::

    GET    /api/plugins                  -> [manifest, ...]
    GET    /api/plugins/{id}             -> manifest
    POST   /api/plugins/install          -> manifest   (multipart .zip upload)
    DELETE /api/plugins/{id}             -> {removed}
    POST   /api/plugins/{id}/transform   -> session meta
    POST   /api/plugins/{id}/contribute  -> session meta
    POST   /api/plugins/{id}/analyze     -> analytics dict

Security: install accepts a .zip of runnable Python that the backend imports —
i.e. remote code execution by design. Acceptable single-user/local; for a
multi-user remote deployment this must be gated behind auth/sandboxing.

See :mod:`backend.app.plugins` for the registry/loader and the plugin contract.
"""
from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import plugins, session_store

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

_ID_RE = re.compile(r"[^a-zA-Z0-9._-]")


class TransformRequest(BaseModel):
    """Body for ``POST /api/plugins/{id}/transform`` and ``/contribute``."""

    config: dict[str, Any] = {}
    sessionId: str = "default"
    filename: str = ""
    scenarioName: str = ""


class AnalyzeRequest(BaseModel):
    """Body for ``POST /api/plugins/{id}/analyze``."""

    config: dict[str, Any] = {}
    result: dict[str, Any] = {}


@router.get("")
def get_plugins(refresh: bool = False) -> dict[str, Any]:
    """List loaded backend plugins. ``refresh=true`` re-scans the plugins dir."""
    return {"plugins": plugins.list_plugins(refresh=refresh)}


@router.get("/{plugin_id}")
def get_plugin(plugin_id: str) -> dict[str, Any]:
    plugin = plugins.get(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Backend plugin {plugin_id!r} not found.")
    return plugin.to_dict()


# ── Lifecycle: install (upload .zip) / uninstall (remove) ─────────────────────


def _safe_extract_zip(data: bytes, dest_root: Path) -> str:
    """Extract a backend-plugin .zip into ``dest_root/<id>/`` (zip-slip-safe).

    The zip must contain ``manifest.json`` (with an ``id``) and ``plugin.py`` at
    the same level (root or one folder deep). Returns the plugin id. Replaces any
    existing plugin with that id.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid .zip.") from exc

    names = [n for n in zf.namelist() if not n.endswith("/")]
    manifest_name = min(
        (n for n in names if n.rsplit("/", 1)[-1] == "manifest.json"),
        key=lambda n: n.count("/"),
        default=None,
    )
    if manifest_name is None:
        raise HTTPException(status_code=400, detail="Backend plugin .zip has no manifest.json.")
    prefix = manifest_name[: manifest_name.rfind("/") + 1] if "/" in manifest_name else ""
    if f"{prefix}plugin.py" not in names:
        raise HTTPException(status_code=400, detail="Backend plugin .zip has no plugin.py next to manifest.json.")

    import json

    try:
        manifest = json.loads(zf.read(manifest_name).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="manifest.json is not valid JSON.") from exc
    raw_id = str(manifest.get("id") or "").strip()
    plugin_id = _ID_RE.sub("", raw_id)
    if not plugin_id or plugin_id != raw_id:
        raise HTTPException(status_code=400, detail="manifest.json has a missing/invalid id.")

    dest = (dest_root / plugin_id).resolve()
    root_resolved = dest_root.resolve()
    if dest.parent != root_resolved:  # paranoia: id can't escape the install dir
        raise HTTPException(status_code=400, detail="Refusing to install outside the plugins dir.")

    if dest.exists():
        shutil.rmtree(dest)  # replace-in-place, like frontend install
    dest.mkdir(parents=True)
    for name in names:
        if not name.startswith(prefix):
            continue
        rel = name[len(prefix):]
        if not rel:
            continue
        target = (dest / rel).resolve()
        if not str(target).startswith(str(dest) + "/") and target != dest:
            raise HTTPException(status_code=400, detail="Unsafe path in .zip (zip-slip).")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(name))
    return plugin_id


@router.post("/install")
async def install_plugin(file: UploadFile = File(...)) -> dict[str, Any]:
    """Install a backend plugin from an uploaded ``.zip`` (manifest.json + plugin.py)."""
    data = await file.read()
    plugins.BACKEND_PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    plugin_id = _safe_extract_zip(data, plugins.BACKEND_PLUGINS_DIR)
    plugins.registry(refresh=True)
    plugin = plugins.get(plugin_id)
    if plugin is None:
        # Extracted but failed to load (bad hook / import error) — clean up.
        shutil.rmtree(plugins.BACKEND_PLUGINS_DIR / plugin_id, ignore_errors=True)
        plugins.registry(refresh=True)
        raise HTTPException(status_code=400, detail=f"Plugin {plugin_id!r} installed but failed to load.")
    return plugin.to_dict()


@router.delete("/{plugin_id}")
def uninstall_plugin(plugin_id: str) -> dict[str, Any]:
    """Remove an installed backend plugin's directory and refresh the registry."""
    root = plugins.BACKEND_PLUGINS_DIR.resolve()
    plugin = plugins.get(plugin_id)
    target = (plugin.directory.resolve() if plugin is not None else (root / _ID_RE.sub("", plugin_id)).resolve())
    # Only ever delete inside the install dir.
    if target.parent != root or not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Installed plugin {plugin_id!r} not found.")
    shutil.rmtree(target)
    plugins.remove_plugin_files(plugin_id)  # also drop the plugin's uploaded data files
    plugins.registry(refresh=True)
    return {"id": plugin_id, "removed": True}


# ── Per-plugin data files (server-side scratch store) ─────────────────────────
# A plugin's heavy input (e.g. a model workbook) is uploaded HERE once and then
# referenced by name in the config — the bytes never live in the browser/config.


@router.post("/{plugin_id}/files")
async def upload_plugin_file(plugin_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a data file into the plugin's server-side scratch dir."""
    if plugins.get(plugin_id) is None:
        raise HTTPException(status_code=404, detail=f"Backend plugin {plugin_id!r} not found.")
    data = await file.read()
    return plugins.save_plugin_file(plugin_id, file.filename or "upload.bin", data)


@router.get("/{plugin_id}/files")
def get_plugin_files(plugin_id: str) -> dict[str, Any]:
    """List the plugin's uploaded data files (for the picker dropdown)."""
    return {"files": plugins.list_plugin_files(plugin_id)}


@router.delete("/{plugin_id}/files/{filename}")
def delete_plugin_file(plugin_id: str, filename: str) -> dict[str, Any]:
    """Delete one uploaded data file."""
    removed = plugins.delete_plugin_file(plugin_id, filename)
    if not removed:
        raise HTTPException(status_code=404, detail=f"File {filename!r} not found.")
    return {"name": filename, "removed": True}


# ── Hooks ─────────────────────────────────────────────────────────────────────


def _save_transformed(plugin_id: str, body: TransformRequest, model: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    try:
        return session_store.save_model(
            body.sessionId,
            model,
            filename=body.filename or f"{plugin_id}.xlsx",
            scenario_name=body.scenarioName,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{plugin_id}/transform")
def transform_plugin(plugin_id: str, body: TransformRequest) -> dict[str, Any]:
    """Run ``transform(model, config)`` on the session model and persist the result.

    Returns the lightweight session meta — the model stays server-side.
    """
    current = session_store.load_full_model(body.sessionId) or {}
    try:
        model = plugins.run_transform(plugin_id, current, body.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Backend plugin {plugin_id!r} not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _save_transformed(plugin_id, body, model)


@router.post("/{plugin_id}/contribute")
def contribute_plugin(plugin_id: str, body: TransformRequest) -> dict[str, Any]:
    """Run ``contribute(model, config)`` and merge its sheets + constraints into the session."""
    current = session_store.load_full_model(body.sessionId) or {}
    try:
        out = plugins.run_contribute(plugin_id, current, body.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Backend plugin {plugin_id!r} not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    fragment: dict[str, list[dict[str, Any]]] = {}
    sheets = out.get("sheets")
    if isinstance(sheets, dict):
        fragment.update({str(k): list(v) for k, v in sheets.items()})
    constraints = out.get("constraints")
    if isinstance(constraints, list) and constraints:
        fragment["RAGNAROK_CustomDSL"] = [{"text": "\n".join(str(c) for c in constraints)}]
    if not fragment:
        meta = session_store.get_meta(body.sessionId)
        if meta is None:
            raise HTTPException(status_code=400, detail="No session to contribute into.")
        return meta
    meta = session_store.merge_static_model(body.sessionId, fragment)
    if meta is None:
        # No existing session — fall back to a full save of the fragment.
        return _save_transformed(plugin_id, body, fragment)
    return meta


@router.post("/{plugin_id}/analyze")
def analyze_plugin(plugin_id: str, body: AnalyzeRequest) -> dict[str, Any]:
    """Run the plugin's ``analyze(result, config)`` and return its output."""
    try:
        return plugins.run_analyze(plugin_id, body.result, body.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Backend plugin {plugin_id!r} not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
