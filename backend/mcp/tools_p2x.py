"""P2X (power-to-X) tools: technology data, chain builder, LCOH / LCOA / LCOM results.

Registered on the shared ``mcp`` object from :mod:`backend.mcp.server` (one import line at the end of
that file). Thin wrappers over the REST API (``/api/p2x/*``) through the :class:`RagnarokClient`;
nothing here imports ``backend.app``.

Tools:

* ``list_p2x_technologies`` - read-only: the technology data file (value, unit, source, cost year, verified flag).
* ``preview_p2x_chain``     - read-only: what a chain spec would add to the working model (nothing is written).
* ``get_p2x_results``       - read-only: LCOH, LCOA, LCOM, e-fuel cost, cost waterfall, RFNBO compliance of a stored run.
* ``build_p2x_chain``       - WRITE (gated, confirm=true): merge the chain into the working model.

RFNBO hourly / monthly matching is a run option, so it needs no tool of its own: pass
``options={"rfnboConfig": {"enabled": true, "temporal": "hourly"}}`` to ``submit_solve`` (or ``options_patch`` of
``submit_scenario``); ``describe_run_options(key="options.rfnboConfig")`` documents every field. A run that sets no
``rfnboConfig`` uses the settings last saved in the P2X tab for the session.
"""

from __future__ import annotations

from typing import Any

from .server import _MUT, _RO, _needs_confirm, _preview, get_client, mcp

_SPEC_HELP = (
    "spec keys (all optional): chainId, anchorBus, discountRate (fraction), products (subset of H2, NH3, MeOH, eFuel), h2Bus, "
    "electrolyser {tech: aec|pem, extendable, pNom (MW_el), pNomMax, enforceMinLoad, applyAvailability, buildYear}, "
    "storage {type: none|tank|cavern, compressor, extendable, eNom (MWh_H2), eNomMax}, co2 {source: dac|point}, "
    "synthesis {NH3|MeOH|eFuel: {extendable, pNom (MW_H2 in), pNomMax}}, productStorage {NH3|MeOH|eFuel: {enabled, extendable, eNom}}, "
    "offtake {H2|NH3|MeOH|eFuel: {mode: none|flat|profile, tonnesPerYear | mw, profile}}, designatedGenerators [generator names for RFNBO matching], "
    "componentType process|link (default process: the synthesis, ASU and CO2-capture steps are PyPSA Process components; link = multi-port Links), "
    "params {'<technology>.<parameter>': value} overriding the technology defaults (see list_p2x_technologies)."
)


async def _chain(spec: dict[str, Any] | None, apply: bool) -> dict[str, Any]:
    client = get_client()
    return await client._post("/api/p2x/chain", {"sessionId": client.session_id, "spec": spec or {}, "apply": apply})


def _trim(res: dict[str, Any]) -> dict[str, Any]:
    return {k: res.get(k) for k in ("applied", "rowCounts", "summary", "warnings", "spec") if k in res}


@mcp.tool(
    annotations=_RO,
    description=(
        "P2X technology data used by the chain builder: electrolysers (alkaline, PEM), H2 compression and storage (tank, salt cavern), "
        "air separation, Haber-Bosch, methanol synthesis, Fischer-Tropsch, CO2 capture (DAC, point source), product tanks and water. Every "
        "parameter has value, unit, source (document, locator, year), cost year and currency, and a verified flag (file | derived | "
        "literature-recalled | assumption). Optional 'technology' narrows to one key. Source: PyPSA/technology-data v0.15.0 (costs_2030.csv) and the "
        "Danish Energy Agency renewable-fuels catalogue."
    ),
)
async def list_p2x_technologies(technology: str | None = None) -> Any:
    data = await get_client()._get("/api/p2x/technologies")
    if technology:
        techs = data.get("technologies") or {}
        if technology not in techs:
            return {"error": f"Unknown technology {technology!r}.", "options": sorted(techs)}
        data = {**data, "technologies": {technology: techs[technology]}}
    return data


@mcp.tool(
    annotations=_RO,
    description=(
        "Preview a P2X chain (electrolyser, H2 compression and storage, ammonia / methanol / e-fuel synthesis, N2 and CO2 supply, product tanks, offtake loads) "
        "without changing the model: the components it would add with their size, efficiencies and overnight cost, row counts and warnings. " + _SPEC_HELP
    ),
)
async def preview_p2x_chain(spec: dict[str, Any] | None = None) -> Any:
    return _trim(await _chain(spec, apply=False))


@mcp.tool(
    annotations=_RO,
    description=(
        "P2X results of a stored run: LCOH per kg H2, LCOA per t NH3, LCOM per t MeOH, e-fuel cost per MWh and per litre, a cost waterfall per product, "
        "electrolyser capacity factor and full-load hours, H2 store SoC, the RFNBO hourly and monthly compliance table (share of compliant hours and the "
        "unmatched electricity), additionality and geographic checks, and the Art. 4 grid-alternative checks. period selects the investment period of a "
        "pathway run; electricity_cost is 'nodal' (nodal price x consumption) or 'ppa' (designated generators' cost). The run must contain a P2X chain."
    ),
)
async def get_p2x_results(
    run_name: str, period: int | None = None, electricity_cost: str = "nodal", chain_id: str | None = None, include_series: bool = False
) -> Any:
    from urllib.parse import quote

    res = await get_client()._get(
        f"/api/p2x/results/{quote(run_name, safe='')}", {"period": period, "electricity_cost": electricity_cost, "chain_id": chain_id}
    )
    if not include_series and isinstance(res, dict):
        res.pop("series", None)
        res["seriesHint"] = "Per-snapshot series omitted; call with include_series=true to get them."
    return res


@mcp.tool(
    annotations=_MUT,
    description=(
        "Build a P2X chain into the working model through the fragment merge (buses, carriers, Links, Stores, offtake Loads and the RAGNAROK_P2X "
        "registry row). Without confirm=true it returns the preview of what would be merged. After applying, solve as usual; add "
        "options={'rfnboConfig': {'enabled': true, 'temporal': 'hourly'}} to submit_solve for RFNBO matching. " + _SPEC_HELP
    ),
)
async def build_p2x_chain(spec: dict[str, Any] | None = None, confirm: bool = False) -> Any:
    if _needs_confirm(cheap=False) and not confirm:
        return _preview("Merge a P2X chain into the working model.", _trim(await _chain(spec, apply=False)))
    return _trim(await _chain(spec, apply=True))
