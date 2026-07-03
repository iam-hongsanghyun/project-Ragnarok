"""``/api/import/*`` — the external-data importer subsystem.

The Data view's three-pane shell routes through these endpoints. The
browser sends only a filter blob (+ any BYOK secrets); fetch and convert
run here. The frontend's entire outside world for data import is this
one router.

  GET  /api/import/databases                  — registry (left rail tree)
  GET  /api/import/countries                  — country index (map search)
  GET  /api/import/boundaries/countries.geojson — polygons (the world map)
  POST /api/import/run                        — fetch + preview + fragment

``POST /run`` is one trip: it returns the preview (right-rail counts /
samples / overlay) AND the workbook fragment together, matching the
main modelling pattern (1 payload in → 1 result out). The frontend holds
the fragment in React state until the user clicks Add to workbook — no
second network call.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..importers import (
    ConvertOptions,
    ImportContext,
    available_databases,
    available_sources,
    registered_databases,
)
from ..importers import region as region_mod
from ..importers.combine import combine_fragments, combine_previews
from ..importers.http import AsyncClientWrapper


router = APIRouter(prefix="/api/import", tags=["import"])

# Server-side API keys, two layers (values never leave the server):
# 1. env: any ``RAGNAROK_SECRET_<NAME>`` provides the importer secret ``<name>``
#    (lowercased) — set in the gitignored ``backend/.env``.
# 2. stored: keys the user typed into Settings → API keys are RECORDED on the
#    backend in ``backend/data/secrets.json`` (gitignored, 0600) via the
#    endpoints below, and win over env. A key sent in a request body (BYOK)
#    overrides both for that one request.
_SERVER_SECRET_PREFIX = "RAGNAROK_SECRET_"
_SECRET_NAME_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_REPO_ROOT = Path(__file__).resolve().parents[3]
SECRETS_PATH = _REPO_ROOT / "backend" / "data" / "secrets.json"


def _env_secrets() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith(_SERVER_SECRET_PREFIX) and value.strip():
            out[key[len(_SERVER_SECRET_PREFIX):].lower()] = value.strip()
    return out


def _stored_secrets() -> dict[str, str]:
    try:
        if not SECRETS_PATH.exists():
            return {}
        data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items() if str(v).strip()} if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — a corrupt file must not break imports
        return {}


def _write_stored_secrets(secrets: dict[str, str]) -> None:
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_PATH.write_text(json.dumps(secrets, indent=2), encoding="utf-8")
    try:
        os.chmod(SECRETS_PATH, 0o600)  # owner-only — these are credentials
    except OSError:
        pass


def _server_secrets() -> dict[str, str]:
    """All importer secrets the server provides: env, overridden by stored."""
    return {**_env_secrets(), **_stored_secrets()}


class ImportRunRequest(BaseModel):
    # Datasets of one source to fetch together (Country → Database → Datasets).
    dataset_ids: list[str] = []
    # Back-compat single-dataset form (older clients): treated as [database_id].
    database_id: str | None = None
    country_iso: str
    filters: dict[str, Any] = {}
    convert_options: dict[str, Any] | None = None
    # BYOK: per-user API keys, used for this request only, never persisted.
    secrets: dict[str, str] = {}


@router.get("/databases")
def list_databases() -> dict[str, Any]:
    """Flat registry contents (one entry per dataset)."""
    return {"databases": available_databases()}


@router.get("/starter-packs")
def list_starter_packs() -> dict[str, Any]:
    """Available country starter-pack recipes (W2) — Country → Year → build."""
    from .. import starter_packs

    return {"packs": starter_packs.list_recipes()}


@router.get("/health")
async def import_health(sources: str | None = None) -> dict[str, Any]:
    """Reachability of each upstream source (D1) — {source_id: {ok, status, …}}."""
    from ..importers import health

    ids = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
    return {"sources": await health.check_sources(ids)}


@router.get("/provenance")
def import_provenance(limit: int = 50) -> dict[str, Any]:
    """Recent import events from the persistent provenance log (D1), newest first."""
    from ..importers import provenance_log

    return {"imports": provenance_log.recent_imports(max(1, min(int(limit), 500)))}


@router.post("/location-model/{iso3}")
async def build_location_model(iso3: str, payload: SecretPayload | None = None) -> dict[str, Any]:
    """One-click: assemble a runnable model for any country (I1).

    Auto-composes the keyless global importers (OSM network + power plants, WRI
    fleet, World Bank demand) for the country and folds them into one workbook —
    the "pick a location → runnable model" path, no API keys needed.
    """
    from .. import starter_packs

    dbs = registered_databases()
    recipe = starter_packs.auto_recipe(iso3, dbs)
    if not recipe["steps"]:
        raise HTTPException(status_code=404, detail=f"No keyless datasets cover {iso3.upper()}.")

    await _ensure_boundaries_warm()
    try:
        region = region_mod.get_region(iso3)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    secrets = {**_server_secrets()}
    if payload is not None:
        secrets.update({k: v for k, v in (payload.secrets or {}).items() if str(v).strip()})
    http = AsyncClientWrapper(secrets=list(secrets.values()))
    ctx = ImportContext(secrets=secrets, http=http, request_id=starter_packs.new_request_id())
    try:
        fragment, dataset_ids, previews = await starter_packs.build_from_recipe(
            recipe, dbs=dbs, region=region, ctx=ctx, options=ConvertOptions(), combine=combine_fragments,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"location-model build failed: {exc}") from exc
    finally:
        await http.aclose()

    summary = combine_previews(fragment, previews)
    return {
        "iso3": recipe["iso3"], "label": recipe["label"], "dataset_ids": dataset_ids,
        "country_iso": region.country_iso, "preview": summary.to_json(), "fragment": fragment.to_json(),
    }


@router.post("/starter-packs/{iso3}/{year}/build")
async def build_starter_pack(iso3: str, year: str, payload: SecretPayload | None = None) -> dict[str, Any]:
    """Assemble a runnable workbook for a country/year from its recipe (W2).

    Runs each recipe step's importer(s) for the country and folds every fragment
    into one workbook — the "state a country + year, get a model" path.
    """
    from .. import starter_packs

    recipe = starter_packs.load_recipe(iso3, year)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"No starter pack for {iso3.upper()}/{year}.")

    dbs = registered_databases()
    await _ensure_boundaries_warm()
    try:
        region = region_mod.get_region(str(recipe.get("iso3", iso3)))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    options = ConvertOptions()
    secrets = {**_server_secrets()}
    if payload is not None:
        secrets.update({k: v for k, v in (payload.secrets or {}).items() if str(v).strip()})
    http = AsyncClientWrapper(secrets=list(secrets.values()))
    ctx = ImportContext(secrets=secrets, http=http, request_id=starter_packs.new_request_id())
    try:
        fragment, dataset_ids, previews = await starter_packs.build_from_recipe(
            recipe, dbs=dbs, region=region, ctx=ctx, options=options, combine=combine_fragments,
        )
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"starter-pack build failed: {exc}") from exc
    finally:
        await http.aclose()

    summary = combine_previews(fragment, previews)
    return {
        "iso3": str(recipe.get("iso3", iso3)).upper(),
        "year": recipe.get("year", year),
        "label": recipe.get("label", ""),
        "dataset_ids": dataset_ids,
        "country_iso": region.country_iso,
        "preview": summary.to_json(),
        "fragment": fragment.to_json(),
    }


@router.get("/sources")
def list_sources() -> dict[str, Any]:
    """Datasets grouped by source for the Country → Database → Datasets tree,
    each with its ``common_filters`` (settings shared by ≥2 of its datasets).

    ``serverSecrets`` lists the secret NAMES the backend already provides from
    its environment (values never leave the server) so the UI can mark those
    API-key requirements as satisfied without the user typing anything.
    """
    return {"sources": available_sources(), "serverSecrets": sorted(_server_secrets())}


# ── Server-recorded API keys (Settings → API keys writes through) ─────────────


class SecretPayload(BaseModel):
    value: str = ""


@router.get("/secrets")
def list_secrets() -> dict[str, Any]:
    """The secret NAMES the server provides — values never leave the server."""
    return {"stored": sorted(_stored_secrets()), "env": sorted(_env_secrets())}


@router.put("/secrets/{name}")
def put_secret(name: str, payload: SecretPayload) -> dict[str, Any]:
    """Record an API key on the backend (gitignored secrets.json, 0600).

    An empty value deletes the stored key. Values are write-only: no endpoint
    ever returns them.
    """
    if not _SECRET_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid secret name (use a-z, 0-9, _).")
    stored = _stored_secrets()
    value = payload.value.strip()
    if value:
        stored[name] = value
    else:
        stored.pop(name, None)
    _write_stored_secrets(stored)
    return {"name": name, "stored": bool(value)}


@router.delete("/secrets/{name}")
def delete_secret(name: str) -> dict[str, Any]:
    """Remove a server-recorded API key."""
    if not _SECRET_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid secret name.")
    stored = _stored_secrets()
    existed = name in stored
    stored.pop(name, None)
    _write_stored_secrets(stored)
    return {"name": name, "removed": existed}


def _resolve_dataset_order(requested: list[str]) -> list[str]:
    """Expand the requested datasets with their declared ``depends_on`` and
    return them dependency-first (so a profile's static anchor is fetched and
    combined before the profile). Guards against unknown ids and cycles."""
    dbs = registered_databases()
    ordered: list[str] = []
    visiting: set[str] = set()

    def visit(did: str) -> None:
        if did in ordered or did in visiting:
            return
        db = dbs.get(did)
        if db is None:
            raise KeyError(f"unknown dataset id: {did!r}")
        visiting.add(did)
        for dep in db.meta.depends_on:
            visit(dep)
        visiting.discard(did)
        ordered.append(did)

    for did in requested:
        visit(did)
    return ordered


@router.get("/countries")
async def list_countries() -> dict[str, Any]:
    """Country index for the map search box. Warms the boundaries cache
    on first call (so the very first request may fetch Natural Earth)."""
    await _ensure_boundaries_warm()
    try:
        return {"countries": region_mod.country_list()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/boundaries/countries.geojson")
async def boundaries() -> Response:
    """Country polygons GeoJSON for the Data-view map."""
    await _ensure_boundaries_warm()
    try:
        data = region_mod.boundaries_geojson_bytes()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="application/geo+json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/run")
async def run_import(payload: ImportRunRequest) -> dict[str, Any]:
    """One-trip fetch of one or more datasets of a source → one combined,
    PyPSA-aligned fragment + one preview.

    The selected datasets are expanded with their dependencies and fetched
    with the *same* shared filters, so e.g. every KPG193 dataset resolves the
    same version/year and their bus-derived names line up. Their fragments are
    folded together (``combine_fragments``) into one result.
    """
    requested = list(payload.dataset_ids) or (
        [payload.database_id] if payload.database_id else []
    )
    if not requested:
        raise HTTPException(status_code=400, detail="no dataset_ids provided")

    try:
        order = _resolve_dataset_order(requested)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    dbs = registered_databases()
    for did in order:
        meta = dbs[did].meta
        if not meta.available:
            raise HTTPException(
                status_code=503,
                detail=f"dataset {did!r} unavailable: {meta.unavailable_reason}",
            )

    await _ensure_boundaries_warm()
    try:
        region = region_mod.get_region(payload.country_iso)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    opts_dict = payload.convert_options or {}
    options = ConvertOptions(
        create_buses_for_plants=bool(opts_dict.get("create_buses_for_plants", True)),
        plant_bus_suffix=str(opts_dict.get("plant_bus_suffix", "_bus")),
        plant_bus_snap_km=float(opts_dict.get("plant_bus_snap_km", 25.0)),
    )

    # Server-held keys (gitignored .env) under the browser's BYOK keys — a key
    # the user typed wins for their request; otherwise the server's is used, so
    # datasets work with no key in the browser at all.
    secrets = {**_server_secrets(), **{k: v for k, v in payload.secrets.items() if str(v).strip()}}
    http = AsyncClientWrapper(secrets=list(secrets.values()))
    ctx = ImportContext(
        secrets=secrets, http=http, request_id=str(uuid.uuid4())[:8],
    )
    fragments = []
    previews = []
    try:
        for did in order:
            db = dbs[did]
            result = await db.fetch(region, dict(payload.filters), ctx)
            previews.append(db.preview(result))
            fragments.append(db.to_sheets(result, options))
    except PermissionError as exc:
        # Missing required API key — actionable 400, not a 502.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"import failed: {exc}") from exc
    finally:
        await http.aclose()

    source_id = dbs[order[0]].meta.source_id or dbs[order[0]].meta.id
    fragment = combine_fragments(
        fragments,
        source_id=source_id,
        country_iso=region.country_iso,
        country_name=region.country_name,
        filters=dict(payload.filters),
        dataset_ids=order,
    )
    summary = combine_previews(fragment, previews)
    # D1 — persistent provenance log (best-effort; never blocks the import).
    from ..importers import provenance_log

    provenance_log.record_import(fragment.provenance, source_id=source_id, dataset_ids=order)

    return {
        "source_id": source_id,
        "dataset_ids": order,
        "country_iso": region.country_iso,
        "preview": summary.to_json(),
        "fragment": fragment.to_json(),
    }


# ── Boundaries warm helper ───────────────────────────────────────────────────

_boundaries_warmed = False


async def _ensure_boundaries_warm() -> None:
    """Fetch + cache the Natural Earth boundaries once per process.

    The first importer interaction (country list, run, or geojson) pays
    the ~3 MB download; everything after reads the on-disk cache.
    """
    global _boundaries_warmed
    if _boundaries_warmed:
        return
    http = AsyncClientWrapper()
    try:
        await region_mod.ensure_boundaries(http)
        _boundaries_warmed = True
    finally:
        await http.aclose()
