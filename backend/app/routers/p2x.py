"""P2X (power-to-X) use-case surface: technologies, chain builder, RFNBO checks, results.

* ``GET  /api/p2x/technologies``          the technology data file (value, unit, source, cost year, verified flag)
* ``GET  /api/p2x/chain/defaults``        the default chain spec
* ``POST /api/p2x/chain``                 build a chain; ``apply=false`` previews, ``apply=true`` merges it into the session
* ``GET|PUT /api/p2x/rfnbo/config``       the session's RFNBO matching settings (a run option kept outside the workbook)
* ``POST /api/p2x/rfnbo/checks``          pre-solve additionality / geographic checks and the candidate filter
* ``GET  /api/p2x/results/{run}``         LCOH, LCOA, LCOM, e-fuel cost, waterfall, compliance of a stored run (``period``)

No separate engine: the chain is ordinary PyPSA components merged through the same fragment
merge as the Build conversions, and the RFNBO constraint is added in ``extra_functionality``
(``backend/pypsa/network/rfnbo.py``). The RFNBO run options are registered here so
``describe_run_options`` documents them.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.p2x import rfnbo
from .. import fragment_merge, model_store, run_store
from ..p2x import chains, config_store, technologies
from ..p2x import results as p2x_results
from ..run_options_reference import RunOption, register_options

router = APIRouter(tags=["p2x"])

_RF = "backend/pypsa/network/rfnbo.py"


def _o(path: str, type_: str, meaning: str, default: Any = None, *, allowed: list[Any] | None = None, unit: str | None = None) -> RunOption:
    return RunOption(path, type_, meaning, default, unit, allowed, _RF, "api", "p2x")


register_options([
    _o("options.rfnboConfig", "object",
       "P2X RFNBO matching (Commission Delegated Regulation (EU) 2023/1184). When enabled the electrolyser electricity must not exceed the "
       "designated renewable generators' output in the same matching period (PPA matching, Art. 6); additionality (Art. 5) and geographic "
       "correlation (Art. 7) are checks / candidate filters, grid alternatives (Art. 4) are reported only. A run without this key takes the "
       "session's P2X-tab settings (GET /api/p2x/rfnbo/config); an explicit value, even {enabled: false}, always wins.", None),
    _o("options.rfnboConfig.enabled", "boolean", "Add the matching constraint to the solve.", False),
    _o("options.rfnboConfig.temporal", "string",
       "Matching period: hourly = every snapshot (Art. 6, required from 1 Jan 2030); monthly = calendar month (allowed until 31 Dec 2029, "
       "sums over the snapshots of the month with snapshot weightings); auto = monthly before hourlyFrom, hourly from it.", "hourly",
       allowed=["hourly", "monthly", "auto"]),
    _o("options.rfnboConfig.hourlyFrom", "string", "temporal=auto: first date of the hourly regime (Art. 6(2): 2030-01-01; a Member State may apply it from 2027-07-01).", "2030-01-01"),
    _o("options.rfnboConfig.chainId", "string | null", "Only this P2X chain's electrolyser and designated generators (default every chain in the model).", None),
    _o("options.rfnboConfig.electrolysers", "string[]", "Electrolyser Link names to match; empty = the P2X chains' electrolysers, else every Link with carrier 'electrolysis'.", []),
    _o("options.rfnboConfig.designatedGenerators", "string[]", "Designated renewable generators (the PPA); empty = the generators named in the P2X chain(s).", []),
    _o("options.rfnboConfig.enforceAdditionality", "boolean",
       "Candidate filter, not an LP constraint: designated generators failing Art. 5(a) (came into operation more than 36 months before the electrolyser) "
       "are removed from the matching set. An extendable generator without build_year is new. A run with no eligible generator is refused (400).", False),
    _o("options.rfnboConfig.additionalityMonths", "number", "Art. 5(a) window.", 36, unit="months"),
    _o("options.rfnboConfig.unknownBuildYearAs", "string", "A designated generator with no build_year under enforceAdditionality.", "fail", allowed=["fail", "pass"]),
    _o("options.rfnboConfig.enforceGeographic", "boolean",
       "Candidate filter: drop designated generators in a different bidding zone (Art. 7(1)(a)). Zone = the bus's bidding_zone / zone / country column, else the bus.", False),
    _o("options.rfnboConfig.zoneColumn", "string | null", "Bus column that holds the bidding zone (default: first of bidding_zone, zone, country).", None),
    _o("options.rfnboConfig.priceRule.enabled", "boolean", "Report the Art. 6(3) count: hours at or below the price threshold are compliant whatever the matching (ex-post, informational).", False),
    _o("options.rfnboConfig.priceRule.thresholdEurPerMwh", "number", "Art. 6(3) price threshold.", 20, unit="EUR/MWh"),
    _o("options.rfnboConfig.priceRule.euaEurPerT", "number | null", "EUA price; the threshold becomes max(threshold, 0.36 x EUA) (Art. 6(3)).", None, unit="EUR/tCO2"),
    _o("options.rfnboConfig.gridAlternatives.renewableShareThreshold", "number", "Art. 4(1) renewable share threshold (reported only).", 0.9),
    _o("options.rfnboConfig.gridAlternatives.intensityThresholdGPerMj", "number", "Art. 4(2) emission-intensity threshold (reported only).", 18, unit="gCO2e/MJ"),
    _o("options.rfnboConfig.gridAlternatives.renewableCarriers", "string[]", "Generator carriers counted as renewable for Art. 4(1).", list(rfnbo.RES_CARRIERS_DEFAULT)),
])


def _session_model(session_id: str, *, full: bool = False) -> dict[str, list[dict[str, Any]]]:
    model = model_store.load_full_model(session_id, static_only=not full)
    if not model:
        raise HTTPException(status_code=400, detail="No working model in this session.")
    return model


@router.get("/api/p2x/technologies")
def get_technologies() -> dict[str, Any]:
    """The P2X technology data: every parameter with value, unit, source, cost year / currency and a verified flag."""
    return technologies.catalogue()


@router.get("/api/p2x/chain/defaults")
def chain_defaults(session_id: str = "default") -> dict[str, Any]:
    """The default chain spec, the products, and the model's anchor bus / generators (for the designer's pickers)."""
    model = model_store.load_full_model(session_id, static_only=True) or {}
    return {"spec": chains.default_spec(), "products": list(chains.ALL_PRODUCTS), "defaultAnchorBus": chains.default_anchor_bus(model),
            "technologies": {k: v["label"] for k, v in technologies.load_technologies()["technologies"].items()}}


class ChainRequest(BaseModel):
    sessionId: str = "default"
    spec: dict[str, Any] = Field(default_factory=dict, description="Chain spec (see GET /api/p2x/chain/defaults); only the keys to change.")
    model: dict[str, list[dict[str, Any]]] | None = Field(None, description="Inline model (UI mirror); default = the session's model.")
    apply: bool = Field(False, description="Merge the fragment into the session model (preview when false).")


@router.post("/api/p2x/chain")
def build_chain(req: ChainRequest) -> dict[str, Any]:
    """Build a P2X chain; preview by default, ``apply`` merges it into the session through the fragment merge."""
    if req.apply and req.model is not None:
        raise HTTPException(status_code=400, detail="`apply` works on the session model, not an inline one.")
    model = req.model if req.model is not None else _session_model(req.sessionId, full=req.apply)
    try:
        built = chains.build_chain(req.spec, model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fragment = built["fragment"]
    out: dict[str, Any] = {k: built[k] for k in ("fragment", "registry", "summary", "warnings", "spec")}
    out["applied"] = False
    out["rowCounts"] = {s: len(rows) for s, rows in fragment["sheets"].items()}
    if req.apply:
        merged = fragment_merge.merge_fragment(model, fragment)
        if any(rfnbo_sheet_is_series(s) for s in fragment["sheets"]):
            out["meta"] = model_store.resave_model(req.sessionId, merged)
        else:
            if model_store.merge_static_model(req.sessionId, {**model, **{s: merged[s] for s in fragment["sheets"]}}) is None:
                raise HTTPException(status_code=400, detail="No session to write into.")
        out["applied"] = True
    return out


def rfnbo_sheet_is_series(name: str) -> bool:
    return "-" in name and not name.endswith("-pw")


class RfnboConfigBody(BaseModel):
    sessionId: str = "default"
    config: dict[str, Any]


@router.get("/api/p2x/rfnbo/config")
def get_rfnbo_config(session_id: str = "default") -> dict[str, Any]:
    """The session's stored RFNBO settings (``null`` = never set) and the defaults."""
    return {"config": config_store.get_rfnbo_config(session_id), "defaults": rfnbo.normalise_config(None)}


@router.put("/api/p2x/rfnbo/config")
def put_rfnbo_config(body: RfnboConfigBody) -> dict[str, Any]:
    """Store the session's RFNBO settings; a later run that sets no ``options.rfnboConfig`` uses them."""
    try:
        return {"config": config_store.set_rfnbo_config(body.sessionId, body.config)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ChecksRequest(BaseModel):
    sessionId: str = "default"
    config: dict[str, Any] | None = Field(None, description="RFNBO config to check; default = the session's stored settings.")
    model: dict[str, list[dict[str, Any]]] | None = None


@router.post("/api/p2x/rfnbo/checks")
def rfnbo_checks(req: ChecksRequest) -> dict[str, Any]:
    """Pre-solve RFNBO checks: additionality (Art. 5(a)), geographic correlation (Art. 7(1)(a)) and what each filter would drop.

    Art. 5(b) (no aid), Art. 7(1)(b)/(c) and Art. 4 need attestation or a solved run and are listed as such.
    """
    model = req.model if req.model is not None else _session_model(req.sessionId)
    try:
        cfg = rfnbo.normalise_config(req.config if req.config is not None else config_store.get_rfnbo_config(req.sessionId))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sets = rfnbo.resolve_sets(model, cfg)
    keep, report = rfnbo.eligible_generators(model, cfg, sets)
    return {
        "config": cfg, "electrolysers": sets["electrolysers"], "designated": sets["designated"], "chains": sets["chains"],
        "additionality": report["additionality"], "geographic": report["geographic"], "dropped": report["dropped"],
        "eligible": keep, "willBeRefused": bool(cfg["enabled"] and (not sets["electrolysers"] or not keep)),
        "attest": [
            {"article": "Art. 5(b)", "rule": "designated installations received no operating or investment aid", "status": "attest"},
            {"article": "Art. 7(1)(b)/(c)", "rule": "interconnected zone with an equal or higher day-ahead price, or an offshore zone", "status": "attest"},
            {"article": "Art. 4", "rule": "grid alternatives: zone renewable share above 90 % or emission intensity below 18 gCO2e/MJ (reported after the solve)", "status": "after-solve"},
        ],
        "regulation": "Commission Delegated Regulation (EU) 2023/1184",
    }


@router.get("/api/p2x/results/{run}")
def get_results(
    run: str,
    period: int | None = Query(None, description="Investment period of a pathway run; default the whole horizon."),
    electricity_cost: str = Query("nodal", description="nodal = nodal price x consumption; ppa = designated generators' cost."),
    chain_id: str | None = Query(None, description="Which P2X chain when the model has several."),
) -> dict[str, Any]:
    """LCOH per kg H2, LCOA per t NH3, LCOM per t MeOH, e-fuel cost, cost waterfall, matching compliance and checks of a stored run."""
    bundle = run_store.get_run(run)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    try:
        return p2x_results.p2x_results(bundle, period=period, electricity_cost=electricity_cost, chain_id=chain_id)
    except p2x_results.P2XResultsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
