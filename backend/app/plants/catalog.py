"""Plant types: their fields and defaults, and ``build_plant`` (the one entry the API, the MCP tools and the UI share).

Types: ``generator`` (a plain Generator), ``bess`` (StorageUnit), ``ccgt``, ``ocgt``, ``cofiring_simple`` (one Generator
burning a fixed gas / H2 blend), ``cofiring_network`` (gas bus + H2 bus -> fuel bus -> turbine Link, with the blend-share
run option) and ``p2x`` (the P2X chain through :func:`backend.app.p2x.chains.build_chain`, not duplicated).

Every plant is added with **a bus and a capacity** (fixed MW or extendable) plus a few key fields; everything else comes
from the technology data file and sits behind ``advanced: true`` fields. The spec is flat so a form, a JSON body and an
MCP call are the same object.
"""

from __future__ import annotations

from typing import Any

from pypsa.costs import annuity as _pypsa_annuity

from ...pypsa.network.cost_basis import horizon_years
from ..p2x import chains as p2x_chains
from . import technologies as tech
from .registry import (
    PLANT_COLUMN,
    Ctx,
    PlantError,
    check_plant_id,
    merge_spec,
    next_plant_id,
    registry_row,
)
from .thermal import (
    TURBINES,
    build_cofiring_network,
    build_cofiring_simple,
    build_gas_turbine,
    default_ac_bus,
    num,
    opt,
)

SPEC_VERSION = 1
REGISTRY_SHEET = "RAGNAROK_PLANTS"


def _f(key: str, label: str, kind: str, default: Any, *, unit: str | None = None, advanced: bool = False, help: str | None = None,
       options: list[Any] | None = None, minimum: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"key": key, "label": label, "kind": kind, "default": default, "advanced": advanced}
    for k, v in (("unit", unit), ("help", help), ("options", options), ("min", minimum)):
        if v is not None:
            out[k] = v
    return out


_COMMON = [
    _f("plantId", "Plant name", "text", "", help="Blank = generated from the type. Also the id every component carries in its `plant` column."),
    _f("bus", "Connect at bus", "bus", None, help="The electricity bus the plant delivers to (or draws from). Blank = the first electricity bus."),
    _f("extendable", "Let the solver size it", "bool", False),
    _f("pNom", "Capacity", "number", 100.0, unit="MW", minimum=0, help="Fixed size (net electric output; electrolyser input for P2X). Ignored when the solver sizes it."),
    _f("pNomMax", "Maximum size", "number", None, unit="MW", advanced=True, minimum=0, help="Upper bound when the solver sizes it (blank = none)."),
    _f("discountRate", "Discount rate", "number", None, unit="1/a", advanced=True,
       help="Written on every cost row as PyPSA's discount_rate (PyPSA annualises overnight_cost with it) and used to restate the BESS inverter at the storage lifetime. The Build view passes the Settings rate; blank = the data-file default."),
]
_THERMAL = [
    _f("committable", "Unit commitment (on/off, minimum load, starts)", "bool", False,
       help="Fixed size only. Makes the solve a MILP; minimum load, ramps, minimum up/down time and start-up cost then take effect."),
    _f("gasPrice", "Gas price", "number", None, unit="EUR/MWh_th", advanced=True, help="Blank = the data-file price (technology-data)."),
    _f("gasBus", "Gas bus", "bus", None, advanced=True, help="Blank = an existing gas bus, else a new one with a supplier."),
    _f("efficiency", "Rated efficiency", "number", None, unit="per unit (LHV)", advanced=True, help="Blank = the data-file value."),
    _f("params", "Parameter overrides", "json", {}, advanced=True,
       help="{'ccgt.min_load': 0.35, 'ccgt.start_up_cost': 90, 'fuels.h2_price': 80, ...}; keys in GET /api/build/plant/technologies."),
]
_BLEND_SIMPLE = [
    _f("turbine", "Turbine", "select", "ccgt", options=list(TURBINES)),
    _f("h2Share", "H2 share of the fuel", "number", 0.3, minimum=0, help="Fixed share in the basis below (0.3 = 30 %)."),
    _f("h2ShareUnit", "Share basis", "select", "vol", options=["vol", "energy"], help="vol% is converted with the LHV per Nm3 (30 vol% = 11.4 % of the energy)."),
    _f("h2Price", "H2 price", "number", None, unit="EUR/MWh_LHV", help="Blank = the data-file assumption."),
]
_BLEND_NETWORK = [
    _f("turbine", "Turbine", "select", "ccgt", options=list(TURBINES)),
    _f("h2Bus", "H2 bus", "bus", None, help="An existing H2 bus (e.g. a P2X chain's). Blank = a new bus with an H2 supplier at the price below."),
    _f("h2Price", "H2 price", "number", None, unit="EUR/MWh_LHV", help="Only for the new H2 supplier. Blank = the data-file assumption."),
    _f("blendMax", "Maximum H2 share", "number", None, help="Fraction (0.3 = 30 %) in the basis below. Blank = no cap. Enforced in the solve."),
    _f("blendMin", "Minimum H2 share", "number", None, help="Fraction; blank = no minimum."),
    _f("blendUnit", "Share basis", "select", "vol", options=["vol", "energy"]),
    _f("blendScope", "Applies", "select", "hourly", options=["hourly", "period"], help="hourly = every snapshot; period = the weighted total over the run."),
]

TYPES: dict[str, dict[str, Any]] = {
    "generator": {"label": "Generator", "description": "A plain generator (wind, solar, gas, ...): a carrier, a capacity and a marginal cost.",
                  "technology": None,
                  "fields": [*_COMMON,
                             _f("carrier", "Carrier", "carrier", "", help="Blank = none."),
                             _f("marginalCost", "Marginal cost", "number", 0.0, unit="EUR/MWh"),
                             _f("capitalCost", "Overnight capital cost", "number", 0.0, unit="EUR/MW", advanced=True,
                                help="Overnight cost (PyPSA overnight_cost); the discount rate (advanced) and the lifetime annualise it when the solver sizes it."),
                             _f("lifetime", "Lifetime", "number", None, unit="a", advanced=True),
                             _f("efficiency", "Efficiency", "number", None, advanced=True),
                             _f("buildYear", "Build year", "number", 0, advanced=True)]},
    "bess": {"label": "BESS (battery storage)", "technology": "bess",
             "description": "Battery energy storage as a StorageUnit: power, duration, round-trip efficiency; cost from technology-data.",
             "fields": [*_COMMON,
                        _f("maxHours", "Duration", "number", None, unit="h", help="Energy = capacity x duration (blank = the data-file default)."),
                        _f("efficiency", "One-way efficiency", "number", None, advanced=True, help="Charge and discharge each; blank = the data-file value."),
                        _f("params", "Parameter overrides", "json", {}, advanced=True)]},
    "ccgt": {"label": "CCGT (gas combined cycle)", "technology": "ccgt",
             "description": "Gas combined-cycle plant as a gas-to-electricity Link with DEA / technology-data cost and operating characteristics.",
             "fields": [*_COMMON, *_THERMAL]},
    "ocgt": {"label": "OCGT (gas peaker)", "technology": "ocgt",
             "description": "Open-cycle gas turbine: cheaper, lower efficiency, fast start.", "fields": [*_COMMON, *_THERMAL]},
    "cofiring_simple": {"label": "Gas + H2 co-firing (simple)", "technology": "ccgt | ocgt",
                        "description": "One generator burning a fixed gas / H2 blend: cost and CO2 factor follow from the share; H2 is bought at a fixed price.",
                        "fields": [*_COMMON, *_BLEND_SIMPLE, *_THERMAL]},
    "cofiring_network": {"label": "Gas + H2 co-firing (fuel network)", "technology": "ccgt | ocgt",
                         "description": "Gas bus and H2 bus feed a turbine-fuel bus; the solver chooses the blend within the limits (blend-share constraint).",
                         "fields": [*_COMMON, *_BLEND_NETWORK, *_THERMAL]},
    "p2x": {"label": "P2X chain", "technology": "p2x (P2X technologies file)",
            "description": "Electrolyser, H2 storage and (optionally) ammonia / methanol / e-fuel synthesis with an offtake, from the P2X technology data.",
            "fields": [*_COMMON,
                       _f("product", "Product", "select", "H2", options=list(p2x_chains.ALL_PRODUCTS)),
                       _f("storage", "H2 storage", "select", "tank", options=["none", "tank", "cavern"]),
                       _f("offtakeMw", "Product offtake", "number", 30.0, unit="MW (LHV)", help="Constant demand for the product."),
                       _f("chain", "Chain spec overrides", "json", {}, advanced=True, help="Any key of the P2X chain spec (GET /api/p2x/chain/defaults).")]},
}


def default_spec(type_id: str) -> dict[str, Any]:
    """The flat spec with every default for ``type_id``."""
    if type_id not in TYPES:
        raise PlantError(f"Unknown plant type {type_id!r}. Options: {list(TYPES)}.")
    return {f["key"]: f["default"] for f in TYPES[type_id]["fields"]}


def list_types() -> list[dict[str, Any]]:
    """The type catalogue for the picker: id, label, description, fields with defaults, technology key."""
    return [{"id": k, "label": v["label"], "description": v["description"], "fields": v["fields"], "defaults": default_spec(k),
             "technology": v["technology"]} for k, v in TYPES.items()]


def _build_generator(spec: dict[str, Any], ctx: Ctx, bus: str, r: float) -> dict[str, Any]:
    ext = bool(spec.get("extendable"))
    ctx.carrier(str(spec.get("carrier") or ""))
    row: dict[str, Any] = {"name": ctx.nm(), "bus": bus, "marginal_cost": num(spec.get("marginalCost"))}
    if spec.get("carrier"):
        row["carrier"] = str(spec["carrier"])
    if opt(spec.get("efficiency")):
        row["efficiency"] = opt(spec["efficiency"])
    if ext:
        row.update({"p_nom_extendable": True, "p_nom": 0.0, "overnight_cost": num(spec.get("capitalCost")), "discount_rate": r})
        if opt(spec.get("pNomMax")):
            row["p_nom_max"] = opt(spec["pNomMax"])
    else:
        row["p_nom"] = num(spec.get("pNom"))
    if opt(spec.get("lifetime")):
        row["lifetime"] = opt(spec["lifetime"])
    if int(num(spec.get("buildYear"))) > 0:
        row["build_year"] = int(num(spec["buildYear"]))
    ctx.add("generators", row, "generator")
    return {"main": {"sheet": "generators", "name": row["name"]}, "capacityMwEl": None if ext else num(spec.get("pNom")),
            "feeders": None, "powerSeries": ["generators", "p"], "fuelSeries": None}


def _build_bess(spec: dict[str, Any], ctx: Ctx, bus: str, r: float) -> dict[str, Any]:
    over = dict(spec.get("params") or {})
    if opt(spec.get("efficiency")):
        over["bess.efficiency_one_way"] = spec["efficiency"]
    if opt(spec.get("maxHours")):
        over["bess.max_hours"] = spec["maxHours"]
    P = tech.resolve_parameters(over)["bess"]
    if not 0.0 < P["efficiency_one_way"] <= 1.0:
        raise PlantError("BESS efficiency must be in (0, 1].")
    hours = P["max_hours"]
    # One lifetime per row: the storage lifetime. The inverter (shorter life) is expressed as the overnight cost that has the same annual
    # charge over that lifetime, K_inv a(r, L_inv) / a(r, L_st), at the plant's discount rate (the only place a rate enters a template).
    # This is a module-side data conversion; the annuity is PyPSA's own (pypsa.costs.annuity).
    a_i, a_s = float(_pypsa_annuity(r, P["inverter_lifetime"])), float(_pypsa_annuity(r, P["storage_lifetime"]))
    overnight = P["inverter_capex"] * 1000.0 * a_i / a_s + P["storage_capex"] * 1000.0 * hours
    # fom_cost is PyPSA's per-HORIZON column: the yearly O&M x the workbook's horizon in years (shown in the preview warning).
    years = horizon_years(ctx.model)
    fom = P["inverter_capex"] * 1000.0 * P["inverter_fom"] / 100.0 * years

    ext = bool(spec.get("extendable"))
    ctx.carrier("battery")
    row: dict[str, Any] = {
        "name": ctx.nm(), "bus": bus, "carrier": "battery", "max_hours": hours, "efficiency_store": round(P["efficiency_one_way"], 6),
        "efficiency_dispatch": round(P["efficiency_one_way"], 6), "cyclic_state_of_charge": True, "lifetime": P["storage_lifetime"],
        "overnight_cost": round(overnight, 6), "fom_cost": round(fom, 6), "discount_rate": r,
    }
    if ext:
        row.update({"p_nom_extendable": True, "p_nom": 0.0})
        if opt(spec.get("pNomMax")):
            row["p_nom_max"] = opt(spec["pNomMax"])
    else:
        row["p_nom"] = num(spec.get("pNom"))
    ctx.add("storage_units", row, "battery")
    return {"main": {"sheet": "storage_units", "name": row["name"]}, "parameters": P, "capacityMwEl": None if ext else num(spec.get("pNom")),
            "feeders": None, "powerSeries": ["storage_units", "p"], "fuelSeries": None}


def _build_p2x(spec: dict[str, Any], ctx: Ctx, bus: str, r: float) -> dict[str, Any]:
    product = str(spec.get("product") or "H2")
    if product not in p2x_chains.ALL_PRODUCTS:
        raise PlantError(f"product must be one of {list(p2x_chains.ALL_PRODUCTS)}, got {product!r}.")
    ext = bool(spec.get("extendable"))
    mw = num(spec.get("offtakeMw"))
    chain: dict[str, Any] = {
        "chainId": ctx.pid, "anchorBus": bus, "discountRate": r, "products": ["H2"] if product == "H2" else ["H2", product],
        "electrolyser": {"tech": "aec", "extendable": ext, "pNom": num(spec.get("pNom")), "pNomMax": opt(spec.get("pNomMax"))},
        "storage": {"type": str(spec.get("storage") or "tank")},
        "offtake": {product: {"mode": "flat", "mw": mw}} if mw > 0 else {},
    }
    chain = merge_spec(chain, spec.get("chain") or {})
    chain["chainId"] = ctx.pid
    try:
        built = p2x_chains.build_chain(chain, ctx.model)
    except ValueError as exc:
        raise PlantError(str(exc)) from exc
    role_of = {(c["sheet"], c["name"]): role for role, c in built["registry"]["components"].items()}
    for sheet, rows in built["fragment"]["sheets"].items():
        if "-" not in sheet:
            for row in rows:
                row[PLANT_COLUMN] = ctx.pid
                if sheet != p2x_chains.REGISTRY_SHEET:
                    ctx.components.append({"sheet": sheet, "name": str(row["name"]), "role": role_of.get((sheet, str(row["name"])), sheet)})
        ctx.sheets[sheet].extend(rows)
    ctx.summary.extend(built["summary"])
    ctx.warnings.extend(w for w in built["warnings"] if not (product != "H2" and w.startswith("No H2 offtake")))
    if "snapshots" in built["fragment"]:
        ctx.extra_fragment["snapshots"] = built["fragment"]["snapshots"]
    return {"main": built["registry"]["components"]["electrolyser"], "capacityMwEl": None if ext else num(spec.get("pNom")),
            "feeders": None, "product": product, "chainId": ctx.pid, "powerSeries": None, "fuelSeries": None}


_SIMPLE = {"generator": _build_generator, "bess": _build_bess, "p2x": _build_p2x}


def build_plant(type_id: str, spec_in: dict[str, Any] | None, model: dict[str, list[dict[str, Any]]], *, plant_id: str | None = None) -> dict[str, Any]:
    """Build a plant of ``type_id`` from the flat ``spec_in`` (only the keys to change) against ``model``.

    Args:
        type_id: one of :data:`TYPES`.
        spec_in: spec overrides (see :func:`default_spec` / :func:`list_types`).
        model: the working model (sheets -> rows); read for the bus, names, carriers and snapshots.
        plant_id: force the id (an edit re-derives under the same id); default ``spec.plantId`` or a free id of the type.

    Returns:
        ``{plantId, type, label, fragment, registry, summary, warnings, spec}``; ``fragment`` merges through
        :func:`backend.app.fragment_merge.merge_fragment` and already contains the registry row.

    Raises:
        PlantError: unknown type, bad bus, name clash, invalid numbers.
    """
    if type_id not in TYPES:
        raise PlantError(f"Unknown plant type {type_id!r}. Options: {list(TYPES)}.")
    keys = {f["key"] for f in TYPES[type_id]["fields"]}
    spec = {**default_spec(type_id), **{k: v for k, v in (spec_in or {}).items() if k in keys}}
    unknown = sorted(set(spec_in or {}) - keys)
    pid = check_plant_id(plant_id or spec.get("plantId") or next_plant_id(type_id, model), model)
    bus = spec.get("bus") or default_ac_bus(model)
    if not bus or not any(str(b.get("name")) == str(bus) for b in model.get("buses") or []):
        raise PlantError(f"Bus {bus!r} not found in the model; a plant needs a bus to connect to.")
    spec.update({"plantId": pid, "bus": str(bus)})
    r = float(spec["discountRate"]) if spec.get("discountRate") not in (None, "") else tech.default_discount_rate()
    if not 0.0 <= r < 1.0:
        raise PlantError(f"discountRate must be a fraction in [0, 1) (0.05 = 5 %), got {r!r}.")
    if not spec.get("extendable") and num(spec.get("pNom")) <= 0:
        raise PlantError("A fixed plant needs pNom > 0 (MW), or tick 'Let the solver size it'.")
    ctx = Ctx(model, pid)
    if unknown:
        ctx.warnings.append(f"Ignored spec keys not used by a {type_id} plant: {unknown}.")
    try:
        if type_id in _SIMPLE:
            extra = _SIMPLE[type_id](spec, ctx, str(bus), r)
        else:
            turbine = type_id if type_id in TURBINES else str(spec.get("turbine") or "ccgt").lower()
            if turbine not in TURBINES:
                raise PlantError(f"turbine must be one of {list(TURBINES)}, got {spec.get('turbine')!r}.")
            fn = {"ccgt": build_gas_turbine, "ocgt": build_gas_turbine, "cofiring_simple": build_cofiring_simple,
                  "cofiring_network": build_cofiring_network}[type_id]
            extra = fn(turbine, spec, ctx, str(bus), r)
            extra["turbine"] = turbine
    except PlantError:
        raise
    except ValueError as exc:                      # bad parameter key / value from the technology loader or a share conversion
        raise PlantError(str(exc)) from exc
    years = horizon_years(model)
    if any(r.get("fom_cost") for rows in ctx.sheets.values() for r in rows if isinstance(r, dict)):
        ctx.warnings.append(f"fom_cost is written per modelled HORIZON, as PyPSA charges it: fixed O&M per year x {years:g} years "
                            "(the workbook's snapshots). Re-apply the plant after changing the snapshots to refresh it.")
    registry = {
        "horizonYears": years, "version": SPEC_VERSION, "plantId": pid, "type": type_id, "label": f"{TYPES[type_id]['label']} {pid}", "bus": str(bus),
        "spec": spec, "extendable": bool(spec.get("extendable")), "discountRate": r, "components": list(ctx.components), **extra,
    }
    ctx.sheets[REGISTRY_SHEET].append(registry_row(registry))
    fragment = ctx.fragment()
    fragment.update(ctx.extra_fragment)
    return {"plantId": pid, "type": type_id, "label": registry["label"], "fragment": fragment, "registry": registry,
            "summary": ctx.summary, "warnings": ctx.warnings, "spec": spec}


def edit_plant(model: dict[str, list[dict[str, Any]]], plant_id: str, patch: dict[str, Any] | None) -> dict[str, Any]:
    """Re-derive plant ``plant_id`` from its stored spec with ``patch`` laid over it.

    Returns the change set of :mod:`registry` (``remove`` the old rows, ``release`` shared ones, merge the new ``fragment``) plus
    the build's ``registry`` / ``summary`` / ``warnings``.

    Raises:
        PlantError: no such plant, or it has no registry row (imported from a file: delete and add it again).
    """
    from .registry import apply_change, delete_change, registry_map

    reg = registry_map(model).get(plant_id)
    if reg is None:
        raise PlantError(f"Plant {plant_id!r} has no registry row (it was imported without one), so it cannot be edited: delete it and add it again.")
    change = delete_change(model, plant_id)
    base = apply_change(model, change)
    spec = merge_spec(reg["spec"], patch or {})
    built = build_plant(reg["type"], spec, base, plant_id=plant_id)
    return {**change, "fragment": built["fragment"], "plantId": plant_id, "type": reg["type"], "registry": built["registry"],
            "summary": built["summary"], "warnings": built["warnings"], "spec": built["spec"]}
