"""``/api/plugins`` — backend (server-side) plugins.

Backend plugins run inside the Ragnarok backend and may import the bundled
PyPSA source directly. The frontend lists them alongside browser plugins and
runs them here; a ``build`` plugin writes its model straight into the session
(the source of truth), so the produced model never travels through the browser.

Endpoints::

    GET  /api/plugins                 -> [manifest, ...] (backend plugins)
    GET  /api/plugins/{id}            -> manifest
    POST /api/plugins/{id}/build      -> session meta (build model -> session)
    POST /api/plugins/{id}/analyze    -> analytics dict

See :mod:`backend.app.plugins` for the registry/loader and the plugin contract.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import plugins, session_store

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class BuildRequest(BaseModel):
    """Body for ``POST /api/plugins/{id}/build``."""

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


@router.post("/{plugin_id}/build")
def build_plugin(plugin_id: str, body: BuildRequest) -> dict[str, Any]:
    """Run the plugin's ``build(config)`` and persist the model into the session.

    Returns the lightweight session meta — the model itself stays server-side.
    """
    try:
        model = plugins.run_build(plugin_id, body.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Backend plugin {plugin_id!r} not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return session_store.save_model(
            body.sessionId,
            model,
            filename=body.filename or f"{plugin_id}.xlsx",
            scenario_name=body.scenarioName,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{plugin_id}/analyze")
def analyze_plugin(plugin_id: str, body: AnalyzeRequest) -> dict[str, Any]:
    """Run the plugin's ``analyze(result, config)`` and return its output."""
    try:
        return plugins.run_analyze(plugin_id, body.result, body.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Backend plugin {plugin_id!r} not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
