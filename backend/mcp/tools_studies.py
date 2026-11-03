"""Study tools: which reliability / market / company studies a solve can carry, and one study's result without the rest.

Studies are module hooks (``backend/app/<module>/hooks.py``, kind ``study``) and a few core run modes. They are switched on by
options of a normal ``submit_solve`` and their results land as keys of the run payload, so there is no tool per study; these two
tools are the index and the reader:

* ``describe_studies``  - read-only: every study with the option that enables it, the result key it writes and what it needs.
* ``get_study_result``  - read-only: one study's result of a stored run (``GET /api/runs/{name}/analytics`` or, for a pathway
  period, ``/period/{period}?fields=``), with long lists capped and a truncation notice.

``STUDIES`` is checked against the live hook registry by ``backend/tests/test_mcp_coverage.py``: a study hook whose payload key is
not listed here fails the test, so a new module cannot ship unreachable. Nothing here imports ``backend.app``.
"""
from __future__ import annotations

from typing import Any

from .catalogue import declare_areas
from .server import _RO, get_client, mcp

# id, title, option key (None = always computed / input-sheet driven), result keys in the run payload, how to turn it on.
# ``hook`` is the registered study-hook id (None for a core run mode); the coverage test compares them with the registry.
STUDIES: tuple[dict[str, Any], ...] = (
    {"id": "adequacy", "title": "Loss of load (LOLE / EENS) readout", "optionKey": "adequacyReadout", "resultKeys": ("adequacy",), "hook": "adequacy",
     "enable": "On by default on every solve; options.adequacyReadout=false switches it off."},
    {"id": "reserves", "title": "Operating-reserve co-optimisation and reserve price", "optionKey": "reserveConfig", "resultKeys": ("reserve",), "hook": "reserves",
     "enable": "options.reserveConfig={enabled: true, requirementType, fraction, providers}."},
    {"id": "outage-mc", "title": "Forced-outage Monte Carlo (LOLE / EUE distribution)", "optionKey": "outageMcConfig", "resultKeys": ("outageMc",), "hook": "outage-mc",
     "enable": "options.outageMcConfig={enabled: true, nMembers, seed, forcedOutageRate, mttrHours}."},
    {"id": "elcc", "title": "Effective load-carrying capability (capacity credit)", "optionKey": "elccConfig", "resultKeys": ("elcc",), "hook": "elcc",
     "enable": "options.elccConfig={enabled: true, ...}."},
    {"id": "correlated-sampling", "title": "Correlated weather / demand sampling", "optionKey": "correlatedSamplingConfig", "resultKeys": ("correlatedSampling",), "hook": "correlated-sampling",
     "enable": "options.correlatedSamplingConfig={enabled: true, ...}."},
    {"id": "convergence", "title": "Monte-Carlo convergence of the sampled indicators", "optionKey": "convergenceConfig", "resultKeys": ("convergenceSampling",), "hook": "convergence",
     "enable": "options.convergenceConfig={enabled: true, ...}."},
    {"id": "lmp-decomposition", "title": "LMP decomposition (energy, congestion, loss components)", "optionKey": "lmpDecompositionConfig", "resultKeys": ("lmpDecomposition",), "hook": "lmp-decomposition",
     "enable": "options.lmpDecompositionConfig={enabled: true}."},
    {"id": "price-formation", "title": "Price vs residual demand and the price-setting carrier", "optionKey": None, "resultKeys": ("priceFormation",), "hook": "price-formation",
     "enable": "Computed on every LP solve (null on a non-LP run)."},
    {"id": "merchant", "title": "Merchant revenue of one owner's fleet", "optionKey": "merchantConfig", "resultKeys": ("merchant",), "hook": "merchant",
     "enable": "options.merchantConfig={enabled: true, owner, priceSource: lmp | flat | series, flatPrice}."},
    {"id": "bid-strategy", "title": "Bid strategy: a fixed mark-up over marginal cost", "optionKey": "bidStrategyConfig", "resultKeys": ("bidStrategy",), "hook": "bid-strategy",
     "enable": "options.bidStrategyConfig={enabled: true, mode: 'fixed', owner, markupType, markup}."},
    {"id": "optimal-bid", "title": "Optimal bid: best mark-up of one owner against the market", "optionKey": "bidStrategyConfig", "resultKeys": ("optimalBid",), "hook": "optimal-bid",
     "enable": "options.bidStrategyConfig={enabled: true, mode: 'optimal', owner, maxMarkup, steps}."},
    {"id": "ppa", "title": "PPA valuation against the LMP and alternative contract shapes", "optionKey": "ppaConfig", "resultKeys": ("ppa", "ppaExplorer"), "hook": "ppa",
     "enable": "options.ppaConfig={enabled: true, owner, strikePrice, flatMW, volumeType}."},
    {"id": "asset-swap", "title": "Asset swap between owners", "optionKey": "assetSwapConfig", "resultKeys": ("assetSwap",), "hook": "asset-swap",
     "enable": "options.assetSwapConfig={enabled: true, ...}; needs owner-tagged assets."},
    {"id": "ess", "title": "Energy-storage business case", "optionKey": "essConfig", "resultKeys": ("essBusinessCase",), "hook": "ess",
     "enable": "options.essConfig={enabled: true, ...}."},
    {"id": "company-breakdown", "title": "Per-owner capacity, energy, revenue and emissions", "optionKey": "ownerColumn", "resultKeys": ("companies",), "hook": "company-breakdown",
     "enable": "Assets tagged with an owner (options.ownerColumn names the column, default 'owner')."},
    {"id": "company-finance", "title": "Company project finance (NPV, IRR, payback, DSCR)", "optionKey": "financeConfig", "resultKeys": ("companyFinance",), "hook": "company-finance",
     "enable": "Owner-tagged assets and scenario.discountRate; options.financeConfig adds debt terms."},
    {"id": "company-statement", "title": "Company annual P&L (revenue to net income)", "optionKey": "financeConfig", "resultKeys": ("companyStatement",), "hook": "company-statement",
     "enable": "Owner-tagged assets on an LP run; options.financeConfig adds debt terms."},
    {"id": "demand-response", "title": "Demand response and price-elastic demand outcome", "optionKey": "demandResponseConfig", "resultKeys": ("demandResponse", "priceElastic"), "hook": "demand-response",
     "enable": "options.demandResponseConfig plus dr_* rows (apply_demand_response writes them)."},
    {"id": "emissions-breakdown", "title": "Emissions by carrier, storage and PyPSA-basis total", "optionKey": None, "resultKeys": ("emissionsBreakdown",), "hook": "emissions-breakdown",
     "enable": "Computed on every solve."},
    {"id": "fuel-costs", "title": "Fuel / VOM / carbon split of each unit's marginal cost, ex-post LCOE", "optionKey": "fuelCosts", "resultKeys": ("fuelCosts",), "hook": "fuel-costs",
     "enable": "On when the model has fuel prices, VOM rows or carriers.fuel_cost_thermal (set_fuel_price, set_vom); options.fuelCosts.enabled=false switches it off."},
    {"id": "stochastic", "title": "Stochastic scenarios: expected cost, per-scenario results", "optionKey": "stochasticConfig", "resultKeys": ("stochastic",), "hook": "stochastic-collapse",
     "enable": "options.stochasticConfig={enabled: true, scenarios: [{name, weight, overrides}]}; fuel prices per scenario with set_fuel_price_scenario."},
    {"id": "near-optimal", "title": "Near-optimal alternatives (modelling to generate alternatives)", "optionKey": "mgaConfig", "resultKeys": ("nearOptimal",), "hook": None,
     "enable": "options.mgaConfig={enabled: true, slack, carriers}."},
    {"id": "commitment", "title": "Unit commitment: starts, start-up costs, on / off pattern", "optionKey": None, "resultKeys": ("commitment",), "hook": None,
     "enable": "Computed when units are committable (not with force-LP / linearised unit commitment)."},
    {"id": "maintenance", "title": "Scheduled maintenance outcome", "optionKey": None, "resultKeys": ("maintenance",), "hook": None,
     "enable": "Maintenance set on units (set_maintenance)."},
    {"id": "ramp", "title": "Ramp-rate limits and which bind", "optionKey": "rampConfig", "resultKeys": ("ramp",), "hook": None,
     "enable": "options.rampConfig={enabled: true, ...} or per-unit ramp rows (set_time_units)."},
)

_BY_ID = {s["id"]: s for s in STUDIES}
_ROW_CAP = 100


def _cap(value: Any, max_rows: int, path: str, cut: list[str]) -> Any:
    """``value`` with every list longer than ``max_rows`` cut to its head; ``cut`` records where and how long it was."""
    if isinstance(value, list):
        head = value[:max_rows]
        if len(value) > max_rows:
            cut.append(f"{path or 'result'} ({len(value)} items)")
        return [_cap(v, max_rows, f"{path}[]", cut) for v in head]
    if isinstance(value, dict):
        return {k: _cap(v, max_rows, f"{path}.{k}" if path else str(k), cut) for k, v in value.items()}
    return value


@mcp.tool(
    annotations=_RO,
    description=(
        "Index of the studies a solve can carry (연구·분석 모듈: 공급 신뢰도 adequacy LOLE / EENS, reserves, forced-outage Monte Carlo, ELCC, LMP decomposition, price formation, merchant revenue, bid strategy, PPA, "
        "asset swap, ESS business case, company finance and P&L, demand response, emissions, fuel costs, stochastic, near-optimal, commitment, maintenance, ramp): per study its id, the options.* key that enables it, "
        "the result key(s) it writes into the run payload and how to turn it on. Studies are run options of submit_solve, not separate calls; describe_run_options(key='options.<key>') lists every field of an option, "
        "get_study_result(run, study) reads one study's result. optional 'study' narrows to one id."
    ),
)
async def describe_studies(study: str | None = None) -> Any:
    if study is not None:
        if study not in _BY_ID:
            return {"error": f'unknown study "{study}"; valid: {", ".join(_BY_ID)}.'}
        rows = [_BY_ID[study]]
    else:
        rows = list(STUDIES)
    return {
        "studies": [{k: v for k, v in s.items() if k != "hook"} for s in rows],
        "howTo": "Enable with submit_solve(options={...}); then get_study_result(run_name, study). Core run modes (pathway, rolling, sampling, SCLOPF, contingency, power flow) are in describe_run_options.",
    }


@mcp.tool(
    annotations=_RO,
    description=(
        "One study's result of a stored run (연구 결과 읽기), without the rest of the analytics payload: study is an id from describe_studies (adequacy, reserves, outage-mc, elcc, lmp-decomposition, merchant, ppa, "
        "company-finance, fuel-costs, stochastic, ...). Returns {study, resultKeys, ran, result}; ran=false (with how to enable it) when the run did not carry that study. period reads one investment period of a "
        "pathway run. Lists longer than max_rows (default 100) are cut to their head and named in 'truncated' with their full length; raise max_rows or read the run series for more."
    ),
)
async def get_study_result(run_name: str, study: str, period: int | None = None, max_rows: int = _ROW_CAP) -> Any:
    spec = _BY_ID.get(study)
    if spec is None:
        return {"error": f'unknown study "{study}"; valid: {", ".join(_BY_ID)}.'}
    keys: tuple[str, ...] = spec["resultKeys"]
    client = get_client()
    if period is not None:
        res = await client.get_run_period(run_name, period, fields=",".join(keys))
        payload = res.get("result") or {}
    else:
        payload = (await client.get_analytics(run_name)).get("result") or {}
    found = {k: payload.get(k) for k in keys if payload.get(k) is not None}
    if not found:
        return {"study": study, "resultKeys": list(keys), "ran": False, "enable": spec["enable"],
                "hint": "The run carries no result for this study; enable it and solve again (describe_studies)."}
    cut: list[str] = []
    out: dict[str, Any] = {"study": study, "run": run_name, "resultKeys": list(keys), "ran": True,
                           "result": _cap(found, max(1, int(max_rows)), "", cut)}
    if cut:
        out["truncated"] = f"{len(cut)} list(s) cut to {max(1, int(max_rows))} items: {'; '.join(cut[:8])}. Raise max_rows for more."
    return out


# Tool areas (see catalogue.py).
declare_areas({
    "describe_studies": "studies",
    "get_study_result": "studies",
})
