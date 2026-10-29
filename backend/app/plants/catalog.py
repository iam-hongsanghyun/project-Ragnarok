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
       options: list[Any] | None = None, minimum: float | None = None, port: str | None = None, blank: str | None = None) -> dict[str, Any]:
    """A spec field. ``port`` marks a connection: the role of the bus (``electricity`` / ``gas`` / ``h2`` / ``product``) or ``generators`` (a
    list of existing generators); ``blank`` says in words what leaving it empty does (the UI shows it as the empty option)."""
    out: dict[str, Any] = {"key": key, "label": label, "kind": kind, "default": default, "advanced": advanced}
    for k, v in (("unit", unit), ("help", help), ("options", options), ("min", minimum), ("port", port), ("blank", blank)):
        if v is not None:
            out[k] = v
    return out


def _common(bus_label: str, bus_help: str) -> list[dict[str, Any]]:
    """Fields every type has; the electricity port is worded per type (it delivers, draws, or both)."""
    return [
        _f("plantId", "Plant name", "text", "", help="Blank = generated from the type. Also the id every component carries in its `plant` column."),
        _f("bus", bus_label, "bus", None, port="electricity", blank="first electricity bus", help=bus_help),
        *_SIZING,
    ]


_SIZING = [
    _f("extendable", "Let the solver size it", "bool", False),
    _f("pNom", "Capacity", "number", 100.0, unit="MW", minimum=0, help="Fixed size (net electric output; electrolyser input for P2X). Ignored when the solver sizes it."),
    _f("pNomMax", "Maximum size", "number", None, unit="MW", advanced=True, minimum=0, help="Upper bound when the solver sizes it (blank = none)."),
    _f("buildYear", "Commissioning year (build_year)", "number", None, unit="year", minimum=0,
       help="Written on EVERY sub-component row of this composite (and the fuel supplies it creates), so one value moves them all. Blank = none."),
    _f("lifetime", "Lifetime", "number", None, unit="a", minimum=0,
       help="Written on every sub-component row, replacing each part's own lifetime (the same life for the whole asset). Blank = each part keeps its technology-data lifetime."),
    _f("discountRate", "Discount rate", "number", None, unit="1/a", advanced=True,
       help="Written on every cost row as PyPSA's discount_rate (PyPSA annualises overnight_cost with it) and used to restate the BESS inverter at the storage lifetime. The Build view passes the Settings rate; blank = the data-file default."),
]
_GAS_PORT = [
    _f("gasBus", "Gas bus (fuel in)", "bus", None, port="gas", blank="existing gas bus, else create one with a supplier",
       help="The bus the turbine draws gas from (MW thermal, LHV). Leave blank to reuse a gas bus that already has a supplier, or create one (priced by the gas price)."),
]
_THERMAL = [
    _f("committable", "Unit commitment (on/off, minimum load, starts)", "bool", False,
       help="Fixed size only. Makes the solve a MILP; minimum load, ramps, minimum up/down time and start-up cost then take effect."),
    _f("gasPrice", "Gas price", "number", None, unit="EUR/MWh_th", advanced=True, help="Blank = the data-file price (technology-data)."),
    _f("efficiency", "Rated efficiency", "number", None, unit="per unit (LHV)", advanced=True, help="Blank = the data-file value."),
    _f("params", "Parameter overrides", "json", {}, advanced=True,
       help="{'ccgt.min_load': 0.35, 'ccgt.start_up_cost': 90, 'fuels.h2_price': 80, ...}; keys in GET /api/build/plant/technologies."),
    # Opt-in unit-commitment refinements (blank = off: the plant keeps the single rated efficiency and the single start cost). Committable, fixed size only.
    _f("minLoadEfficiency", "Efficiency at minimum load", "number", None, unit="per unit (LHV)", advanced=True, minimum=0,
       help="Part-load efficiency. With the rated efficiency it gives a two-point heat-rate line (no-load fuel + incremental heat rate); a gas turbine Link gets "
            "PyPSA's piecewise efficiency curve, a co-firing generator a stand_by_cost + marginal_cost. Blank = one efficiency at every load."),
    _f("startCostHot", "Hot start cost", "number", None, unit="EUR/MW per start", advanced=True, minimum=0,
       help="Blank = the technology start-up cost. It becomes PyPSA's start_up_cost; warm / cold starts add the difference."),
    _f("startCostWarm", "Warm start cost", "number", None, unit="EUR/MW per start", advanced=True, minimum=0,
       help="Charged when the unit was offline at least 'warm after' hours; needs startWarmAfterHours; at least the hot cost."),
    _f("startWarmAfterHours", "Warm start after", "number", None, unit="h offline", advanced=True, minimum=0),
    _f("startCostCold", "Cold start cost", "number", None, unit="EUR/MW per start", advanced=True, minimum=0,
       help="Charged when the unit was offline at least 'cold after' hours; needs startColdAfterHours; at least the warm cost."),
    _f("startColdAfterHours", "Cold start after", "number", None, unit="h offline", advanced=True, minimum=0),
    _f("startUpMinutes", "Start-up time to minimum load", "number", None, unit="min", advanced=True, minimum=0,
       help="PyPSA's ramp_limit_start_up as minimum load / minutes per minute (RAGNAROK_TimeUnits). Bounds the start snapshot only; blank = no limit."),
    _f("shutDownMinutes", "Shut-down time from minimum load", "number", None, unit="min", advanced=True, minimum=0,
       help="PyPSA's ramp_limit_shut_down, same convention; blank = no limit."),
]
_BLEND_SIMPLE = [
    _f("turbine", "Turbine", "select", "ccgt", options=list(TURBINES)),
    _f("h2Share", "H2 share of the fuel", "number", 0.3, minimum=0, help="Fixed share in the basis below (0.3 = 30 %)."),
    _f("h2ShareUnit", "Share basis", "select", "vol", options=["vol", "energy"], help="vol% is converted with the LHV per Nm3 (30 vol% = 11.4 % of the energy)."),
    _f("h2Price", "H2 price", "number", None, unit="EUR/MWh_LHV", help="Blank = the data-file assumption."),
]
_BLEND_NETWORK = [
    _f("turbine", "Turbine", "select", "ccgt", options=list(TURBINES)),
    _f("h2Bus", "H2 bus (hydrogen in)", "bus", None, port="h2", blank="create an H2 bus with a supplier",
       help="An existing hydrogen bus (e.g. a P2X composite's). Blank = a new bus with an H2 supplier at the price below."),
    _f("h2Price", "H2 price", "number", None, unit="EUR/MWh_LHV", help="Only for the new H2 supplier. Blank = the data-file assumption."),
    _f("blendMax", "Maximum H2 share", "number", None, help="Fraction (0.3 = 30 %) in the basis below. Blank = no cap. Enforced in the solve."),
    _f("blendMin", "Minimum H2 share", "number", None, help="Fraction; blank = no minimum."),
    _f("blendUnit", "Share basis", "select", "vol", options=["vol", "energy"]),
    _f("blendScope", "Applies", "select", "hourly", options=["hourly", "period"], help="hourly = every snapshot; period = the weighted total over the run."),
]

TYPES: dict[str, dict[str, Any]] = {
    "generator": {"label": "Generator", "description": "A plain generator (wind, solar, gas, ...): a carrier, a capacity and a marginal cost.",
                  "technology": None,
                  "fields": [*_common("Electricity bus (output)", "The electricity bus the generator delivers to. Blank = the first electricity bus."),
                             _f("carrier", "Carrier", "carrier", "", help="Blank = none."),
                             _f("marginalCost", "Marginal cost", "number", 0.0, unit="EUR/MWh"),
                             _f("capitalCost", "Overnight capital cost", "number", 0.0, unit="EUR/MW", advanced=True,
                                help="Overnight cost (PyPSA overnight_cost); the discount rate (advanced) and the lifetime annualise it when the solver sizes it."),
                             _f("efficiency", "Efficiency", "number", None, advanced=True)]},
    "bess": {"label": "BESS (battery storage)", "technology": "bess",
             "description": "Battery energy storage as a StorageUnit: power, duration, round-trip efficiency; cost from technology-data.",
             "fields": [*_common("Electricity bus (charge and discharge)", "The electricity bus the battery charges from and discharges to. Blank = the first electricity bus."),
                        _f("maxHours", "Duration", "number", None, unit="h", help="Energy = capacity x duration (blank = the data-file default)."),
                        _f("efficiency", "One-way efficiency", "number", None, unit="per unit", minimum=0,
                           help="Charge and discharge each (round trip = its square); blank = the data-file value."),
                        _f("cyclicSoc", "Cyclic state of charge", "bool", True,
                           help="The battery ends the horizon with the charge it started with (PyPSA cyclic_state_of_charge). Untick to give a starting charge."),
                        _f("initialSoc", "Initial state of charge", "number", None, unit="share of energy capacity", minimum=0,
                           help="Only when not cyclic, and for a fixed size: written as state_of_charge_initial = share x power x duration (MWh). Blank = empty."),
                        _f("standingLoss", "Standing loss", "number", None, unit="per hour", minimum=0,
                           help="PyPSA standing_loss: the share of the stored energy lost every hour. Blank = none."),
                        _f("params", "Parameter overrides", "json", {}, advanced=True)]},
    "ccgt": {"label": "CCGT (gas combined cycle)", "technology": "ccgt",
             "description": "Gas combined-cycle plant as a gas-to-electricity Link with DEA / technology-data cost and operating characteristics.",
             "fields": [*_common("Electricity bus (power out)", "The electricity bus the turbine delivers its net output to. Blank = the first electricity bus."), *_GAS_PORT, *_THERMAL]},
    "ocgt": {"label": "OCGT (gas peaker)", "technology": "ocgt",
             "description": "Open-cycle gas turbine: cheaper, lower efficiency, fast start.", "fields": [*_common("Electricity bus (power out)", "The electricity bus the turbine delivers its net output to. Blank = the first electricity bus."), *_GAS_PORT, *_THERMAL]},
    "cofiring_simple": {"label": "Gas + H2 co-firing (simple)", "technology": "ccgt | ocgt",
                        "description": "One generator burning a fixed gas / H2 blend: cost and CO2 factor follow from the share; H2 is bought at a fixed price.",
                        "portNote": "Gas and hydrogen are bought inside the generator's marginal cost, so there is no gas or H2 bus to connect: only the electricity bus.",
                        "fields": [*_common("Electricity bus (power out)", "The electricity bus the generator delivers to. Blank = the first electricity bus."), *_BLEND_SIMPLE, *_THERMAL]},
    "cofiring_network": {"label": "Gas + H2 co-firing (fuel network)", "technology": "ccgt | ocgt",
                         "description": "Gas bus and H2 bus feed a turbine-fuel bus; the solver chooses the blend within the limits (blend-share constraint).",
                         "fields": [*_common("Electricity bus (power out)", "The electricity bus the turbine delivers its net output to. Blank = the first electricity bus."), *_GAS_PORT, *_BLEND_NETWORK, *_THERMAL]},
    "p2x": {"label": "P2X chain", "technology": "p2x (P2X technologies file)",
            "description": "Electrolyser, H2 storage and (optionally) ammonia / methanol / e-fuel synthesis with an offtake, from the P2X technology data.",
            "fields": [*_common("Electricity bus (electrolyser input)", "The electricity bus the electrolyser (and any compressor or synthesis) draws from. Blank = the first electricity bus."),
                       _f("h2Bus", "H2 bus (hydrogen out)", "bus", None, port="h2", blank="create an H2 bus for this composite",
                          help="The bus the electrolyser delivers hydrogen to, and the H2 offtake and store sit on. Pick an existing H2 bus to share it (e.g. with a co-firing turbine); blank creates one."),
                       _f("productBus", "Product bus (NH3 / MeOH / e-fuel out)", "bus", None, port="product", blank="create a product bus",
                          help="Only for a derivative product: the bus the synthesis delivers it to. Blank creates one. Ignored for H2."),
                       _f("designatedGenerators", "Renewable supply matched to (generators)", "generators", [], port="generators",
                          blank="none (RFNBO matching has nothing to match to)",
                          help="Existing generators the electrolyser is matched to for RFNBO rules (the PPA). Used by the RFNBO rules and the PPA electricity-cost option; no row is changed on them."),
                       _f("product", "Product", "select", "H2", options=list(p2x_chains.ALL_PRODUCTS)),
                       _f("storage", "H2 storage", "select", "tank", options=["none", "tank", "cavern"]),
                       _f("offtakeMw", "Product offtake", "number", 30.0, unit="MW (LHV)", help="Constant demand for the product."),
                       _f("chain", "Chain spec overrides", "json", {}, advanced=True, help="Any key of the P2X chain spec (GET /api/p2x/chain/defaults).")]},
}


_STORED_WHEN_SET = ("h2Bus", "productBus", "designatedGenerators", "buildYear", "lifetime")
COMPOSITES_SHEET = "RAGNAROK_Composites"
TEMPLATES_SHEET = "RAGNAROK_CompositeTemplates"
#: The instance sheet's columns (PyPSA-style names) and the spec key each one edits; a column the sheet lacks is simply not edited there.
SHEET_COLUMNS: dict[str, tuple[str, str]] = {
    "bus": ("bus", "text"), "gas_bus": ("gasBus", "text"), "h2_bus": ("h2Bus", "text"), "product_bus": ("productBus", "text"),
    "designated_generators": ("designatedGenerators", "list"), "p_nom": ("pNom", "number"), "p_nom_extendable": ("extendable", "bool"),
    "p_nom_max": ("pNomMax", "number"), "build_year": ("buildYear", "number"), "lifetime": ("lifetime", "number"), "discount_rate": ("discountRate", "number"),
}


def default_spec(type_id: str) -> dict[str, Any]:
    """The flat spec with every default for ``type_id``."""
    if type_id not in TYPES:
        raise PlantError(f"Unknown plant type {type_id!r}. Options: {list(TYPES)}.")
    return {f["key"]: f["default"] for f in TYPES[type_id]["fields"]}


def list_types() -> list[dict[str, Any]]:
    """The type catalogue for the picker: id, label, description, fields with defaults, technology key."""
    return [{"id": k, "label": v["label"], "description": v["description"], "fields": v["fields"], "defaults": default_spec(k),
             "technology": v["technology"], "portNote": v.get("portNote")} for k, v in TYPES.items()]


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
    cyclic = bool(spec.get("cyclicSoc", True))
    loss, soc0 = num(spec.get("standingLoss")), opt(spec.get("initialSoc"))
    if not 0.0 <= loss < 1.0:
        raise PlantError("standingLoss is a share per hour in [0, 1).")
    if soc0 is not None and not 0.0 <= soc0 <= 1.0:
        raise PlantError("initialSoc is a share of the energy capacity in [0, 1].")
    ctx.carrier("battery")
    row: dict[str, Any] = {
        "name": ctx.nm(), "bus": bus, "carrier": "battery", "max_hours": hours, "efficiency_store": round(P["efficiency_one_way"], 6),
        "efficiency_dispatch": round(P["efficiency_one_way"], 6), "cyclic_state_of_charge": cyclic, "lifetime": P["storage_lifetime"],
        "overnight_cost": round(overnight, 6), "fom_cost": round(fom, 6), "discount_rate": r,
    }
    if ext:
        row.update({"p_nom_extendable": True, "p_nom": 0.0})
        if opt(spec.get("pNomMax")):
            row["p_nom_max"] = opt(spec["pNomMax"])
    else:
        row["p_nom"] = num(spec.get("pNom"))
    if loss > 0:
        row["standing_loss"] = loss
    if soc0 is not None and not cyclic:
        if ext:
            ctx.warnings.append("initialSoc needs a fixed size (the initial charge is in MWh): it is not written for a solver-sized battery.")
        else:
            row["state_of_charge_initial"] = round(soc0 * hours * num(spec.get("pNom")), 6)
    elif soc0 is not None and cyclic:
        ctx.warnings.append("initialSoc is ignored while the state of charge is cyclic.")
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
        "electrolyser": {"tech": "aec", "extendable": ext, "pNom": num(spec.get("pNom")), "pNomMax": opt(spec.get("pNomMax")),
                         **({"buildYear": int(num(spec["buildYear"]))} if opt(spec.get("buildYear")) else {})},
        "storage": {"type": str(spec.get("storage") or "tank")},
        "offtake": {product: {"mode": "flat", "mw": mw}} if mw > 0 else {},
    }
    if spec.get("h2Bus"):
        chain["h2Bus"] = str(spec["h2Bus"])
    if product != "H2" and spec.get("productBus"):
        chain["productBuses"] = {product: str(spec["productBus"])}
    if spec.get("designatedGenerators"):
        chain["designatedGenerators"] = [str(g) for g in spec["designatedGenerators"]]
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
    return {"p2xTechnologies": list(built["registry"]["parameters"]), "main": built["registry"]["components"]["electrolyser"], "capacityMwEl": None if ext else num(spec.get("pNom")),
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
        ``{plantId, type, label, fragment, registry, summary, warnings, spec, technologies}`` (``technologies`` = the technology-data keys the build read: ``plants`` and ``p2x``); ``fragment`` merges through
        :func:`backend.app.fragment_merge.merge_fragment` and already contains the registry row.

    Raises:
        PlantError: unknown type, bad bus, name clash, invalid numbers.
    """
    if type_id not in TYPES:
        raise PlantError(f"Unknown plant type {type_id!r}. Options: {list(TYPES)}.")
    keys = {f["key"] for f in TYPES[type_id]["fields"]}
    spec = {**default_spec(type_id), **{k: v for k, v in (spec_in or {}).items() if k in keys}}
    for key in _STORED_WHEN_SET:       # fields added later: stored only when chosen, so older plants re-derive unchanged
        if spec.get(key) in (None, "", []):
            spec.pop(key, None)
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
    shared: dict[str, Any] = {}                    # investment fields identical on every sub-component
    if opt(spec.get("buildYear")):
        shared["build_year"] = int(num(spec["buildYear"]))
    if opt(spec.get("lifetime")):
        shared["lifetime"] = num(spec["lifetime"])
    if shared:
        for sheet in ("generators", "links", "stores", "storage_units", "processes"):
            for row in ctx.sheets.get(sheet, []):
                row.update(shared)
    p2x_techs = extra.pop("p2xTechnologies", [])
    technologies = {"plants": {"bess": ["bess"], "generator": [], "p2x": []}[type_id] if type_id in _SIMPLE else [extra["turbine"], "fuels"], "p2x": p2x_techs}
    years = horizon_years(model)
    if any(r.get("fom_cost") for rows in ctx.sheets.values() for r in rows if isinstance(r, dict)):
        ctx.warnings.append(f"fom_cost is written per modelled HORIZON, as PyPSA charges it: fixed O&M per year x {years:g} years "
                            "(the workbook's snapshots). Re-apply the plant after changing the snapshots to refresh it.")
    registry = {
        "horizonYears": years, "version": SPEC_VERSION, "plantId": pid, "type": type_id, "label": f"{TYPES[type_id]['label']} {pid}", "bus": str(bus),
        "spec": spec, "extendable": bool(spec.get("extendable")), "discountRate": r, "components": list(ctx.components), **extra,
    }
    ctx.sheets[REGISTRY_SHEET].append(registry_row(registry))
    ctx.sheets[COMPOSITES_SHEET].append(composite_row(registry))
    fragment = ctx.fragment()
    fragment.update(ctx.extra_fragment)
    return {"plantId": pid, "type": type_id, "label": registry["label"], "fragment": fragment, "registry": registry,
            "summary": ctx.summary, "warnings": ctx.warnings, "spec": spec, "technologies": technologies}


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
            "summary": built["summary"], "warnings": built["warnings"], "spec": built["spec"], "technologies": built["technologies"]}


# ── the instance sheet: one visible row per composite, editable as ONE asset ─────────────────────────────────────


def composite_row(registry: dict[str, Any]) -> dict[str, Any]:
    """The ``RAGNAROK_Composites`` row of a built composite: its name, type, ports, size and shared investment fields.

    The row is the user's surface (a normal sheet in the Model tables); :func:`sync_composites` re-expands the children when a cell differs
    from the stored spec. Blank cell = the backend default.
    """
    spec = registry["spec"]
    row: dict[str, Any] = {"name": registry["plantId"], "type": registry["type"], "template": spec.get("template") or ""}
    for col, (key, kind) in SHEET_COLUMNS.items():            # every column, blank when unset, in this fixed order: the user can fill a blank cell
        v = spec.get(key)
        if kind == "list":
            row[col] = ",".join(str(x) for x in v) if isinstance(v, list) else ""
        else:
            row[col] = "" if v is None else v
    row[PLANT_COLUMN] = registry["plantId"]                    # owner tag last: the grid's last column, not something to edit
    return row


def _parse_cell(raw: Any, kind: str) -> Any:
    """A sheet cell as a spec value (None = blank): numbers parsed, bool from true/false/1/0, a list from a comma list."""
    if raw is None or (isinstance(raw, float) and raw != raw) or str(raw).strip() == "":
        return [] if kind == "list" else None
    if kind == "number":
        try:
            return float(raw)
        except (TypeError, ValueError) as exc:
            raise PlantError(f"Cell {raw!r} must be a number.") from exc
    if kind == "bool":
        return raw if isinstance(raw, bool) else str(raw).strip().lower() in ("true", "1", "yes")
    if kind == "list":
        return [x.strip() for x in str(raw).split(",") if x.strip()]
    return str(raw).strip()


def _same(a: Any, b: Any, kind: str) -> bool:
    if kind == "number":
        return (a is None and b in (None, "")) or (b is None and a in (None, "")) or (a is not None and b not in (None, "") and abs(float(a) - float(b)) < 1e-9)
    if kind == "list":
        return list(a or []) == list(b or [])
    if kind == "bool":
        return bool(a) == bool(b)
    return (a or None) == (b or None)


def sheet_patches(model: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """``{plantId: spec patch}`` for every ``RAGNAROK_Composites`` row whose cells differ from the stored spec (rows of unknown plants are ignored).

    Raises:
        PlantError: a cell cannot be parsed.
    """
    from .registry import registry_map

    regs = registry_map(model)
    out: dict[str, dict[str, Any]] = {}
    for row in model.get(COMPOSITES_SHEET) or []:
        pid = str(row.get("name") or "")
        reg = regs.get(pid)
        if reg is None:
            continue
        patch: dict[str, Any] = {}
        for col, (key, kind) in SHEET_COLUMNS.items():
            if col not in row:
                continue
            new = _parse_cell(row.get(col), kind)
            if not _same(new, reg["spec"].get(key), kind):
                patch[key] = new
        if patch:
            out[pid] = patch
    return out


def _combine(model_fragments: list[dict[str, Any]]) -> dict[str, Any]:
    """One fragment from several (rows merged by name, like the fragment merge does)."""
    from .. import fragment_merge

    acc: dict[str, list[dict[str, Any]]] = {}
    for frag in model_fragments:
        acc = fragment_merge.merge_fragment(acc, frag)
    return {"sheets": {s: r for s, r in acc.items() if isinstance(r, list) and r}}


def sync_composites(model: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Re-expand every composite whose sheet row was edited: one combined change set (remove the old children, merge the new ones).

    Returns ``{plantIds, patches, added, change}``; ``change`` is None when no row differs. ``added`` = composites of an older workbook that
    had no sheet row yet: their row is written (the migration; nothing is re-derived for them).
    """
    from .registry import apply_change

    from .registry import registry_map

    patches = sheet_patches(model)
    have = {str(r.get("name")) for r in model.get(COMPOSITES_SHEET) or []}
    missing = [composite_row(reg) for pid, reg in registry_map(model).items() if pid not in have]     # a workbook from before the sheet existed
    if not patches and not missing:
        return {"plantIds": [], "patches": {}, "added": [], "change": None, "warnings": []}
    working, remove, release, frags, warnings = model, {}, [], [], []
    if missing:
        frags.append({"sheets": {COMPOSITES_SHEET: missing}})
    for pid, patch in patches.items():
        change = edit_plant(working, pid, patch)
        working = apply_change(working, change)
        for sheet, names in change["remove"].items():
            remove[sheet] = sorted(set(remove.get(sheet, [])) | set(names))
        release.extend(change["release"])
        frags.append(change["fragment"])
        warnings.extend(f"{pid}: {w}" for w in change["warnings"])
    return {"plantIds": list(patches), "patches": patches, "added": [r["name"] for r in missing], "warnings": warnings,
            "change": {"remove": remove, "release": release, "fragment": _combine(frags), "kept": {"buses": [], "carriers": []}}}


def place_plants(type_id: str, spec_in: dict[str, Any] | None, buses: list[str], model: dict[str, list[dict[str, Any]]], *,
                 prefix: str | None = None, share_ports: bool = False) -> dict[str, Any]:
    """Build one instance of ``type_id`` per bus in ``buses`` (copy-paste placement), each named ``<prefix>_<bus>`` and editable alone.

    Args:
        type_id: plant type.
        spec_in: the template spec (ports, size, investment fields); ``bus`` / ``plantId`` are set per instance.
        buses: electricity buses to place on (distinct).
        model: the working model.
        prefix: instance name prefix (default the type id).
        share_ports: False (default) = every instance gets its OWN fuel / H2 / product buses: the fuel ports of the template are dropped and each
            instance is built against the original model, so what it creates is its own. True = the template's fuel / H2 / product ports are
            kept and instances are built one after the other, so later ones reuse what the first created.

    Returns:
        ``{plantIds, instances, fragment, warnings}``; ``fragment`` merges through the fragment merge.

    Raises:
        PlantError: no buses, a bus not in the model, or a name clash.
    """
    import re

    from .. import fragment_merge

    if not buses or len(set(buses)) != len(buses):
        raise PlantError("Pick at least one bus, each once.")
    base = re.sub(r"[^A-Za-z0-9_]", "_", prefix or type_id)
    ports = [f["key"] for f in TYPES.get(type_id, {"fields": []})["fields"] if f.get("port") and f["key"] != "bus" and f["kind"] == "bus"]
    working, frags, instances, warnings, ids = model, [], [], [], []
    for bus in buses:
        pid = f"{base}_{re.sub(r'[^A-Za-z0-9_]', '_', str(bus))}"
        if pid in ids:
            raise PlantError(f"Two buses give the same instance name {pid!r}.")
        spec = {**(spec_in or {}), "bus": bus, "plantId": pid}
        if not share_ports:
            for k in ports:
                spec.pop(k, None)
        built = build_plant(type_id, spec, working if share_ports else model)
        frags.append(built["fragment"])
        ids.append(pid)
        instances.append({"plantId": pid, "bus": bus, "rowCounts": {s: len(r) for s, r in built["fragment"]["sheets"].items() if not s.startswith("RAGNAROK")}})
        warnings.extend(f"{pid}: {w}" for w in built["warnings"])
        if share_ports:
            working = fragment_merge.merge_fragment(working, built["fragment"])
    return {"plantIds": ids, "instances": instances, "fragment": _combine(frags), "warnings": warnings}


def detach_change(model: dict[str, list[dict[str, Any]]], plant_id: str) -> dict[str, Any]:
    """Turn composite ``plant_id`` into plain rows: its children keep every value but lose the owner tag; the registry and sheet rows go."""
    from .registry import REGISTRY_SHEET as REG, plant_rows

    rows = plant_rows(model, plant_id)
    if not rows:
        raise PlantError(f"No composite {plant_id!r} in the model.")
    remove = {s: [plant_id] for s in (REG, COMPOSITES_SHEET) if plant_id in rows.get(s, [])}
    release = [{"sheet": s, "name": n} for s, names in rows.items() if s not in remove for n in names]
    return {"plantId": plant_id, "remove": remove, "release": release, "fragment": None, "kept": {"buses": [], "carriers": []}, "warnings": []}
