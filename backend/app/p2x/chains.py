"""P2X chain templates: a chain spec -> a workbook fragment for the session model.

Everything is built from ordinary PyPSA components and merged through the same
fragment path as the Build conversions (``fragment_merge.merge_fragment``), so a
P2X chain is part of the one core model — there is no separate engine.

Components: the electrolyser, compressor and H2 discharge are ordinary ``Link``s (the RFNBO
constraint, the availability / minimum-load switches and every Link view key on them). The
multi-input conversion steps - Haber-Bosch, methanolisation, Fischer-Tropsch, the ASU and the CO2
capture - are PyPSA 1.4 ``Process``es (``rate0 = -1`` on the H2 / electricity input, ``rate1..3`` the
output and the further inputs; see :func:`conversion_row`). ``spec.componentType = "link"`` builds the
same steps as multi-port Links instead (the pre-0.x form, kept so a chain can be rebuilt either way
and old sessions stay readable); the two are the same LP. ``Process`` only became usable once
``build_network`` annualised its ``capital_cost`` like the other extendable components
(``backend/pypsa/network/__init__.py`` -> ``annuitisable``), which is why the first version used Links.

Units of the chain's buses (PyPSA only conserves the number, so each bus has one unit):

* electricity ``MW_el``; hydrogen, ammonia, methanol, e-fuel ``MW`` on an LHV basis;
* nitrogen ``t_N2/h``; CO2 ``t_CO2/h``.

A synthesis ``Link`` takes H2 at ``bus0`` (``p_nom`` in ``MW_H2`` LHV), delivers the
product at ``bus1`` and draws the other inputs through negative ``efficiency2`` (electricity,
``MWh_el`` per ``MWh_H2``) and ``efficiency3`` (N2 or CO2, ``t`` per ``MWh_H2``):

    $$\\eta_1 = \\frac{1}{h},\\quad \\eta_2 = -\\frac{e}{h},\\quad \\eta_3 = -\\frac{m}{h}$$

    ASCII: eff1 = 1/h; eff2 = -e/h; eff3 = -m/h

with ``h`` = MWh_H2 per MWh_product, ``e`` = MWh_el per MWh_product, ``m`` = t per MWh_product
(the technology file's ``h2_input``, ``el_input``, ``n2_input`` / ``co2_input``).

Costs follow PyPSA's own split: every extendable component carries ``overnight_cost`` (EUR per MW or MWh), ``fom_cost``
(EUR per MW or MWh per year), ``lifetime`` and ``discount_rate`` (the chain's rate, which the UI sets from Settings); ``capital_cost`` is
left blank. PyPSA annualises ``overnight_cost`` with the row's rate and the build pro-rates it to the window. The results read the
effective cost back from the rebuilt network (``p2x/results.py``) and never recompute an annuity.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from . import technologies as tech

Row = dict[str, Any]
Model = dict[str, list[Row]]

REGISTRY_SHEET = "RAGNAROK_P2X"
HOURS_PER_YEAR = 8760.0

#: Per derivative product: technology key, bus / carrier names, the other input and storage tech.
PRODUCTS: dict[str, dict[str, Any]] = {
    "NH3": {"tech": "haber_bosch", "bus_carrier": "NH3", "link_carrier": "Haber-Bosch", "lhv": "nh3_lhv_kwh_per_kg",
            "feed": "n2", "storage": "nh3_storage", "label": "Ammonia"},
    "MeOH": {"tech": "methanolisation", "bus_carrier": "methanol", "link_carrier": "methanolisation", "lhv": "meoh_lhv_kwh_per_kg",
             "feed": "co2", "storage": "meoh_storage", "label": "Methanol"},
    "eFuel": {"tech": "fischer_tropsch", "bus_carrier": "e-fuel", "link_carrier": "Fischer-Tropsch", "lhv": "efuel_lhv_kwh_per_kg",
              "feed": "co2", "storage": "efuel_storage", "label": "E-fuel (FT liquids)"},
}
ALL_PRODUCTS = ("H2", *PRODUCTS)
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_AC_CARRIERS = {"", "ac", "dc", "electricity", "elec", "power"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _opt(value: Any) -> float | None:
    """A positive finite number, else None (unbounded)."""
    out = _num(value, 0.0)
    return out if out > 0 else None


COMPONENT_TYPES = ("process", "link")


def conversion_row(kind: str, name: str, ports: list[tuple[str, float]], carrier: str, **common: Any) -> tuple[str, Row]:
    """A multi-port conversion unit as a PyPSA 1.4 ``Process`` (default) or as a multi-port ``Link``.

    The two carry the same physics. With ``p`` the unit's level (MW at port 0 = its main input, which is also
    ``p_nom``) and ``eta_i`` the port ratios (output ports > 0, further inputs < 0)::

        Link:     p_i = -eta_i * p  (i >= 1),   p_0 = p      (efficiency, efficiency2, ...)
        Process:  rate_0 = -1, rate_i = eta_i, p_i = -rate_i * p  (rate1, rate2, ...)

    so ``p_nom``, ``overnight_cost``, ``fom_cost``, ``marginal_cost`` and every port flow are identical and the LP is the same.

    Args:
        kind: ``"process"`` or ``"link"``.
        name: component name.
        ports: ``[(bus0, 1.0), (bus1, eta1), (bus2, eta2), ...]``; the first entry is the input port.
        carrier: component carrier.
        **common: ``overnight_cost``, ``fom_cost``, ``lifetime``, ``marginal_cost``, ``p_nom`` ... (same for both).

    Returns:
        ``(sheet, row)``.
    """
    if kind not in COMPONENT_TYPES:
        raise ValueError(f"componentType must be one of {COMPONENT_TYPES}, got {kind!r}.")
    row: Row = {"name": name, "carrier": carrier}
    for i, (bus, eta) in enumerate(ports):
        row[f"bus{i}"] = bus
        if i == 0:
            if kind == "process":
                row["rate0"] = -1.0
        elif kind == "process":
            row[f"rate{i}"] = round(eta, 8)
        else:
            row["efficiency" if i == 1 else f"efficiency{i}"] = round(eta, 8)
    row.update(common)
    return ("processes" if kind == "process" else "links"), row


def _names(model: Model) -> set[str]:
    taken: set[str] = set()
    for sheet in ("buses", "generators", "loads", "links", "processes", "stores", "storage_units", "lines", "transformers"):
        taken.update(str(r.get("name")) for r in model.get(sheet) or [] if r.get("name") is not None)
    taken.update(str(r.get("name")) for r in model.get(REGISTRY_SHEET) or [] if r.get("name") is not None)
    return taken


def default_anchor_bus(model: Model) -> str | None:
    """First electricity-carrier bus, else the first bus (same rule as the Build conversions)."""
    buses = model.get("buses") or []
    elec = next((b for b in buses if str(b.get("carrier") or "").strip().lower() in _AC_CARRIERS), None)
    chosen = elec if elec is not None else (buses[0] if buses else None)
    return str(chosen.get("name")) if chosen and chosen.get("name") else None


def default_spec() -> dict[str, Any]:
    """The chain spec with every default (what the UI starts from)."""
    return {
        "chainId": "p2x", "anchorBus": None, "discountRate": tech.default_discount_rate(),
        "products": ["H2"], "h2Bus": None, "componentType": "process",
        "electrolyser": {"tech": "aec", "extendable": True, "pNom": 100.0, "pNomMax": None,
                         "enforceMinLoad": False, "applyAvailability": True, "buildYear": 0},
        "storage": {"type": "tank", "compressor": False, "extendable": True, "eNom": 0.0, "eNomMax": None},
        "co2": {"source": "dac"},
        "synthesis": {p: {"extendable": True, "pNom": 0.0, "pNomMax": None} for p in PRODUCTS},
        "productStorage": {p: {"enabled": True, "extendable": True, "eNom": 0.0, "eNomMax": None} for p in PRODUCTS},
        "offtake": {p: {"mode": "none"} for p in ALL_PRODUCTS},
        "designatedGenerators": [], "params": {},
    }


def _merge(base: dict[str, Any], over: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _unit_row(role: str, label: str, sheet: str, row: Row, **extra: Any) -> dict[str, Any]:
    keys = ("name", "bus", "bus0", "bus1", "bus2", "bus3", "carrier", "efficiency", "efficiency2", "efficiency3",
            "rate0", "rate1", "rate2", "rate3", "p_nom", "p_nom_extendable", "e_nom", "e_nom_extendable", "p_set", "overnight_cost", "fom_cost", "capital_cost", "marginal_cost", "p_max_pu")
    return {"role": role, "label": label, "sheet": sheet, **{k: row[k] for k in keys if k in row}, **extra}


def build_chain(spec_in: dict[str, Any] | None, model: Model) -> dict[str, Any]:
    """Build a P2X chain.

    Args:
        spec_in: the chain spec (see :func:`default_spec`); only the keys to change are needed.
        model: the working model (sheets -> rows), read for the anchor bus, names and snapshots.

    Returns:
        ``{fragment, registry, summary, warnings, parameters, spec}``. ``fragment`` is a
        ``WorkbookFragment`` (``{"sheets": ..., "snapshots"?: [...]}``) for the fragment merge.

    Raises:
        ValueError: bad spec (unknown product, missing bus, name collision, bad profile ...).
    """
    spec = _merge(default_spec(), spec_in)
    warnings: list[str] = []
    cid = str(spec["chainId"] or "").strip()
    if not _NAME_RE.match(cid):
        raise ValueError(f"chainId {cid!r} must start with a letter and use letters, digits and underscores only.")
    if any(str(r.get("name")) == cid for r in model.get(REGISTRY_SHEET) or []):
        raise ValueError(f"A P2X chain {cid!r} already exists in this model; choose another chainId.")
    products = [str(p) for p in spec["products"]]
    bad = [p for p in products if p not in ALL_PRODUCTS]
    if bad:
        raise ValueError(f"Unknown product(s) {bad}. Options: {list(ALL_PRODUCTS)}.")
    products = [p for p in ALL_PRODUCTS if p in products]
    if not products:
        raise ValueError("Pick at least one product.")
    derivatives = [p for p in products if p in PRODUCTS]

    buses = model.get("buses") or []
    anchor_name = spec.get("anchorBus") or default_anchor_bus(model)
    anchor = next((b for b in buses if str(b.get("name")) == anchor_name), None)
    if anchor is None:
        raise ValueError(f"Anchor bus {anchor_name!r} not found in the model.")
    r_disc = float(spec["discountRate"])
    if not 0.0 <= r_disc < 1.0:
        raise ValueError(f"discountRate must be a fraction in [0, 1) (0.05 = 5 %), got {r_disc!r}.")

    el = spec["electrolyser"]
    ely_key = {"aec": "electrolyser_aec", "pem": "electrolyser_pem"}.get(str(el["tech"]).lower())
    if ely_key is None:
        raise ValueError(f"electrolyser.tech must be 'aec' or 'pem', got {el['tech']!r}.")
    st = spec["storage"]
    if st["type"] not in ("none", "tank", "cavern"):
        raise ValueError(f"storage.type must be none|tank|cavern, got {st['type']!r}.")
    co2_source = spec["co2"]["source"]
    if co2_source not in ("dac", "point"):
        raise ValueError(f"co2.source must be 'dac' or 'point', got {co2_source!r}.")

    P = tech.resolve_parameters(spec.get("params"))
    K = tech.constants()
    h2_lhv = K["h2_lhv_kwh_per_kg"]

    taken = _names(model)
    new_names: list[str] = []

    def nm(suffix: str) -> str:
        name = f"{cid}_{suffix}"
        if name in taken or name in new_names:
            raise ValueError(f"Component name {name!r} is already used in the model; choose another chainId.")
        new_names.append(name)
        return name

    sheets: dict[str, list[Row]] = {"buses": [], "carriers": [], "links": [], "processes": [], "stores": [], "loads": []}
    ctype = str(spec.get("componentType") or "process").lower()
    if ctype not in COMPONENT_TYPES:
        raise ValueError(f"componentType must be one of {COMPONENT_TYPES}, got {spec.get('componentType')!r}.")
    existing_carriers = {str(c.get("name")) for c in model.get("carriers") or []}
    summary: list[dict[str, Any]] = []
    components: dict[str, dict[str, str]] = {}
    fixed: dict[str, dict[str, Any]] = {}
    bus_names: dict[str, str] = {"anchor": str(anchor_name)}

    def carrier(name: str) -> None:
        if name and name not in existing_carriers and not any(c["name"] == name for c in sheets["carriers"]):
            sheets["carriers"].append({"name": name})

    def new_bus(role: str, carrier_name: str, name: str | None = None) -> str:
        bname = name or nm(f"bus_{role}")
        row: Row = {"name": bname, "carrier": carrier_name}
        for key in ("x", "y"):
            if anchor.get(key) not in (None, ""):
                row[key] = anchor[key]
        sheets["buses"].append(row)
        carrier(carrier_name)
        bus_names[role] = bname
        return bname

    def cost(per_unit: float, fom_pct: float) -> dict[str, float]:
        """PyPSA's own cost split: ``overnight_cost`` (per MW or MWh; the build annualises it with the run's discount rate and the
        row's ``lifetime`` and ``discount_rate``) and ``fom_cost`` (per MW or MWh per year). ``capital_cost`` stays blank: no annuity is folded in here."""
        return {"overnight_cost": round(per_unit, 6), "fom_cost": round(per_unit * fom_pct / 100.0, 6), "discount_rate": r_disc}

    def register(role: str, label: str, sheet: str, row: Row, overnight: float, fom_pct: float, life: float, unit: str) -> None:
        components[role] = {"sheet": sheet, "name": str(row["name"])}
        fixed[role] = {"overnightPerUnit": overnight, "unit": unit, "fomPct": fom_pct, "lifetimeYears": life}
        summary.append(_unit_row(role, label, sheet, row, overnightCapex=overnight, overnightUnit=unit))

    # ── H2 bus ─────────────────────────────────────────────────────────────────
    h2_name = spec.get("h2Bus")
    if h2_name:
        if not any(str(b.get("name")) == h2_name for b in buses):
            raise ValueError(f"H2 bus {h2_name!r} not found in the model.")
        bus_names["h2"] = str(h2_name)
    else:
        new_bus("h2", "H2")

    # ── Electrolyser: AC -> H2 ─────────────────────────────────────────────────
    pe = P[ely_key]
    eff_el = tech.lhv_efficiency(pe["specific_energy"], h2_lhv)
    if not 0.0 < eff_el <= 1.0:
        raise ValueError(f"Electrolyser LHV efficiency {eff_el:.3f} must be in (0, 1]; check specific_energy and the H2 LHV.")
    stack_wear = pe["stack_capex"] * 1000.0 / pe["stack_lifetime_hours"]           # EUR/MWh_el
    water_m3_per_mwh = pe["water_use"] / 1000.0                                       # m3/MWh_el (1 m3 = 1000 kg)
    water_cost = water_m3_per_mwh * P["water"]["supply_cost"]                         # EUR/MWh_el
    ely_name = nm("electrolyser")
    carrier("electrolysis")
    ely: Row = {
        "name": ely_name, "bus0": bus_names["anchor"], "bus1": bus_names["h2"], "carrier": "electrolysis",
        "efficiency": round(eff_el, 8),
        "marginal_cost": round(stack_wear + water_cost, 6),
        **cost(pe["capex"] * 1000.0, pe["fom"]),
        "lifetime": pe["lifetime"],
    }
    if el.get("applyAvailability", True):
        ely["p_max_pu"] = round(pe["availability"], 6)
    if int(_num(el.get("buildYear"))) > 0:
        ely["build_year"] = int(_num(el.get("buildYear")))
    if el.get("extendable", True):
        ely["p_nom_extendable"] = True
        ely["p_nom"] = 0.0
        if _opt(el.get("pNomMax")):
            ely["p_nom_max"] = _opt(el.get("pNomMax"))
    else:
        ely["p_nom"] = _num(el.get("pNom"))
        if el.get("enforceMinLoad"):
            ely["committable"] = True
            ely["p_min_pu"] = round(pe["min_load"] / 100.0, 6)
    if el.get("enforceMinLoad") and el.get("extendable", True):
        warnings.append("Minimum load needs a fixed electrolyser size (committable and extendable are mutually exclusive): "
                        "the minimum load is NOT enforced; set extendable=false and pNom to enforce it (MIP).")
    sheets["links"].append(ely)
    register("electrolyser", f"Electrolyser ({'alkaline' if ely_key.endswith('aec') else 'PEM'})", "links", ely,
             pe["capex"] * 1000.0, pe["fom"], pe["lifetime"], "EUR/MW_el")

    # ── H2 compression and storage ─────────────────────────────────────────────
    h2_store_bus = bus_names["h2"]
    if st["type"] != "none":
        use_comp = bool(st.get("compressor"))
        store_tech = {"tank": "h2_storage_tank_bare" if use_comp else "h2_storage_tank", "cavern": "h2_storage_cavern"}[st["type"]]
        ps = P[store_tech]
        if use_comp:
            pc = P["h2_compressor"]
            h2_store_bus = new_bus("h2_store", "H2 (compressed)")
            carrier("H2 compressor")
            comp: Row = {
                "name": nm("compressor"), "bus0": bus_names["h2"], "bus1": h2_store_bus, "bus2": bus_names["anchor"],
                "carrier": "H2 compressor", "efficiency": 1.0, "efficiency2": -round(pc["specific_energy_el"], 8),
                "p_nom_extendable": True, "p_nom": 0.0,
                **cost(pc["capex"] * 1000.0, pc["fom"]), "lifetime": pc["lifetime"],
            }
            dis: Row = {
                "name": nm("h2_discharge"), "bus0": h2_store_bus, "bus1": bus_names["h2"], "carrier": "H2 compressor",
                "efficiency": 1.0, "p_nom_extendable": True, "p_nom": 0.0, "capital_cost": 0.0,
            }
            sheets["links"] += [comp, dis]
            register("compressor", "H2 compressor", "links", comp, pc["capex"] * 1000.0, pc["fom"], pc["lifetime"], "EUR/MW_H2")
            components["h2_discharge"] = {"sheet": "links", "name": dis["name"]}
            summary.append(_unit_row("h2_discharge", "H2 store discharge", "links", dis))
        carrier("H2 store")
        store: Row = {
            "name": nm("h2_store"), "bus": h2_store_bus, "carrier": "H2 store", "e_cyclic": True,
            **cost(ps["capex"] * 1000.0, ps["fom"]), "lifetime": ps["lifetime"],
        }
        if st.get("extendable", True):
            store.update({"e_nom_extendable": True, "e_nom": 0.0})
            if _opt(st.get("eNomMax")):
                store["e_nom_max"] = _opt(st.get("eNomMax"))
        else:
            store["e_nom"] = _num(st.get("eNom"))
        sheets["stores"].append(store)
        register("h2_store", {"tank": "H2 tank", "cavern": "H2 salt cavern"}[st["type"]], "stores", store,
                 ps["capex"] * 1000.0, ps["fom"], ps["lifetime"], "EUR/MWh_H2")

    # ── Nitrogen and CO2 feeds ─────────────────────────────────────────────────
    needs_n2 = any(PRODUCTS[p]["feed"] == "n2" for p in derivatives)
    needs_co2 = any(PRODUCTS[p]["feed"] == "co2" for p in derivatives)
    if needs_n2:
        pa = P["asu"]
        eta = 1.0 / pa["specific_energy_el"]                                          # t_N2/MWh_el
        n2 = new_bus("n2", "N2")
        carrier("air separation")
        asu_sheet, asu = conversion_row(
            ctype, nm("asu"), [(bus_names["anchor"], 1.0), (n2, eta)], "air separation", p_nom_extendable=True, p_nom=0.0,
            **cost(pa["capex"] * eta, pa["fom"]), lifetime=pa["lifetime"])
        sheets[asu_sheet].append(asu)
        register("asu", "Air separation unit (N2)", asu_sheet, asu, pa["capex"] * eta, pa["fom"], pa["lifetime"], "EUR/MW_el")
    if needs_co2:
        key = "co2_dac" if co2_source == "dac" else "co2_point"
        pc2 = P[key]
        el_per_t = pc2["el_input"] + pc2["compression_el"] + pc2["heat_input"] / pc2["heat_cop"]   # MWh_el/t_CO2
        eta = 1.0 / el_per_t                                                                       # t_CO2/MWh_el
        co2 = new_bus("co2", "CO2 feed")
        link_c = "direct air capture" if co2_source == "dac" else "point-source capture"
        carrier(link_c)
        cs_extra: dict[str, Any] = {"marginal_cost": round(pc2["vom"] * eta, 6)} if pc2.get("vom") else {}   # EUR/MWh_el
        cs_sheet, cs = conversion_row(
            ctype, nm("co2_supply"), [(bus_names["anchor"], 1.0), (co2, eta)], link_c, p_nom_extendable=True, p_nom=0.0,
            **cost(pc2["capex"] * eta, pc2["fom"]), lifetime=pc2["lifetime"], **cs_extra)
        sheets[cs_sheet].append(cs)
        register("co2_supply", "Direct air capture" if co2_source == "dac" else "Point-source CO2 capture", cs_sheet, cs,
                 pc2["capex"] * eta, pc2["fom"], pc2["lifetime"], "EUR/MW_el")

    # ── Synthesis links and product stores ─────────────────────────────────────
    for prod in derivatives:
        meta = PRODUCTS[prod]
        pp = P[meta["tech"]]
        h = pp["h2_input"]
        pbus = new_bus(f"{prod}", meta["bus_carrier"])
        feed_bus = bus_names["n2"] if meta["feed"] == "n2" else bus_names["co2"]
        feed_in = pp["n2_input"] if meta["feed"] == "n2" else pp["co2_input"]
        carrier(meta["link_carrier"])
        eta1 = 1.0 / h
        sy = spec["synthesis"].get(prod) or {}
        size: dict[str, Any] = {"p_nom_extendable": True, "p_nom": 0.0}
        if sy.get("extendable", True):
            if _opt(sy.get("pNomMax")):
                size["p_nom_max"] = _opt(sy.get("pNomMax"))
        else:
            size = {"p_nom": _num(sy.get("pNom"))}
        vom = {"marginal_cost": round(pp["vom"] * eta1, 6)} if pp.get("vom") else {}      # EUR/MWh_H2 in
        syn_sheet, synth = conversion_row(
            ctype, nm(f"synth_{prod}"),
            [(bus_names["h2"], 1.0), (pbus, eta1), (bus_names["anchor"], -pp["el_input"] / h), (feed_bus, -feed_in / h)],
            meta["link_carrier"], **cost(pp["capex"] * 1000.0 * eta1, pp["fom"]),
            lifetime=pp["lifetime"], **vom, **size)
        sheets[syn_sheet].append(synth)
        register(f"synth_{prod}", f"{meta['label']} synthesis", syn_sheet, synth, pp["capex"] * 1000.0 * eta1, pp["fom"], pp["lifetime"], "EUR/MW_H2")
        ps_cfg = spec["productStorage"].get(prod) or {}
        if ps_cfg.get("enabled", True):
            pst = P[meta["storage"]]
            if "capex" in pst:
                per_mwh = pst["capex"]
            else:   # liquid tank priced per m3 -> per MWh_LHV
                dens = K["meoh_density_t_per_m3"] if prod == "MeOH" else K["efuel_density_t_per_m3"]
                per_mwh = pst["capex_per_m3"] / (dens * K[meta["lhv"]])
            carrier(f"{prod} store")
            ps_row: Row = {
                "name": nm(f"store_{prod}"), "bus": pbus, "carrier": f"{prod} store", "e_cyclic": True,
                **cost(per_mwh, pst["fom"]), "lifetime": pst["lifetime"],
            }
            if ps_cfg.get("extendable", True):
                ps_row.update({"e_nom_extendable": True, "e_nom": 0.0})
                if _opt(ps_cfg.get("eNomMax")):
                    ps_row["e_nom_max"] = _opt(ps_cfg.get("eNomMax"))
            else:
                ps_row["e_nom"] = _num(ps_cfg.get("eNom"))
            sheets["stores"].append(ps_row)
            register(f"store_{prod}", f"{meta['label']} tank", "stores", ps_row, per_mwh, pst["fom"], pst["lifetime"], f"EUR/MWh_{prod}")

    # ── Offtake loads (flat or profile) ────────────────────────────────────────
    snapshots = [str(r.get("snapshot")) for r in model.get("snapshots") or [] if r.get("snapshot") not in (None, "")]
    series_rows: dict[str, dict[str, float]] = {}
    for prod in products:
        cfg = spec["offtake"].get(prod) or {"mode": "none"}
        mode = cfg.get("mode", "none")
        if mode == "none":
            warnings.append(f"No {prod} offtake: nothing asks for {prod}, so the chain stays idle.")
            continue
        bus = bus_names["h2"] if prod == "H2" else bus_names[prod]
        lhv = K["h2_lhv_kwh_per_kg"] if prod == "H2" else K[PRODUCTS[prod]["lhv"]]        # kWh/kg = MWh/t
        if cfg.get("tonnesPerYear") not in (None, ""):
            level = _num(cfg["tonnesPerYear"]) * lhv / HOURS_PER_YEAR                    # MW_LHV
        else:
            level = _num(cfg.get("mw"))
        if level <= 0:
            raise ValueError(f"{prod} offtake needs tonnesPerYear or mw > 0.")
        load: Row = {"name": nm(f"load_{prod}"), "bus": bus, "p_set": round(level, 6)}
        if mode == "profile":
            prof = cfg.get("profile")
            if isinstance(prof, dict):
                values = [_num(prof.get(s)) for s in snapshots]
            elif isinstance(prof, list):
                if len(prof) != len(snapshots):
                    raise ValueError(f"{prod} offtake profile has {len(prof)} values but the model has {len(snapshots)} snapshots.")
                values = [_num(v) for v in prof]
            else:
                raise ValueError(f"{prod} offtake mode 'profile' needs a profile list (one value per snapshot) or a {{snapshot: value}} map.")
            mean = sum(values) / len(values) if values else 0.0
            if mean <= 0:
                raise ValueError(f"{prod} offtake profile must have a positive mean.")
            for s, v in zip(snapshots, values):                  # shape normalised to mean 1, scaled by the level
                series_rows.setdefault(s, {})[load["name"]] = round(level * v / mean, 6)
        elif mode != "flat":
            raise ValueError(f"{prod} offtake mode must be none|flat|profile, got {mode!r}.")
        sheets["loads"].append(load)
        components[f"load_{prod}"] = {"sheet": "loads", "name": load["name"]}
        summary.append(_unit_row(f"load_{prod}", f"{prod} offtake", "loads", load, mode=mode))

    # ── Designated RES + registry ──────────────────────────────────────────────
    gen_names = {str(g.get("name")) for g in model.get("generators") or []}
    designated = [str(g) for g in spec.get("designatedGenerators") or []]
    missing = [g for g in designated if g not in gen_names]
    if missing:
        raise ValueError(f"Designated generator(s) not in the model: {missing}.")
    registry = {
        "version": 2, "componentType": ctype, "chainId": cid, "anchorBus": bus_names["anchor"], "discountRate": r_disc, "products": products,
        "buses": bus_names, "components": components, "fixedCosts": fixed,
        "electrolyser": {"tech": ely_key, "specificEnergyKwhPerKg": pe["specific_energy"], "efficiencyLhv": eff_el,
                         "stackWearEurPerMwhEl": stack_wear, "waterM3PerMwhEl": water_m3_per_mwh,
                         "waterCostEurPerM3": P["water"]["supply_cost"], "buildYear": int(_num(el.get("buildYear")))},
        "lhvKwhPerKg": {"H2": h2_lhv, **{p: K[PRODUCTS[p]["lhv"]] for p in derivatives}},
        "efuelDensityTPerM3": K["efuel_density_t_per_m3"],
        "designatedGenerators": designated,
        "parameters": {k: {n: v for n, v in vals.items()} for k, vals in P.items()
                       if k in (ely_key, "water", "h2_compressor", "asu", "co2_dac", "co2_point", "nh3_storage", "meoh_storage", "efuel_storage",
                                "h2_storage_tank", "h2_storage_tank_bare", "h2_storage_cavern", *(PRODUCTS[p]["tech"] for p in derivatives))},
    }
    sheets[REGISTRY_SHEET] = [{"name": cid, "json": json.dumps(registry, sort_keys=True)}]
    sheets = {k: v for k, v in sheets.items() if v}
    fragment: dict[str, Any] = {"sheets": sheets}
    if series_rows:
        sheets["loads-p_set"] = [{"snapshot": s, **series_rows[s]} for s in snapshots if s in series_rows]
        fragment["snapshots"] = snapshots
    return {"fragment": fragment, "registry": registry, "summary": summary, "warnings": warnings,
            "parameters": tech.catalogue(spec.get("params"))["technologies"], "spec": spec}
