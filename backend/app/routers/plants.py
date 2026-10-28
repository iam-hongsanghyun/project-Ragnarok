"""Build plants: one plant-type picker, one endpoint per action (types, preview / apply, edit, delete, list, results).

* ``GET  /api/build/plant/types``          the plant types, their fields (key / label / unit / default / advanced) and defaults
* ``GET  /api/build/plant/technologies``   the technology data file (value, unit, source, verified flag; LHV per Nm3)
* ``GET  /api/build/plants``               the plants of the session model (one card each; components expandable)
* ``POST /api/build/plant``                build a plant; ``apply=false`` previews, ``apply=true`` merges it into the session
* ``POST /api/build/plant/edit``           re-derive a plant's components from its stored spec + a patch (preview / apply)
* ``POST /api/build/plant/delete``         delete a plant and nothing else; shared buses / carriers are kept (preview / apply)
* ``GET  /api/build/plant/results/{run}``  results of a stored run grouped by plant id (generation, fuel, H2 share, avoided CO2, starts)

Every write returns a *change set* (``remove`` / ``release`` / ``fragment``, see ``backend/app/plants/registry.py``). With an
inline ``model`` the call is stateless (the browser applies the change set to the model it holds); without one it works on
the session model and ``apply`` writes it. The H2 blend-share run option (``options.cofiringConfig``) is registered here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...pypsa.network import cofiring
from .. import model_store, run_store
from ..plants import catalog, registry, technologies
from ..plants import results as plant_results
from ..run_options_reference import RunOption, register_options

router = APIRouter(tags=["plants"])

_CF = "backend/pypsa/network/cofiring.py"


def _o(path: str, type_: str, meaning: str, default: Any = None, *, allowed: list[Any] | None = None, unit: str | None = None) -> RunOption:
    return RunOption(path, type_, meaning, default, unit, allowed, _CF, "api", "plants")


register_options([
    _o("options.cofiringConfig", "object",
       "Gas + H2 co-firing blend-share limits for the fuel-network plants (Build -> Generators -> 'Gas + H2 co-firing (fuel network)'). The H2 share of the fuel "
       "burned, h/(h+g) on an LHV basis, is held within [minShare, maxShare] in every snapshot (hourly) or over the run (period, snapshot-weighted). "
       "Shares are entered as vol% or energy% (vol is converted with the LHV per Nm3 in the plant data file: 30 vol% = 11.4 % energy). A run that sets no "
       "cofiringConfig takes the limits stored with each plant (its blendMax / blendMin); an explicit value, even {enabled: false}, always wins. "
       "A limit that names no fuel-network plant is refused (400).", None),
    _o("options.cofiringConfig.enabled", "boolean", "Add the blend-share constraints to the solve.", True),
    _o("options.cofiringConfig.plants", "string[]", "Plant ids to constrain; empty = every fuel-network co-firing plant in the model.", []),
    _o("options.cofiringConfig.minShare", "number | null", "Minimum H2 share, a fraction (0.1 = 10 %) in `unit`. Applies to every listed plant unless perPlant overrides.", None),
    _o("options.cofiringConfig.maxShare", "number | null", "Maximum H2 share, a fraction in `unit`.", None),
    _o("options.cofiringConfig.unit", "string", "Basis of minShare / maxShare: energy (LHV) or vol (Nm3 of H2 per Nm3 of mixture).", "energy", allowed=list(cofiring.UNITS)),
    _o("options.cofiringConfig.scope", "string", "hourly = every snapshot; period = snapshot-weighted total over the run (looser than hourly; with rolling horizon, each window).",
       "hourly", allowed=list(cofiring.SCOPES)),
    _o("options.cofiringConfig.perPlant", "object", "{plantId: {minShare, maxShare, unit, scope}} overriding the values above for one plant.", {}),
])


def _session_model(session_id: str, *, full: bool = False) -> dict[str, list[dict[str, Any]]]:
    model = model_store.load_full_model(session_id, static_only=not full)
    if not model:
        raise HTTPException(status_code=400, detail="No working model in this session.")
    return model


@router.get("/api/build/plant/types")
def plant_types() -> dict[str, Any]:
    """The plant types with their fields and defaults (what the picker renders)."""
    return {"types": catalog.list_types(), "turbines": list(catalog.TURBINES), "technologiesFile": str(technologies.technologies_path())}


@router.get("/api/build/plant/technologies")
def plant_technologies() -> dict[str, Any]:
    """The plant technology data: every parameter with value, unit, source, cost year / currency and a verified flag."""
    return technologies.catalogue()


@router.get("/api/build/plants")
def get_plants(session_id: str = "default") -> dict[str, Any]:
    """The plants of the session model: one card each with its components."""
    model = model_store.load_full_model(session_id, static_only=True) or {}
    plants = registry.list_plants(model)
    return {"plants": plants, "total": len(plants)}


class PlantRequest(BaseModel):
    sessionId: str = "default"
    type: str
    spec: dict[str, Any] = Field(default_factory=dict, description="Flat plant spec (see GET /api/build/plant/types); only the keys to change.")
    model: dict[str, list[dict[str, Any]]] | None = Field(None, description="Inline model (UI mirror); default = the session's model.")
    apply: bool = Field(False, description="Merge into the session model (preview when false).")


class EditRequest(BaseModel):
    sessionId: str = "default"
    plantId: str
    spec: dict[str, Any] = Field(default_factory=dict, description="Patch laid over the stored spec.")
    model: dict[str, list[dict[str, Any]]] | None = None
    apply: bool = False


class DeleteRequest(BaseModel):
    sessionId: str = "default"
    plantId: str
    model: dict[str, list[dict[str, Any]]] | None = None
    apply: bool = False


def _row_counts(fragment: dict[str, Any] | None) -> dict[str, int]:
    return {s: len(r) for s, r in ((fragment or {}).get("sheets") or {}).items()}


def _has_series(fragment: dict[str, Any] | None) -> bool:
    return any("-" in s for s in ((fragment or {}).get("sheets") or {}))


def _commit(req_session: str, base_static: dict[str, list[dict[str, Any]]], change: dict[str, Any]) -> dict[str, Any]:
    """Write a change set into the session: static sheets in place; the full model when the fragment carries series."""
    series = _has_series(change.get("fragment"))
    base = _session_model(req_session, full=True) if series else base_static
    merged = registry.apply_change(base, change)
    if series:
        return model_store.resave_model(req_session, merged)
    touched = set(change.get("remove") or {}) | {r["sheet"] for r in change.get("release") or []} | set(((change.get("fragment") or {}).get("sheets")) or {})
    if model_store.merge_static_model(req_session, merged) is None:
        raise HTTPException(status_code=400, detail="No session to write into.")
    return {"sheetsWritten": sorted(touched)}


def _inline_guard(req: Any) -> None:
    if req.apply and req.model is not None:
        raise HTTPException(status_code=400, detail="`apply` works on the session model, not an inline one.")


@router.post("/api/build/plant")
def build_plant(req: PlantRequest) -> dict[str, Any]:
    """Build a plant; preview by default, ``apply`` merges it into the session (one atomic write)."""
    _inline_guard(req)
    model = req.model if req.model is not None else _session_model(req.sessionId, full=False)
    try:
        built = catalog.build_plant(req.type, req.spec, model)
    except registry.PlantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    change = {"remove": {}, "release": [], "fragment": built["fragment"], "kept": {"buses": [], "carriers": []}}
    out: dict[str, Any] = {k: built[k] for k in ("plantId", "type", "label", "fragment", "registry", "summary", "warnings", "spec")}
    out.update({"change": change, "rowCounts": _row_counts(built["fragment"]), "applied": False})
    if req.apply:
        out["write"] = _commit(req.sessionId, model, change)
        out["applied"] = True
    return out


@router.post("/api/build/plant/edit")
def edit_plant(req: EditRequest) -> dict[str, Any]:
    """Edit a plant: its components are re-derived from the stored spec with the patch laid over it (old rows removed, shared ones kept)."""
    _inline_guard(req)
    model = req.model if req.model is not None else _session_model(req.sessionId, full=False)
    try:
        change = catalog.edit_plant(model, req.plantId, req.spec)
    except registry.PlantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    out = {k: change[k] for k in ("plantId", "type", "registry", "summary", "warnings", "spec", "fragment")}
    out["label"] = change["registry"]["label"]
    out.update({"change": {k: change[k] for k in ("remove", "release", "fragment", "kept")}, "applied": False,
                "removed": {s: len(n) for s, n in change["remove"].items()}, "rowCounts": _row_counts(change["fragment"])})
    if req.apply:
        out["write"] = _commit(req.sessionId, model, out["change"])
        out["applied"] = True
    return out


@router.post("/api/build/plant/delete")
def delete_plant(req: DeleteRequest) -> dict[str, Any]:
    """Delete a plant and nothing else; a bus or carrier another component still uses is kept (and released from the plant)."""
    _inline_guard(req)
    model = req.model if req.model is not None else _session_model(req.sessionId, full=False)
    try:
        change = registry.delete_change(model, req.plantId)
    except registry.PlantError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    out = {"plantId": req.plantId, "change": change, "removed": {s: len(n) for s, n in change["remove"].items()}, "kept": change["kept"],
           "warnings": change["warnings"], "applied": False}
    if req.apply:
        out["write"] = _commit(req.sessionId, model, change)
        out["applied"] = True
    return out


@router.get("/api/build/plant/results/{run}")
def get_plant_results(
    run: str,
    plant: str | None = Query(None, description="Only this plant id (default every plant)."),
    period: int | None = Query(None, description="Investment period of a pathway run."),
    include_series: bool = Query(True, description="Per-hour series (H2 share, flows) for co-firing plants."),
) -> dict[str, Any]:
    """Results of a stored run grouped by plant id (a server-side groupby): generation, capacity factor, fuel, H2 share, emissions avoided, starts, cost."""
    bundle = run_store.get_run(run)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    try:
        return plant_results.plant_results(bundle, plant_id=plant, period=period, include_series=include_series)
    except plant_results.PlantResultsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
