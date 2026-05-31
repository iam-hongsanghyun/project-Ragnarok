"""``/api/config`` — the boot bundle the frontend fetches at startup.

Isolated module: knows nothing about importers, solver runs, or any
other backend concern. Just hands back the shared `ConfigBundle` that
``backend/app/config_provider.py`` produces — which itself is dynamic
(PyPSA schema computed live from the installed package, capabilities
pulled from the live backend registry).

Endpoints:

    GET  /api/config         — full bundle (~110 kB JSON, gzip ~25 kB).
    GET  /api/config/build-id  — just the ``{build_id, backend_version}``
                                 pair; cheap call for the frontend to
                                 check freshness without a full fetch.
    POST /api/config/reload  — drop the in-memory cache so the next
                               request rebuilds. Useful in dev when
                               PyPSA is upgraded without a restart.
"""
from __future__ import annotations

from fastapi import APIRouter

from ..config_provider import load_bundle, reset_cache


router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def get_config() -> dict:
    """Return the full shared-config bundle.

    Caller is expected to cache the response in `localStorage` keyed by
    ``build_id`` and re-fetch only when the id changes.
    """
    return load_bundle().to_json()


@router.get("/build-id")
def get_build_id() -> dict:
    """Cheap freshness probe — returns just the build_id + version.

    Lets the frontend decide whether its cached bundle is still current
    without paying the full payload cost.
    """
    bundle = load_bundle()
    return {
        "build_id": bundle.build_id,
        "backend_version": bundle.backend_version,
    }


@router.post("/reload")
def reload_config() -> dict:
    """Drop the cached bundle. The next ``GET /api/config`` rebuilds.

    Dev affordance: skip a server restart after bumping PyPSA. In
    production the bundle is stable for the life of the process, so
    this endpoint just no-ops the next caller into a fresh build.
    """
    reset_cache()
    bundle = load_bundle()
    return {"reloaded": True, "build_id": bundle.build_id}
