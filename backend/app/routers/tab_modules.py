"""``/api/modules/*`` — third-party TAB-MODULE install/list/remove.

A module is a whole Ragnarok tab; a plugin is a small extension
(``/api/plugins``). Packages live on the SERVER (``backend/data/modules/``) so
they belong to the project rather than one browser's cache: a "Clear cache", an
app update (which resets ``localStorage`` on a build-id change) or a different
browser never loses them. See ``docs/module.md``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import tab_modules

router = APIRouter(prefix="/api/modules", tags=["modules"])


class InstallFromPathRequest(BaseModel):
    """Install from a directory already on the server's filesystem."""
    path: str


class EnabledRequest(BaseModel):
    enabled: bool


@router.get("")
def list_installed() -> dict[str, Any]:
    """Every usable installed module (manifest + text files + enabled flag)."""
    return {"modules": tab_modules.list_modules()}


@router.post("/install")
async def install(file: UploadFile = File(...)) -> dict[str, Any]:
    """Install (or update in place) a module from an uploaded ``.zip``."""
    data = await file.read()
    try:
        return tab_modules.install_from_zip(data)
    except tab_modules.ModuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/install-path")
def install_path(body: InstallFromPathRequest) -> dict[str, Any]:
    """Install from a server-side directory — the path form an agent/CLI uses."""
    try:
        return tab_modules.install_from_path(body.path)
    except tab_modules.ModuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{module_id}/enabled")
def set_enabled(module_id: str, body: EnabledRequest) -> dict[str, Any]:
    """Show/hide a module's tab. Persisted server-side, so it survives a cache clear."""
    if tab_modules.get_module(module_id) is None:
        raise HTTPException(status_code=404, detail=f"Module {module_id!r} is not installed.")
    try:
        tab_modules.set_enabled(module_id, body.enabled)
    except tab_modules.ModuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": module_id, "enabled": body.enabled}


@router.delete("/{module_id}")
def remove(module_id: str) -> dict[str, Any]:
    """Uninstall a module: its directory and its enabled flag."""
    try:
        removed = tab_modules.remove_module(module_id)
    except tab_modules.ModuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"Module {module_id!r} is not installed.")
    return {"id": module_id, "removed": True}
